"""一期全流程端到端驱动：电脑端 + 手机端协作跑完一整批。

为什么单独写这个工具：现有脚本各覆盖一段 —— `acceptance.py` 核 P0 清单、
`smoke_test.py` 只验证服务起得来、`frontend/e2e` 只跑界面。
这里跑的是**一条完整的现实流程**：

    识别管线读现场照片 → 扫箱号 → 扫罐号 → 录粒子 → 本罐核对
    → 下一罐 → 整体核对 → 导出 XML / HTML → 校验产物字节

其中罐 1 由电脑端完成，罐 2 / 罐 3 留给手机端（HBuilderX 基座）做完，
用来验证"两端共同喂同一个批次"这条一期核心路径。

用法：
    cd backend
    .venv\\Scripts\\python.exe tools\\phase1_e2e.py --out <证据目录> start    # 电脑端上半场
    #   ……手机端在基座里把罐 2 / 罐 3 扫完……
    .venv\\Scripts\\python.exe tools\\phase1_e2e.py --out <证据目录> finish   # 电脑端收尾 + 导出
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

PHOTO = BACKEND_DIR.parent / "private" / "条形码.jpg"

# 箱号与罐号取自阶段 0 冻结的 1箱3罐 基准（同一批真实标签）；
# 粒子码不写死 —— 它们由识别管线从现场照片里读出来，再按顺序分配到三罐。
BOX_CODE = "80217619000000001003"
CAN_CODES = (
    "80217629000000001005",
    "80217629000000001004",
    "80217629000000001006",
)
BATCH_NO = "20260926"
MADE_DATE = "2026-09-26"
VALIDATE_DATE = "2026-10-26"


def split_plan(codes: list[str], cans: int = 3) -> list[list[str]]:
    """把识别到的粒子码按罐数均分（余数优先给前面的罐）。

    计划不写死：识别管线能解出几枚，计划就装几枚 —— 现场照片是唯一事实来源。
    """

    base, remainder = divmod(len(codes), cans)
    groups: list[list[str]] = []
    cursor = 0
    for index in range(cans):
        size = base + (1 if index < remainder else 0)
        groups.append(codes[cursor : cursor + size])
        cursor += size
    return groups


def use_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


class Client:
    """极简 HTTP 客户端。带一份请求流水，作为"真的发过这些请求"的证据。"""

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")
        self.trace: list[dict[str, object]] = []

    def request(self, method: str, path: str, payload: object | None = None) -> tuple[int, object, bytes]:
        url = f"{self.base}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            body = exc.read()
            status = exc.code

        parsed: object
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        self.trace.append({"method": method, "path": path, "status": status})
        return status, parsed, body

    def get(self, path: str) -> tuple[int, object, bytes]:
        return self.request("GET", path)

    def post(self, path: str, payload: object | None = None) -> tuple[int, object, bytes]:
        return self.request("POST", path, payload if payload is not None else {})


class Report:
    """断言收集器：每条都带证据文本，最后整体落盘。"""

    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def check(self, label: str, ok: bool, evidence: str = "") -> bool:
        self.items.append({"label": label, "ok": bool(ok), "evidence": evidence})
        print(f"[{' OK ' if ok else 'FAIL'}] {label}{('  ' + evidence) if evidence else ''}")
        return ok

    def note(self, label: str, evidence: str) -> None:
        self.items.append({"label": label, "ok": True, "evidence": evidence, "note": True})
        print(f"[INFO] {label}  {evidence}")

    @property
    def failed(self) -> list[dict[str, object]]:
        return [item for item in self.items if not item["ok"]]


def short(payload: object, limit: int = 400) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


# ---------------------------------------------------------------------------
# 上半场：电脑端
# ---------------------------------------------------------------------------


def run_start(args: argparse.Namespace, report: Report) -> int:
    client = Client(args.base_url)
    out = Path(args.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    state: dict[str, object] = {"batchNo": BATCH_NO, "canCodes": list(CAN_CODES)}

    # ---------------------------------------------------------------- 基线
    status, health, _ = client.get("/api/health")
    report.check(
        "服务健康检查",
        status == 200 and isinstance(health, dict) and health.get("status") == "ok",
        f"HTTP {status} · 版本 {health.get('version') if isinstance(health, dict) else '?'}",
    )
    golden = health.get("golden", []) if isinstance(health, dict) else []
    report.check(
        "黄金基准随包可用且往返一致",
        bool(health.get("goldenOk")) and len(golden) == 2,
        "、".join(f"{item['name']}({item['byteLength']}B)" for item in golden),
    )

    # ------------------------------------------------- 识别管线读现场照片
    # 先不绑批次：这一步只回答"照片里能解出什么"，计划随后按识别结果定。
    if not PHOTO.is_file():
        report.check("现场照片存在", False, str(PHOTO))
        return 1
    report.note("现场照片", f"{PHOTO.name} · {PHOTO.stat().st_size} 字节")

    client.post("/api/camera/stop")
    status, camera, _ = client.post(
        "/api/camera/start",
        {
            "kind": "test_image",
            "images": [str(PHOTO)],
            "recognizeIntervalMs": 600,
        },
    )
    report.check(
        "启动识别管线（喂现场照片）",
        status == 200 and isinstance(camera, dict) and camera.get("running") is True,
        f"源 {camera.get('source') if isinstance(camera, dict) else '?'}",
    )

    detection: dict[str, object] = {}
    deadline = time.time() + 60
    while time.time() < deadline:
        _, payload, _ = client.get("/api/camera/detections")
        current = payload.get("detection") if isinstance(payload, dict) else None
        if isinstance(current, dict) and current.get("codes"):
            detection = current
            break
        time.sleep(2)

    photo_codes = sorted(str(code) for code in detection.get("codes", []))
    report.check(
        "识别管线从照片解出条码",
        len(photo_codes) >= 6,
        f"{len(photo_codes)} 个：{'、'.join(photo_codes)}",
    )
    report.check(
        "解出的都是粒子层条码（前缀 8206233）",
        bool(photo_codes) and all(code.startswith("8206233") for code in photo_codes),
        f"变体 {detection.get('variantsUsed') or detection.get('variants_used') or '—'}",
    )
    state["photoCodes"] = photo_codes
    (out / "evidence" / "camera_detection.json").write_text(
        json.dumps(detection, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _, _, frame_bytes = client.get("/api/camera/frame.jpg")
    if frame_bytes[:2] == b"\xff\xd8":
        (out / "evidence" / "camera_frame.jpg").write_bytes(frame_bytes)
        report.check("取流画面可取（JPEG）", True, f"{len(frame_bytes)} 字节")
    else:
        report.check("取流画面可取（JPEG）", False, f"{len(frame_bytes)} 字节")
    client.post("/api/camera/stop")

    groups = split_plan(photo_codes)
    plan = [len(group) for group in groups]
    state["plan"] = plan
    state["expectedPerCan"] = groups
    report.note("包装结构（按识别结果）", f"每罐计划 {plan} · 合计 {sum(plan)} 粒")

    # ---------------------------------------------------------------- 建批次
    create_payload = {
        "batchNo": BATCH_NO,
        "madeDate": MADE_DATE,
        "validateDate": VALIDATE_DATE,
        "plannedParticleCounts": plan,
        "box": {"code": "", "cans": []},
    }
    status, created, _ = client.post("/api/batches", create_payload)
    if status != 201 or not isinstance(created, dict):
        report.check("创建批次（草稿）", False, f"HTTP {status} {short(created)}")
        return 1
    batch_id = created["id"]
    state["batchId"] = batch_id
    report.check(
        "创建批次（草稿）",
        created.get("status") == "draft",
        f"批号 {created.get('batchNo')} · id {batch_id[:8]} · 状态 {created.get('statusLabel')}",
    )

    status, transition, _ = client.post(
        f"/api/batches/{batch_id}/status", {"target": "collecting"}
    )
    moved = (transition or {}).get("batch", {}) if isinstance(transition, dict) else {}
    report.check(
        "草稿 → 采集中（生成扫码网格）",
        status == 200 and moved.get("status") == "collecting",
        f"HTTP {status} · {moved.get('statusLabel', '')}",
    )

    status, snapshot, _ = client.get(f"/api/scan/{batch_id}/session")
    report.check(
        "进入扫码会话：等待箱号",
        isinstance(snapshot, dict) and snapshot.get("status") == "box_scanning",
        f"状态 {snapshot.get('statusLabel') if isinstance(snapshot, dict) else '?'}",
    )

    # ------------------------------------------- 识别管线接入状态机（多码报警）
    # 照片是"一张纸多枚"，在拍箱号这一步必然触发多码报警（A-11）。
    # 这一步同时证明"取流 → 识别 → 状态机"确实是连起来的。
    client.post(
        "/api/camera/start",
        {
            "kind": "test_image",
            "images": [str(PHOTO)],
            "batchId": batch_id,
            "recognizeIntervalMs": 600,
        },
    )
    camera_session: dict[str, object] = {}
    deadline = time.time() + 60
    while time.time() < deadline:
        _, payload, _ = client.get(f"/api/scan/{batch_id}/session")
        if isinstance(payload, dict) and (payload.get("lastEvent") or {}).get("code"):
            camera_session = payload
            break
        time.sleep(2)
    _, camera_session, _ = client.get(f"/api/scan/{batch_id}/session")
    last_event = camera_session.get("lastEvent") if isinstance(camera_session, dict) else None
    event_code = (last_event or {}).get("code")
    report.check(
        "识别管线结果进入状态机并触发多码报警（A-11）",
        event_code == "MULTI_CODE",
        f"事件 {event_code} · 报警计数 {camera_session.get('alarmCount')}",
    )
    client.post("/api/camera/stop")
    client.post(f"/api/scan/{batch_id}/reset")

    # ------------------------------------------------------ 拦截（用真实照片码）
    _, multi, _ = client.post(f"/api/scan/{batch_id}/frame", {"codes": photo_codes})
    report.check(
        "拍箱号时多码被拦截（整帧拒绝）",
        (multi.get("lastEvent") or {}).get("code") == "MULTI_CODE"
        and multi.get("pendingCode") == "",
        f"事件 {(multi.get('lastEvent') or {}).get('code')}",
    )

    _, wrong_layer, _ = client.post(
        f"/api/scan/{batch_id}/frame", {"codes": [photo_codes[0]]}
    )
    report.check(
        "拍箱号时喂粒子码 → 层级不符被拦截",
        (wrong_layer.get("lastEvent") or {}).get("code") == "WRONG_LAYER",
        f"事件 {(wrong_layer.get('lastEvent') or {}).get('code')}",
    )
    client.post(f"/api/scan/{batch_id}/reset")

    # ------------------------------------------------------------ 电脑端采集
    steps: list[tuple[str, bool, str]] = []

    _, box_frame, _ = client.post(f"/api/scan/{batch_id}/frame", {"codes": [BOX_CODE]})
    steps.append(
        (
            "拍箱号 → 待确认",
            box_frame.get("status") == "box_confirm" and box_frame.get("pendingCode") == BOX_CODE,
            f"状态 {box_frame.get('statusLabel')}",
        )
    )
    _, box_confirmed, _ = client.post(f"/api/scan/{batch_id}/confirm")
    steps.append(
        (
            "确认箱号 → 拍罐号",
            box_confirmed.get("status") == "can_scanning",
            f"状态 {box_confirmed.get('statusLabel')}",
        )
    )

    _, can_frame, _ = client.post(f"/api/scan/{batch_id}/frame", {"codes": [CAN_CODES[0]]})
    steps.append(
        (
            "拍罐 1 号 → 待确认",
            can_frame.get("status") == "can_confirm",
            f"状态 {can_frame.get('statusLabel')}",
        )
    )
    _, can_confirmed, _ = client.post(f"/api/scan/{batch_id}/confirm")
    steps.append(
        (
            "确认罐 1 号 → 拍粒子",
            can_confirmed.get("status") == "particle_scanning",
            f"状态 {can_confirmed.get('statusLabel')}",
        )
    )

    can1_codes = groups[0]
    _, dup, _ = client.post(
        f"/api/scan/{batch_id}/frame", {"codes": [can1_codes[0], can1_codes[0]]}
    )
    steps.append(
        (
            "同一帧内重复码被拦截（且不入库）",
            (dup.get("lastEvent") or {}).get("code") == "DUPLICATE_CODE"
            and dup.get("actualParticleTotal") == 0,
            f"事件 {(dup.get('lastEvent') or {}).get('code')} · 已录 {dup.get('actualParticleTotal')} 粒",
        )
    )

    _, filled, _ = client.post(f"/api/scan/{batch_id}/frame", {"codes": can1_codes})
    steps.append(
        (
            f"罐 1 录满 {len(can1_codes)} 粒 → 本罐核对",
            filled.get("status") == "can_review"
            and filled.get("actualParticleTotal") == len(can1_codes),
            f"状态 {filled.get('statusLabel')} · 已录 {filled.get('actualParticleTotal')} 粒",
        )
    )
    _, reviewed, _ = client.post(f"/api/scan/{batch_id}/confirm")
    steps.append(
        (
            "本罐确认 → 询问是否继续",
            reviewed.get("status") == "next_can_prompt",
            f"状态 {reviewed.get('statusLabel')}",
        )
    )
    _, next_can, _ = client.post(f"/api/scan/{batch_id}/next-can", {"proceed": True})
    steps.append(
        (
            "继续下一罐 → 等罐 2 号",
            next_can.get("status") == "can_scanning" and next_can.get("currentCanIndex") == 2,
            f"状态 {next_can.get('statusLabel')} · 当前第 {next_can.get('currentCanIndex')} 罐",
        )
    )
    for label, ok, evidence in steps:
        report.check(label, bool(ok), str(evidence))

    # 缺漏时导出必须被拒（A-06），此时罐 2/3 还没扫
    status, blocked, _ = client.post(
        f"/api/batches/{batch_id}/export", {"kinds": ["xml"], "operator": "e2e"}
    )
    reason = ((blocked or {}).get("error", {}) or {}).get("detail", {}) if isinstance(blocked, dict) else {}
    report.check(
        "缺漏未扫完时导出被拒（A-06）",
        status == 409,
        f"HTTP {status} · reason {reason.get('reason')} · {(blocked or {}).get('error', {}).get('message', '') if isinstance(blocked, dict) else ''}",
    )

    state["can1Codes"] = can1_codes
    (out / "phase1_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "evidence" / "trace_start.json").write_text(
        json.dumps(client.trace, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "evidence" / "phase1_evidence_start.json").write_text(
        json.dumps(
            {"batchId": batch_id, "plan": plan, "photoCodes": photo_codes, "checks": report.items},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("")
    print(f"电脑端上半场结束：批次 {batch_id[:8]} 已完成箱号 + 罐 1，当前等待罐 2 号。")
    print(f"粒子码分配：罐1 {groups[0]} / 罐2 {groups[1]} / 罐3 {groups[2]}")
    return 0 if not report.failed else 1


# ---------------------------------------------------------------------------
# 收尾：核对 + 导出 + 校验
# ---------------------------------------------------------------------------


def verify_xml(xml_bytes: bytes, state: dict[str, object], report: Report) -> None:
    text = xml_bytes.decode("utf-8")
    report.check(
        "XML 无 BOM",
        not xml_bytes.startswith(b"\xef\xbb\xbf"),
        f"前 3 字节 {xml_bytes[:3].hex()}",
    )
    report.check(
        "XML 纯 LF 且末尾恰好一个换行",
        b"\r\n" not in xml_bytes and xml_bytes.endswith(b"\n") and not xml_bytes.endswith(b"\n\n"),
        f"CRLF {xml_bytes.count(b'\\r\\n')} 处",
    )
    first_line = text.split("\n", 1)[0]
    report.check(
        "第 1 行 = XML 声明紧接根节点",
        first_line.startswith("<?xml ") and "<Document " in first_line,
        first_line[:110] + "…",
    )
    report.check(
        "Document 属性顺序（xmlns:xsi → noNamespaceSchemaLocation → License）",
        re.search(
            r'<Document\s+xmlns:xsi="[^"]+"\s+xsi:noNamespaceSchemaLocation="[^"]+"\s+License="[^"]+"',
            first_line,
        )
        is not None,
    )
    relation = re.search(r"<Relation\s+[^>]*>", text)
    report.check(
        "Relation 属性顺序（productCode → subTypeNo → cascade → packageSpec → comment）",
        relation is not None
        and re.match(
            r'<Relation\s+productCode="[^"]*"\s+subTypeNo="[^"]*"\s+cascade="[^"]*"\s+'
            r'packageSpec="[^"]*"\s+comment="[^"]*"',
            relation.group(0),
        )
        is not None,
    )
    batch = re.search(r"<Batch\s+[^>]*>", text)
    report.check(
        "Batch 属性顺序（batchNo → madeDate → validateDate → workshop → lineName → lineManager）",
        batch is not None
        and re.match(
            r'<Batch\s+batchNo="[^"]*"\s+madeDate="[^"]*"\s+validateDate="[^"]*"\s+'
            r'workshop="[^"]*"\s+lineName="[^"]*"\s+lineManager="[^"]*"',
            batch.group(0),
        )
        is not None,
    )
    cascade = re.search(r'cascade="([^"]*)"', text)
    report.check(
        "cascade 为固定字面量（不随实际结构变化）",
        cascade is not None and cascade.group(1) == "1:5:2500",
        f"cascade={cascade.group(1) if cascade else '?'}",
    )

    code_lines = [line for line in text.split("\n") if line.startswith("<Code ")]
    expected_codes = 1 + len(state.get("canCodes", [])) + len(state.get("photoCodes", []))
    report.check(
        "每个 <Code/> 独占一行、无缩进",
        len(code_lines) == expected_codes and all(not line.startswith(" ") for line in code_lines),
        f"Code 行数 {len(code_lines)}（1 箱 + {len(state.get('canCodes', []))} 罐"
        f" + {len(state.get('photoCodes', []))} 粒子）",
    )
    order_ok = all(
        re.match(
            # 箱号行不带 parentCode（与冻结基准一致），罐与粒子行带
            r'<Code\s+curCode="[^"]*"\s+packLayer="[^"]*"'
            r'(?:\s+parentCode="[^"]*")?\s+flag="[^"]*"/?>',
            line,
        )
        for line in code_lines
    )
    report.check("Code 属性顺序（curCode → packLayer → parentCode → flag）", order_ok)

    actual_particles: list[list[str]] = []
    for expected in state.get("expectedPerCan", []):
        position = text.find(f'curCode="{expected[0]}"')
        actual_particles.append([expected[0]] if position >= 0 else [])
    # 逐罐按采集顺序校验：粒子之间的相对顺序必须与录入顺序一致
    sequence_ok = True
    for expected in state.get("expectedPerCan", []):
        offsets = [text.find(f'curCode="{code}"') for code in expected]
        if any(offset < 0 for offset in offsets) or offsets != sorted(offsets):
            sequence_ok = False
    report.check("粒子顺序 = 采集原始顺序（未排序）", sequence_ok)


def run_finish(args: argparse.Namespace, report: Report) -> int:
    out = Path(args.out).resolve()
    state_path = out / "phase1_state.json"
    if not state_path.is_file():
        print(f"找不到状态文件 {state_path}，请先跑 start。")
        return 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    batch_id = str(state["batchId"])
    client = Client(args.base_url)

    # ------------------------------------------------------- 手机端的结果核对
    _, snapshot, _ = client.get(f"/api/scan/{batch_id}/session")
    report.check(
        "手机端已完成罐 2 / 罐 3（会话到达整体核对）",
        isinstance(snapshot, dict) and snapshot.get("status") == "overall_review",
        f"状态 {snapshot.get('statusLabel') if isinstance(snapshot, dict) else '?'}"
        f" · 已录 {snapshot.get('actualParticleTotal') if isinstance(snapshot, dict) else '?'} 粒",
    )
    report.check(
        f"实际粒子总数 = 计划 {sum(state.get('plan', []))}",
        snapshot.get("actualParticleTotal") == sum(state.get("plan", []))
        and snapshot.get("missingParticles") == 0,
        f"计划 {snapshot.get('plannedParticleTotal')} · 实际 {snapshot.get('actualParticleTotal')}"
        f" · 缺 {snapshot.get('missingParticles')}",
    )
    per_can = snapshot.get("canParticles") if isinstance(snapshot, dict) else None
    expected = state.get("expectedPerCan", [])
    report.check(
        "逐罐粒子码与分配一致",
        [sorted(item) for item in (per_can or [])] == [sorted(item) for item in expected],
        short(per_can),
    )
    (out / "evidence" / "session_final.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ------------------------------------------- 采集中 → 待核对 → 已核对
    # 真实流程里这一步由「预览导出」页完成：核对通过才能导出。
    status, moved, _ = client.post(
        f"/api/batches/{batch_id}/status", {"target": "pending_review"}
    )
    batch_after = (moved or {}).get("batch", {}) if isinstance(moved, dict) else {}
    report.check(
        "采集中 → 待核对",
        status == 200 and batch_after.get("status") == "pending_review",
        f"HTTP {status} · {batch_after.get('statusLabel', '')}",
    )

    status, review, _ = client.get(f"/api/batches/{batch_id}/review")
    plan_total = ((review or {}).get("plan") or {}).get("particleTotal")
    actual_total = ((review or {}).get("actual") or {}).get("particleTotal")
    checks = (review or {}).get("checks", [])
    report.check(
        "整体核对：计划 vs 实际逐罐对照通过",
        status == 200
        and plan_total == actual_total == sum(state.get("plan", []))
        and (review or {}).get("missingParticles") == 0
        and all(item.get("passed") for item in checks),
        f"计划 {plan_total} / 实际 {actual_total} · 检查项 "
        + "、".join(f"{item['code']}={'✓' if item['passed'] else '✗'}" for item in checks),
    )
    (out / "evidence" / "review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    status, moved, _ = client.post(f"/api/batches/{batch_id}/status", {"target": "verified"})
    batch_after = (moved or {}).get("batch", {}) if isinstance(moved, dict) else {}
    report.check(
        "待核对 → 已核对（核对通过）",
        status == 200 and batch_after.get("status") == "verified",
        f"HTTP {status} · {batch_after.get('statusLabel', '')}",
    )
    _, review_after, _ = client.get(f"/api/batches/{batch_id}/review")
    report.check(
        "已核对后导出闸门打开",
        (review_after or {}).get("canExport") is True and not (review_after or {}).get("blocking"),
        f"canExport {(review_after or {}).get('canExport')} · 阻断项 {len((review_after or {}).get('blocking', []))}",
    )

    # ---------------------------------------------------------------- 导出
    status, exported, _ = client.post(
        f"/api/batches/{batch_id}/export", {"kinds": ["xml", "html"], "operator": "现场操作员"}
    )
    if status != 200 or not isinstance(exported, dict):
        report.check("导出 XML + HTML", False, f"HTTP {status} {short(exported)}")
        return 1
    items = exported.get("items", [])
    report.check(
        "导出 XML + HTML",
        len(items) == 2 and {item["kind"] for item in items} == {"xml", "html"},
        "、".join(f"{item['kind']} {item['byteLength']}B" for item in items),
    )

    saved: dict[str, Path] = {}
    for item in items:
        record_id = item["id"]
        _, body, raw = client.get(f"/api/exports/{record_id}/download")
        target = out / item["filename"]
        target.write_bytes(raw)
        saved[item["kind"]] = target
        report.check(
            f"下载并保存 {item['kind'].upper()}",
            raw is not None and len(raw) == item["byteLength"],
            f"{target.name} · {len(raw)} 字节",
        )
        report.check(
            f"{item['kind'].upper()} 的 SHA-256 与导出记录一致",
            hashlib_sha256(raw) == item["sha256"],
            item["sha256"][:16] + "…",
        )

    xml_path = saved.get("xml")
    if xml_path is not None:
        verify_xml(xml_path.read_bytes(), state, report)

    # ---------------------------------------------------------- 审计与状态
    _, audit, _ = client.get(f"/api/audit?batch_id={batch_id}&limit=500")
    entries = audit.get("items", []) if isinstance(audit, dict) else []
    actions: dict[str, int] = {}
    for entry in entries:
        actions[entry.get("action", "?")] = actions.get(entry.get("action", "?"), 0) + 1
    report.check(
        "审计日志覆盖扫码与报警",
        actions.get("scan", 0) > 0 and actions.get("scan_alarm", 0) > 0,
        "、".join(f"{key}×{value}" for key, value in sorted(actions.items())),
    )
    (out / "evidence" / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _, detail, _ = client.get(f"/api/batches/{batch_id}")
    report.check(
        "导出后批次状态推进为「已导出」",
        isinstance(detail, dict) and detail.get("status") == "exported",
        f"状态 {detail.get('statusLabel') if isinstance(detail, dict) else '?'}",
    )

    # ---------------------------------------------------- A-06 缺漏闸门单测
    # 另起一个批次：计划 3 粒、实际 0 粒，走到「已核对」后导出仍必须被拒。
    _, partial, _ = client.post(
        "/api/batches",
        {
            "batchNo": f"{BATCH_NO}-A06",
            "madeDate": MADE_DATE,
            "validateDate": VALIDATE_DATE,
            "plannedParticleCounts": [3],
            "box": {"code": "", "cans": []},
        },
    )
    if isinstance(partial, dict) and partial.get("id"):
        partial_id = partial["id"]
        for target in ("collecting", "pending_review", "verified"):
            client.post(f"/api/batches/{partial_id}/status", {"target": target})
        status, blocked, _ = client.post(
            f"/api/batches/{partial_id}/export", {"kinds": ["xml"], "operator": "e2e"}
        )
        error = (blocked or {}).get("error", {}) if isinstance(blocked, dict) else {}
        report.check(
            "A-06 缺漏时导出被拒（计划 3 粒 / 实际 0 粒）",
            status == 409,
            f"HTTP {status} · reason {error.get('detail', {}).get('reason')} · {error.get('message', '')}",
        )
    else:
        report.check("A-06 缺漏时导出被拒（计划 3 粒 / 实际 0 粒）", False, short(partial))

    (out / "evidence" / "trace_finish.json").write_text(
        json.dumps(client.trace, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    evidence = {
        "batchNo": state.get("batchNo"),
        "batchId": batch_id,
        "photoCodes": state.get("photoCodes"),
        "perCan": state.get("expectedPerCan"),
        "checks": report.items,
        "auditActions": actions,
        "exports": items,
    }
    (out / "evidence" / "phase1_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if not report.failed else 1


def hashlib_sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def main() -> int:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="一期全流程端到端驱动")
    parser.add_argument("stage", choices=("start", "finish"))
    parser.add_argument("--base-url", default="http://127.0.0.1:17800")
    parser.add_argument("--out", required=True, help="证据与产物目录")
    args = parser.parse_args()

    report = Report()
    code = run_start(args, report) if args.stage == "start" else run_finish(args, report)

    print("")
    if report.failed:
        print(f"未通过 {len(report.failed)} 项：")
        for item in report.failed:
            print(f"  - {item['label']}  {item['evidence']}")
        return 1
    print(f"全部通过（{len(report.items)} 项）。")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
