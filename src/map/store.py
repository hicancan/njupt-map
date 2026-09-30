"""Read the current GeoPackage without requiring QGIS or GDAL at runtime.

Coordinates in the database are EPSG:32650 metres. Geometry is authoritative;
mesh triangles, areas and local coordinates are calculated exports.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from shapely import constrained_delaunay_triangles, from_wkb
from shapely.affinity import translate
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "projects/map/campus.gpkg"
POLYGON_LAYERS = ("waters", "greens", "sports", "surfaces", "context_buildings")
LAYERS = ("boundary", "buildings", "building_volumes", "roads", *POLYGON_LAYERS,
          "pois", "trees", "landscape_exclusions")
COLUMN_KEYS = {
    "height_m": "height", "min_height_m": "min_height", "levels": "levels",
    "style_hint": "style_hint", "height_source": "height_source",
    "levels_source": "levels_source", "base_z_m": "base_z", "width_m": "width",
}


def read_geometry(blob: bytes):
    """Decode the OGC GeoPackage binary header and its WKB geometry."""
    if not blob or blob[:2] != b"GP" or blob[2] != 0:
        raise ValueError("Expected a GeoPackage geometry binary, version 0")
    flags = blob[3]
    envelope = (flags >> 1) & 7
    if envelope > 4 or flags & 0x20:
        raise ValueError("Unsupported GeoPackage geometry header")
    offset = 8 + (0, 32, 48, 48, 64)[envelope]
    return from_wkb(blob[offset:])


def connect(path: Path = SOURCE):
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def read_metadata(con):
    return {row["key"]: json.loads(row["value_json"])
            for row in con.execute("SELECT key, value_json FROM map_metadata ORDER BY key")}


def rows(con, layer: str):
    if layer not in LAYERS:
        raise ValueError(f"Unsupported current map layer: {layer}")
    return [dict(row) for row in con.execute(f'SELECT * FROM "{layer}" ORDER BY fid')]


def coordinates(ring):
    return [[round(float(x), 6), round(float(y), 6)] for x, y in ring]


def polygon_fields(poly: Polygon, triangle_key="triangles"):
    poly = orient(poly, sign=1.0)
    return {
        "outer": coordinates(list(poly.exterior.coords)[:-1]),
        "holes": [coordinates(list(r.coords)[:-1]) for r in poly.interiors],
        triangle_key: [coordinates(list(t.exterior.coords)[:-1])
                       for t in constrained_delaunay_triangles(poly).geoms],
        "area_m2": round(poly.area, 6),
    }


def record_fields(row):
    extra = json.loads(row.get("attributes_json") or "{}")
    # Extras must not shadow editable columns or derived geometry.
    forbidden = {"id", "asset_id", "space_id", "map_feature_id", "name", "outer", "holes",
                 "center", "points", "point", "area_m2", "length_m", "roof_triangles", "triangles",
                 "upper_volumes", "geometry_role", "source_url", "source_timestamp",
                 "height", "min_height", "levels", "style_hint", "height_source", "levels_source",
                 "base_z", "width", "spatial_signature"}
    if forbidden.intersection(extra):
        raise ValueError(f"Duplicated canonical fields in attributes_json: {sorted(forbidden.intersection(extra))}")
    extra.update({"id": row["asset_id"], "asset_id": row["asset_id"], "name": row["name"] or "",
                  "space_id": row.get("space_id"), "map_feature_id": row.get("map_feature_id"),
                  "geometry_role": row["geometry_role"], "source_url": row.get("source_url") or ""})
    if row.get("source_timestamp"):
        extra["source_timestamp"] = row["source_timestamp"]
    for column, key in COLUMN_KEYS.items():
        if column in row and row[column] is not None:
            extra[key] = row[column]
    return extra


def spatial_signature(building):
    """Placement-independent signature: translating a footprint preserves a mesh.

    A different outline, courtyard, height or upper volume requires an explicit
    asset edit. Names and source descriptions never cause geometry regeneration.
    """
    cx, cy = building["center"]

    def shape(rec):
        local = Polygon([(x-cx, y-cy) for x, y in rec["outer"]],
                        [[(x-cx, y-cy) for x, y in h] for h in rec.get("holes", [])])
        # Grid snapping absorbs projection/subtraction roundoff, not genuine edits.
        from shapely import normalize, set_precision
        return normalize(set_precision(local, 0.001)).wkb_hex

    signature = {"shape": shape(building), "height": building["height"],
                 "levels": building["levels"], "min_height": building.get("min_height", 0),
                 "geometry_role": building["geometry_role"],
                 "upper_volumes": [{"shape": shape(v), "base_z": v["base_z"], "height": v["height"]}
                                   for v in building.get("upper_volumes", [])]}
    return hashlib.sha256(json.dumps(signature, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_campus(path: Path = SOURCE):
    with connect(path) as con:
        metadata = read_metadata(con)
        ox, oy = metadata["origin_easting_northing"]

        def local_geom(row):
            return translate(read_geometry(row["geom"]), xoff=-ox, yoff=-oy)

        def polygon_record(row, triangles="triangles", anchored=False):
            geom = local_geom(row)
            if not isinstance(geom, Polygon) or not geom.is_valid or geom.is_empty:
                raise ValueError(f"Invalid Polygon in {row['asset_id']}")
            rec = record_fields(row)
            rec.update(polygon_fields(geom, triangles))
            cx, cy = geom.centroid.coords[0]
            if anchored:
                cx += row["anchor_offset_e_m"]
                cy += row["anchor_offset_n_m"]
            rec["center"] = [round(cx, 6), round(cy, 6)]
            return rec

        boundary = rows(con, "boundary")
        if len(boundary) != 1:
            raise ValueError("Exactly one campus boundary is required")
        data = {"metadata": metadata, "boundary": polygon_record(boundary[0])}
        data["buildings"] = [polygon_record(row, "roof_triangles", True) for row in rows(con, "buildings")]
        building_by_id = {b["id"]: b for b in data["buildings"]}
        for row in rows(con, "building_volumes"):
            rec = polygon_record(row, "roof_triangles")
            building_by_id[row["parent_asset_id"]].setdefault("upper_volumes", []).append(rec)
        for b in data["buildings"]:
            b["spatial_signature"] = spatial_signature(b)
        for layer in POLYGON_LAYERS:
            data[layer] = [polygon_record(row, "roof_triangles" if layer == "context_buildings" else "triangles")
                           for row in rows(con, layer)]
        data["landscape_exclusions"] = [polygon_record(row) for row in rows(con, "landscape_exclusions")]
        data["roads"] = []
        for row in rows(con, "roads"):
            geom = local_geom(row)
            if not isinstance(geom, LineString) or geom.is_empty:
                raise ValueError(f"Expected a road LineString: {row['asset_id']}")
            rec = record_fields(row)
            rec.update(points=coordinates(geom.coords), length_m=round(geom.length, 6))
            data["roads"].append(rec)
        for layer in ("pois", "trees"):
            data[layer] = []
            for row in rows(con, layer):
                geom = local_geom(row)
                if not isinstance(geom, Point) or geom.is_empty:
                    raise ValueError(f"Expected a Point: {row['asset_id']}")
                rec = record_fields(row)
                rec["point"] = coordinates(geom.coords)[0]
                data[layer].append(rec)
        data["metadata"]["counts"] = {k: len(v) for k, v in data.items() if isinstance(v, list)}
        data["metadata"]["source_path"] = "projects/map/campus.gpkg"
        # Semantic hash excludes physical SQLite layout and self-reference.
        data["metadata"]["dataset_sha256"] = hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return data
