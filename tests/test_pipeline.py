import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from audio_radar.pipeline import load_config, process, run


ROOT = Path(__file__).resolve().parents[1]


class PipelineTest(unittest.TestCase):
    def test_demo_build_writes_all_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "topics.yml").write_text((ROOT / "config" / "topics.yml").read_text(encoding="utf-8"), encoding="utf-8")
            items = run(root, root / "config" / "topics.yml", demo=True, now=datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc))
            self.assertEqual(len(items), 3)
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


if __name__ == "__main__":
    unittest.main()

