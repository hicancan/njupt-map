"""Spatial contracts: identity, translation, courtyards and authored mesh protection."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

from src.map.export import export
from src.map.store import ROOT, load_campus, spatial_signature
from src.map.validate import validate
from src.sync.plan import make_plan
from src.sync.__main__ import plans_for_scenes


class MapContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.campus = load_campus()
        cls.by_id = {b["asset_id"]: b for b in cls.campus["buildings"]}
        cls.catalog = {b["asset_id"]: {"spatial_signature": b["spatial_signature"],
            "map_center_m": b["center"], "map_base_z_m": b.get("base_z", 0),
            "stats": {"name": b["name"] or b["asset_id"]}} for b in cls.campus["buildings"]}

    def test_current_geopackage_contract(self):
        report = validate()
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(len(self.by_id), 129)
        self.assertEqual(sum(bool(b["space_id"]) for b in self.by_id.values()), 4)

    def test_floorplan_and_clearance_dimensions_have_one_source(self):
        teaching = self.by_id["osm_way_223699451"]
        self.assertEqual((teaching["height"], teaching["levels"]), (18.5, 5))
        self.assertIn("inferred", teaching["height_source"])
        for asset_id in ("osm_way_224990427", "osm_way_224990428"):
            rec = self.by_id[asset_id]
            self.assertEqual((rec["height"], rec["levels"], rec["min_height"]), (10.8, 3, 3.8))

    def test_upper_floor_and_courtyard_triangulation(self):
        building = self.by_id["osm_way_155434036"]
        shell = Polygon(building["outer"], building["holes"])
        mesh = unary_union([Polygon(t) for t in building["roof_triangles"]])
        self.assertLess(mesh.symmetric_difference(shell).area, 0.002)
        for ring in building["holes"]:
            self.assertLess(mesh.intersection(Polygon(ring)).area, 0.002)
        self.assertEqual(building["upper_volumes"][0]["base_z"], building["height"])

    def test_registered_assets_require_no_changes(self):
        plan = make_plan(self.campus, self.catalog)
        self.assertTrue(plan["ready_to_apply"])
        self.assertEqual(plan["operations"], [])

    def test_map_translation_moves_instance_without_replacing_shape(self):
        campus = copy.deepcopy(self.campus)
        building = next(b for b in campus["buildings"] if b["asset_id"] == "osm_way_155434036")
        dx, dy = 13.125, -7.75
        building["center"] = [building["center"][0]+dx, building["center"][1]+dy]
        for rec in [building, *building.get("upper_volumes", [])]:
            rec["outer"] = [[x+dx, y+dy] for x,y in rec["outer"]]
            rec["holes"] = [[[x+dx, y+dy] for x,y in ring] for ring in rec["holes"]]
        building["spatial_signature"] = spatial_signature(building)
        self.assertEqual(building["spatial_signature"], self.by_id[building["asset_id"]]["spatial_signature"])
        plan = make_plan(campus, self.catalog)
        self.assertTrue(plan["ready_to_apply"])
        self.assertEqual(len(plan["operations"]), 1)
        self.assertEqual(plan["operations"][0]["action"], "update_instance")
        self.assertEqual(plan["operations"][0]["location"][:2], building["center"])

    def test_height_change_requires_authored_geometry_review(self):
        campus = copy.deepcopy(self.campus)
        b = campus["buildings"][0]
        b["height"] += 0.5
        b["spatial_signature"] = spatial_signature(b)
        plan = make_plan(campus, self.catalog)
        self.assertFalse(plan["ready_to_apply"])
        self.assertEqual(plan["issues"][0]["action"], "review_geometry")
        self.assertFalse(plan["operations"])

    def test_name_change_preserves_identity_and_mesh(self):
        campus = copy.deepcopy(self.campus)
        b = campus["buildings"][0]
        b["name"] = "新的建筑名称"
        self.assertEqual(spatial_signature(b), self.by_id[b["asset_id"]]["spatial_signature"])
        plan = make_plan(campus, self.catalog)
        self.assertTrue(plan["ready_to_apply"])
        self.assertEqual(plan["operations"][0]["asset_id"], b["asset_id"])
        self.assertEqual(plan["operations"][0]["name"], "新的建筑名称")

    def test_removed_map_object_is_never_deleted_automatically(self):
        campus = copy.deepcopy(self.campus)
        removed = campus["buildings"].pop()
        plan = make_plan(campus, self.catalog)
        self.assertFalse(plan["ready_to_apply"])
        self.assertEqual(plan["issues"][0]["asset_id"], removed["asset_id"])
        self.assertEqual(plan["issues"][0]["action"], "review_removed_map_object")
        self.assertFalse(plan["operations"])

    def test_scene_drift_is_detected_using_actual_instances(self):
        actual = {b["asset_id"]: {"name": b["name"] or b["asset_id"], "location": [*b["center"], b.get("base_z",0)]}
                  for b in self.campus["buildings"]}
        changed = self.campus["buildings"][0]["asset_id"]
        actual[changed]["location"][0] += 1
        plan = make_plan(self.campus, self.catalog, actual)
        self.assertTrue(plan["ready_to_apply"])
        self.assertEqual(len(plan["operations"]), 1)
        self.assertEqual(plan["operations"][0]["asset_id"], changed)

    def test_blender_unique_name_suffix_is_not_a_map_rename(self):
        actual = {b["asset_id"]: {"name": (b["name"] or b["asset_id"])+".001", "location": [*b["center"], b.get("base_z",0)]}
                  for b in self.campus["buildings"]}
        plan = make_plan(self.campus, self.catalog, actual)
        self.assertTrue(plan["ready_to_apply"])
        self.assertEqual(plan["operations"], [])

    def test_unregistered_scene_instance_requires_review(self):
        actual = {b["asset_id"]: {"name": b["name"] or b["asset_id"], "location": [*b["center"], b.get("base_z",0)]}
                  for b in self.campus["buildings"]}
        actual["unregistered-building"] = {"name": "Unknown", "location": [0,0,0]}
        plan = make_plan(self.campus, self.catalog, actual)
        self.assertFalse(plan["ready_to_apply"])
        self.assertEqual(plan["issues"][0]["action"], "review_unregistered_instance")

    def test_film_is_checked_even_after_campus_catalog_was_updated(self):
        actual = {b["asset_id"]: {"name": b["name"] or b["asset_id"], "location": [*b["center"], b.get("base_z",0)]}
                  for b in self.campus["buildings"]}
        stale_film = copy.deepcopy(actual)
        asset_id = self.campus["buildings"][0]["asset_id"]
        stale_film[asset_id]["location"][0] -= 5
        plans = plans_for_scenes(self.campus, self.catalog, {"campus": actual, "film": stale_film})
        self.assertEqual(plans["campus"]["operations"], [])
        self.assertEqual(len(plans["film"]["operations"]), 1)
        self.assertEqual(plans["film"]["operations"][0]["asset_id"], asset_id)

    def test_two_scenes_are_both_reviewed_before_apply(self):
        actual = {b["asset_id"]: {"name": b["name"] or b["asset_id"], "location": [*b["center"], b.get("base_z",0)]}
                  for b in self.campus["buildings"]}
        film = copy.deepcopy(actual)
        film.pop(self.campus["buildings"][0]["asset_id"])
        plans = plans_for_scenes(self.campus, self.catalog, {"campus": actual, "film": film})
        self.assertTrue(plans["campus"]["ready_to_apply"])
        self.assertFalse(all(plan["ready_to_apply"] for plan in plans.values()))
        self.assertEqual(plans["film"]["issues"][0]["action"], "restore_instance")

    def test_export_is_deterministic_and_does_not_modify_source(self):
        # CI may set its own temp root. Windows Codex tasks use their dedicated root.
        temp_root = Path(tempfile.gettempdir())
        with tempfile.TemporaryDirectory(prefix="njupt-map-export-test-", dir=temp_root) as folder:
            source = ROOT / "projects/map/campus.gpkg"
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            output = Path(folder)
            export(output=output)
            first = {p.name: p.read_bytes() for p in output.iterdir()}
            export(output=output)
            self.assertEqual(first, {p.name: p.read_bytes() for p in output.iterdir()})
            self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
            geojson = json.loads(first["buildings.geojson"])
            self.assertEqual(len(geojson["features"]), 129)
            lon, lat = geojson["features"][0]["geometry"]["coordinates"][0][0]
            self.assertTrue(118 < lon < 120 and 31 < lat < 33)


if __name__ == "__main__":
    unittest.main()
