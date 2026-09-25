"""P0 验收清单自动核对（阶段 5）。

对照 V1.1 第 15 章的补充验收清单，一期覆盖 8 项（A-01/02/05/06/08/09/11/14）。
这里把能自动化的部分真正跑一遍，而不是在报告里打勾 ——
验收报告里的结论必须由可复现的检查产出。

用法：
    cd backend
    .venv\\Scripts\\python.exe tools\\acceptance.py
    .venv\\Scripts\\python.exe tools\\acceptance.py --markdown reports/验收报告.md
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Database  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import golden  # noqa: E402
from app.services.xml_parser import parse_bytes  # noqa: E402

BOX = "80217619000000001003"
CAN1 = "80217629000000001005"
CAN2 = "80217629000000001004"


@dataclass
class Item:
    code: str
    title: str
    expected: str
    passed: bool = False
    evidence: str = ""
    notes: list[str] = field(default_factory=list)


def use_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def golden_payload(batch_no: str) -> dict[str, object]:
    batch = parse_bytes(golden.read_bytes("1箱3罐.xml"))
    return {
        "batchNo": batch_no,
        "madeDate": batch.made_date,
        "validateDate": batch.validate_date,
        "plannedParticleCounts": [len(can.particles) for can in batch.box.cans],
        "box": {
            "code": batch.box.code,
            "cans": [
                {
                    "index": can.index,
                    "code": can.code,
                    "plannedParticleCount": len(can.particles),
                    "particles": list(can.particles),
                }
                for can in batch.box.cans
            ],
        },
    }


def run(client: TestClient) -> list[Item]:
    items: list[Item] = []

    # ---------------------------------------------------------------- A-01
    item = Item("A-01", "批次状态流转", "状态不可逆向跳跃，锁定后不可编辑")
    batch_id = client.post("/api/batches", json=golden_payload("A01")).json()["id"]
    skipped = client.post(f"/api/batches/{batch_id}/status", json={"target": "verified"})
    for target in ("collecting", "pending_review", "verified", "exported", "locked"):
        client.post(f"/api/batches/{batch_id}/status", json={"target": target})
    readonly = client.put(f"/api/batches/{batch_id}", json=golden_payload("A01"))
    item.passed = skipped.status_code == 409 and readonly.status_code == 409
    item.evidence = f"跳级流转 HTTP {skipped.status_code}；锁定后写入 HTTP {readonly.status_code}"
    items.append(item)

    # ---------------------------------------------------------------- A-02
    item = Item("A-02", "重复批号拦截", "提示打开已有/创建新版本/取消")
    client.post("/api/batches", json=golden_payload("A02"))
    conflict = client.post("/api/batches", json=golden_payload("A02"))
    options = conflict.json().get("error", {}).get("detail", {}).get("options", [])
    suggested = conflict.json().get("error", {}).get("detail", {}).get("suggestedBatchNo", "")
    item.passed = conflict.status_code == 409 and len(options) == 3 and bool(suggested)
    item.evidence = f"HTTP {conflict.status_code}；三个选项：{[o['action'] for o in options]}；建议新版本 {suggested}"
    items.append(item)

    # ---------------------------------------------------------------- A-05
    item = Item("A-05", "粒子槽位替换", "可替换、删除、撤销、重做")
    batch_id = client.post("/api/batches", json=golden_payload("A05")).json()["id"]
    client.post(f"/api/batches/{batch_id}/status", json={"target": "collecting"})
    target = parse_bytes(golden.read_bytes("1箱3罐.xml")).box.cans[2].particles[0]
    spare = "82062339000000001005"
    replaced = client.post(
        f"/api/batches/{batch_id}/slots/replace", json={"code": target, "newCode": spare}
    )
    deleted = client.post(f"/api/batches/{batch_id}/slots/delete", json={"code": spare})
    undone = client.post(f"/api/batches/{batch_id}/undo")
    redone = client.post(f"/api/batches/{batch_id}/redo")
    history = client.get(f"/api/batches/{batch_id}/history").json()
    operations = (replaced, deleted, undone, redone)
    item.passed = all(r.status_code == 200 for r in operations) and history["maxSteps"] >= 50
    item.evidence = (
        f"替换/删除/撤销/重做 HTTP {[r.status_code for r in operations]}；"
        f"撤销栈上限 {history['maxSteps']} 步"
    )
    items.append(item)

    # ---------------------------------------------------------------- A-06
    item = Item("A-06", "缺漏槽位导出拦截", "缺漏时禁止导出，提前结束需签名")
    batch_id = client.post("/api/batches", json=golden_payload("A06")).json()["id"]
    for status in ("collecting", "pending_review", "verified"):
        client.post(f"/api/batches/{batch_id}/status", json={"target": status})
    target = parse_bytes(golden.read_bytes("1箱3罐.xml")).box.cans[2].particles[0]
    client.post(f"/api/batches/{batch_id}/slots/delete", json={"code": target})
    client.post(f"/api/batches/{batch_id}/status", json={"target": "pending_review"})
    client.post(f"/api/batches/{batch_id}/status", json={"target": "verified"})

    blocked = client.post(f"/api/batches/{batch_id}/export", json={"kinds": ["xml"]})
    unsigned = client.post(
        f"/api/batches/{batch_id}/early-end", json={"reason": " ", "operator": ""}
    )
    client.post(
        f"/api/batches/{batch_id}/early-end",
        json={"reason": "药液不足", "operator": "操作员甲", "note": ""},
    )
    allowed = client.post(f"/api/batches/{batch_id}/export", json={"kinds": ["xml"]})
    item.passed = (
        blocked.status_code == 409
        and unsigned.status_code == 422
        and allowed.status_code == 200
        and allowed.json()["exportKind"] == "early_end"
    )
    item.evidence = (
        f"缺漏导出 HTTP {blocked.status_code}；无签名提前结束 HTTP {unsigned.status_code}；"
        f"签名后导出 HTTP {allowed.status_code}（{allowed.json().get('exportKind')}）"
    )
    items.append(item)

    # ---------------------------------------------------------------- A-08
    item = Item("A-08", "审计日志", "关键操作可追溯，不可删除")
    entries = client.get(f"/api/audit?batchId={batch_id}").json()["items"]
    schema = client.get("/openapi.json").json()
    # 审计只增不改：接口层不能出现删除入口
    deletable = any(
        "delete" in schema["paths"].get(path, {})
        for path in schema["paths"]
        if path.startswith("/api/audit") or path.startswith("/api/exports")
    )
    actions = {entry["action"] for entry in entries}
    item.passed = bool(entries) and not deletable and "export" in actions
    item.evidence = f"该批次审计 {len(entries)} 条，动作含 {sorted(actions)}；审计接口无删除入口"
    items.append(item)

    # ---------------------------------------------------------------- A-09
    item = Item("A-09", "12500 粒子导出", "导出时间 ≤ 3s，XML 正确")
    plan = [2500] * 5
    batch_id = client.post(
        "/api/batches",
        json={
            "batchNo": "A09",
            "madeDate": "2026-09-23",
            "validateDate": "2026-10-23",
            "plannedParticleCounts": plan,
            "box": {"code": BOX, "cans": []},
        },
    ).json()["id"]
    # 直接按结构生成 12500 条粒子：走界面要扫一万多次，验收只看导出性能
    cans = []
    counter = 0
    for can in range(1, 6):
        particles = []
        for _ in range(2500):
            counter += 1
            particles.append(f"8206233{counter:013d}")
        cans.append(
            {
                "index": can,
                # 定长 20 位：7 位前缀 + 13 位序号
                "code": f"8021762{can:013d}",
                "plannedParticleCount": 2500,
                "particles": particles,
            }
        )
    client.put(
        f"/api/batches/{batch_id}",
        json={
            "batchNo": "A09",
            "madeDate": "2026-09-23",
            "validateDate": "2026-10-23",
            "plannedParticleCounts": plan,
            "box": {"code": BOX, "cans": cans},
        },
    )
    for status in ("collecting", "pending_review", "verified"):
        client.post(f"/api/batches/{batch_id}/status", json={"target": status})
    started = time.perf_counter()
    exported = client.post(f"/api/batches/{batch_id}/export", json={"kinds": ["xml", "html"]})
    elapsed = time.perf_counter() - started
    items_payload = exported.json().get("items", []) if exported.status_code == 200 else []
    xml_size = next((i["byteLength"] for i in items_payload if i["kind"] == "xml"), 0)
    item.passed = exported.status_code == 200 and elapsed <= 3.0 and xml_size > 0
    item.evidence = (
        f"12500 粒导出 XML+HTML 耗时 {elapsed:.2f}s（指标 ≤3s），"
        f"XML {xml_size:,} 字节"
    )
    if elapsed > 3.0:
        item.notes.append("超出 3s 指标")
    items.append(item)

    # ---------------------------------------------------------------- A-11
    item = Item("A-11", "多码报警", "声音 + 视觉双重提示")
    # 用一个"有计划但还没扫"的批次：已扫满的批次状态在整体核对，不接受新的识别结果
    batch_id = client.post(
        "/api/batches",
        json={
            "batchNo": "A11",
            "madeDate": "2026-09-23",
            "validateDate": "2026-10-23",
            "plannedParticleCounts": [2],
            "box": {"code": "", "cans": []},
        },
    ).json()["id"]
    client.post(f"/api/batches/{batch_id}/status", json={"target": "collecting"})
    snapshot = client.post(
        f"/api/scan/{batch_id}/frame", json={"codes": [BOX, "80217619000000001004"]}
    ).json()
    event = snapshot["lastEvent"]
    # 后端负责"该不该报警"，前端负责"怎么报"（声音 WebAudio + 视觉告警条）
    item.passed = (
        event["code"] == "MULTI_CODE"
        and event["needsAlarm"] is True
        and event["blocking"] is True
        and snapshot["alarmCount"] >= 1
        and snapshot["actualParticleTotal"] == 0
    )
    item.evidence = (
        f"多码事件 {event['code']}，needsAlarm={event['needsAlarm']}，"
        f"阻断且未写入（实际粒子 0）"
    )
    item.notes.append("视觉提示由 E2E 验证；声音输出需在有扬声器的机器上人工确认")
    items.append(item)

    # ---------------------------------------------------------------- A-14
    item = Item("A-14", "导出文件哈希", "每次导出生成 SHA-256")
    # 批号必须与基准样例一致，导出的 XML 才能与冻结基准逐字节比对
    batch_id = client.post("/api/batches", json=golden_payload("20260901")).json()["id"]
    for status in ("collecting", "pending_review", "verified"):
        client.post(f"/api/batches/{batch_id}/status", json={"target": status})
    exported = client.post(
        f"/api/batches/{batch_id}/export", json={"kinds": ["xml", "html"]}
    ).json()["items"]
    baseline = golden.sha256_of(golden.read_bytes("1箱3罐.xml"))
    xml_item = next(i for i in exported if i["kind"] == "xml")
    downloaded = client.get(f"/api{xml_item['downloadUrl']}")
    item.passed = (
        len(xml_item["sha256"]) == 64
        and xml_item["sha256"] == baseline
        and downloaded.headers["X-Content-SHA256"] == baseline
        and downloaded.content == golden.read_bytes("1箱3罐.xml")
    )
    item.evidence = (
        f"SHA-256 {baseline[:16]}… 与阶段 0 冻结基准一致；"
        f"下载响应头哈希一致；文件 {xml_item['byteLength']} 字节逐字节相同"
    )
    items.append(item)

    return items


def render_markdown(items: list[Item]) -> str:
    lines = [
        "| 编号 | 验收项 | 预期结果 | 结论 | 证据 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in items:
        mark = "通过" if item.passed else "**未通过**"
        lines.append(
            f"| {item.code} | {item.title} | {item.expected} | {mark} | {item.evidence} |"
        )
    return "\n".join(lines)


def main() -> int:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="P0 验收清单自动核对")
    parser.add_argument("--markdown", type=Path, help="把结果表格写入指定文件")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="pharmrelate-acceptance-") as tmp:
        client = TestClient(create_app(database=Database(Path(tmp) / "acceptance.db")))
        items = run(client)

    print("P0 验收清单（一期覆盖项）")
    print("=" * 78)
    for item in items:
        print(f"[{'通过' if item.passed else '未通过'}] {item.code} {item.title}")
        print(f"        预期：{item.expected}")
        print(f"        证据：{item.evidence}")
        for note in item.notes:
            print(f"        备注：{note}")

    failed = [item for item in items if not item.passed]
    print()
    print(f"合计 {len(items)} 项，通过 {len(items) - len(failed)} 项，未通过 {len(failed)} 项。")

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(items) + "\n", encoding="utf-8")
        print(f"已写入 {args.markdown}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
