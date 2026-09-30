"""Validate the current editable spatial source and observation references."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .store import ROOT, SOURCE, LAYERS, connect, load_campus, read_geometry, read_metadata, rows


def validate(source: Path = SOURCE, catalog_path: Path = ROOT / "observations/catalog.json",
             bindings_path: Path = ROOT / "observations/bindings/assets.json"):
    errors = []
    checks = Counter()
    notes = []

    def error(issue, **context):
        errors.append({"issue": issue, **context})

    with connect(source) as con:
        result = con.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            error("sqlite_integrity", detail=result)
        checks["sqlite_integrity"] += 1
        metadata = read_metadata(con)
        if metadata.get("schema_version") != 1:
            error("unsupported_current_schema")
        if metadata.get("crs") != "EPSG:32650" or metadata.get("units") != "m":
            error("coordinate_contract")
        ox, oy = metadata["origin_easting_northing"]
        actual_origin = Transformer.from_crs("EPSG:4326", metadata["crs"], always_xy=True).transform(*metadata["origin_lonlat"])
        if max(abs(v-w) for v, w in zip(actual_origin, (ox, oy))) > 1e-5:
            error("origin_transform_mismatch")
        checks["origin_transform"] += 1
        for layer in LAYERS:
            registration = con.execute("SELECT geometry_type_name,srs_id,z,m FROM gpkg_geometry_columns WHERE table_name=?", (layer,)).fetchone()
            if not registration or tuple(registration)[1:] != (32650, 0, 0):
                error("gpkg_layer_coordinate_contract", layer=layer)
            layer_rows = rows(con, layer)
            ids = [row["asset_id"] for row in layer_rows]
            if len(ids) != len(set(ids)) or any(not value for value in ids):
                error("invalid_or_duplicate_asset_id", layer=layer)
            for row in layer_rows:
                geom = read_geometry(row["geom"])
                if geom.is_empty or not geom.is_valid or not all(math.isfinite(v) for v in geom.bounds):
                    error("invalid_geometry", layer=layer, asset_id=row["asset_id"])
                if not row["geometry_role"]:
                    error("missing_geometry_semantics", layer=layer, asset_id=row["asset_id"])
                json.loads(row["attributes_json"])
                checks["geometries"] += 1
            checks["layers"] += 1
    data = load_campus(source)
    campus = Polygon(data["boundary"]["outer"], data["boundary"]["holes"])

    def mesh(rec, triangle_key):
        polygon = Polygon(rec["outer"], rec["holes"])
        triangles = [Polygon(ring) for ring in rec[triangle_key]]
        difference = unary_union(triangles).symmetric_difference(polygon).area
        if difference > max(0.002, polygon.area * 1e-8):
            error("triangulation_mismatch", asset_id=rec["id"], difference_m2=difference)
        if abs(sum(t.area for t in triangles)-polygon.area) > max(0.002, polygon.area*1e-8):
            error("overlapping_triangles", asset_id=rec["id"])
        checks["triangles"] += len(triangles)
        checks["courtyards"] += len(rec["holes"])
        return polygon

    mesh(data["boundary"], "triangles")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))["sources"]
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))["bindings"]
    binding_ids = [item["asset_id"] for item in bindings]
    building_ids = {b["id"] for b in data["buildings"]}
    if len(binding_ids) != len(set(binding_ids)):
        error("duplicate_observation_binding")
    if set(binding_ids) != building_ids:
        error("observation_binding_asset_mismatch", missing=sorted(building_ids-set(binding_ids)), extra=sorted(set(binding_ids)-building_ids))
    for b in data["buildings"]:
        polygon = mesh(b, "roof_triangles")
        if campus.intersection(polygon).area / polygon.area < 0.5:
            error("building_majority_outside_campus", asset_id=b["id"])
        if not (0 <= b.get("min_height", 0) < b["height"] < 150) or not (0 < b["levels"] < 50):
            error("invalid_building_dimensions", asset_id=b["id"])
        if not b["height_source"] or not b["levels_source"]:
            error("missing_dimension_basis", asset_id=b["id"])
        if b["id"].startswith("njupt_k_") and b["geometry_role"] != "roof_block_proxy":
            error("inferred_roof_proxy_mislabeled", asset_id=b["id"])
        for source_id in b.get("source_ids", []):
            if source_id not in catalog:
                error("unknown_observation_source", asset_id=b["id"], source_id=source_id)
            checks["source_bindings"] += 1
        for upper in b.get("upper_volumes", []):
            shape = mesh(upper, "roof_triangles")
            if not polygon.buffer(0.002).covers(shape):
                error("upper_volume_outside_outline", asset_id=b["id"])
            if abs(upper["base_z"]-b["height"]) > 0.002 or upper["height"] <= 0:
                error("upper_volume_vertical_contract", asset_id=b["id"])
            checks["upper_volumes"] += 1
        checks["buildings"] += 1
    for layer in ("waters", "greens", "sports", "surfaces", "context_buildings", "landscape_exclusions"):
        for rec in data[layer]:
            mesh(rec, "roof_triangles" if layer == "context_buildings" else "triangles")
    for road in data["roads"]:
        if road["width"] <= 0 or len(road["points"]) < 2:
            error("invalid_road", asset_id=road["id"])
        checks["roads"] += 1
    # Source files are independent observations. Missing restricted images are not
    # needed to open the public map; present source bytes must match the catalog.
    for source_id in metadata.get("source_ids", []):
        record = catalog.get(source_id)
        if not record:
            error("unknown_map_source", source_id=source_id)
            continue
        path = ROOT / record["local_path"]
        if path.is_file():
            with path.open("rb") as stream:
                is_lfs_pointer = stream.read(128).startswith(b"version https://git-lfs.github.com/spec/v1\n")
            if is_lfs_pointer:
                notes.append({"issue": "observation_lfs_not_fetched", "source_id": source_id})
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != record.get("sha256"):
                error("observation_sha256_mismatch", source_id=source_id)
            checks["source_sha256"] += 1
        else:
            notes.append({"issue": "observation_not_present", "source_id": source_id,
                          "redistribution": record.get("redistribution", {}).get("status")})
    return {"passed": not errors, "source": str(source), "dataset_sha256": data["metadata"]["dataset_sha256"],
            "checks": dict(checks), "errors": errors, "notes": notes,
            "scope": metadata["scope"], "survey_accuracy": "not established"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=ROOT / "build/checks/map/validation.json")
    args = parser.parse_args()
    report = validate(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
