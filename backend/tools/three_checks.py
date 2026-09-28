"""三条关键结论的一键复核（验收前抽检用）。

对应 `docs/58-三条复核清单.md` 的三条：
    1. 导入 `private/1箱3罐.XML` → 再导出 → SHA-256 是否一致
    2. 上传 `private/条形码.jpg` → 是否一次识别出 6 个粒子码
    3. 导出记录里的 SHA-256 是否与文件内容一致

**为什么要写成脚本而不是一串 curl：**
    - 导入接口收的是 JSON（`{"xml": "..."}`），不是文件上传；curl 传文件会 422；
    - 导出接口是 GET + 查询参数，不是 POST + JSON；
    - 拍照上传的字段名是 `photo`，不是 `file`；
    - 导入进来的批次是"草稿"，必须先流转到"已核对"才允许导出，否则 409。
    这些坑写进命令清单会让复核人卡住，所以固化成脚本，一条命令跑完并打印可抄写的证据。

用法：
    cd backend
    .venv\\Scripts\\python.exe tools\\three_checks.py
    .venv\\Scripts\\python.exe tools\\three_checks.py --base-url http://127.0.0.1:17800 --out <证据目录>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

GOLDEN_FILE = REPO_DIR / "private" / "1箱3罐.XML"
PHOTO_FILE = REPO_DIR / "private" / "条形码.jpg"


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

    def request(self, method: str, path: str, payload: object | None = None):
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{self.base}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                # 响应头的键名大小写不固定（HTTP/1.1 实际发的是小写），统一转小写再比对
                return (
                    response.status,
                    response.read(),
                    {key.lower(): value for key, value in response.headers.items()},
                )
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), {key.lower(): value for key, value in exc.headers.items()}

    def get(self, path: str):
        return self.request("GET", path)

    def post(self, path: str, payload: object | None = None):
        return self.request("POST", path, payload if payload is not None else {})

    def upload_photo(self, path: str, file_path: Path, *, batch_id: str = ""):
        boundary = "----pharmrelate-check"
        parts = [f"--{boundary}\r\n".encode()]
        if batch_id:
            parts += [
                b'Content-Disposition: form-data; name="batchId"\r\n\r\n',
                batch_id.encode(),
                b"\r\n",
                f"--{boundary}\r\n".encode(),
            ]
        parts += [
            f'Content-Disposition: form-data; name="photo"; filename="{file_path.name}"\r\n'.encode(),
            b"Content-Type: image/jpeg\r\n\r\n",
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=b"".join(parts),
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="三条关键结论复核")
    parser.add_argument("--base-url", default="http://127.0.0.1:17800")
    parser.add_argument("--out", default="", help="导出文件与报告的存放目录")
    args = parser.parse_args()

    if not GOLDEN_FILE.is_file() or not PHOTO_FILE.is_file():
        print(f"缺少输入文件：{GOLDEN_FILE} / {PHOTO_FILE}")
        return 1

    out_dir = Path(args.out).resolve() if args.out else (REPO_DIR / "private" / "测试输出" / "三条复核-20260927")
    out_dir.mkdir(parents=True, exist_ok=True)

    client = Client(args.base_url)
    failures: list[str] = []

    def check(ok: bool, label: str, evidence: str = "") -> None:
        print(f"[{' OK ' if ok else 'FAIL'}] {label}{('  ' + evidence) if evidence else ''}")
        if not ok:
            failures.append(label)

    original = GOLDEN_FILE.read_bytes()
    original_hash = sha256(original)

    # ------------------------------------------------------------ 复核 1
    print("==== 复核 1：导入 → 再导出 ====")
    status, _, _ = client.get("/api/health")
    check(status == 200, "服务可用（GET /api/health）", f"HTTP {status}")
    print(f"       原始文件 {GOLDEN_FILE.name}：{len(original)} 字节 · SHA-256 {original_hash}")

    status, body, _ = client.post(
        "/api/import/xml",
        {"xml": original.decode("utf-8"), "sourceName": GOLDEN_FILE.name, "forceNewVersion": True},
    )
    imported = json.loads(body.decode("utf-8"))
    if status != 200:
        check(False, "导入 XML", f"HTTP {status} {imported}")
        return 1
    batch_id = imported["batchId"]
    summary = imported["summary"]
    check(
        summary["particleTotal"] == 4 and summary["canCount"] == 3,
        "导入解析正确",
        f"批号 {summary['batchNo']} · {summary['canCount']} 罐 / {summary['particleTotal']} 粒",
    )

    # 导入进来是草稿；导出闸门要求"已核对"，这一步不能省（否则 409）
    for target in ("collecting", "pending_review", "verified"):
        client.post(f"/api/batches/{batch_id}/status", {"target": target})
    _, review_body, _ = client.get(f"/api/batches/{batch_id}/review")
    review = json.loads(review_body.decode("utf-8"))
    check(review["canExport"] is True, "核对通过、允许导出", f"计划 {review['plan']['particleTotal']} / 实际 {review['actual']['particleTotal']}")

    status, exported, headers = client.get(f"/api/export/xml?batchId={batch_id}&operator=three-checks")
    check(status == 200, "导出 XML", f"HTTP {status}")
    exported_file = out_dir / "复核1-导出的XML.xml"
    exported_file.write_bytes(exported)
    exported_hash = sha256(exported)
    print(f"       导出文件 {exported_file.name}：{len(exported)} 字节 · SHA-256 {exported_hash}")

    suffix = str(summary["batchNo"]).replace("20260901", "")
    expected = original.replace(b'batchNo="20260901"', f'batchNo="20260901{suffix}"'.encode())
    if suffix == "":
        check(exported_hash == original_hash, "两个 SHA-256 完全相同", "批号未被占用，严格比对")
    else:
        check(
            exported == expected,
            "除批号版本后缀外逐字节相同",
            f"批号 {summary['batchNo']}（原批号已被占用，导出按新版本号写入）",
        )
        check(
            exported_hash == sha256(expected),
            f"哈希等于「原文件按批号 {summary['batchNo']} 重算」的值",
            sha256(expected),
        )
    check(
        headers.get("x-content-sha256") == exported_hash,
        "响应头 X-Content-SHA256 与文件一致",
        headers.get("x-content-sha256", "（缺失）"),
    )

    # ------------------------------------------------------------ 复核 2
    print("")
    print("==== 复核 2：上传条形码.jpg ====")
    status, body = client.upload_photo("/api/capture/upload", PHOTO_FILE)
    capture_body = json.loads(body.decode("utf-8"))
    if status != 200:
        check(False, "上传照片", f"HTTP {status} {capture_body}")
        return 1
    capture = capture_body["capture"]
    codes = capture["codes"]
    check(len(codes) == 6, "识别出 6 个粒子码", f"{len(codes)} 个 · {capture['elapsedMs']} ms")
    check(all(str(code).startswith("8206233") for code in codes), "全部是粒子层前缀 8206233")
    check(all(len(str(code)) == 20 and str(code).isdigit() for code in codes), "全部是 20 位数字")
    check(capture["conflicts"] == [], "无同区域冲突", f"conflicts={len(capture['conflicts'])}")
    print("       " + "、".join(str(code) for code in codes))

    # ------------------------------------------------------------ 复核 3
    print("")
    print("==== 复核 3：导出记录的 SHA-256 与文件一致 ====")
    _, history_body, _ = client.get(f"/api/batches/{batch_id}/exports")
    history = json.loads(history_body.decode("utf-8"))
    check(history["total"] >= 1, "导出记录存在", f"{history['total']} 条")
    record = history["items"][0]
    print(f"       记录：{record['filename']} · {record['byteLength']} 字节 · SHA-256 {record['sha256']}")

    _, downloaded, _ = client.get(f"/api/exports/{record['id']}/download")
    check(record["sha256"] == sha256(downloaded), "记录哈希 = 下载内容重算值", sha256(downloaded))
    check(len(downloaded) == record["byteLength"], "记录字节数 = 下载长度", f"{len(downloaded)}")
    check(
        re.match(r"^Relation_20260901(-V\d+)?_\d{14}\.xml$", record["filename"]) is not None,
        "文件名符合 Relation_{批号}_{时间戳}.xml",
        record["filename"],
    )

    # 服务端落盘的那一份（复核人可以自己 certutil 再算一遍）
    # 记录里服务端落盘路径的字段名是 storedAt（文件本体在数据目录 exports/{批号}/ 下）
    stored_raw = record.get("storedAt") or record.get("filePath")
    stored = Path(str(stored_raw)) if stored_raw else None
    if stored and stored.is_file():
        check(record["sha256"] == sha256(stored.read_bytes()), "记录哈希 = 服务端落盘文件重算值", str(stored))
    else:
        print(f"       （记录未提供 filePath，落盘位置：{out_dir.parent / 'data' / 'exports'}）")

    payload = {
        "batchId": batch_id,
        "batchNo": summary["batchNo"],
        "original": {"file": GOLDEN_FILE.name, "bytes": len(original), "sha256": original_hash},
        "exported": {"file": exported_file.name, "bytes": len(exported), "sha256": exported_hash},
        "codes": codes,
        "exportRecord": {k: record.get(k) for k in ("filename", "byteLength", "sha256", "operator")},
        "failed": failures,
    }
    (out_dir / "三条复核结果.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("")
    if failures:
        print(f"复核未通过 {len(failures)} 项：{'、'.join(failures)}")
        return 1
    print(f"三条复核全部通过。证据已写入 {out_dir}")
    print("复核人可在本结果上签字，或用下面两条命令自行验算哈希：")
    print(f'  certutil -hashfile "{GOLDEN_FILE}" SHA256')
    print(f'  certutil -hashfile "{exported_file}" SHA256')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
