"""Meaningful checks for source-PTS curation and complete review timelines."""
from __future__ import annotations

import copy
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.observations import video_review as review
from src.observations.common import checksum


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.sources = {"video": {"kind": "videos", "sha256": "content",
                                  "technical": {"duration_seconds": 3.5}}}
        self.annotation = {"source_id": "video", "source_sha256": "content", "duration_seconds": 3.5,
                           "segments": [
                               {"start_seconds": 0, "end_seconds": 1.5, "campus": "xianlin",
                                "status": "accepted", "asset_ids": ["building"],
                                "map_feature_ids": ["feature"], "place_ids": ["entrance"],
                                "selected_frame_pts_seconds": [.5],
                                "observed_connections": [{"from_place_id": "entrance", "to_place_id": "hall",
                                                          "basis": "continuous_shot"}]},
                               {"start_seconds": 1.5, "end_seconds": 3.5, "campus": "unknown",
                                "status": "unknown", "basis": "No identifiable landmark"}]}

    def check(self, annotation):
        return review.validate_annotation(annotation, self.sources, {"building"}, {"feature"}, {"entrance", "hall"})

    def test_unknown_is_valid_without_claiming_a_location(self):
        self.assertEqual(self.check(self.annotation), [])

    def test_gaps_overlaps_and_missing_tail_are_rejected(self):
        for start, end in [(1.6, 3.5), (1.4, 3.5), (1.5, 3.4)]:
            with self.subTest(start=start, end=end):
                value = copy.deepcopy(self.annotation)
                value["segments"][1]["start_seconds"] = start
                value["segments"][1]["end_seconds"] = end
                self.assertTrue(self.check(value))

    def test_outside_campus_cannot_be_accepted(self):
        value = copy.deepcopy(self.annotation)
        value["segments"][0]["campus"] = "sanpailou"
        self.assertTrue(any("Only Xianlin" in e for e in self.check(value)))

    def test_wrong_identity_hash_and_frame_are_rejected(self):
        value = copy.deepcopy(self.annotation)
        value["source_sha256"] = "another-video"
        value["segments"][0]["asset_ids"] = ["unregistered"]
        value["segments"][0]["selected_frame_pts_seconds"] = [1.5]
        errors = self.check(value)
        self.assertTrue(any("hash" in e for e in errors))
        self.assertTrue(any("asset_ids" in e for e in errors))
        self.assertTrue(any("frame" in e for e in errors))

    def test_exclusion_and_topology_need_explicit_basis(self):
        value = copy.deepcopy(self.annotation)
        value["segments"][0]["status"] = "excluded"
        value["segments"][0]["observed_connections"][0]["basis"] = "consecutive_edit"
        errors = self.check(value)
        self.assertTrue(any("Exclusion requires" in e for e in errors))
        self.assertTrue(any("Topology relation" in e for e in errors))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools unavailable")
class DecodeTests(unittest.TestCase):
    def test_short_insert_between_grid_samples_retains_exact_pts(self):
        temporary_root = Path("D:/Temp/codex/njupt-map-video-review-test") if os.name == "nt" else Path(tempfile.gettempdir())
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            root = Path(directory)
            video = root / "insert.mp4"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=black:s=320x180:r=25:d=0.28[b1];color=c=white:s=320x180:r=25:d=0.08[w];"
                            "color=c=black:s=320x180:r=25:d=0.64[b2];[b1][w][b2]concat=n=3:v=1:a=0",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
            source = {"local_path": "insert.mp4", "sha256": checksum(video),
                      "platform_identifiers": {"bvid": "synthetic"},
                      "redistribution": {"status": "local_only", "license": "unknown"}}
            with patch.object(review, "ROOT", root), patch.object(review, "resolve", lambda value: root / value):
                result = review.prepare("video", source, interval=1, output_root=root / "build/review")
            cut_times = result["scene_cuts_seconds"]
            self.assertTrue(any(abs(t - .28) < .001 for t in cut_times), cut_times)
            white = next(frame for frame in result["frames"] if abs(frame["decoded_pts_seconds"] - .28) < .001)
            self.assertEqual(white["decoded_pts_seconds"], white["decoded_pts"] * float(review.Fraction(white["time_base"])))
            with Image.open(root / "build/review/synthetic" / white["path"]) as image:
                self.assertGreater(image.getpixel((120, 67))[0], 240)
            self.assertEqual(checksum(video), source["sha256"])
            self.assertTrue(any("near-cut" in frame["selection"] for frame in result["frames"]))


if __name__ == "__main__":
    unittest.main()
