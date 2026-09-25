"""20 台移动端并发压测。

设计原则：

1. **用 SyncTransport 接口，不用自定义协议。** 压测客户端就是
   `SyncTransport` 的一个使用者，真机到位后把 `InMemorySyncTransport`
   换成 `WebSocketTransport`，脚本主体一行不改。

2. **假实现只能验"脚本可用 + 服务端逻辑承载能力"，不能验真实网络。**
   报告里会把这两件事分开写，不混为一谈。

3. **只用标准库。** 压测工具本身不该引入依赖，否则换台机器就跑不起来。

用法：
    cd backend
    .venv\\Scripts\\python.exe tools\\loadtest.py                  # 20 客户端 × 50 条
    .venv\\Scripts\\python.exe tools\\loadtest.py --quick           # 缩小规模，供 CI 用
    .venv\\Scripts\\python.exe tools\\loadtest.py --clients 20 --per-client 200
"""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.sync import InMemoryHub, InMemorySyncTransport  # noqa: E402

BATCH = "LOADTEST"


def use_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def particle_code(serial: int) -> str:
    """生成合法形状的 20 位粒子码：7 位前缀 + 13 位序号。"""

    return f"8206233{serial:013d}"


def can_code(index: int) -> str:
    return f"8021762{index:013d}"


BOX_CODE = "80217619000000001003"


@dataclass
class Metrics:
    latencies_ms: list[float] = field(default_factory=list)
    messages: int = 0
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    gaps: int = 0
    errors: list[str] = field(default_factory=list)
    lock = threading.Lock()

    def record(self, latency_ms: float, result) -> None:
        with self.lock:
            self.latencies_ms.append(latency_ms)
            self.messages += 1
            self.accepted += len(result.accepted)
            self.rejected += len(result.rejected)
            self.duplicates += len(result.duplicate)
            self.gaps += 1 if result.gap_detected else 0

    def error(self, message: str) -> None:
        with self.lock:
            self.errors.append(message)

    def summary(self, elapsed: float) -> dict[str, object]:
        latencies = sorted(self.latencies_ms)
        def pct(p: float) -> float:
            if not latencies:
                return 0.0
            index = min(len(latencies) - 1, int(len(latencies) * p))
            return latencies[index]

        return {
            "messages": self.messages,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "duplicates": self.duplicates,
            "gaps": self.gaps,
            "errors": len(self.errors),
            "throughput": round(self.messages / elapsed, 1) if elapsed > 0 else 0.0,
            "p50": round(pct(0.5), 1),
            "p95": round(pct(0.95), 1),
            "max": round(max(latencies), 1) if latencies else 0.0,
            "mean": round(statistics.fmean(latencies), 1) if latencies else 0.0,
        }


class Client(threading.Thread):
    """一个模拟移动端。每个客户端占一个罐，扫自己那一罐的粒子。"""

    def __init__(
        self,
        hub: InMemoryHub,
        index: int,
        per_client: int,
        metrics: Metrics,
        *,
        shared_can: bool = False,
    ) -> None:
        super().__init__(daemon=True)
        self.hub = hub
        self.index = index
        self.device_id = f"android-{index:02d}"
        self.per_client = per_client
        self.metrics = metrics
        self.shared_can = shared_can
        self.serial_base = 1_000_000 + index * 100_000
        self.sent_codes: list[str] = []

    def run(self) -> None:
        transport = InMemorySyncTransport(self.hub, self.device_id)
        transport.open(batch_id=BATCH, device_id=self.device_id)
        try:
            # 每台先报箱号与罐号；共享罐时所有客户端用同一个罐号（验证互斥语义）
            can_index = 1 if self.shared_can else self.index
            # 这两条的返回也要计入指标：罐号被抢占时的拒绝正是发生在这一步，
            # 不计入的话"同一罐只允许一台"就无从验证。
            for envelope in (
                transport.next_envelope(
                    [{"code": BOX_CODE, "packLayer": 3, "batchId": BATCH}]
                ),
                transport.next_envelope(
                    [{"code": can_code(can_index), "packLayer": 2, "batchId": BATCH}]
                ),
            ):
                started = time.perf_counter()
                try:
                    result = transport.send([envelope])
                except Exception as exc:  # noqa: BLE001
                    self.metrics.error(f"{self.device_id}: {exc}")
                    continue
                self.metrics.record((time.perf_counter() - started) * 1000, result)
                if result.rejected:
                    # 罐号/箱号被拒绝（例如被别的设备抢占）后不必再扫粒子
                    return

            for offset in range(self.per_client):
                code = particle_code(self.serial_base + offset)
                started = time.perf_counter()
                try:
                    result = transport.send(
                        [transport.next_envelope([{"code": code, "packLayer": 1, "batchId": BATCH}])]
                    )
                except Exception as exc:  # noqa: BLE001 - 压测要汇总所有异常
                    self.metrics.error(f"{self.device_id}: {exc}")
                    continue
                self.metrics.record((time.perf_counter() - started) * 1000, result)
                if not result.rejected:
                    self.sent_codes.append(code)
        finally:
            transport.close()


def run_connections(hub: InMemoryHub, clients: int) -> bool:
    transports = []
    for index in range(1, clients + 1):
        transport = InMemorySyncTransport(hub, f"conn-{index:02d}")
        transport.open(batch_id=BATCH, device_id=f"conn-{index:02d}")
        transports.append(transport)
    # 先取在线数再关闭：关掉之后这个数就没有意义了
    online = len(hub.online_devices())
    for transport in transports:
        transport.close()
    return online == clients


def run_concurrent_scan(hub: InMemoryHub, clients: int, per_client: int) -> tuple[Metrics, float]:
    metrics = Metrics()
    started = time.perf_counter()
    threads = [Client(hub, index, per_client, metrics) for index in range(1, clients + 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return metrics, time.perf_counter() - started


def run_shared_can(hub: InMemoryHub, clients: int, per_client: int) -> tuple[Metrics, float]:
    """所有客户端抢同一个罐号：验证互斥语义（重复罐号应被拒绝）。"""

    metrics = Metrics()
    started = time.perf_counter()
    threads = [
        Client(hub, index, per_client, metrics, shared_can=True)
        for index in range(1, clients + 1)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return metrics, time.perf_counter() - started


def run_disconnect_recovery(
    hub: InMemoryHub, clients: int, per_client: int, drop: int
) -> tuple[Metrics, float]:
    """中途断线若干台，重连后按服务端要求的序号补发。"""

    metrics = Metrics()
    started = time.perf_counter()

    transports: list[InMemorySyncTransport] = []
    for index in range(1, clients + 1):
        transport = InMemorySyncTransport(hub, f"recon-{index:02d}")
        transport.open(batch_id=BATCH, device_id=f"recon-{index:02d}")
        transports.append(transport)

    try:
        for index, transport in enumerate(transports):
            if index < drop:
                hub.disconnect(transport._device_id)  # noqa: SLF001 - 模拟断网

        for index, transport in enumerate(transports):
            for offset in range(per_client):
                code = particle_code(9_000_000 + index * 100_000 + offset)
                # 先构造信封（即"扫码动作"）。断线只是这次投递失败，
                # 重连后必须补发**同一个信封**：重新 next_envelope 会拿到新序号，
                # 旧序号永久空缺，服务端按缺口拒绝，数据就真丢了。
                envelope = transport.next_envelope(
                    [{"code": code, "packLayer": 1, "batchId": BATCH}]
                )
                try:
                    result = transport.send([envelope])
                except Exception:  # noqa: BLE001 - 断线：重连后补发同一个信封
                    hub.connect(transport._device_id)  # noqa: SLF001
                    result = transport.send([envelope])
                metrics.record(0.0, result)

                # 服务端报缺口时按它要求的序号补发（真实客户端也应如此）
                while result.gap_detected:
                    envelope.seq = result.expected_seq
                    result = transport.send([envelope])
                    metrics.record(0.0, result)
    finally:
        for transport in transports:
            transport.close()

    return metrics, time.perf_counter() - started


def main() -> int:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="20 台移动端并发压测（模拟客户端）")
    parser.add_argument("--clients", type=int, default=20)
    parser.add_argument("--per-client", type=int, default=50)
    parser.add_argument("--drop", type=int, default=5, help="场景 4 断线台数")
    parser.add_argument("--quick", action="store_true", help="缩小规模（供 CI）")
    args = parser.parse_args()

    if args.quick:
        args.clients = 20
        args.per_client = 10
        args.drop = 5

    tracemalloc.start()
    baseline, _ = tracemalloc.get_traced_memory()
    failures: list[str] = []

    def check(ok: bool, label: str, extra: str = "") -> None:
        print(f"[{' OK ' if ok else 'FAIL'}] {label}{('  ' + extra) if extra else ''}")
        if not ok:
            failures.append(label)

    print(f"规模：{args.clients} 客户端 × 每台 {args.per_client} 条")
    print()

    # ---------------------------------------------------------------- 场景 1
    hub = InMemoryHub()
    connected = InMemorySyncTransport(hub, "probe")
    check(
        run_connections(hub, args.clients),
        f"场景 1：{args.clients} 客户端同时连接",
        f"期望 {args.clients} 台",
    )
    del connected

    # ---------------------------------------------------------------- 场景 2
    hub = InMemoryHub()
    metrics, elapsed = run_concurrent_scan(hub, args.clients, args.per_client)
    summary = metrics.summary(elapsed)
    expected_total = args.clients * args.per_client
    digest = hub.state(BATCH)
    check(
        digest.particle_count == expected_total,
        "场景 2：并发扫码数据无丢失",
        f"服务端 {digest.particle_count} / 预期 {expected_total}",
    )
    check(
        digest.can_count == args.clients,
        "场景 2：各罐各就各位",
        f"罐 {digest.can_count} / 预期 {args.clients}",
    )
    check(
        summary["errors"] == 0 and summary["rejected"] == 0,
        "场景 2：无通道错误、无业务拒绝",
        f"错误 {summary['errors']}，拒绝 {summary['rejected']}",
    )
    check(
        summary["mean"] <= 200.0,
        "场景 2：平均同步延迟 ≤ 200ms（V1.1 指标）",
        f"平均 {summary['mean']}ms，P95 {summary['p95']}ms",
    )
    check(
        summary["throughput"] >= 100.0,
        "场景 2：吞吐 ≥ 100 msg/s",
        f"{summary['throughput']} msg/s",
    )

    # ---------------------------------------------------------------- 场景 3
    hub_shared = InMemoryHub()
    shared_metrics, shared_elapsed = run_shared_can(hub_shared, args.clients, 5)
    shared_summary = shared_metrics.summary(shared_elapsed)
    # 20 台都用同一个罐号 → 只有 1 台能成功，其余 19 台应被拒绝
    check(
        shared_summary["rejected"] >= args.clients - 1,
        "场景 3：同一罐被多台抢占时，仅一台成功",
        f"拒绝 {shared_summary['rejected']} 次",
    )
    check(
        hub_shared.state(BATCH).can_count == 1,
        "场景 3：服务端只记录一个罐",
        f"罐 {hub_shared.state(BATCH).can_count}",
    )

    # ---------------------------------------------------------------- 场景 4
    hub_recovery = InMemoryHub()
    recovery_metrics, recovery_elapsed = run_disconnect_recovery(
        hub_recovery, args.clients, args.per_client, args.drop
    )
    recovery_summary = recovery_metrics.summary(recovery_elapsed)
    expected_codes = args.clients * args.per_client
    check(
        hub_recovery.state(BATCH).particle_count == expected_codes,
        f"场景 4：断线 {args.drop} 台重连后补发无丢失",
        f"服务端 {hub_recovery.state(BATCH).particle_count} / 预期 {expected_codes}",
    )
    check(
        recovery_summary["errors"] == 0,
        "场景 4：补发无残留错误",
        f"错误 {recovery_summary['errors']}",
    )

    # ---------------------------------------------------------------- 场景 5
    hub_sustain = InMemoryHub()
    before, _ = tracemalloc.get_traced_memory()
    sustain_metrics, sustain_elapsed = run_concurrent_scan(
        hub_sustain, args.clients, args.per_client * 2
    )
    after, _ = tracemalloc.get_traced_memory()
    growth_mb = (after - before) / 1024 / 1024
    check(
        growth_mb <= 200.0,
        "场景 5：持续压测后内存增长可控（≤200MB）",
        f"增长 {growth_mb:.1f}MB，本轮 {sustain_metrics.messages} 条",
    )
    check(
        threading.active_count() <= args.clients + 10,
        "场景 5：无线程泄漏",
        f"活跃线程 {threading.active_count()}",
    )

    # ---------------------------------------------------------------- 摘要
    print()
    print("指标汇总（假实现，不含真实网络）")
    print(f"  平均延迟 {summary['mean']}ms  P50 {summary['p50']}ms  P95 {summary['p95']}ms  最大 {summary['max']}ms")
    print(f"  吞吐 {summary['throughput']} msg/s  消息 {summary['messages']} 条")
    print(f"  内存增长 {growth_mb:.1f}MB  峰值线程 {threading.active_count()}")
    print()

    if failures:
        print(f"压测未通过（{len(failures)} 项）：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("压测通过：脚本可用，服务端同步逻辑在 20 客户端下行为正确。")
    print("注意：本轮用的是内存假实现，**不含真实网络延迟与 WSS**；真机到位后需重跑。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
