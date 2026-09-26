"""两端联调：手机采集 → 手机导出 XML → 电脑导入 → 界面就位。

这是本次改造要打通的那条链路，一步都不跳：

    1. 电脑端建批次（定包装结构计划，手机才有"要扫几粒"的靶子）
    2. 手机拍箱号 / 罐号（单码路径；箱罐标签是一枚一码）
    3. 手机拍照上传粒子标签纸 → 服务端一次识别多枚并按顺序入格
    4. 电脑端完成整体核对（采集中 → 待核对 → 已核对）
    5. 手机端导出 XML（服务端产出，手机只保存）
    6. 电脑端导入这份 XML → 新建批次，各页面数据就位
    7. 逐项比对：导入结果与导出内容必须一致

用法：
    cd backend
    .venv\\Scripts\\python.exe tools\\mobile_roundtrip_e2e.py --out <证据目录>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.xml_parser import parse_bytes  # noqa: E402

PHOTO = BACKEND_DIR.parent / "private" / "条形码.jpg"

BOX_CODE = "80217619000000001003"
CAN_CODE = "80217629000000001005"
PLAN = (6,)
BATCH_NO = "RT-20260926"


def use_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


class Client:
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
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read()
                status = response.status
                response_headers = dict(response.headers)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            status = exc.code
            response_headers = dict(exc.headers)
        parsed: object
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        self.trace.append({"method": method, "path": path, "status": status})
        return status, parsed, body

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, payload: object | None = None):
        return self.request("POST", path, payload if payload is not None else {})

    def upload_photo(self, path: str, *, batch_id: str, filename: str) -> tuple[int, object]:
        """按 multipart/form-data 上传照片（与手机端 uni.uploadFile 的字段一致）。"""

        boundary = "----pharmrelate-e2e"
        data = PHOTO.read_bytes()
        parts = [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="batchId"\r\n\r\n',
            batch_id.encode(),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: image/jpeg\r\n\r\n",
            data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        body = b"".join(parts)
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        self.trace.append({"method": "POST", "path": path, "status": status, "multipart": True})
        try:
            parsed: object = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        return status, parsed


class Report:
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


def main() -> int:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="手机采集 → 手机导出 → 电脑导入 全流程")
    parser.add_argument("--base-url", default="http://127.0.0.1:17800")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if not PHOTO.is_file():
        print(f"找不到现场照片：{PHOTO}")
        return 1

    client = Client(args.base_url)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = Report()

    # ------------------------------------------------ 1. 电脑端建批次（定计划）
    status, created, _ = client.post(
        "/api/batches",
        {
            "batchNo": BATCH_NO,
            "madeDate": "2026-09-26",
            "validateDate": "2026-10-26",
            "plannedParticleCounts": list(PLAN),
            "box": {"code": "", "cans": []},
        },
    )
    if status != 201 or not isinstance(created, dict):
        report.check("电脑端建批次", False, f"HTTP {status}")
        return 1
    batch_id = created["id"]
    report.check("电脑端建批次（草稿 + 计划）", created.get("status") == "draft",
                 f"批号 {created.get('batchNo')} · 计划 {list(PLAN)}")
    client.post(f"/api/batches/{batch_id}/status", {"target": "collecting"})

    # ------------------------------------------- 2. 手机扫箱号 / 罐号（单码）
    _, box_frame, _ = client.post(f"/api/scan/{batch_id}/frame", {"codes": [BOX_CODE]})
    _, box_done, _ = client.post(f"/api/scan/{batch_id}/confirm")
    report.check("手机拍箱号 → 确认", box_frame.get("status") == "box_confirm" and box_done.get("status") == "can_scanning",
                 f"{box_frame.get('statusLabel')} → {box_done.get('statusLabel')}")

    _, can_frame, _ = client.post(f"/api/scan/{batch_id}/frame", {"codes": [CAN_CODE]})
    _, can_done, _ = client.post(f"/api/scan/{batch_id}/confirm")
    report.check("手机拍罐号 → 确认", can_frame.get("status") == "can_confirm" and can_done.get("status") == "particle_scanning",
                 f"{can_frame.get('statusLabel')} → {can_done.get('statusLabel')}")

    # --------------------------------------------- 3. 手机拍照上传粒子标签纸
    status, capture_body, = client.upload_photo(
        "/api/capture/upload", batch_id=batch_id, filename=PHOTO.name
    )
    capture = (capture_body or {}).get("capture", {}) if isinstance(capture_body, dict) else {}
    codes = capture.get("codes", [])
    snapshot = capture.get("snapshot") or {}
    report.check("手机上传照片 → 服务端一次识别多枚", status == 200 and len(codes) >= 6,
                 f"{len(codes)} 个码 · {capture.get('elapsedMs')} ms")
    report.check("多枚粒子按顺序一次入格", snapshot.get("actualParticleTotal") == len(codes) and snapshot.get("status") == "can_review",
                 f"状态 {snapshot.get('statusLabel')} · 已录 {snapshot.get('actualParticleTotal')} 粒")
    _, reviewed, _ = client.post(f"/api/scan/{batch_id}/confirm")
    report.check("本罐确认 → 整体核对", reviewed.get("status") == "overall_review",
                 f"状态 {reviewed.get('statusLabel')}")

    # ----------------------------------------------- 4. 电脑端完成整体核对
    for target in ("pending_review", "verified"):
        client.post(f"/api/batches/{batch_id}/status", {"target": target})
    _, review, _ = client.get(f"/api/batches/{batch_id}/review")
    report.check("整体核对通过（计划 = 实际）", isinstance(review, dict) and review.get("canExport") is True,
                 f"计划 {review.get('plan', {}).get('particleTotal')} / 实际 {review.get('actual', {}).get('particleTotal')}")

    # ------------------------------------------------- 5. 手机端导出 XML 文件
    status, _, xml_bytes = client.get(
        f"/api/export/xml?batchId={batch_id}&operator=honorANDROID_DEVICE"
    )
    report.check("手机端一步导出 XML", status == 200 and xml_bytes.startswith(b"<?xml"),
                 f"{len(xml_bytes)} 字节")
    history = client.get(f"/api/batches/{batch_id}/exports")[1]
    record = (history or {}).get("items", [{}])[0] if isinstance(history, dict) else {}
    phone_file = out / str(record.get("filename") or "phone-export.xml")
    phone_file.write_bytes(xml_bytes)
    report.check("导出记录与文件哈希一致",
                 record.get("sha256") == hashlib.sha256(xml_bytes).hexdigest(),
                 f"{phone_file.name} · {record.get('operator')}")

    # --------------------------------------- 6. 电脑端导入这份 XML（批号冲突→新版本）
    status, imported, _ = client.post(
        "/api/import/xml",
        {"xml": xml_bytes.decode("utf-8"), "sourceName": phone_file.name, "forceNewVersion": True},
    )
    if status != 200 or not isinstance(imported, dict):
        report.check("电脑端导入手机产出的 XML", False, f"HTTP {status} {imported}")
        return 1
    new_id = imported["batchId"]
    summary = imported["summary"]
    report.check("电脑端导入手机产出的 XML", summary.get("particleTotal") == len(codes),
                 f"新批次 {summary.get('batchNo')} · {summary.get('canCount')} 罐 / {summary.get('particleTotal')} 粒")

    # ------------------------------------------- 7. 比对：导入结果 = 导出内容
    parsed = parse_bytes(xml_bytes, source=phone_file.name)
    detail = client.get(f"/api/batches/{new_id}")[1]
    data = (detail or {}).get("data", {}) if isinstance(detail, dict) else {}
    imported_codes = [can["code"] for can in data.get("box", {}).get("cans", [])]
    source_codes = [can.code for can in parsed.box.cans]
    imported_particles = [list(can["particles"]) for can in data.get("box", {}).get("cans", [])]
    source_particles = [list(can.particles) for can in parsed.box.cans]
    report.check("导入后的箱号与文件一致", data.get("box", {}).get("code") == parsed.box.code,
                 f"{parsed.box.code}")
    report.check("导入后的罐号与文件一致", imported_codes == source_codes, "、".join(imported_codes))
    report.check("导入后的粒子与顺序与文件一致", imported_particles == source_particles,
                 f"逐罐 {[len(item) for item in imported_particles]}")
    report.check("导入后的计划由文件推断（计划 = 实际）",
                 data.get("plannedParticleCounts") == [len(item) for item in source_particles],
                 f"计划 {data.get('plannedParticleCounts')}")

    # 导入 → 再导出：必须回到与手机产出**完全相同的字节**（除批号后缀外）
    for target in ("collecting", "pending_review", "verified"):
        client.post(f"/api/batches/{new_id}/status", {"target": target})
    _, _, again = client.get(f"/api/export/xml?batchId={new_id}&operator=pc")
    normalised = again.replace(f'batchNo="{summary.get("batchNo")}"'.encode(), f'batchNo="{BATCH_NO}"'.encode())
    report.check("导入 → 再导出：除批号版本后缀外逐字节相同", normalised == xml_bytes,
                 f"{len(again)} 字节 vs {len(xml_bytes)} 字节")

    (out / "mobile_roundtrip_evidence.json").write_text(
        json.dumps(
            {
                "batchId": batch_id,
                "importedBatchId": new_id,
                "phoneFile": phone_file.name,
                "phoneFileSha256": hashlib.sha256(xml_bytes).hexdigest(),
                "codes": codes,
                "checks": report.items,
                "trace": client.trace,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("")
    if report.failed:
        print(f"未通过 {len(report.failed)} 项：")
        for item in report.failed:
            print(f"  - {item['label']}  {item['evidence']}")
        return 1
    print(f"全流程通过（{len(report.items)} 项）。手机产出的 XML：{phone_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
