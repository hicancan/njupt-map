from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import mapbox_vector_tile
from PIL import Image, ImageDraw
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from pyproj import Transformer
from shapely.geometry import box, shape
from shapely.ops import unary_union

WGS_TO_M = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True).transform
EXTENT = 4096
BUFFER = 64


def lonlat_to_tile(c: tuple[float, float], z: int) -> tuple[float, float]:
    lon, lat = c
    n = 2**z
    x = (lon + 180) / 360 * n
    lat = max(-85.05112878, min(85.05112878, lat))
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile_to_lonlat(x: float, y: float, z: int) -> tuple[float, float]:
    n = 2**z
    lon = x / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lon, lat


def tile_bounds(z: int, x: int, y: int, buffer: int = 0) -> tuple[float, float, float, float]:
    margin = buffer / EXTENT
    west, north = tile_to_lonlat(x - margin, y - margin, z)
    east, south = tile_to_lonlat(x + 1 + margin, y + 1 + margin, z)
    return west, south, east, north


def tile_range(geometry: Any, z: int):
    minx, miny, maxx, maxy = shape(geometry).bounds
    a = lonlat_to_tile((minx, miny), z)
    b = lonlat_to_tile((maxx, maxy), z)
    n = 2**z
    return (
        range(max(0, int(math.floor(min(a[0], b[0])))), min(n - 1, int(math.floor(max(a[0], b[0])))) + 1),
        range(max(0, int(math.floor(min(a[1], b[1])))), min(n - 1, int(math.floor(max(a[1], b[1])))) + 1),
    )


def tile_bytes(tile_layers: dict[str, list[dict]], z: int, x: int, y: int) -> bytes:
    bounds = tile_bounds(z, x, y)
    clip = box(*tile_bounds(z, x, y, BUFFER))
    layers = []
    for name, features in sorted(tile_layers.items()):
        clipped = []
        for feature in features:
            geometry = shape(feature["geometry"])
            if geometry.is_empty:
                continue
            geometry = geometry.intersection(clip)
            if geometry.is_empty:
                continue
            if geometry.geom_type == "LineString" and len(geometry.coords) < 2:
                continue
            if geometry.geom_type == "MultiLineString" and not any(len(line.coords) > 1 for line in geometry.geoms):
                continue
            clipped.append({"id": feature.get("id"), "properties": feature.get("properties") or {}, "geometry": geometry})
        if clipped:
            layers.append({"name": name, "features": clipped})
    return mapbox_vector_tile.encode(
        layers,
        default_options={
            "quantize_bounds": bounds,
            "extents": EXTENT,
            "y_coord_down": True,
            "check_winding_order": True,
            "on_invalid_geometry": mapbox_vector_tile.encoder.on_invalid_geometry_make_valid,
        },
    )


def write_pmtiles(path: Path, layers: dict[str, list[dict]], minzoom: int = 12, maxzoom: int = 18):
    tiles: dict[int, bytes] = {}
    for z in range(minzoom, maxzoom + 1):
        by_tile: dict[tuple[int, int], dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for name, features in layers.items():
            for feature in features:
                if not feature.get("geometry"):
                    continue
                xs, ys = tile_range(feature["geometry"], z)
                for x in xs:
                    for y in ys:
                        by_tile[(x, y)][name].append(feature)
        for (x, y), tile_layers in by_tile.items():
            data = tile_bytes(tile_layers, z, x, y)
            if data:
                tiles[zxy_to_tileid(z, x, y)] = data

    metadata = {
        "name": "njupt-map authored basemap",
        "format": "pbf",
        "version": "1",
        "minzoom": minzoom,
        "maxzoom": maxzoom,
        "vector_layers": [{"id": name, "fields": {}} for name in sorted(layers)],
        "bounds": [118.8, 32.09, 119.0, 32.14],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as output:
        writer = Writer(output)
        for tile_id in sorted(tiles):
            writer.write_tile(tile_id, tiles[tile_id])
        writer.finalize(
            {
                "tile_type": TileType.MVT,
                "tile_compression": Compression.NONE,
                "min_lon_e7": 1188000000,
                "min_lat_e7": 320900000,
                "max_lon_e7": 1190000000,
                "max_lat_e7": 321400000,
                "center_lon_e7": 1189250000,
                "center_lat_e7": 321150000,
                "center_zoom": 14,
            },
            metadata,
        )
    return {"tiles": len(tiles), "bytes": path.stat().st_size, "minzoom": minzoom, "maxzoom": maxzoom}


def render_preview(path: Path, layers: dict[str, list[dict]], width: int = 1600, height: int = 1200):
    geoms = [shape(f["geometry"]) for fs in layers.values() for f in fs if f.get("geometry")]
    minx, miny, maxx, maxy = unary_union(geoms).bounds
    pad = 0.0005
    minx -= pad
    miny -= pad
    maxx += pad
    maxy += pad

    def px(c):
        return ((c[0] - minx) / (maxx - minx) * width, height - (c[1] - miny) / (maxy - miny) * height)

    image = Image.new("RGB", (width, height), "#f4f1e9")
    draw = ImageDraw.Draw(image)
    colors = {"greens": "#b8cda5", "waters": "#9cced8", "sports": "#d69a87", "surfaces": "#ddd7ca", "context_buildings": "#cfc9bd", "buildings": "#b9956d", "ways": "#a99f91", "campuses": "#f0eee5"}

    def draw_geom(geometry, color):
        if geometry.geom_type == "Polygon":
            draw.polygon([px(c) for c in geometry.exterior.coords], fill=color, outline="#918879")
        elif geometry.geom_type == "LineString":
            draw.line([px(c) for c in geometry.coords], fill=color, width=2)

    for name in ("greens", "waters", "sports", "surfaces", "context_buildings", "campuses", "buildings", "ways"):
        for feature in layers.get(name, []):
            draw_geom(shape(feature["geometry"]), colors.get(name, "#888"))
    image.save(path, "PNG")
    return {"path": str(path), "bounds": [minx, miny, maxx, maxy], "bytes": path.stat().st_size}
