"""Blender-side spatial instance synchronization, with authored asset protection.

blender --background projects/blender/campus.blend --python src/sync/apply.py -- --apply
Without --apply, export actual placements only. Supply a current plan from src.sync.plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]


def protected_state(linked):
    """Fingerprint the native composition that spatial placement must preserve.

    Camera bases and animation ownership are checked rather than evaluated world
    matrices, since a preserved tracking constraint may follow a moved building.
    """
    excluded = set(linked.values())
    records = []
    for obj in bpy.context.scene.objects:
        if obj in excluded:
            continue
        data = obj.data
        record = {"name": obj.name, "type": obj.type,
                  "basis": [float(value) for row in obj.matrix_basis for value in row],
                  "data": data.name if data else None,
                  "materials": [slot.material.name if slot.material else None for slot in obj.material_slots],
                  "action": obj.animation_data.action.name if obj.animation_data and obj.animation_data.action else None,
                  "constraints": [(constraint.name, constraint.type, constraint.influence) for constraint in obj.constraints]}
        if obj.type == "CAMERA":
            record["camera"] = {key: getattr(data, key) for key in ("type", "lens", "sensor_width", "sensor_height", "clip_start", "clip_end")}
        if obj.type == "MESH":
            record["mesh_counts"] = [len(data.vertices), len(data.polygons)]
        records.append(record)
    scene = bpy.context.scene
    snapshot = {"objects": sorted(records, key=lambda record: record["name"]),
                "active_camera": scene.camera.name if scene.camera else None,
                "timeline": [scene.frame_start, scene.frame_end, scene.frame_current, scene.render.fps, scene.render.fps_base],
                "actions": sorted(action.name for action in bpy.data.actions)}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def instances():
    items = {}
    for obj in bpy.context.scene.objects:
        asset_id = obj.get("asset_id")
        if not asset_id or obj.instance_type != "COLLECTION":
            continue
        if asset_id in items:
            raise ValueError(f"Multiple building instances share asset_id: {asset_id}")
        items[asset_id] = obj
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "build/checks/sync/plan.json")
    parser.add_argument("--output", type=Path, default=ROOT / "build/checks/sync/instances.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    linked = instances()
    if args.apply:
        protected_before = protected_state(linked)
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        if not plan["ready_to_apply"] or plan["issues"]:
            raise ValueError("Resolve proposed geometry/identity changes before applying this plan")
        for path, key in ((ROOT / "projects/map/campus.gpkg", "source_file_sha256"),
                          (ROOT / "projects/blender/buildings/catalog.json", "catalog_file_sha256")):
            if hashlib.sha256(path.read_bytes()).hexdigest() != plan[key]:
                raise ValueError(f"Source changed since this plan was prepared: {path}")
        catalog_path = ROOT / "projects/blender/buildings/catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        # Validate the whole plan before any mutation.
        for change in plan["operations"]:
            obj = linked.get(change["asset_id"])
            if obj is None or change["action"] != "update_instance":
                raise ValueError(f"Missing or unsupported instance update: {change['asset_id']}")
            if catalog[change["asset_id"]]["spatial_signature"] != change["spatial_signature"]:
                raise ValueError("Authored shape differs from update plan")
            if max(abs(a-b) for a,b in zip(obj.location, change["previous_location"])) > 0.001:
                raise ValueError(f"Instance moved since plan preparation: {change['asset_id']}")
        if plan["operations"]:
            for change in plan["operations"]:
                obj = linked[change["asset_id"]]
                obj.location = change["location"]
                obj.name = change["name"]
                entry = catalog[change["asset_id"]]
                entry["map_center_m"] = change["location"][:2]
                entry["map_base_z_m"] = change["location"][2]
                entry["stats"]["center"] = change["location"][:2]
                entry["stats"]["name"] = change["name"]
            bpy.context.scene["map_dataset_sha256"] = plan["dataset_sha256"]
            if protected_state(linked) != protected_before:
                raise ValueError("Camera, animation or campus composition changed during instance update; refusing to save")
            # Blender's automatic previous-save files are replaced by Git history.
            bpy.context.preferences.filepaths.save_version = 0
            bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath, relative_remap=True)
            catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    placements = {asset_id: {"location": list(obj.location), "name": obj.name}
                  for asset_id, obj in linked.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(placements, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"instances": len(placements), "applied": args.apply, "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
