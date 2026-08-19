import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from audio_radar.pipeline import Item, keyword_present, load_config, process, reuse_enrichment, run


ROOT = Path(__file__).resolve().parents[1]


class PipelineTest(unittest.TestCase):
    def test_demo_build_writes_all_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "topics.yml").write_text((ROOT / "config" / "topics.yml").read_text(encoding="utf-8"), encoding="utf-8")
            items = run(root, root / "config" / "topics.yml", demo=True, now=datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc))
            self.assertEqual(len(items), 4)
            self.assertTrue((root / "docs" / "index.html").exists())
            self.assertTrue((root / "docs" / "data" / "latest.json").exists())
            self.assertTrue((root / "reports" / "2026-08-18.md").exists())

    def test_items_are_tagged_and_scored(self):
        config = load_config(ROOT / "config" / "topics.yml")
        now = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            items = run(Path(tmp), ROOT / "config" / "topics.yml", demo=True, now=now)
        self.assertTrue(all(item.tags for item in items))
        self.assertTrue(all(item.score > 0 for item in items))
        self.assertTrue(all(item.keywords_cn for item in items))
        self.assertTrue(all(item.creative_cn for item in items))
        self.assertTrue(all(item.icon for item in items))
        products = [item for item in items if item.kind == "product"]
        self.assertTrue(all(item.product_name_cn for item in products))
        self.assertTrue(all(item.company_cn for item in products))
        self.assertTrue(all(item.what_is_it_cn for item in products))

    def test_report_date_uses_project_timezone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "topics.yml").write_text((ROOT / "config" / "topics.yml").read_text(encoding="utf-8"), encoding="utf-8")
            run(root, root / "config" / "topics.yml", demo=True, now=datetime(2026, 8, 18, 23, 40, tzinfo=timezone.utc))
            self.assertTrue((root / "reports" / "2026-08-19.md").exists())

    def test_keyword_matching_respects_token_boundaries(self):
        self.assertTrue(keyword_present("new asr model", "asr"))
        self.assertFalse(keyword_present("research toolkit", "asr"))
        self.assertTrue(keyword_present("image-to-video editor", "image-to-video"))

    def test_cached_ai_enrichment_is_reused_only_for_same_content(self):
        item = Item("product", "AI video editor", "https://example.com/cached", "video editing", "Demo", "2026-08-18T00:00:00Z").finalize()
        from audio_radar.pipeline import enrichment_fingerprint
        cached = {
            item.item_id: {
                "enrichment_fingerprint": enrichment_fingerprint(item),
                "summary_cn": "缓存摘要",
                "keywords_cn": ["视频编辑"],
                "creative_cn": "缓存玩法",
            }
        }
        self.assertEqual(reuse_enrichment([item], cached), 1)
        self.assertEqual(item.summary_cn, "缓存摘要")


if __name__ == "__main__":
    unittest.main()
