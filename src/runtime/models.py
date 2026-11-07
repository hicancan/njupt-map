"""The buildings as a real-time model: what the map draws, baked from the Blender assets.

Blender keeps the authored detail. Each exterior is placed on its authored footprint, triangles too
small to see from the air are dropped, and what remains is packed for the GPU as one buffer, so both
clients draw the same thing and neither needs a model loader:

    map/models/campus.bin    12 bytes a vertex: x, y, z int16 (1/20 m from the origin),
                             normal int8 x3, colour uint8 x3. Three vertices a triangle, no index.
    map/models/campus.json   {"origin": [lon, lat], "scale": .05, "buildings": {id: [first, count]}}

A building's bindings/appearance.json entry overrides what its model guessed, with the photo that says so.
map/models/trees.json places the trees of the Blender scene; each is a few faces, so the campus reads green.

Run after src.runtime.forms has extracted the triangles.
"""
from __future__ import annotations
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from shapely import union_all
from shapely.geometry import shape
from shapely.ops import transform

from ..map.authored import M_TO_WGS, ROOT, WGS_TO_M
from .forms import fitted, parts_of

SCALE = .05
MIN_AREA = .5
WALL_LIFT = .22
ROOF_LIFT = .36


def lean(triangles, colours, min_area=MIN_AREA):
    """Drop what cannot be seen from a campus view: rails, bolts, interior-facing slivers."""
    edge = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    area = np.linalg.norm(edge, axis=1) / 2
    keep = area >= min_area
    return triangles[keep], colours[keep], edge[keep] / (area[keep, None] * 2)


def hex_rgb(value):
    return np.array([int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)], dtype=np.float32)


def trees(rows, origin):
    """Each tree a six-sided crown of 24 faces, darker underneath, in a green of its own."""
    out = np.empty(len(rows) * 72, dtype=[('p', '<i2', 3), ('n', 'i1', 3), ('c', 'u1', 3)])
    angles = np.radians(np.arange(6) * 60)
    for index, (lon, lat, radius, height) in enumerate(rows):
        east = (lon - origin[0]) * 111320 * np.cos(np.radians(origin[1]))
        north = (lat - origin[1]) * 110574
        turn = (index * 137.5) % 60
        ring = np.stack([np.cos(angles + np.radians(turn)), np.sin(angles + np.radians(turn))], axis=1)
        low, mid, top = height * .3, height * .62, height
        def at(xy, r, z):
            return [east + xy[0] * r, north + xy[1] * r, z]
        faces = []
        for a in range(6):
            b = (a + 1) % 6
            pa, pb = ring[a], ring[b]
            faces += [(at(pa, radius * .72, low), pa, -.5), (at(pb, radius * .72, low), pb, -.5), ([east, north, low * .8], (0, 0), -1.)]
            faces += [(at(pa, radius * .72, low), pa, -.2), (at(pa, radius, mid), pa, .3), (at(pb, radius, mid), pb, .3)]
            faces += [(at(pa, radius * .72, low), pa, -.2), (at(pb, radius, mid), pb, .3), (at(pb, radius * .72, low), pb, -.2)]
            faces += [(at(pa, radius, mid), pa, .3), ([east, north, top], (0, 0), 1.), (at(pb, radius, mid), pb, .3)]
        tone = np.array([.50, .62, .46]) * (.9 + (index * 2654435761 % 100) / 100 * .2)
        tone[0] += ((index * 40503) % 100) / 100 * .05
        for corner, (position, side, up) in enumerate(faces):
            row = index * 72 + corner
            shade = .84 + .16 * (up + 1) / 2
            out['p'][row] = np.round(np.array(position) / SCALE).astype(np.int16)
            out['n'][row] = np.round(np.array([side[0] * .8, side[1] * .8, up]) / max(1e-6, np.linalg.norm([side[0] * .8, side[1] * .8, up])) * 127).astype(np.int8)
            out['c'][row] = np.round(np.clip(tone * shade, 0, 1) * 255).astype(np.uint8)
    return out


def outward(triangles, normals):
    """Models wind their faces any way: roofs look up, walls look away from the building's middle."""
    middle = triangles[..., :2].reshape(-1, 2).mean(axis=0)
    away = triangles[..., :2].mean(axis=1) - middle
    flat = np.abs(normals[:, 2]) > .7
    flip = np.where(flat, normals[:, 2] < 0, (normals[:, :2] * away).sum(axis=1) < 0)
    return np.where(flip[:, None], -normals, normals)


def placed(args):
    """One building in campus metres east and north of the origin, and its colours and normals."""
    asset, map_id, geometry, origin, min_area, look = args
    data = np.load(asset)
    triangles, colours = data['triangles'], data['colours']
    parts = parts_of(Path(asset))[1]
    footprint = transform(WGS_TO_M, shape(geometry))
    fit = fitted(union_all([part[0] for part in parts]), footprint) if parts else None
    if fit is None:
        return map_id, None
    tris, tones, normals = lean(triangles, colours, min_area)
    normals = outward(tris, normals)
    x, y = fit(tris[..., 0].ravel(), tris[..., 1].ravel())
    lon, lat = M_TO_WGS(x, y)
    east = (np.asarray(lon) - origin[0]) * 111320 * np.cos(np.radians(origin[1]))
    north = (np.asarray(lat) - origin[1]) * 110574
    z = tris[..., 2].ravel()
    # The same turn applied to the normals: two nearby points give its angle.
    px, py = fit(np.array([0., 1.]), np.array([0., 0.]))
    cos, sin = (px[1] - px[0]), (py[1] - py[0])
    nx = normals[:, 0] * cos - normals[:, 1] * sin
    ny = normals[:, 0] * sin + normals[:, 1] * cos
    vertex = np.empty(len(z), dtype=[('p', '<i2', 3), ('n', 'i1', 3), ('c', 'u1', 3)])
    vertex['p'] = np.round(np.stack([east, north, z], axis=1) / SCALE).astype(np.int16)
    vertex['n'] = np.repeat(np.round(np.stack([nx, ny, normals[:, 2]], axis=1) * 127).astype(np.int8), 3, axis=0)
    # Models are lit for a render; the map has one soft light, so colours rise toward white, roofs most.
    lift = np.where(np.abs(normals[:, 2]) > .7, ROOF_LIFT, WALL_LIFT)[:, None]
    rgb = tones[:, :3] + (1 - tones[:, :3]) * lift
    if look:
        # What a photo shows replaces the guess on roofs and light walls; glass and frames stay.
        light = tones[:, :3].mean(axis=1) > .35
        rgb[(np.abs(normals[:, 2]) > .7) & light] = hex_rgb(look['roof'])
        rgb[(np.abs(normals[:, 2]) < .3) & light] = hex_rgb(look['wall'])
    vertex['c'] = np.repeat(np.round(np.clip(rgb, 0, 1) * 255).astype(np.uint8), 3, axis=0)
    return map_id, vertex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('triangles', type=Path, help='Directory of <asset>.npz from src.runtime.forms')
    parser.add_argument('--output', type=Path, default=ROOT / 'map/models')
    parser.add_argument('--min-area', type=float, default=MIN_AREA)
    args = parser.parse_args()
    ids = {row['legacy_asset_id']: row['map_id'] for row in json.loads((ROOT / 'bindings/ids.json').read_text(encoding='utf-8')) if row.get('legacy_asset_id') and row.get('map_id')}
    authored = {f['properties']['id']: f['geometry'] for f in json.loads((ROOT / 'map/layers/buildings.geojson').read_text(encoding='utf-8'))['features']}
    origin = [118.9262, 32.1146]
    looks = json.loads((ROOT / 'bindings/appearance.json').read_text(encoding='utf-8'))
    jobs = [(str(path), ids[path.stem], authored[ids[path.stem]], origin, args.min_area, looks.get(ids[path.stem])) for path in sorted(args.triangles.glob('*.npz')) if ids.get(path.stem) in authored]
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(placed, jobs))
    buildings, first, chunks = {}, 0, []
    for map_id, vertex in sorted(results, key=lambda row: row[0]):
        if vertex is None:
            continue
        buildings[map_id] = [first, len(vertex)]
        first += len(vertex)
        chunks.append(vertex)
    forest = trees(json.loads((ROOT / 'map/models/trees.json').read_text(encoding='utf-8')), origin)
    buildings['trees'] = [first, len(forest)]
    first += len(forest)
    chunks.append(forest)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'campus.bin').write_bytes(b''.join(chunk.tobytes() for chunk in chunks))
    (args.output / 'campus.json').write_text(json.dumps({'origin': origin, 'scale': SCALE, 'buildings': buildings}, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(json.dumps({'buildings': len(buildings), 'triangles': first // 3, 'bytes': first * 12, 'missing': sorted(set(authored) - set(buildings))}, ensure_ascii=False))


if __name__ == '__main__':
    main()
