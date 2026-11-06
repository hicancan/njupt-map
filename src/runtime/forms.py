"""The shape of every building as stacked prisms, read from the Blender models from above.

Each building's roofline becomes plates of equal height, each a body in its facade colour with a
thin cap in its roof colour, and a ribbon of glass at each floor for close views. Prisms are all a
tile renderer needs, so the form costs almost nothing to draw. Writes map/layers/building_forms.geojson
and building_bands.geojson, which then build alone without Blender.
"""
from __future__ import annotations
import argparse
import json
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import subprocess
from pathlib import Path

import numpy as np
from shapely import box, union_all
from shapely.geometry import mapping, shape
from shapely.ops import transform

from ..map.authored import M_TO_WGS, ROOT, load_authored

CELL = .6
CAP = .35
GROUND = 1.2
STEP = .8
MIN_AREA = 5.0
GLASS_ALPHA = .75
WINDOW_FROM = 1.05
WINDOW_HEIGHT = 1.45
FLOOR = 3.6
WALL_LIFT = .68
ROOF_LIFT = .8
GLASS_LIFT = .3


def hex_colour(rgb, lift=0.) -> str:
    """Models are lit for a render; the map is lit by its own day, so colours are lifted toward white."""
    return '#' + ''.join(f'{round((float(v) + (1 - float(v)) * lift) * 255):02X}' for v in rgb[:3])


def roofline(triangles, colours):
    """The highest surface over each cell, and its colour."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    normal = np.cross(b - a, c - a)
    keep = np.abs(normal[:, 2]) > 1e-3
    lo = triangles[..., :2].reshape(-1, 2).min(axis=0)
    hi = triangles[..., :2].reshape(-1, 2).max(axis=0)
    shape_ = np.ceil((hi - lo) / CELL).astype(int) + 1
    height = np.full(shape_[::-1], -np.inf, dtype=np.float32)
    tone = np.zeros((*shape_[::-1], 3), dtype=np.float32)
    for tri, rgba in zip(triangles[keep], colours[keep]):
        xy = (tri[:, :2] - lo) / CELL
        x0, y0 = np.floor(xy.min(axis=0)).astype(int)
        x1, y1 = np.ceil(xy.max(axis=0)).astype(int)
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
        (ax, ay), (bx, by), (cx, cy) = xy
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-9:
            continue
        u = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / det
        v = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / det
        w = 1 - u - v
        inside = (u >= -.02) & (v >= -.02) & (w >= -.02)
        if not inside.any():
            continue
        z = u * tri[0, 2] + v * tri[1, 2] + w * tri[2, 2]
        rows = np.clip(ys[inside].astype(int), 0, height.shape[0] - 1)
        cols = np.clip(xs[inside].astype(int), 0, height.shape[1] - 1)
        values = z[inside]
        higher = values > height[rows, cols]
        height[rows[higher], cols[higher]] = values[higher]
        tone[rows[higher], cols[higher]] = rgba[:3]
    return lo, height, tone


def smooth(height):
    """A median over 3x3 removes railings, poles and other things thinner than a wall."""
    padded = np.pad(np.where(np.isfinite(height), height, 0), 1, mode='edge')
    return np.median(np.lib.stride_tricks.sliding_window_view(padded, (3, 3)), axis=(2, 3))


def plates(flat):
    """Connected cells whose neighbours differ by less than a step: each is one flat piece of roof."""
    rows, cols = flat.shape
    parent = np.arange(rows * cols)

    def find(cell):
        while parent[cell] != cell:
            parent[cell] = parent[parent[cell]]
            cell = parent[cell]
        return cell

    built = flat >= GROUND
    across = np.nonzero(built[:, :-1] & built[:, 1:] & (np.abs(flat[:, :-1] - flat[:, 1:]) < STEP))
    down = np.nonzero(built[:-1, :] & built[1:, :] & (np.abs(flat[:-1, :] - flat[1:, :]) < STEP))
    for row, col in zip(*across):
        parent[find(row * cols + col)] = find(row * cols + col + 1)
    for row, col in zip(*down):
        parent[find(row * cols + col)] = find((row + 1) * cols + col)
    labels = np.fromiter((find(cell) for cell in range(rows * cols)), dtype=np.int64, count=rows * cols).reshape(rows, cols)
    labels[~built] = -1
    return labels


def region(mask, lo):
    """The cells of a mask as polygons, merged by rows first so the union stays fast."""
    boxes = []
    for row in range(mask.shape[0]):
        cols = np.nonzero(np.diff(np.concatenate(([0], mask[row].astype(np.int8), [0]))))[0]
        for start, end in zip(cols[::2], cols[1::2]):
            boxes.append(box(lo[0] + start * CELL, lo[1] + row * CELL, lo[0] + end * CELL, lo[1] + (row + 1) * CELL))
    return union_all(boxes) if boxes else None


def facade(triangles, colours):
    """What the walls read as from a distance, and their glass: the area-weighted colour of each."""
    edge = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    area = np.linalg.norm(edge, axis=1) / 2
    upright = np.abs(edge[:, 2]) / np.maximum(1e-9, area * 2) < .3
    lightness = colours[:, :3].mean(axis=1)
    glass = upright & ((colours[:, 3] < GLASS_ALPHA) | (colours[:, 2] > colours[:, 0] * 1.25) & (lightness < .55))
    walls = upright & ~glass
    if not walls.any():
        walls = np.ones(len(triangles), bool)
    wall = np.average(colours[walls, :3], axis=0, weights=area[walls] + 1e-6)
    window = np.average(colours[glass, :3], axis=0, weights=area[glass] + 1e-6) if glass.any() else None
    share = area[glass].sum() / max(1e-6, area[upright].sum())
    return wall, window, float(share)


def parts_of(path):
    """One building's plates in metres around its centre, with its wall and window colours."""
    data = np.load(path)
    triangles, colours = data['triangles'], data['colours']
    lo, height, tone = roofline(triangles, colours)
    flat = smooth(height)
    wall, window, glazing = facade(triangles, colours)
    labels = plates(flat)
    parts = []
    for label in np.unique(labels[labels >= 0]):
        mask = labels == label
        if mask.sum() * CELL * CELL < MIN_AREA:
            continue
        polygon = region(mask, lo).buffer(-CELL * .6, join_style=2).buffer(CELL * .75, join_style=2).simplify(.3)
        for piece in getattr(polygon, 'geoms', [polygon]):
            if piece.is_empty or piece.area < MIN_AREA:
                continue
            piece = type(piece)(piece.exterior, [hole for hole in piece.interiors if abs(_area(hole)) > 4])
            parts.append((piece, float(np.percentile(flat[mask], 85)), np.median(tone[mask], axis=0).tolist()))
    return path.stem, parts, wall.tolist(), window.tolist() if window is not None and glazing > .02 else None


def _area(ring):
    xy = np.array(ring.coords)
    return .5 * np.sum(xy[:-1, 0] * xy[1:, 1] - xy[1:, 0] * xy[:-1, 1])


def extract(blender, asset, collection, out):
    target = out / f'{asset}.npz'
    if not target.exists():
        request = json.dumps({'source': str(ROOT / 'projects/blender/buildings' / f'{asset}.blend'), 'collection': collection, 'output': str(target)})
        subprocess.run([str(blender), '--background', '--factory-startup', '--python', str(Path(__file__).with_name('forms_worker.py')), '--', request], check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('triangles', type=Path, help='Directory holding <asset>.npz; missing assets are extracted with --blender')
    parser.add_argument('--blender', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'map/layers/building_forms.geojson')
    args = parser.parse_args()
    data = load_authored(ROOT)
    origin = data['metadata']['origin_easting_northing']
    catalog = json.loads((ROOT / 'projects/blender/buildings/catalog.json').read_text(encoding='utf-8'))
    ids = {row['legacy_asset_id']: row['map_id'] for row in json.loads((ROOT / 'bindings/ids.json').read_text(encoding='utf-8')) if row.get('legacy_asset_id') and row.get('map_id')}
    authored = {f['properties']['id']: f for f in json.loads((ROOT / 'map/layers/buildings.geojson').read_text(encoding='utf-8'))['features']}
    args.triangles.mkdir(parents=True, exist_ok=True)
    if args.blender:
        with ThreadPoolExecutor(6) as pool:
            list(pool.map(lambda asset: extract(args.blender, asset, catalog[asset]['collection'], args.triangles), catalog))
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(parts_of, sorted(args.triangles.glob('*.npz'))))
    features, bands, placed = [], [], set()
    for asset, parts, wall, window in results:
        map_id = ids.get(asset)
        if map_id not in authored:
            continue
        placed.add(map_id)
        cx, cy = catalog[asset]['map_center_m']
        def lonlat(x, y, z=None):
            return M_TO_WGS(np.asarray(x) + cx + origin[0], np.asarray(y) + cy + origin[1])
        for polygon, top, roof in parts:
            geometry = mapping(transform(lonlat, polygon))
            features.append((map_id, 0.0, round(top - CAP, 1), hex_colour(wall, WALL_LIFT), geometry))
            features.append((map_id, round(top - CAP, 1), round(top, 1), hex_colour(roof, ROOF_LIFT), geometry))
            if window is None or top < FLOOR or polygon.area < 40:
                continue
            ribbon = mapping(transform(lonlat, polygon.buffer(.12, join_style=2)))
            for floor in range(int(top // FLOOR)):
                base = floor * FLOOR + WINDOW_FROM
                bands.append((map_id, round(base, 1), round(base + WINDOW_HEIGHT, 1), hex_colour(window, GLASS_LIFT), ribbon))
    # A building no model covers still stands: its footprint, at its height, in plain colours.
    for map_id, feature in authored.items():
        if map_id in placed:
            continue
        top = feature['properties'].get('height_m') or (feature['properties'].get('levels') or 3) * 3.4
        features.append((map_id, 0.0, round(top - CAP, 1), '#E9E6E0', feature['geometry']))
        features.append((map_id, round(top - CAP, 1), round(top, 1), '#CFCDC9', feature['geometry']))
    def rounded(value):
        return [rounded(v) for v in value] if isinstance(value[0], (list, tuple)) else [round(float(value[0]), 7), round(float(value[1]), 7)]

    def write(path, rows, kind):
        rows.sort(key=lambda row: (row[0], row[1], row[2], json.dumps(row[4], sort_keys=True)))
        path.write_text(json.dumps({'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'properties': {'id': f'{kind}/{map_id}/{index}', 'building': map_id, 'base': base, 'top': top, 'color': colour}, 'geometry': {'type': geometry['type'], 'coordinates': rounded(geometry['coordinates'])}}
            for index, (map_id, base, top, colour, geometry) in enumerate(rows)]}, ensure_ascii=False, indent=0, separators=(',', ':')) + '\n', encoding='utf-8')

    write(args.output, features, 'form')
    write(args.output.with_name('building_bands.geojson'), bands, 'band')
    print(json.dumps({'features': len(features), 'bands': len(bands), 'buildings': len(placed), 'without_model': sorted(set(authored) - placed), 'bytes': args.output.stat().st_size}, ensure_ascii=False))


if __name__ == '__main__':
    main()
