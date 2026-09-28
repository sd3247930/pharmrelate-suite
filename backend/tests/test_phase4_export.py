"""阶段 4：XML / HTML 导出、SHA-256、导出记录、导出闸门、字节级断言。"""

from __future__ import annotations

import hashlib
import re
import unittest

try:
    from tests.support import BACKEND_DIR, TempDatabaseTestCase
except ImportError:
    from support import BACKEND_DIR, TempDatabaseTestCase

from fastapi.testclient import TestClient

from app.services import golden
from app.services.export_service import build_filename, render_html
from app.services.xml_builder import render_bytes
from app.services.xml_parser import parse_bytes

GOLDEN_DIR = BACKEND_DIR / "tests" / "golden"


class NamingTests(unittest.TestCase):
    def test_filename_follows_agreed_pattern(self) -> None:
        from datetime import datetime

        name = build_filename("20260901", "xml", at=datetime(2026, 9, 25, 22, 31, 5))
        self.assertEqual(name, "Relation_20260901_20260925223105.xml")
        self.assertTrue(re.fullmatch(r"Relation_[0-9A-Za-z-]+_\d{14}\.(xml|html)", name))

    def test_html_filename_uses_html_suffix(self) -> None:
        from datetime import datetime

        name = build_filename("20260901", "html", at=datetime(2026, 9, 25, 22, 31, 5))
        self.assertTrue(name.endswith(".html"))


class HtmlTemplateTests(unittest.TestCase):
    def test_html_matches_prd_template_shape(self) -> None:
        html = render_html("<Document/>", "20260901").decode("utf-8")
        for fragment in (
            "<!DOCTYPE html>",
            '<html lang="zh-CN">',
            '<meta charset="UTF-8">',
            "<title>包装关联关系导出 - 批号: 20260901</title>",
            "三级包装关联数据预览 (批号: 20260901)",
            'class="xml-container"',
            "white-space: pre-wrap",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, html)

    def test_xml_text_is_escaped_but_visible(self) -> None:
        xml = '<?xml version="1.0" encoding="utf-8"?><Document License="1001123"/>'
        html = render_html(xml, "20260901").decode("utf-8")
        # 尖括号被转义（否则浏览器会把它当标签吃掉），但双引号保持原样
        self.assertIn("&lt;?xml version=\"1.0\" encoding=\"utf-8\"?&gt;", html)
        self.assertIn('License="1001123"', html)

    def test_batch_no_is_escaped(self) -> None:
        html = render_html("<Document/>", "<script>").decode("utf-8")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class ExportGateAndRecordsTests(TempDatabaseTestCase):
    """用 1箱3罐 基准数据建批次，走到 verified 后导出。"""

    def setUp(self) -> None:
        super().setUp()
        self.client = TestClient(self.make_app())
        batch = parse_bytes(golden.read_bytes("1箱3罐.xml"))
        payload = {
            "batchNo": "20260901",
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
        self.batch_id = self.client.post("/api/batches", json=payload).json()["id"]

    def move_to(self, target: str) -> None:
        response = self.client.post(
            f"/api/batches/{self.batch_id}/status", json={"target": target}
        )
        self.assertEqual(response.status_code, 200, response.text)

    def verify(self) -> None:
        for target in ("collecting", "pending_review", "verified"):
            self.move_to(target)

    def export(self, kinds: list[str]) -> object:
        return self.client.post(
            f"/api/batches/{self.batch_id}/export", json={"kinds": kinds}
        )

    # ------------------------------------------------------------ 闸门

    def test_export_blocked_before_verified(self) -> None:
        response = self.export(["xml"])
        self.assertEqual(response.status_code, 409)
        detail = response.json()["error"]["detail"]
        self.assertEqual(detail["reason"], "STATUS_NOT_VERIFIED")
        self.assertEqual(detail["status"], "draft")
        self.assertIn("核对", response.json()["error"]["message"])

    def test_export_blocked_when_missing_without_early_end(self) -> None:
        self.verify()
        # 把罐 3 的一粒删掉，制造缺漏
        target = parse_bytes(golden.read_bytes("1箱3罐.xml")).box.cans[2].particles[0]
        deleted = self.client.post(
            f"/api/batches/{self.batch_id}/slots/delete", json={"code": target}
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)

        response = self.export(["xml"])
        self.assertEqual(response.status_code, 409)
        blocking = response.json()["error"]["detail"]["blocking"]
        self.assertIn("MISSING_PARTICLES", {item["code"] for item in blocking})

    def test_export_allowed_after_early_end_signature(self) -> None:
        self.verify()
        target = parse_bytes(golden.read_bytes("1箱3罐.xml")).box.cans[2].particles[0]
        self.client.post(f"/api/batches/{self.batch_id}/slots/delete", json={"code": target})
        self.move_to("pending_review")
        self.move_to("verified")
        self.client.post(
            f"/api/batches/{self.batch_id}/early-end",
            json={"reason": "药液不足", "operator": "操作员甲", "note": ""},
        )

        response = self.export(["xml"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["exportKind"], "early_end")

    # ------------------------------------------------------ 字节级一致性

    def test_exported_xml_is_byte_identical_to_golden(self) -> None:
        """这是阶段 0 冻结的合同：导出结果必须与基准逐字节相同。"""

        self.verify()
        response = self.export(["xml"])
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()["items"][0]

        downloaded = self.client.get(f"/api{item['downloadUrl']}")
        self.assertEqual(downloaded.status_code, 200)
        expected = (GOLDEN_DIR / "1箱3罐.xml").read_bytes()

        self.assertEqual(downloaded.content, expected)
        self.assertEqual(item["sha256"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(item["byteLength"], len(expected))
        self.assertEqual(
            self.client.get(f"/api{item['downloadUrl']}").headers["X-Content-SHA256"],
            item["sha256"],
        )

    def test_golden_sha_matches_the_frozen_baseline(self) -> None:
        self.assertEqual(
            golden.sha256_of(golden.read_bytes("1箱3罐.xml")),
            "43c19388b2280fd2aba7bbdeac85a1fa27aa69e464f0266d9718cfdcadc8a464",
        )

    def test_html_contains_the_same_xml_text(self) -> None:
        self.verify()
        response = self.export(["xml", "html"])
        items = {item["kind"]: item for item in response.json()["items"]}
        self.assertEqual(set(items), {"xml", "html"})

        xml_content = self.client.get(f"/api{items['xml']['downloadUrl']}").content.decode("utf-8")
        html_content = self.client.get(f"/api{items['html']['downloadUrl']}").content.decode("utf-8")

        self.assertIn("三级包装关联数据预览 (批号: 20260901)", html_content)
        # XML 原文（转义后）必须完整出现在 HTML 里
        for line in xml_content.strip().split("\n"):
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            self.assertIn(escaped, html_content, f"HTML 缺少行：{line}")

    # ---------------------------------------------------------- 记录

    def test_export_creates_records_with_hashes(self) -> None:
        self.verify()
        self.export(["xml", "html"])
        body = self.client.get(f"/api/batches/{self.batch_id}/exports").json()
        self.assertEqual(body["total"], 2)

        for item in body["items"]:
            self.assertEqual(len(item["sha256"]), 64)
            self.assertGreater(item["byteLength"], 0)
            self.assertTrue(item["filename"].startswith("Relation_20260901_"))
            self.assertEqual(item["exportKind"], "normal")
            self.assertEqual(item["particleTotal"], 4)

    def test_repeated_export_appends_records(self) -> None:
        self.verify()
        self.export(["xml"])
        self.export(["xml"])
        body = self.client.get(f"/api/batches/{self.batch_id}/exports").json()
        self.assertEqual(body["total"], 2)

    def test_first_export_advances_status_to_exported(self) -> None:
        self.verify()
        self.export(["xml"])
        body = self.client.get(f"/api/batches/{self.batch_id}").json()
        self.assertEqual(body["status"], "exported")
        self.assertFalse(body["editable"], "导出后默认只读")

    def test_second_export_still_allowed_when_exported(self) -> None:
        self.verify()
        self.export(["xml"])
        response = self.export(["xml"])
        self.assertEqual(response.status_code, 200, response.text)

    def test_export_is_audited_with_hashes(self) -> None:
        self.verify()
        item = self.export(["xml"]).json()["items"][0]
        entries = self.client.get(
            f"/api/audit?batchId={self.batch_id}&action=export"
        ).json()["items"]
        self.assertEqual(len(entries), 1)
        files = entries[0]["newValue"]["files"]
        self.assertEqual(files[0]["sha256"], item["sha256"])
        self.assertEqual(entries[0]["reason"], "正常导出")

    def test_empty_kinds_is_rejected(self) -> None:
        self.verify()
        response = self.export([])
        self.assertEqual(response.status_code, 409)
        self.assertIn("未指定导出格式", response.json()["error"]["message"])

    def test_unknown_kind_is_ignored_and_defaults_rejected(self) -> None:
        self.verify()
        response = self.export(["pdf"])
        self.assertEqual(response.status_code, 409)

    def test_download_of_unknown_record_returns_404(self) -> None:
        response = self.client.get("/api/exports/does-not-exist/download")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
