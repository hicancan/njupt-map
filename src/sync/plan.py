"""Plan placement updates; shape changes never overwrite editable Blender assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from src.map.store import ROOT, SOURCE, load_campus

CATALOG = ROOT / "projects/blender/buildings/catalog.json"


def name_matches(actual: str, expected: str):
    """Blender adds a numeric suffix when several objects share a human name."""
    return actual == expected or bool(actual and re.fullmatch(re.escape(expected) + r"\.\d{3,}", actual))


def make_plan(campus, catalog, actual_instances=None):
    operations = []
    issues = []
    expected = {b["asset_id"]: b for b in campus["buildings"]}
    for asset_id, building in expected.items():
        display_name = building["name"] or asset_id
        entry = catalog.get(asset_id)
        if entry is None:
            issues.append({"asset_id": asset_id, "action": "author_new_asset", "reason": "Map asset has no editable Blender source"})
            continue
        if entry.get("spatial_signature") != building["spatial_signature"]:
            issues.append({"asset_id": asset_id, "action": "review_geometry", "reason": "Outline, courtyard, dimension, or upper volume differs from the authored asset",
                           "current_map_signature": building["spatial_signature"], "authored_signature": entry.get("spatial_signature")})
            continue
        reference = (actual_instances or {}).get(asset_id)
        if actual_instances is not None and reference is None:
            issues.append({"asset_id": asset_id, "action": "restore_instance", "reason": "Authored asset is absent from scene"})
            continue
        if reference is None:
            center = entry.get("map_center_m")
            base_z = entry.get("map_base_z_m")
            if center is None or base_z is None:
                issues.append({"asset_id": asset_id, "action": "register_placement", "reason": "Authored asset has no accepted map placement"})
                continue
            reference = {"location": [*center, base_z], "name": entry.get("stats", {}).get("name", display_name)}
        desired = [*building["center"], building.get("base_z", 0.0)]
        if any(not math.isfinite(value) for value in desired):
            raise ValueError(f"Non-finite placement for {asset_id}")
        moved = max(abs(a-b) for a, b in zip(reference["location"], desired)) > 0.0001
        renamed = not name_matches(reference.get("name"), display_name)
        if moved or renamed:
            operations.append({"asset_id": asset_id, "action": "update_instance", "location": desired,
                               "name": display_name, "previous_location": reference["location"],
                               "spatial_signature": building["spatial_signature"]})
    for asset_id in set(catalog) - set(expected):
        issues.append({"asset_id": asset_id, "action": "review_removed_map_object", "reason": "Blender asset is absent from current map; never deleted automatically"})
    if actual_instances is not None:
        for asset_id in set(actual_instances) - set(expected):
            issues.append({"asset_id": asset_id, "action": "review_unregistered_instance", "reason": "Scene building has no current map identity; never deleted automatically"})
    return {"schema_version": 1, "dataset_sha256": campus["metadata"]["dataset_sha256"],
            "coordinate_reference": {key: campus["metadata"][key] for key in ("crs", "origin_lonlat", "origin_easting_northing", "ground_elevation")},
            "operations": operations, "issues": issues, "ready_to_apply": not issues,
            "policy": "Only linked instance translation and name are mutable. Geometry, materials, cameras, landscape, animation and asset files remain authored sources."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--instances", type=Path, help="Actual scene placements exported by Blender")
    parser.add_argument("--output", type=Path, default=ROOT / "build/checks/sync/plan.json")
    args = parser.parse_args()
    campus = load_campus(args.source)
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    actual = json.loads(args.instances.read_text(encoding="utf-8")) if args.instances else None
    plan = make_plan(campus, catalog, actual)
    plan["source_file_sha256"] = hashlib.sha256(args.source.read_bytes()).hexdigest()
    plan["catalog_file_sha256"] = hashlib.sha256(args.catalog.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(args.output), "operations": len(plan["operations"]), "issues": len(plan["issues"]), "ready_to_apply": plan["ready_to_apply"]}, ensure_ascii=False))
    raise SystemExit(0 if plan["ready_to_apply"] else 1)


if __name__ == "__main__":
    main()
