"""Validate source identity, portable paths, lineage, and formal asset bindings."""
from __future__ import annotations

import argparse
import json
import subprocess

from .common import BINDINGS, CATALOG, ROOT, checksum, read, resolve


def validate(*, hashes: bool = False, strict_local: bool = False, public: bool = False) -> dict:
    catalog = read(CATALOG)
    sources = catalog["sources"]
    errors = []
    unavailable = []
    local_only_missing = []
    tracked = set()
    if public:
        result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", check=True)
        tracked = set(result.stdout.split("\0"))
    for sid, source in sources.items():
        if source.get("id") != sid:
            errors.append(f"Source key/identity mismatch: {sid}")
        rights = source.get("redistribution", {})
        if rights.get("status") not in {"allowed", "local_only"} or not rights.get("license"):
            errors.append(f"Missing redistribution classification: {sid}")
        relative = source.get("local_path")
        if relative:
            if public and rights.get("status") == "local_only" and relative in tracked:
                errors.append(f"Local-only source must not be publicly tracked: {sid}: {relative}")
            try:
                path = resolve(relative)
            except ValueError as error:
                errors.append(str(error))
                continue
            if not relative.startswith(("observations/", "projects/blender/identity/")):
                errors.append(f"Source points at generated or obsolete storage: {sid}: {relative}")
            if not path.is_file():
                if rights.get("status") == "local_only" and not strict_local:
                    local_only_missing.append(sid)
                else:
                    errors.append(f"Required source missing: {sid}: {relative}")
            elif hashes and source.get("sha256") != checksum(path):
                errors.append(f"Source content differs from catalog: {sid}")
        elif source.get("status") == "unavailable":
            unavailable.append(sid)
        lineage = source.get("derived_from", {})
        if lineage:
            parent_ids = lineage.get("source_ids", [])
            if not parent_ids or set(parent_ids) - sources.keys():
                errors.append(f"Unknown derivation source: {sid}")
            elif source.get("kind") == "selected_video_frame":
                parent = sources[parent_ids[0]]
                if len(parent_ids) != 1 or parent.get("kind") != "videos" or lineage.get("requested_timestamp_seconds", -1) < 0:
                    errors.append(f"Invalid video lineage: {sid}")
                if not source.get("selection_reason"):
                    errors.append(f"Selected frame lacks a curation reason: {sid}")
                if rights.get("status") == "allowed" and parent.get("redistribution", {}).get("status") != "allowed":
                    errors.append(f"Derived frame may not broaden source redistribution: {sid}")
    bindings = read(BINDINGS)["bindings"]
    seen = set()
    for binding in bindings:
        aid = binding["asset_id"]
        if aid in seen:
            errors.append(f"Duplicate asset binding: {aid}")
        seen.add(aid)
        used = set(binding.get("source_ids", []))
        used.update(f["source_id"] for f in binding.get("floorplans", []))
        for assertion in binding.get("assertions", []):
            used.update(assertion.get("source_ids", []))
        for sid in used - sources.keys():
            errors.append(f"Unknown source bound to {aid}: {sid}")
        for floor in binding.get("floorplans", []):
            registration = floor.get("registration", {})
            if registration.get("building_id") != aid:
                errors.append(f"Floorplan registered against a different building: {aid}: {floor['floor']}")
            if registration.get("status") not in {"approximate", "calibrated", "unregistered"}:
                errors.append(f"Floorplan registration status missing: {aid}: {floor['floor']}")
        if binding.get("spatial_binding", {}).get("coordinate_frame") != "campus_local_m":
            errors.append(f"Unrecognized coordinate frame: {aid}")
    groups_path = ROOT / "observations/bindings/groups.json"
    groups = read(groups_path)["groups"]
    group_ids = {g["id"] for g in groups}
    for binding in bindings:
        group = binding.get("observation_group")
        if group and group not in group_ids:
            errors.append(f"Unknown observation group: {binding['asset_id']}: {group}")
    for group in groups:
        for sid in set(group.get("source_ids", [])) - sources.keys():
            errors.append(f"Unknown group source: {group['id']}: {sid}")
    return {"valid": not errors, "source_count": len(sources), "asset_binding_count": len(bindings),
            "unavailable_source_ids": unavailable, "omitted_local_only_source_ids": local_only_missing, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hashes", action="store_true", help="Verify SHA-256 of all locally available source files")
    parser.add_argument("--strict-local", action="store_true", help="Require local-only media as well as public media")
    parser.add_argument("--public", action="store_true", help="Reject Git-tracked media that have no redistribution permission")
    args = parser.parse_args()
    result = validate(hashes=args.hashes, strict_local=args.strict_local, public=args.public)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
