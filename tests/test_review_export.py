"""Check provenance references and local-only review output semantics."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.observations import review_export as review


class ReviewExportTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {"sources": {"video": {"id": "video", "kind": "videos", "platform": "bilibili",
                                               "sha256": "hash", "technical": {"duration_seconds": 5},
                                               "source_name": "校园</script><script>bad()",
                                               "local_path": "observations/videos/校园.mp4"}}}
        self.annotations = [{"source_id": "video", "source_sha256": "hash", "duration_seconds": 5,
                             "segments": [{"id": "s001", "start_seconds": 0, "end_seconds": 5,
                                           "campus": "xianlin", "status": "accepted", "eligibility": "current_candidate",
                                           "place_ids": ["entrance"], "asset_ids": ["building"],
                                           "map_object_ids": ["road"], "map_feature_ids": ["external-building"],
                                           "selected_frame_pts_seconds": [], "review_frame_pts_seconds": [0]}]}]
        self.topology = {"places": {"entrance": {"label": "入口", "kind": "entrance", "campus": "xianlin",
                                                "asset_ids": ["building"], "map_object_ids": ["road"],
                                                "spatial_binding": {"status": "semantic_parent_only"},
                                                "source_refs": [{"source_id": "video", "segment_id": "s001"}]}}, "edges": []}
        self.campus = {"metadata": {"dataset_sha256": "map-hash"},
                       "boundary": {"asset_id": "boundary", "outer": [[0, 0], [100, 0], [100, 100]], "name": "边界"},
                       "buildings": [{"asset_id": "building", "map_feature_id": "external-building",
                                      "outer": [[10, 10], [20, 10], [20, 20]], "center": [15, 15], "name": "楼"}],
                       "roads": [{"asset_id": "road", "map_feature_id": None, "points": [[0, 0], [100, 100]], "name": "路"}]}

    def test_map_object_and_external_feature_identity_are_distinct(self):
        self.assertEqual(review.validate_data(self.catalog, self.annotations, self.topology, self.campus), [])
        value = copy.deepcopy(self.annotations)
        value[0]["segments"][0]["map_feature_ids"] = ["road"]
        self.assertTrue(any("map_feature_ids" in e for e in review.validate_data(self.catalog, value, self.topology, self.campus)))

    def test_topology_provenance_and_inference_guard(self):
        value = copy.deepcopy(self.topology)
        value["edges"] = [{"id": "edge", "from_place_id": "entrance", "to_place_id": "entrance",
                           "basis": "inferred", "verified": True,
                           "source_refs": [{"source_id": "video", "segment_id": "missing"}]}]
        errors = review.validate_data(self.catalog, self.annotations, value, self.campus)
        self.assertTrue(any("Inference" in e for e in errors))
        self.assertTrue(any("Unknown segment" in e for e in errors))

    def test_unreviewed_video_cannot_be_silently_omitted(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["sources"]["another"] = {"kind": "videos", "platform": "bilibili"}
        self.assertTrue(any("no complete review" in e for e in review.validate_data(catalog, self.annotations, self.topology, self.campus)))

    def test_edge_temporal_status_cannot_promote_historical_segment(self):
        annotations = copy.deepcopy(self.annotations)
        annotations[0]["segments"][0].update(status="excluded", eligibility="excluded_historical", exclusion_reason="Old footage")
        topology = copy.deepcopy(self.topology)
        topology["edges"] = [{"id": "edge", "from_place_id": "entrance", "to_place_id": "entrance",
                              "basis": "continuous_shot", "temporal_status": "current_candidate",
                              "source_refs": [{"source_id": "video", "segment_id": "s001"}]}]
        errors = review.validate_data(self.catalog, annotations, topology, self.campus)
        self.assertTrue(any("Temporal status" in e for e in errors))

    def test_curated_frame_requires_bidirectional_provenance_and_inherited_rights(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["sources"]["video"].update(platform_identifiers={"bvid": "BVtest"}, redistribution={"status": "local_only", "license": "unknown"})
        annotations = copy.deepcopy(self.annotations)
        annotations[0]["segments"][0].update(selected_frame_pts_seconds=[1], selected_frame_source_ids=["video-frame-pts-000000001000"])
        catalog["sources"]["video-frame-pts-000000001000"] = {"kind": "selected_video_frame", "annotation_path": "observations/annotations/video-review/BVtest.json",
                                         "annotation_segment_id": "s001", "redistribution": {"status": "local_only", "license": "unknown"},
                                         "spatial_binding": {"asset_ids": ["building"], "map_object_ids": ["road"], "map_feature_ids": ["external-building"], "place_ids": ["entrance"]},
                                         "derived_from": {"source_ids": ["video"], "source_sha256": "hash", "decoded_pts_seconds": 1, "decoded_pts": 1000, "time_base": "1/1000"}}
        self.assertEqual(review.validate_data(catalog, annotations, self.topology, self.campus), [])
        catalog["sources"]["video-frame-pts-000000001000"]["redistribution"]["status"] = "allowed"
        annotations[0]["segments"][0]["selected_frame_source_ids"] = []
        errors = review.validate_data(catalog, annotations, self.topology, self.campus)
        self.assertTrue(any("bidirectional" in e for e in errors))
        self.assertTrue(any("permissions" in e for e in errors))
        catalog["sources"]["video-frame-pts-000000001000"]["derived_from"]["decoded_pts"] = 9999
        errors = review.validate_data(catalog, annotations, self.topology, self.campus)
        self.assertTrue(any("PTS/time base differs" in e for e in errors))
        self.assertTrue(any("Frame ID ticks differ" in e for e in errors))

    def test_export_reads_sources_but_writes_only_build_and_escapes_script(self):
        task_root = Path("D:/Temp/codex/njupt-map-review-export-test") if os.name == "nt" else Path(tempfile.gettempdir())
        task_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=task_root) as directory:
            root = Path(directory)
            fixture = root / "observations/catalog.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text(json.dumps(self.catalog), encoding="utf-8")
            before = fixture.read_bytes()
            with patch.object(review, "inputs", return_value=(self.catalog, self.annotations, self.topology, self.campus)):
                summary = review.export(root)
            self.assertEqual(fixture.read_bytes(), before)
            page = (root / "build/review/index.html").read_text(encoding="utf-8")
            self.assertNotIn("校园</script>", page)
            self.assertIn("\\u003c/script\\u003e", page)
            self.assertIn("../../observations/videos/", page)
            self.assertEqual(summary["videos"], 1)
            coverage = json.loads((root / "build/review/coverage.json").read_text(encoding="utf-8"))
            self.assertEqual(coverage["current_candidate_asset_count"], 1)
            self.assertNotIn("entrance", coverage["assets"])


if __name__ == "__main__":
    unittest.main()
