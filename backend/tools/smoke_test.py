"""端到端冒烟测试：真启动 uvicorn，真发 HTTP 请求，再关闭。

用法：
    cd backend
    .venv\\Scripts\\python.exe tools\\smoke_test.py

与单元测试的区别：单元测试用 TestClient（进程内），本脚本验证真实进程、
真实端口、真实 HTTP 栈，覆盖"服务到底能不能起来"这类问题。
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import golden  # noqa: E402

STARTUP_TIMEOUT_SECONDS = 40.0
POLL_INTERVAL_SECONDS = 0.4


def use_utf8_stdout() -> None:
    """Windows 控制台默认 GBK，中文批号会被打成乱码。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def url_quote(value: str) -> str:
    """中文文件名必须百分号编码，否则 urllib 会以 ASCII 编码失败。"""

    return urllib.parse.quote(value, safe="")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_json(url: str) -> tuple[int, object]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get_bytes(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def post_json(url: str, payload: object) -> tuple[int, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def build_payload(batch_no: str, cans: list[dict[str, object]]) -> dict[str, object]:
    return {
        "batchNo": batch_no,
        "madeDate": "2026-09-23",
        "validateDate": "2026-10-23",
        "box": {"code": "80217619000000001003", "cans": cans},
    }


SMOKE_CANS: list[dict[str, object]] = [
    {
        "index": 1,
        "code": "80217629000000001005",
        "plannedParticleCount": 1,
        "particles": ["82062339000000001004"],
    },
    {
        "index": 2,
        "code": "80217629000000001004",
        "plannedParticleCount": 1,
        "particles": ["82062339000000001001"],
    },
    {
        "index": 3,
        "code": "80217629000000001006",
        "plannedParticleCount": 2,
        "particles": ["82062339000000001003", "82062339000000001002"],
    },
]


def main() -> int:
    use_utf8_stdout()
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    failures: list[str] = []

    def check(condition: bool, label: str, extra: str = "") -> None:
        mark = " OK " if condition else "FAIL"
        suffix = f"  {extra}" if extra else ""
        print(f"[{mark}] {label}{suffix}")
        if not condition:
            failures.append(label)

    print(f"启动 uvicorn: {base}")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(BACKEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        health: dict[str, object] | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                status, body = get_json(f"{base}/api/health")
                if status == 200 and isinstance(body, dict):
                    health = body
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(POLL_INTERVAL_SECONDS)

        if health is None:
            print("[FAIL] 服务未能在超时内就绪")
            output = process.stdout.read() if process.stdout else ""
            if output:
                print(output[-2000:])
            return 1

        print()
        check(
            health.get("status") == "ok",
            "GET /api/health 返回 200 且 status=ok",
            str(health.get("version")),
        )
        check(bool(health.get("goldenOk")), "健康检查确认黄金基准往返一致")

        status, openapi = get_json(f"{base}/openapi.json")
        paths = openapi.get("paths", {}) if isinstance(openapi, dict) else {}
        check(status == 200 and "/api/xml/preview" in paths, "GET /openapi.json 自动生成")

        for name in golden.GOLDEN_NAMES:
            status, body = get_bytes(f"{base}/api/golden/{url_quote(name)}/xml")
            expected = golden.read_bytes(name)
            check(
                status == 200 and body == expected,
                f"GET /api/golden/{name}/xml 字节与基准一致",
                f"{len(body)} 字节",
            )

        status, listing = get_json(f"{base}/api/golden")
        all_ok = isinstance(listing, dict) and listing.get("allOk") is True
        check(status == 200 and all_ok, "GET /api/golden 全部往返通过")

        sample = golden.read_text("1箱3罐.xml")
        status, preview = post_json(f"{base}/api/xml/preview", build_payload("20260901", SMOKE_CANS))
        check(
            status == 200 and isinstance(preview, dict) and preview.get("xml") == sample,
            "POST /api/xml/preview 输出与阶段 0 基准逐字符相同",
        )

        wrong_layer = json.loads(json.dumps(SMOKE_CANS))
        wrong_layer[0]["code"] = "82062339000000001004"
        status, error = post_json(f"{base}/api/xml/preview", build_payload("20260901", wrong_layer))
        issues = error.get("error", {}).get("detail", {}).get("issues", [])
        codes = {issue["code"] for issue in issues}
        check(status == 422 and "CODE_LAYER_MISMATCH" in codes, "层级前缀校验拦住错层条码")

        one_can = [SMOKE_CANS[0]]
        status, created = post_json(f"{base}/api/batches", build_payload("SMOKE-0001", one_can))
        check(
            status == 201 and isinstance(created, dict) and created.get("status") == "draft",
            "POST /api/batches 创建草稿批次",
        )

        status, conflict = post_json(f"{base}/api/batches", build_payload("SMOKE-0001", one_can))
        options = conflict.get("error", {}).get("detail", {}).get("options", [])
        check(status == 409 and len(options) == 3, "重复批号返回三选一")

    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    print()
    if failures:
        print(f"冒烟测试未通过（{len(failures)} 项）：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("冒烟测试通过：服务可启动，关键接口行为全部正确。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
