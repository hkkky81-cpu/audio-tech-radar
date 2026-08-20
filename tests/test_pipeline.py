import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from audio_radar.pipeline import (
    Item,
    arxiv_hf_paper_url,
    fetch_huggingface_spaces,
    fetch_semantic_scholar,
    keyword_present,
    load_config,
    process,
    reuse_enrichment,
    run,
)


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
            self.assertTrue((root / "docs" / "data" / "history.json").exists())
            self.assertTrue((root / "reports" / "2026-08-18.md").exists())
            page = (root / "docs" / "index.html").read_text(encoding="utf-8")
            self.assertIn("全部历史", page)
            self.assertIn("首次收录", page)
            self.assertIn("本期精选", page)
            self.assertIn("综合推荐", page)
            self.assertIn("只看收藏", page)
            self.assertIn("历史数据", page)
            self.assertIn("仅看 Demo", page)
            self.assertIn("可体验 Demo", page)
            self.assertIn("toolkit-demo", page)

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
        self.assertTrue(all(item.resource_type_cn for item in items))
        self.assertTrue(all(isinstance(item.resource_links, dict) for item in items))
        self.assertTrue(any(item.resource_links.get("demo") for item in items))
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

    def test_history_accumulates_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            config_path = root / "config" / "topics.yml"
            config_path.write_text((ROOT / "config" / "topics.yml").read_text(encoding="utf-8"), encoding="utf-8")
            run(root, config_path, demo=True, now=datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc))
            history_path = root / "docs" / "data" / "history.json"
            history = json.loads(history_path.read_text(encoding="utf-8"))
            legacy = Item("product", "Legacy AI Music Tool", "https://example.com/legacy-music", "A music generation product.", "Legacy", "2026-08-17T00:00:00Z").finalize()
            legacy.tags = ["music"]
            legacy.first_seen_at = "2026-08-17"
            legacy.last_seen_at = "2026-08-17"
            history["items"].append(legacy.__dict__)
            history_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
            run(root, config_path, demo=True, now=datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc))
            updated = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["total"], 5)
            self.assertEqual(len({item["item_id"] for item in updated["items"]}), 5)
            retained = next(item for item in updated["items"] if item["item_id"] == legacy.item_id)
            self.assertEqual(retained["first_seen_at"], "2026-08-17")

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

    def test_arxiv_id_builds_huggingface_paper_link(self):
        self.assertEqual(
            arxiv_hf_paper_url("https://arxiv.org/abs/2608.12345v2"),
            "https://huggingface.co/papers/2608.12345",
        )

    @patch("audio_radar.pipeline.request")
    def test_huggingface_space_is_marked_as_demo(self, mocked_request):
        response = Mock()
        response.json.return_value = [
            {
                "id": "demo/audio-video-lab",
                "lastModified": "2026-08-20T00:00:00Z",
                "likes": 42,
                "private": False,
                "tags": ["text-to-audio", "text-to-video"],
                "cardData": {"title": "Audio Video Lab", "short_description": "Generate audio and video from text."},
            }
        ]
        mocked_request.return_value = response
        items = fetch_huggingface_spaces(
            {"huggingface_sources": {"space_searches": ["audio video"], "min_likes": 2, "max_results_per_query": 5}},
            Mock(),
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].resource_type_cn, "可运行 Demo")
        self.assertEqual(items[0].resource_links["demo"], "https://huggingface.co/spaces/demo/audio-video-lab")

    @patch("audio_radar.pipeline.request")
    def test_semantic_scholar_adds_paper_resources(self, mocked_request):
        response = Mock()
        response.json.return_value = {
            "data": [
                {
                    "title": "Recent Audio Generation Study",
                    "abstract": "A recent audio generation method.",
                    "publicationDate": "2026-08-20",
                    "authors": [{"name": "A. Researcher"}],
                    "externalIds": {"ArXiv": "2608.12345"},
                    "openAccessPdf": {"url": "https://arxiv.org/pdf/2608.12345"},
                    "citationCount": 3,
                }
            ]
        }
        mocked_request.return_value = response
        items = fetch_semantic_scholar(
            {"semantic_scholar_sources": {"queries": ["audio generation"], "max_results_per_query": 5}},
            Mock(),
        )
        self.assertEqual(items[0].resource_links["paper"], "https://arxiv.org/abs/2608.12345")
        self.assertIn("hf_paper", items[0].resource_links)


if __name__ == "__main__":
    unittest.main()
