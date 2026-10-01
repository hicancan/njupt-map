"""Export the editable GeoPackage to disposable local Blender and web inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.ops import transform

from .store import ROOT, SOURCE, load_campus
from .precision import wgs84_coordinates


def write_json(path, data):
    # Explicit bytes avoid platform-dependent LF -> CRLF translation.
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def export(source: Path = SOURCE, output: Path = ROOT / "build/map"):
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    data = load_campus(source)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "campus.json", data)
    ox, oy = data["metadata"]["origin_easting_northing"]
    inverse = Transformer.from_crs(data["metadata"]["crs"], "EPSG:4326", always_xy=True)

    def wgs(x, y, z=None):
        return wgs84_coordinates(inverse.transform(x + ox, y + oy))

    for layer in ("boundary", "buildings", "roads", "waters", "greens", "sports", "surfaces", "pois", "trees", "context_buildings"):
        items = [data[layer]] if layer == "boundary" else data[layer]
        features = []
        for rec in items:
            geom = Polygon(rec["outer"], rec.get("holes", [])) if "outer" in rec else (
                LineString(rec["points"]) if "points" in rec else Point(rec["point"]))
            properties = {k: v for k, v in rec.items() if k not in {"outer", "holes", "roof_triangles", "triangles", "points", "point", "upper_volumes"}}
            features.append({"type": "Feature", "id": rec["id"], "properties": properties,
                             "geometry": mapping(transform(wgs, geom))})
        write_json(output / f"{layer}.geojson", {"type": "FeatureCollection", "name": layer,
                    "features": features})
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError('Spatial source changed during export; retry after editing finishes')
    write_json(output/'export.json', {
        'source_file_sha256': source_hash,
        'campus_json_sha256': hashlib.sha256((output/'campus.json').read_bytes()).hexdigest(),
        'dataset_sha256': data['metadata']['dataset_sha256'],
        'note': 'Dataset hash describes semantic data; source file hash describes the physical GeoPackage.'
    })
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=ROOT / "build/map")
    args = parser.parse_args()
    data = export(args.source, args.output)
    print(json.dumps({"output": str(args.output), "buildings": len(data["buildings"]),
                      "dataset_sha256": data["metadata"]["dataset_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
