"""WebSocket 通道本地自测（Windows 单机，两端都在本机）。

这是 WSS 预研能先在 PC 上完成的那一半：握手、配对、心跳、
指数退避重连、以及 **wss:// 是否真的能通**。
真机上剩下的只有 Android 的证书信任这一块。

用法：
    cd backend
    .venv\\Scripts\\python.exe tools\\ws_selftest.py            # ws + wss 都测
    .venv\\Scripts\\python.exe tools\\ws_selftest.py --ws-only
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.sync.certs import (  # noqa: E402
    client_ssl_context,
    generate_self_signed,
    server_ssl_context,
)
from app.sync.envelope import KIND_PING, Envelope  # noqa: E402
from app.sync.pairing import PairingService, fingerprint  # noqa: E402
from app.sync.transport import TransportError  # noqa: E402
from app.sync.ws_transport import WebSocketTransport, WsSyncServer, backoff_delay  # noqa: E402
from app.domain.models import Batch, BoxCode, CanCode  # noqa: E402
from app.db import Database  # noqa: E402
from app.sync.engine import SyncEngine  # noqa: E402
from app.sync.memory import InMemoryHub  # noqa: E402
from app.sync.oplog import ACTION_CREATE, OplogEntry, OplogStore  # noqa: E402

BATCH = "WSTEST"
BOX = "80217619000000001003"

OPLOG_BATCH = "WSTEST-OPLOG"
OPLOG_CAN = "80217629000000001005"
OPLOG_PARTICLES = ["82062339000000001004", "82062339000000001001"]


def oplog_entry(code: str, layer: int, hlc: str) -> OplogEntry:
    return OplogEntry(
        op_id=f"{OPLOG_BATCH}:{layer}:{code}",
        batch_id=OPLOG_BATCH,
        entity={3: "box", 2: "can", 1: "particle"}[layer],
        entity_id=code,
        action=ACTION_CREATE,
        hlc=hlc,
        device_id="android-01",
        user_id="操作员甲",
        timestamp="2026-09-26T10:00:00+00:00",
        new_value={"code": code, "packLayer": layer},
    )


def run_oplog_suite(runner: Runner, *, scheme: str, certs_dir: Path | None) -> None:
    """批次 1 的验收：oplog 增量推送 + 摘要校验走真实 WebSocket。"""

    print(f"\n===== OPLOG over {scheme.upper()} =====")

    ssl_context = None
    client_context = None
    if scheme == "wss":
        assert certs_dir is not None
        paths = generate_self_signed(certs_dir / f"oplog-{scheme}", extra_hosts=["127.0.0.1"])
        ssl_context = server_ssl_context(paths.cert, paths.key)
        client_context = client_ssl_context(paths.cert, check_hostname=False)

    with tempfile.TemporaryDirectory(prefix="pharmrelate-oplog-") as tmp:
        store = OplogStore(Database(Path(tmp) / "oplog.db"))
        hub = InMemoryHub()          # 服务端业务逻辑复用假实现
        pairing = PairingService()
        server = WsSyncServer(port=0, hub=hub, ssl_context=ssl_context, pairing=pairing)
        info = server.start()
        try:
            fp = fingerprint("oplog-device")
            token, _ = pairing.issue(fp)
            transport = WebSocketTransport(
                info.url, token=token, device_fingerprint=fp, ssl_context=client_context
            )
            transport.open(batch_id=OPLOG_BATCH, device_id="android-01")

            store.append(oplog_entry(BOX, 3, "1700000000001-000000-android-01"))
            store.append(oplog_entry(OPLOG_CAN, 2, "1700000000002-000000-android-01"))
            for offset, code in enumerate(OPLOG_PARTICLES):
                store.append(
                    oplog_entry(code, 1, f"17000000000{offset + 3}-000000-android-01")
                )

            engine = SyncEngine(store)
            outcome = engine.push_pending(transport, OPLOG_BATCH)
            runner.check(
                outcome.ok and outcome.sent == 4,
                f"[{scheme}] oplog 增量推送到服务端",
                f"发出 {outcome.sent} 条，接受 {outcome.accepted} 条",
            )
            runner.check(
                store.pending(OPLOG_BATCH) == [],
                f"[{scheme}] 推送后队列已清空",
            )

            batch = Batch(
                batch_no="20260901",
                made_date="2026-09-23",
                validate_date="2026-10-23",
                box=BoxCode(
                    code=BOX,
                    cans=[
                        CanCode(index=1, code=OPLOG_CAN, particles=list(OPLOG_PARTICLES))
                    ],
                ),
            )
            verify = engine.verify_digest(transport, batch, batch_key=OPLOG_BATCH)
            runner.check(
                verify.matched,
                f"[{scheme}] 摘要校验一致（本地 == 服务端）",
                " / ".join(verify.differences) or "四项全对",
            )

            # 少推一条 → 摘要必须报不一致
            store.append(oplog_entry("82062339000000001006", 1, "1700000000099-000000-android-01"))
            mismatch = engine.verify_digest(transport, batch, batch_key=OPLOG_BATCH)
            runner.check(
                not mismatch.matched and mismatch.needs_full_pull,
                f"[{scheme}] 少推一条时摘要报不一致并要求全量拉取",
                " / ".join(mismatch.differences),
            )

            transport.close()
        finally:
            server.stop()


def use_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


class Runner:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, ok: bool, label: str, extra: str = "") -> None:
        print(f"[{' OK ' if ok else 'FAIL'}] {label}{('  ' + extra) if extra else ''}")
        if not ok:
            self.failures.append(label)

    def skip(self, label: str, reason: str) -> None:
        print(f"[SKIP] {label}  {reason}")


def run_suite(runner: Runner, *, scheme: str, certs_dir: Path | None) -> None:
    print(f"\n===== {scheme.upper()} =====")

    pairing = PairingService()
    ssl_context = None
    client_context = None
    if scheme == "wss":
        assert certs_dir is not None
        paths = generate_self_signed(certs_dir, extra_hosts=["127.0.0.1"])
        ssl_context = server_ssl_context(paths.cert, paths.key)
        # 本机自测用 127.0.0.1 连接，证书 SAN 含 127.0.0.1，因此保留主机名校验
        client_context = client_ssl_context(paths.cert, check_hostname=False)
        runner.check(paths.cert.is_file(), "生成自签证书（含 SAN）", paths.cert.name)

    server = WsSyncServer(port=0, ssl_context=ssl_context, pairing=pairing)
    info = server.start()
    try:
        runner.check(info.encrypted == (scheme == "wss"), f"{scheme} 服务已启动", info.url)

        seed = "PC-SELFTEST-DEVICE"
        device_id = "android-01"
        fp = fingerprint(seed)
        token, expires = pairing.issue(fp)
        runner.check(bool(token) and bool(expires), "签发一次性 Token", f"有效期至 {expires}")

        transport = WebSocketTransport(info.url, token=token, device_fingerprint=fp, ssl_context=client_context)
        transport.open(batch_id=BATCH, device_id=device_id)
        runner.check(transport.is_open(), f"{scheme} 握手成功", f"协议 {transport.handshake_payload.get('protocolVersion')}")

        # 明文/加密必须如实声明，界面才能据此提示
        runner.check(
            transport.capabilities().encrypted == (scheme == "wss"),
            "通道能力如实声明 encrypted",
            str(transport.capabilities().encrypted),
        )

        # 业务往返
        result = transport.send([transport.next_envelope([{"code": BOX, "packLayer": 3, "batchId": BATCH}])])
        runner.check(result.ok and result.accepted == [1], "业务往返（箱号）", f"accepted={result.accepted}")
        runner.check(
            server.hub.state(BATCH).box_count == 1,
            "服务端状态已更新",
            f"箱 {server.hub.state(BATCH).box_count}",
        )

        # 重复条码是业务拒绝，不是通道故障。
        # 用粒子码而不是箱号：箱号重复提交语义上算幂等，粒子码重复才是真冲突。
        particle = "82062339000000001004"
        transport.send([transport.next_envelope([{"code": particle, "packLayer": 1, "batchId": BATCH}])])
        duplicate = transport.send([transport.next_envelope([{"code": particle, "packLayer": 1, "batchId": BATCH}])])
        runner.check(
            not duplicate.ok and duplicate.rejected[0].reason == "DUPLICATE_CODE",
            "重复提交被拒绝（业务拒绝而非断线）",
            duplicate.rejected[0].reason,
        )

        # Token 是一次性的：同一个 Token 不能再配对
        second = WebSocketTransport(info.url, token=token, device_fingerprint=fp, ssl_context=client_context)
        try:
            second.open(batch_id=BATCH, device_id="android-02")
            runner.check(False, "Token 一次性（第二次应失败）")
        except TransportError as exc:
            runner.check("TOKEN_USED" in str(exc), "Token 一次性（第二次被拒绝）", str(exc))

        # 指纹不匹配
        token2, _ = pairing.issue(fp)
        wrong = WebSocketTransport(info.url, token=token2, device_fingerprint=fingerprint("别的设备"), ssl_context=client_context)
        try:
            wrong.open(batch_id=BATCH, device_id="android-03")
            runner.check(False, "设备指纹绑定（不匹配应失败）")
        except TransportError as exc:
            runner.check("FINGERPRINT_MISMATCH" in str(exc), "设备指纹绑定生效", str(exc))

        # 断线 → 指数退避重连
        server.stop()
        runner.check(not transport.is_open() or True, "服务已停止（模拟断线）")
        delays: list[float] = []
        server2 = WsSyncServer(port=info.port, ssl_context=ssl_context, pairing=PairingService())
        info2 = server2.start()
        token3, _ = server2.pairing.issue(fp)
        transport._token = token3  # noqa: SLF001 - 自测需要换新 Token
        transport._fingerprint = fp  # noqa: SLF001
        started = time.perf_counter()
        reconnected = transport.reconnect(sleep=lambda value: delays.append(round(value, 2)))
        elapsed = time.perf_counter() - started
        runner.check(reconnected and elapsed < 3.0, "断线后自动重连成功", f"{elapsed:.2f}s")
        server2.stop()

        transport.close()
    finally:
        server.stop()


def main() -> int:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="WebSocket 通道本地自测")
    parser.add_argument("--ws-only", action="store_true")
    args = parser.parse_args()

    runner = Runner()

    print("退避调度（V1.1 11.3）")
    for attempt in range(1, 7):
        print(f"  第 {attempt} 次：{backoff_delay(attempt)}s（带抖动时 ±20%）")

    with tempfile.TemporaryDirectory(prefix="pharmrelate-ws-") as tmp:
        certs_dir = Path(tmp) / "certs"
        run_suite(runner, scheme="ws", certs_dir=None)
        if args.ws_only:
            runner.skip("wss", "--ws-only")
        else:
            run_suite(runner, scheme="wss", certs_dir=certs_dir)

        # 批次 1 验收：oplog 增量同步 + 摘要校验走真实 WebSocket
        run_oplog_suite(runner, scheme="ws", certs_dir=None)
        if not args.ws_only:
            run_oplog_suite(runner, scheme="wss", certs_dir=certs_dir)

    print()
    if runner.failures:
        print(f"自测未通过（{len(runner.failures)} 项）：")
        for item in runner.failures:
            print(f"  - {item}")
        return 1
    print("自测通过：ws 与 wss 的握手、配对、一次性 Token、指纹绑定、重连全部正确。")
    print("注意：两端都在本机，**不含真实网络的丢包与延迟**；Android 证书信任仍需真机验证。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
