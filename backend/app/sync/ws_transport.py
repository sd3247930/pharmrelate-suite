"""真实 WebSocket 通道（Windows 本地自测版）。

它不是"另一个假实现"——这是**真的在跑 WebSocket**，只是两端都在同一台 PC 上。
真机到位后，Android 端用一个等价客户端连过来即可，服务端一行不改。

服务端业务逻辑复用 `InMemoryHub`：**通道与业务逻辑是分开的**，
换通道不影响仲裁规则 —— 这正是先做假实现的价值。

两种模式同一份代码，差别只在有没有 ssl_context：
    ws://    明文（选项 B）
    wss://   加密（选项 A / A-07）
"""

from __future__ import annotations

import asyncio
import json
import ssl
import threading
from dataclasses import dataclass
from typing import Any

from .envelope import (
    KIND_HELLO,
    KIND_HELLO_ACK,
    KIND_OPLOG,
    KIND_OPLOG_ACK,
    KIND_PING,
    KIND_PONG,
    PROTOCOL_VERSION,
    Envelope,
)
from .memory import InMemoryHub
from .pairing import PairingService
from .transport import (
    RejectedOp,
    SendResult,
    TransportCapabilities,
    TransportError,
    TransportStatus,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17801

BACKOFF_SCHEDULE = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
"""重连退避（V1.1 11.3）。最后一档是上限。"""

JITTER_RATIO = 0.2


def backoff_delay(attempt: int, *, jitter: float = 0.0) -> float:
    """第 attempt 次重连等待多久（attempt 从 1 开始），带 ±20% 抖动避免惊群。"""

    base = BACKOFF_SCHEDULE[min(max(attempt, 1), len(BACKOFF_SCHEDULE)) - 1]
    if jitter <= 0:
        return base
    return base * (1 + max(-JITTER_RATIO, min(JITTER_RATIO, jitter)))


@dataclass(slots=True)
class ServerInfo:
    host: str
    port: int
    scheme: str
    encrypted: bool

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "host": self.host,
            "port": self.port,
            "scheme": self.scheme,
            "encrypted": self.encrypted,
        }


class WsSyncServer:
    """Windows 端 WebSocket 服务。

    在后台线程里跑 asyncio 事件循环，因此同步的测试脚本或主线程可以直接用，
    不需要调用方改写异步。
    """

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        port: int = 0,
        hub: InMemoryHub | None = None,
        ssl_context: ssl.SSLContext | None = None,
        pairing: PairingService | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.hub = hub or InMemoryHub(encrypted=ssl_context is not None)
        self.pairing = pairing or PairingService()
        self._ssl_context = ssl_context
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: Any = None
        self._ready = threading.Event()
        self.last_error = ""
        self.connections = 0
        self.sessions: dict[str, str] = {}
        """deviceId → deviceFingerprint（已完成配对的会话）。"""

    # ------------------------------------------------------------------ 生命周期

    def start(self) -> ServerInfo:
        self._thread = threading.Thread(target=self._run, name="ws-server", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise TransportError(f"WebSocket 服务启动超时：{self.last_error}")
        return self.info()

    def stop(self) -> None:
        loop = self._loop
        if loop is None:
            return

        async def shutdown() -> None:
            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
            # 取消残留任务再停事件循环，否则 websockets 会在解释器退出时
            # 打一片 "Task was destroyed but it is pending" 噪声
            current = asyncio.current_task()
            pending = [
                task for task in asyncio.all_tasks() if task is not current and not task.done()
            ]
            for task in pending:
                task.cancel()

        try:
            asyncio.run_coroutine_threadsafe(shutdown(), loop).result(timeout=5)
        except Exception:  # noqa: BLE001 - 关闭失败不值得抛给调用方
            pass
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None
        self._server = None

    def info(self) -> ServerInfo:
        if self._server is not None and getattr(self._server, "sockets", None):
            try:
                self.port = self._server.sockets[0].getsockname()[1]
            except (IndexError, OSError):  # pragma: no cover
                pass
        return ServerInfo(
            host=self.host,
            port=self.port,
            scheme="wss" if self._ssl_context else "ws",
            encrypted=self._ssl_context is not None,
        )

    # ------------------------------------------------------------------ 事件循环

    def _run(self) -> None:
        import websockets

        async def handler(connection) -> None:
            device_id = ""
            try:
                async for raw in connection:
                    envelope = Envelope.from_dict(json.loads(raw))

                    if envelope.kind == KIND_HELLO:
                        device_id, reply = self._handshake(envelope)
                        await connection.send(json.dumps(reply.to_dict(), ensure_ascii=False))
                        continue

                    if envelope.kind == KIND_PING:
                        await connection.send(
                            json.dumps(
                                Envelope(
                                    kind=KIND_PONG,
                                    device_id="server",
                                    batch_id=envelope.batch_id,
                                    seq=envelope.seq,
                                ).to_dict(),
                                ensure_ascii=False,
                            )
                        )
                        continue

                    if envelope.kind == KIND_OPLOG:
                        result = self.hub.deliver(envelope)
                        ack = Envelope(
                            kind=KIND_OPLOG_ACK,
                            device_id="server",
                            batch_id=envelope.batch_id,
                            seq=envelope.seq,
                            payload={
                                "accepted": result.accepted,
                                "rejected": [item.to_dict() for item in result.rejected],
                                "duplicate": result.duplicate,
                                "gapDetected": result.gap_detected,
                                "expectedSeq": result.expected_seq,
                            },
                        )
                        await connection.send(json.dumps(ack.to_dict(), ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001 - 单连接异常不能拖垮服务
                self.last_error = f"{device_id or 'unknown'}: {exc}"

        async def main() -> None:
            try:
                self._server = await websockets.serve(
                    handler,
                    self.host,
                    self.port,
                    ssl=self._ssl_context,
                    ping_interval=None,  # 心跳由应用层负责，避免双重超时
                )
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                self._ready.set()
                return
            self._ready.set()
            await asyncio.Future()  # 一直跑到 loop.stop()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        loop.create_task(main())
        try:
            loop.run_forever()
        finally:
            loop.close()

    def _handshake(self, hello: Envelope) -> tuple[str, Envelope]:
        """处理 hello：校验一次性 Token + 设备指纹，回 hello_ack。"""

        token = str(hello.payload.get("token") or "")
        device_id = str(hello.payload.get("deviceId") or hello.device_id)
        device_fp = str(hello.payload.get("deviceFingerprint") or "")

        reason = self.pairing.redeem(token, device_fp)
        if reason != "OK":
            return device_id, Envelope(
                kind=KIND_HELLO_ACK,
                device_id="server",
                batch_id=hello.batch_id,
                seq=hello.seq,
                payload={"ok": False, "reason": reason},
            )

        if hello.version != PROTOCOL_VERSION:
            return device_id, Envelope(
                kind=KIND_HELLO_ACK,
                device_id="server",
                batch_id=hello.batch_id,
                seq=hello.seq,
                payload={"ok": False, "reason": "VERSION_MISMATCH", "expected": PROTOCOL_VERSION},
            )

        self.sessions[device_id] = device_fp
        self.connections += 1
        self.hub.connect(device_id)
        return device_id, Envelope(
            kind=KIND_HELLO_ACK,
            device_id="server",
            batch_id=hello.batch_id,
            seq=hello.seq,
            payload={
                "ok": True,
                "protocolVersion": PROTOCOL_VERSION,
                "digest": self.hub.state(hello.batch_id).to_dict(),
            },
        )


class WebSocketTransport:
    """客户端：实现同一个 `SyncTransport` 契约，只是下面真的走 WebSocket。

    同步用法 —— 内部自己维护一个事件循环，调用方不需要写 async/await。
    """

    name = "websocket"

    def __init__(
        self,
        url: str,
        *,
        token: str = "",
        device_fingerprint: str = "",
        ssl_context: ssl.SSLContext | None = None,
        connect_timeout: float = 5.0,
        max_reconnect_attempts: int = 6,
    ) -> None:
        self.url = url
        self._token = token
        self._fingerprint = device_fingerprint
        self._ssl_context = ssl_context
        self._connect_timeout = connect_timeout
        self._max_attempts = max_reconnect_attempts
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connection: Any = None
        self._batch_id = ""
        self._device_id = ""
        self._seq = 0
        self._open = False
        self.last_error = ""
        self.reconnect_attempts = 0
        self.handshake_payload: dict[str, object] = {}

    # ------------------------------------------------------------------ 连接

    def open(self, *, batch_id: str, device_id: str) -> None:
        if self._open and batch_id == self._batch_id and device_id == self._device_id:
            return  # 幂等
        self._batch_id = batch_id
        self._device_id = device_id
        self._seq = 0

        if self._loop is None:
            self._loop = asyncio.new_event_loop()

        self._connect()
        hello = Envelope(
            kind=KIND_HELLO,
            device_id=device_id,
            batch_id=batch_id,
            seq=0,
            payload={
                "deviceId": device_id,
                "deviceFingerprint": self._fingerprint,
                "token": self._token,
                "protocolVersion": PROTOCOL_VERSION,
            },
        )
        reply = self._round_trip(hello)
        self.handshake_payload = dict(reply.payload)
        if not reply.payload.get("ok"):
            reason = reply.payload.get("reason")
            self.close()
            raise TransportError(
                f"配对失败：{reason}",
                retryable=reason not in {"TOKEN_UNKNOWN", "TOKEN_USED", "FINGERPRINT_MISMATCH"},
            )
        self._open = True

    def _connect(self) -> None:
        import websockets

        assert self._loop is not None
        try:
            self._connection = self._loop.run_until_complete(
                websockets.connect(
                    self.url,
                    ssl=self._ssl_context,
                    open_timeout=self._connect_timeout,
                    ping_interval=None,
                    max_size=8 * 1024 * 1024,
                )
            )
        except Exception as exc:  # noqa: BLE001
            # 连接失败一律转成可重试的 TransportError。
            # 不包装的话调用方会拿到裸的 OSError/ConnectionRefusedError，
            # 重试逻辑就得同时处理两种异常类型 —— 那是通道封装该干的活。
            raise TransportError(f"无法连接 {self.url}：{exc}", retryable=True) from exc

    def _round_trip(self, envelope: Envelope) -> Envelope:
        assert self._loop is not None and self._connection is not None
        try:
            self._loop.run_until_complete(
                self._connection.send(json.dumps(envelope.to_dict(), ensure_ascii=False))
            )
            raw = self._loop.run_until_complete(self._connection.recv())
        except Exception as exc:  # noqa: BLE001 - 统一转成通道故障
            raise TransportError(f"WebSocket 收发失败：{exc}") from exc
        return Envelope.from_dict(json.loads(raw))

    def close(self) -> None:
        connection, loop = self._connection, self._loop
        self._connection = None
        self._open = False
        if connection is not None and loop is not None:
            try:
                loop.run_until_complete(connection.close())
            except Exception:  # noqa: BLE001
                pass
        if loop is not None:
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass
        self._loop = None

    def is_open(self) -> bool:
        return self._open and self._connection is not None

    # ------------------------------------------------------------------ 收发

    def next_envelope(self, ops: list[dict[str, object]], *, hlc: str = "") -> Envelope:
        self._seq += 1
        return Envelope(
            kind=KIND_OPLOG,
            device_id=self._device_id,
            batch_id=self._batch_id,
            seq=self._seq,
            hlc=hlc,
            payload={"ops": ops},
        )

    def send(self, envelopes: list[Envelope]) -> SendResult:
        if not self.is_open():
            raise TransportError("通道未打开")

        combined = SendResult()
        for envelope in envelopes:
            reply = self._round_trip(envelope)
            payload = reply.payload
            combined.accepted.extend(int(item) for item in payload.get("accepted") or [])
            combined.duplicate.extend(int(item) for item in payload.get("duplicate") or [])
            for item in payload.get("rejected") or []:
                combined.rejected.append(
                    RejectedOp(
                        seq=int(item.get("seq") or envelope.seq),
                        reason=str(item.get("reason") or ""),
                        detail=dict(item.get("detail") or {}),
                        retryable=bool(item.get("retryable", False)),
                    )
                )
            if payload.get("gapDetected"):
                combined.gap_detected = True
                combined.expected_seq = int(payload.get("expectedSeq") or 0)
        return combined

    def reconnect(self, *, sleep: Any = None) -> bool:
        """按指数退避重连（V1.1 11.3）。成功返回 True。"""

        self._open = False
        self._connection = None
        for attempt in range(1, self._max_attempts + 1):
            self.reconnect_attempts = attempt
            delay = backoff_delay(attempt, jitter=0.0)
            if sleep is not None:
                sleep(delay)
            try:
                self.open(batch_id=self._batch_id, device_id=self._device_id)
                return True
            except TransportError as exc:
                self.last_error = str(exc)
        return False

    def status(self) -> TransportStatus:
        return TransportStatus(
            open=self.is_open(),
            pending=0,
            last_error=self.last_error,
        )

    def capabilities(self) -> TransportCapabilities:
        return TransportCapabilities(
            push=True,
            max_batch=500,
            encrypted=self.url.startswith("wss://"),
            stable_rtt=True,
        )
