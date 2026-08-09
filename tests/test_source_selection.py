import importlib.util
import os
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
os.environ["RM_LIVE_CACHE_CONFIG"] = str(
    ROOT / "router/etc/rm-live-cache/config.json"
)

spec = importlib.util.spec_from_file_location(
    "rm_live_cache_server", ROOT / "router/usr/lib/rm-live-cache/server.py"
)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class SourceSelectionTest(unittest.TestCase):
    def setUp(self):
        self.event = {
            "zoneName": "复活赛",
            "liveState": 1,
            "matchState": 1,
            "zoneLiveString": [
                {
                    "label": "1080p",
                    "res": "high",
                    "src": "https://rtmp.djicdn.com/robomaster/main.m3u8",
                },
                {
                    "label": "720p",
                    "res": "middle",
                    "src": "https://rtmp.djicdn.com/robomaster/main_ud.m3u8",
                },
            ],
        }

    def test_selects_only_720p_middle_source(self):
        url, label, active = server.select_source(
            {"eventName": "赛事", "eventData": [self.event]}
        )
        self.assertTrue(url.endswith("main_ud.m3u8"))
        self.assertTrue(label.endswith("720p"))
        self.assertTrue(active)

    def test_does_not_fall_back_to_1080p(self):
        self.event["zoneLiveString"] = self.event["zoneLiveString"][:1]
        with self.assertRaisesRegex(ValueError, "720p"):
            server.select_source({"eventName": "赛事", "eventData": [self.event]})


if __name__ == "__main__":
    unittest.main()
