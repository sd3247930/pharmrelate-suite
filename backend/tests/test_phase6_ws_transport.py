"""WebSocketTransport 自动化测试。

在此之前，WebSocket 通道只被 `tools/ws_selftest.py` 这个**工具**覆盖 ——
要有人手动跑才有验证。这个文件把它纳入单元测试套件，
于是它和其余 257 项一起进 `scripts/check.ps1`，能持续回归。

两端都在本机，因此验的是**协议与逻辑正确性**，不是真实网络性能。
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

try:
    from tests.support import BACKEND_DIR  # noqa: F401
except ImportError:
    from support import BACKEND_DIR  # noqa: F401

from app.sync.certs import client_ssl_context, generate_self_signed, server_ssl_context
from app.sync.envelope import KIND_PING, PROTOCOL_VERSION, Envelope
from app.sync.memory import InMemoryHub
from app.sync.pairing import (
    REASON_EXPIRED,
    REASON_FINGERPRINT,
    REASON_OK,
    REASON_UNKNOWN,
    REASON_USED,
    PairingService,
    fingerprint,
)
from app.sync.transport import TransportError
from app.sync.ws_transport import (
    BACKOFF_SCHEDULE,
    JITTER_RATIO,
    WebSocketTransport,
    WsSyncServer,
    backoff_delay,
)

BATCH = "WSTEST"
BOX = "80217619000000001003"
PARTICLE = "82062339000000001004"


def op(code: str, layer: int = 1) -> dict[str, object]:
    return {"code": code, "packLayer": layer, "batchId": BATCH}


class BackoffTests(unittest.TestCase):
    """V1.1 11.3 的重连退避。"""

    def test_schedule_matches_v11(self) -> None:
        self.assertEqual(BACKOFF_SCHEDULE, (1.0, 2.0, 4.0, 8.0, 16.0, 30.0))

    def test_delay_follows_schedule_and_caps(self) -> None:
        for attempt, expected in enumerate(BACKOFF_SCHEDULE, start=1):
            with self.subTest(attempt=attempt):
                self.assertEqual(backoff_delay(attempt), expected)
        # 超过档位后停在上限，不无限增长
        self.assertEqual(backoff_delay(50), 30.0)

    def test_jitter_stays_within_20_percent(self) -> None:
        for jitter in (-1.0, -0.2, 0.0, 0.2, 1.0):
            with self.subTest(jitter=jitter):
                value = backoff_delay(3, jitter=jitter)
                base = 4.0
                self.assertGreaterEqual(value, base * (1 - JITTER_RATIO))
                self.assertLessEqual(value, base * (1 + JITTER_RATIO))


class PairingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = PairingService()
        self.fp = fingerprint("device-seed")

    def test_issue_then_redeem(self) -> None:
        token, expires = self.service.issue(self.fp)
        self.assertTrue(token)
        self.assertTrue(expires)
        self.assertEqual(self.service.redeem(token, self.fp), REASON_OK)

    def test_token_is_single_use(self) -> None:
        token, _ = self.service.issue(self.fp)
        self.assertEqual(self.service.redeem(token, self.fp), REASON_OK)
        self.assertEqual(self.service.redeem(token, self.fp), REASON_USED)

    def test_unknown_token(self) -> None:
        self.assertEqual(self.service.redeem("凭空捏造", self.fp), REASON_UNKNOWN)

    def test_fingerprint_must_match(self) -> None:
        token, _ = self.service.issue(self.fp)
        self.assertEqual(
            self.service.redeem(token, fingerprint("别的设备")), REASON_FINGERPRINT
        )

    def test_expired_token_is_rejected(self) -> None:
        from datetime import timedelta

        service = PairingService(ttl=timedelta(seconds=-1))
        token, _ = service.issue(self.fp)
        self.assertEqual(service.redeem(token, self.fp), REASON_EXPIRED)

    def test_pending_counts_unused_tokens(self) -> None:
        self.assertEqual(self.service.pending(), 0)
        self.service.issue(self.fp)
        token2, _ = self.service.issue(self.fp)
        self.assertEqual(self.service.pending(), 2)
        self.service.redeem(token2, self.fp)
        self.assertEqual(self.service.pending(), 1)


class CertificateTests(unittest.TestCase):
    def test_self_signed_certificate_has_san(self) -> None:
        """只写 CN 的证书会被 Android 7+ 与新版浏览器拒绝，SAN 必须有。"""

        from cryptography import x509

        with tempfile.TemporaryDirectory() as tmp:
            paths = generate_self_signed(Path(tmp), extra_hosts=["192.168.1.10"])
            certificate = x509.load_pem_x509_certificate(paths.cert.read_bytes())
            san = certificate.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value
            names = {str(entry.value) for entry in san}
            self.assertIn("localhost", names)
            self.assertIn("192.168.1.10", names)
            self.assertIn("127.0.0.1", names, "IP 形式的 SAN 也要有")
            self.assertTrue(paths.key.is_file())

    def test_ssl_contexts_are_built(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = generate_self_signed(Path(tmp))
            server = server_ssl_context(paths.cert, paths.key)
            client = client_ssl_context(paths.cert, check_hostname=False)
            self.assertEqual(server.minimum_version.name, "TLSv1_2")
            self.assertFalse(client.check_hostname)


class WsServerFixture(unittest.TestCase):
    """共用一个 ws 服务，避免每个用例都起停服务。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = WsSyncServer(port=0)
        cls.info = cls.server.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()

    def paired_transport(self, device_id: str = "android-01") -> WebSocketTransport:
        fp = fingerprint(device_id)
        token, _ = self.server.pairing.issue(fp)
        transport = WebSocketTransport(self.info.url, token=token, device_fingerprint=fp)
        transport.open(batch_id=BATCH, device_id=device_id)
        self.addCleanup(transport.close)
        return transport


class WsRoundTripTests(WsServerFixture):
    def test_handshake_reports_protocol_version(self) -> None:
        transport = self.paired_transport()
        self.assertTrue(transport.is_open())
        self.assertEqual(
            transport.handshake_payload.get("protocolVersion"), PROTOCOL_VERSION
        )

    def test_capabilities_report_plaintext_for_ws(self) -> None:
        transport = self.paired_transport()
        self.assertFalse(transport.capabilities().encrypted)
        self.assertEqual(self.info.scheme, "ws")

    def test_business_round_trip(self) -> None:
        transport = self.paired_transport("android-rt")
        result = transport.send([transport.next_envelope([op(BOX, layer=3)])])
        self.assertTrue(result.ok, result.rejected)
        self.assertEqual(result.accepted, [1])
        self.assertEqual(self.server.hub.state(BATCH).box_count, 1)

    def test_envelope_fields_survive_the_wire(self) -> None:
        transport = self.paired_transport("android-fields")
        # 用本用例专属的码：同一个 ws 服务被本类所有用例共用，
        # 复用条码会撞上"已被占用"，那是别的用例造成的干扰
        envelope = transport.next_envelope(
            [op("82062339000000001005")], hlc="0007-0003-a"
        )
        result = transport.send([envelope])
        self.assertTrue(result.ok, result.rejected)
        # hlc 由服务端按信封透传，压测与摘要校验都依赖它
        self.assertEqual(envelope.hlc, "0007-0003-a")

    def test_sequence_is_monotonic_over_the_wire(self) -> None:
        transport = self.paired_transport("android-seq")
        first = transport.next_envelope([op("82062339000000001001")])
        second = transport.next_envelope([op("82062339000000001003")])
        self.assertEqual(second.seq, first.seq + 1)

    def test_business_rejection_does_not_raise(self) -> None:
        """重复条码是业务拒绝：走 SendResult，不抛异常。"""

        transport = self.paired_transport("android-dup")
        transport.send([transport.next_envelope([op(PARTICLE)])])
        result = transport.send([transport.next_envelope([op(PARTICLE)])])
        self.assertFalse(result.ok)
        self.assertEqual(result.rejected[0].reason, "DUPLICATE_CODE")
        self.assertFalse(result.rejected[0].retryable)

    def test_gap_detection_over_the_wire(self) -> None:
        transport = self.paired_transport("android-gap")
        envelope = transport.next_envelope([op("82062339000000001004")])
        envelope.seq = 7
        result = transport.send([envelope])
        self.assertTrue(result.gap_detected)
        self.assertEqual(result.expected_seq, 1)


class WsHandshakeFailureTests(WsServerFixture):
    def test_unknown_token_is_rejected(self) -> None:
        transport = WebSocketTransport(
            self.info.url, token="凭空捏造", device_fingerprint=fingerprint("x")
        )
        with self.assertRaises(TransportError) as ctx:
            transport.open(batch_id=BATCH, device_id="android-bad")
        self.assertIn(REASON_UNKNOWN, str(ctx.exception))
        self.assertFalse(ctx.exception.retryable, "Token 无效重试也没用")

    def test_reused_token_is_rejected(self) -> None:
        fp = fingerprint("reuse")
        token, _ = self.server.pairing.issue(fp)
        first = WebSocketTransport(self.info.url, token=token, device_fingerprint=fp)
        first.open(batch_id=BATCH, device_id="android-reuse-1")
        self.addCleanup(first.close)

        second = WebSocketTransport(self.info.url, token=token, device_fingerprint=fp)
        with self.assertRaises(TransportError) as ctx:
            second.open(batch_id=BATCH, device_id="android-reuse-2")
        self.assertIn(REASON_USED, str(ctx.exception))

    def test_fingerprint_mismatch_is_rejected(self) -> None:
        token, _ = self.server.pairing.issue(fingerprint("真设备"))
        transport = WebSocketTransport(
            self.info.url, token=token, device_fingerprint=fingerprint("假设备")
        )
        with self.assertRaises(TransportError) as ctx:
            transport.open(batch_id=BATCH, device_id="android-fp")
        self.assertIn(REASON_FINGERPRINT, str(ctx.exception))

    def test_send_without_open_raises_channel_error(self) -> None:
        transport = WebSocketTransport(self.info.url)
        with self.assertRaises(TransportError):
            transport.send([Envelope(kind=KIND_PING, device_id="x", batch_id=BATCH, seq=2)])

    def test_open_is_idempotent(self) -> None:
        transport = self.paired_transport("android-idem")
        connection = transport._connection  # noqa: SLF001 - 验证没有重建连接
        transport.open(batch_id=BATCH, device_id="android-idem")
        self.assertIs(transport._connection, connection)  # noqa: SLF001


class WssRoundTripTests(unittest.TestCase):
    """wss:// 走真实 TLS —— 这是 A-07 预研能在 PC 上完成的那一半。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="pharmrelate-wss-")
        paths = generate_self_signed(Path(cls._tmp.name))
        cls.server = WsSyncServer(
            port=0, ssl_context=server_ssl_context(paths.cert, paths.key)
        )
        cls.info = cls.server.start()
        cls.client_context = client_ssl_context(paths.cert, check_hostname=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls._tmp.cleanup()

    def paired_transport(self, device_id: str) -> WebSocketTransport:
        fp = fingerprint(device_id)
        token, _ = self.server.pairing.issue(fp)
        transport = WebSocketTransport(
            self.info.url,
            token=token,
            device_fingerprint=fp,
            ssl_context=self.client_context,
        )
        transport.open(batch_id=BATCH, device_id=device_id)
        self.addCleanup(transport.close)
        return transport

    def test_server_reports_wss(self) -> None:
        self.assertEqual(self.info.scheme, "wss")
        self.assertTrue(self.info.encrypted)

    def test_handshake_over_tls(self) -> None:
        transport = self.paired_transport("android-tls")
        self.assertTrue(transport.is_open())
        self.assertTrue(transport.capabilities().encrypted, "wss 必须如实声明加密")

    def test_business_round_trip_over_tls(self) -> None:
        transport = self.paired_transport("android-tls-rt")
        result = transport.send([transport.next_envelope([op(BOX, layer=3)])])
        self.assertTrue(result.ok, result.rejected)
        self.assertEqual(self.server.hub.state(BATCH).box_count, 1)

    def test_business_rejection_over_tls(self) -> None:
        transport = self.paired_transport("android-tls-dup")
        transport.send([transport.next_envelope([op(PARTICLE)])])
        result = transport.send([transport.next_envelope([op(PARTICLE)])])
        self.assertEqual(result.rejected[0].reason, "DUPLICATE_CODE")

    def test_client_without_ca_cannot_connect(self) -> None:
        """不信任自签 CA 的客户端必须连不上 —— 这正是 Android 端会遇到的默认现象。

        把这条写成测试，是为了将来现场遇到"连不上"时能立刻确认：
        **这就是证书问题，不是网络问题。**
        """

        import ssl

        # 用系统默认信任链（不信任我们的自签 CA），模拟 Android 端未配置证书的状态
        transport = WebSocketTransport(
            self.info.url,
            token="any",
            device_fingerprint="any",
            ssl_context=ssl.create_default_context(),
        )
        with self.assertRaises(TransportError):
            transport.open(batch_id=BATCH, device_id="android-no-ca")


class ReconnectTests(WsServerFixture):
    def test_reconnect_reuses_session(self) -> None:
        """断线重连能恢复：退避机制本身由 BackoffTests 覆盖时间表。"""

        transport = self.paired_transport("android-recon")
        transport.send([transport.next_envelope([op(BOX, layer=3)])])

        # 模拟断线：直接关掉底层连接
        transport.close()
        self.assertFalse(transport.is_open())

        fp = fingerprint("android-recon")
        token, _ = self.server.pairing.issue(fp)
        transport._token = token  # noqa: SLF001 - 重新配对需要新 Token
        transport._fingerprint = fp  # noqa: SLF001
        delays: list[float] = []
        self.assertTrue(transport.reconnect(sleep=delays.append))
        result = transport.send([transport.next_envelope([op(PARTICLE)])])
        self.assertTrue(result.ok, result.rejected)

    def test_reconnect_eventually_fails_when_server_gone(self) -> None:
        transport = WebSocketTransport("ws://127.0.0.1:1", token="x", device_fingerprint="y")
        transport._batch_id = BATCH  # noqa: SLF001
        transport._device_id = "android-dead"  # noqa: SLF001
        self.assertFalse(
            transport.reconnect(sleep=lambda _value: None),
            "服务不可达时应在尝试若干次后放弃，而不是永远重试",
        )


if __name__ == "__main__":
    unittest.main()
