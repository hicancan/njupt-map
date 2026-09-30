"""Author editable site components without replacing existing campus source work.

``enrich(campus_data)`` operates on the currently opened campus scene. Its one
owned collection can refresh its generated details while retaining the six
native name-wall curves; linked buildings, trees, lights, cameras and hand-edited
campus composition remain intact. Inputs are the explicitly exported map
dictionary, projects/blender/design/campus.json and the existing native curves.
No restricted source images are loaded or embedded.
"""
from pathlib import Path
import hashlib
import json
import math
import random

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from campus_geometry import Batch, material, point_inside
from campus_details import _bike, _bench, _distance_segment
from campus_landscape import _sample_line, _oriented_bounds, _stadium

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / 'projects/blender/design/campus.json'
COLLECTION = '04 · 校园实体细节 / current authored site components'
TAU = math.tau


def _material(name, colour, roughness=.65, metal=0., noise=0.):
    # Preserve any manual material edits and avoid accumulating shader nodes.
    name = 'Site · ' + name
    return bpy.data.materials.get(name) or material(name, colour, roughness, metal, noise)


def _owned_collection(preserve=()):
    """Replace generated site details while retaining native authored lettering."""
    preserve = tuple(preserve)
    retained = set(preserve)
    existing = bpy.data.collections.get(COLLECTION)
    if existing:
        for ob in list(existing.all_objects):
            if ob in retained:
                continue
            dat = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if dat and not dat.users:
                if isinstance(dat, bpy.types.Mesh):
                    bpy.data.meshes.remove(dat)
                elif isinstance(dat, bpy.types.Curve):
                    bpy.data.curves.remove(dat)
        for child in reversed(list(existing.children_recursive)):
            bpy.data.collections.remove(child)
        bpy.data.collections.remove(existing)
    col = bpy.data.collections.new(COLLECTION)
    bpy.context.scene.collection.children.link(col)
    for ob in preserve:
        col.objects.link(ob)
    return col


def _tag(ob, component, anchors=(), sources=(), note=''):
    ob['component_id'] = component
    ob['anchor_object_ids'] = json.dumps(list(anchors))
    ob['source_ids'] = json.dumps(list(sources))
    ob['placement_status'] = 'authored_inference_not_surveyed'
    ob['modelling_note'] = note
    return ob


def _finish(batch, name, col, component, anchors=(), sources=(), note='', bevel=0.):
    if not batch.faces:
        return None
    return _tag(batch.object(name, col, bevel), component, anchors, sources, note)


class Clearance:
    """Spatial checks for new low site furniture, including inferred track rings."""
    def __init__(self, data):
        self.data = data
        self.solids = []
        for category in ('buildings', 'waters', 'sports', 'landscape_exclusions'):
            self.solids.extend(r for r in data.get(category, [])
                               if not r.get('underground') and r.get('min_height', 0) < 2.5)
        for record in data.get('sports', []):
            if record.get('sport') == 'soccer':
                cc, _, width, angle = _oriented_bounds(record)
                self.solids.append({'outer': _stadium(cc, angle, max(36.5, width/2+1.5)+9.76), 'holes': []})
        self.tree_circles = []
        for ob in bpy.context.scene.objects:
            if ob.library or not ('乔木_' in ob.name or '湖岸垂柳_' in ob.name):
                continue
            # Existing native tree positions are protected, not relocated.
            self.tree_circles.append((ob.location.x, ob.location.y,
                                      float(ob.get('crown_collision_radius_m', 2.5))))
        # Use the native authored terrain directly instead of copying its rise.
        self.terrain = None
        ground = bpy.data.objects.get('连续校园地表_无沙盘底座')
        if ground and ground.type == 'MESH':
            self.terrain = BVHTree.FromPolygons(
                [ground.matrix_world @ v.co for v in ground.data.vertices],
                [tuple(p.vertices) for p in ground.data.polygons])

    def height(self, p):
        if self.terrain:
            hit = self.terrain.ray_cast(Vector((p[0], p[1], 100.)), Vector((0., 0., -1.)))
            if hit[0] is not None:
                return max(0., hit[0].z)
        return 0.

    def free(self, p, radius=0., roads=True, trees=False):
        if not point_inside(p, self.data['boundary']['outer'], self.data['boundary'].get('holes', [])):
            return False
        for record in self.solids:
            if point_inside(p, record['outer'], record.get('holes', [])):
                return False
            if radius:
                for ring in [record['outer']] + record.get('holes', []):
                    if any(_distance_segment(p, a, b) < radius
                           for a, b in zip(ring, ring[1:]+ring[:1])):
                        return False
        if roads:
            for road in self.data.get('roads', []):
                if any(_distance_segment(p, a, b) < road.get('width', 5.5)/2+radius+.15
                       for a, b in zip(road['points'], road['points'][1:])):
                    return False
        if trees and any(math.hypot(p[0]-x, p[1]-y) < radius+r*.6
                         for x, y, r in self.tree_circles):
            return False
        return True

    def rectangle(self, p, sx, sy, angle, roads=True, trees=False):
        c, s = math.cos(angle), math.sin(angle)
        return all(self.free((p[0]+u*c-v*s, p[1]+u*s+v*c), roads=roads, trees=trees)
                   for u in (-sx/2, 0, sx/2) for v in (-sy/2, 0, sy/2))


def _glass(name, colour):
    mat = _material(name, colour, .18, .06)
    p = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    p.inputs['IOR'].default_value = 1.46
    p.inputs['Transmission Weight'].default_value = .55
    p.inputs['Coat Weight'].default_value = .34
    return mat


def _namewall_center(data, config):
    by_id = {b['id']: b for b in data['buildings']}
    guards = [by_id[i] for i in config['anchor_ids']]
    if len(guards) != 2 or len(set(config['anchor_ids'])) != 2:
        raise ValueError('The name wall requires two distinct mapped gatehouse anchors.')
    center = tuple(sum(b['center'][axis] for b in guards)/2 + config['offset_m'][axis]
                   for axis in (0, 1))
    if not all(math.isfinite(value) for value in center):
        raise ValueError('The name wall mapped anchor must contain finite metre coordinates.')
    return center


def _namewall_letter_source(config):
    """Validate and capture the six native curves before any owned work is removed.

    The editable curves in the current .blend are the authoring source. The
    permission-restricted vector extraction is not a public runtime dependency.
    Keep each world transform so manual kerning, scale, mounting and materials
    survive movement of the component's mapped anchor.
    """
    existing = bpy.data.collections.get(COLLECTION)
    if not existing or existing.library:
        raise ValueError('The current native site collection is required before updating its lettering.')
    letters = [ob for ob in existing.all_objects
               if ob.type == 'CURVE' and ob.get('component_id') == config['component_id']]
    if len(letters) != 6:
        raise ValueError(f'The native name wall must contain exactly six authored curves; found {len(letters)}.')
    try:
        center = json.loads(existing['current_statistics'])['south_gate']['namewall_center_m']
        valid_center = len(center) == 2 and all(math.isfinite(float(value)) for value in center)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('The native name wall needs its saved component anchor in current_statistics.') from exc
    if not valid_center:
        raise ValueError('The native name wall component anchor must contain two finite metre coordinates.')
    owned = set(existing.all_objects)
    source = []
    for ob in letters:
        curve = ob.data
        if ob.library or curve.library or ob.parent in owned:
            raise ValueError(f'Native lettering must be local and independent of replaced site objects: {ob.name}')
        if not curve.splines:
            raise ValueError(f'The native letter has no editable contours: {ob.name}')
        for spline in curve.splines:
            points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
            if len(points) < 3 or not spline.use_cyclic_u or not all(
                    math.isfinite(value) for point in points for value in point.co):
                raise ValueError(f'The native letter has an invalid closed contour: {ob.name}')
        matrix = ob.matrix_world.copy()
        if not all(math.isfinite(value) for row in matrix for value in row):
            raise ValueError(f'The native letter has an invalid world transform: {ob.name}')
        source.append((ob, matrix))
    return {'center': tuple(float(value) for value in center), 'letters': source}


def _name_outlines(center, source, config):
    """Move existing six editable curves with their component; never recreate them."""
    offset = Matrix.Translation((center[0]-source['center'][0], center[1]-source['center'][1], 0.))
    for ob, matrix in source['letters']:
        ob.matrix_world = offset @ matrix
        _tag(ob, config['component_id'], config['anchor_ids'], config['sources'],
             'Native authored calligraphic curves, material and relative placement retained; mounted placement is inferred.')


def _south_gate(data, col, config, palette, clear, letter_source):
    x, y = _namewall_center(data, config)
    w, d, h = config['wall_width_m'], config['wall_depth_m'], config['wall_height_m']
    stone, dark, pale, metal = palette['stone'], palette['darkstone'], palette['pale'], palette['metal']
    b = Batch()
    # Basin is a proper open vessel with lowered bed, four kerbs and a name wall.
    pw, pl = config['pool_width_m'], config['pool_length_m']
    cy = y-d/2-pl/2
    b.box((x, cy, .08), (pw, pl, .16), dark)
    for dx in (-pw/2, pw/2):
        b.box((x+dx, cy, .245), (.22, pl+.22, .37), stone)
        b.box((x+dx, cy, .44), (.29, pl+.28, .04), pale)
    for dy in (-pl/2, pl/2):
        b.box((x, cy+dy, .245), (pw+.22, .22, .37), stone)
        b.box((x, cy+dy, .44), (pw+.28, .29, .04), pale)
    b.box((x, y, .19), (w+.5, d+.35, .38), dark)
    b.box((x, y, .38+h/2), (w, d, h), stone)
    b.box((x, y, .39+h), (w+.18, d+.16, .09), pale)
    # Subtle slab joints and inset front frame make the sign a built object.
    for xx in range(1, 10):
        b.box((x-w/2+xx*w/10, y-d/2-.006, .38+h/2), (.009, .014, h-.10), dark)
    for z in (.57, .38+h-.17):
        b.box((x, y-d/2-.013, z), (w-.28, .022, .015), metal)
    b.box((x, y-d/2-.026, .49), (w-.55, .022, .035), pale)
    structure = _finish(b, '南门_低校名墙_实体石壁与完整池体', col,
                        config['component_id'], config['anchor_ids'], config['sources'],
                        config['interpretation'], .012)
    pool = Batch()
    pool.face([(x-pw/2+.13, cy-pl/2+.13, .345), (x+pw/2-.13, cy-pl/2+.13, .345),
               (x+pw/2-.13, cy+pl/2-.13, .345), (x-pw/2+.13, cy+pl/2-.13, .345)], palette['water'])
    _finish(pool, '南门_低校名墙_反射水面', col, config['component_id'], config['anchor_ids'], config['sources'],
            'Separate water shader and lowered reflecting basin; inferred water level, not a simulated or surveyed fountain.')
    _name_outlines((x, y), letter_source, config)
    # Existing inner plaza stops north of the guardhouses; make their approach
    # continuous, but cut native building/water/exclusion polygons out cellwise.
    paving = Batch()
    for xx in range(math.floor(x-34), math.ceil(x+34), 2):
        for yy in range(math.floor(y-25), math.ceil(y+8), 2):
            corners = [(xx+.06, yy+.06), (xx+1.94, yy+.06), (xx+1.94, yy+1.94), (xx+.06, yy+1.94)]
            if any(point_inside(p, bb['outer'], bb.get('holes', [])) for p in corners
                   for bb in clear.solids):
                continue
            if any(x-pw/2-.2 < p[0] < x+pw/2+.2 and cy-pl/2-.2 < p[1] < y+d/2+.2 for p in corners):
                continue
            paving.face([(*p, .094) for p in corners], pale)
    _finish(paving, '南门_门卫房前石材广场_接缝铺装', col, config['component_id'], config['anchor_ids'], config['sources'],
            'Independent approach paving with 2 m slab module; measured dimensions unavailable.')
    return {'namewall_center_m': [x, y], 'pool_center_m': [round(x, 3), round(cy, 3)],
            'solid_structure': structure is not None, 'letter_curves': 6}


def _line_exit(center, target, ring):
    """Boundary crossing on the centre-to-centre ray; no copied world endpoints."""
    x, y = center
    dx, dy = target[0]-x, target[1]-y
    candidates = []
    for a, b in zip(ring, ring[1:]+ring[:1]):
        ex, ey = b[0]-a[0], b[1]-a[1]
        den = dx*ey-dy*ex
        if abs(den) < 1e-8:
            continue
        t = ((a[0]-x)*ey-(a[1]-y)*ex)/den
        u = ((a[0]-x)*dy-(a[1]-y)*dx)/den
        if 0 <= t <= 1 and 0 <= u <= 1:
            candidates.append(t)
    if not candidates:
        raise ValueError('K roof connection anchor ray does not cross a mapped facade')
    t = min(candidates)
    return x+t*dx, y+t*dy


def _k_connection(data, col, config, palette):
    by_id = {b['id']: b for b in data['buildings']}
    first, second = [by_id[i] for i in config['anchor_ids']]
    a = _line_exit(first['center'], second['center'], first['outer'])
    b = _line_exit(second['center'], first['center'], second['outer'])
    dx, dy = b[0]-a[0], b[1]-a[1]
    gap = math.hypot(dx, dy)
    ux, uy, nx, ny = dx/gap, dy/gap, -dy/gap, dx/gap
    a = (a[0]-ux*.60, a[1]-uy*.60)
    b = (b[0]+ux*.60, b[1]+uy*.60)
    length = gap+1.2
    cx, cy = (a[0]+b[0])/2, (a[1]+b[1])/2
    angle = math.atan2(dy, dx)
    top = min(first['height'], second['height'])*config['roof_height_fraction']
    depth = config['open_frame_depth_m']
    beam = config['main_beam_depth_m']
    frame, joints = Batch(), Batch()
    for side in (-1, 1):
        frame.box((cx+nx*side*depth/2, cy+ny*side*depth/2, top), (length, .52, beam), palette['pale'], angle)
        frame.box((cx+nx*side*(depth/2+.016), cy+ny*side*(depth/2+.016), top+.21), (length, .018, .075), palette['darkstone'], angle)
        frame.box((cx+nx*side*depth/2, cy+ny*side*depth/2, top+.32), (length+.14, .66, .07), palette['metal'], angle)
    count = max(5, round(length/config['cross_beam_spacing_m']))
    for i in range(count+1):
        u = -length/2+i*length/count
        frame.box((cx+ux*u, cy+uy*u, top-.19), (.13, depth-.15, .28), palette['metal'], angle)
    for end in (a, b):
        frame.box((*end, top-.07), (.25, depth+.1, .42), palette['pale'], angle)
        for side in (-1, 1):
            joints.box((end[0]+nx*side*(depth/2-.18), end[1]+ny*side*(depth/2-.18), top-.44), (.70, .75, .36), palette['darkstone'], angle)
    _finish(frame, 'K组团_屋顶高跨_开放主梁与密排横梁', col, config['component_id'], config['anchor_ids'], config['sources'],
            config['interpretation'], .014)
    _finish(joints, 'K组团_屋顶高跨_两端结构连接座', col, config['component_id'], config['anchor_ids'], config['sources'],
            'Beam bearing blocks are engineering inference; no columns through the open entrance and no invented upper walkway floor.')
    # Video shows a much lower red glazed entrance. The roof-level span remains
    # open; only this ground entrance receives a floor and glazing.
    floor = config['entry_lobby_floor_m']
    lh = config['entry_lobby_height_m']
    lw = config['entry_lobby_width_m']
    lobby, glass, trim, steps = Batch(), Batch(), Batch(), Batch()
    lobby.box((cx, cy, floor-.15), (length, lw, .3), palette['stone'], angle)
    lobby.box((cx, cy, floor+lh-.06), (length+.1, lw+.2, .24), palette['red'], angle)
    for side in (-1, 1):
        qx, qy = cx+nx*side*lw/2, cy+ny*side*lw/2
        lobby.box((qx, qy, floor+lh-.60), (length+.15, .23, 1.05), palette['red'], angle)
        for i in range(max(3, math.ceil(length/1.30))+1):
            u = -length/2+i*length/max(3, math.ceil(length/1.30))
            trim.box((qx+ux*u, qy+uy*u, floor+1.55), (.075, .095, 3.1), palette['metal'], angle)
        glass.box((qx, qy, floor+1.5), (length-.16, .035, 2.92), palette['glass'], angle)
        trim.box((qx, qy, floor+2.35), (length, .075, .052), palette['metal'], angle)
        # Framed double door panels, handles, thresholds and small vestibule.
        for u in (-.47, .47):
            trim.pipe((qx+ux*u, qy+uy*u-.075, floor+1.05),
                      (qx+ux*u, qy+uy*u-.075, floor+1.67), .016, palette['steel'], 8)
    for end in (a, b):
        lobby.box((*end, floor+lh/2), (.34, lw, lh), palette['stone'], angle)
    stair_depth, stair_width = 2.75, min(length+1.2, 14.2)
    for j in range(5):
        v = -lw/2-(j+.5)*stair_depth/5
        z = floor*(1-j/5)
        steps.box((cx+nx*v, cy+ny*v, z/2), (stair_width, stair_depth/5+.012, z), palette['pale'], angle)
    for side in (-1, 1):
        for j in (0, 2, 4):
            u = side*(stair_width/2-.18)
            v = -lw/2-(j+.5)*stair_depth/5
            z = floor*(1-j/5)
            trim.pipe((cx+ux*u+nx*v, cy+uy*u+ny*v, z), (cx+ux*u+nx*v, cy+uy*u+ny*v, z+1), .025, palette['steel'], 8)
        u = side*(stair_width/2-.18)
        trim.pipe((cx+ux*u-nx*(lw/2+.22), cy+uy*u-ny*(lw/2+.22), floor+1.03),
                  (cx+ux*u-nx*(lw/2+stair_depth-.20), cy+uy*u-ny*(lw/2+stair_depth-.20), 1.16), .034, palette['steel'], 10)
    for batch, name in ((lobby, 'K组团_低红入口_板体与地坪'), (glass, 'K组团_低红入口_独立玻璃门窗'),
                         (trim, 'K组团_低红入口_分格门框与扶手'), (steps, 'K组团_低红入口_五级前台阶')):
        _finish(batch, name, col, config['component_id'], config['anchor_ids'], config['sources'],
                'Low red/glazed entry type observed; pair, floor height, stairs and concealed partitions inferred.', .006 if batch is lobby else 0.)
    return {'anchor_ids': config['anchor_ids'], 'boundary_gap_m': round(gap, 3),
            'span_center_m': [round(cx, 3), round(cy, 3)], 'roof_z_m': round(top, 3),
            'cross_members': count+1, 'type': 'open_roof_frame_with_separate_low_glazed_entry',
            'placement': 'inferred_not_registered'}


def _ellipsoid(batch, center, axes, mat, segments=12, rings=7):
    x, y, z = center
    rx, ry, rz = axes
    for j in range(rings):
        lo, hi = -math.pi/2+j*math.pi/rings, -math.pi/2+(j+1)*math.pi/rings
        for i in range(segments):
            a, b = i*TAU/segments, (i+1)*TAU/segments
            batch.face([(x+rx*math.cos(v)*math.cos(u), y+ry*math.cos(v)*math.sin(u), z+rz*math.sin(v))
                        for u, v in ((a, lo), (b, lo), (b, hi), (a, hi))], mat)


def _car(batch, center, angle, colour, palette):
    start = len(batch.vertices)
    batch.box((0, 0, .60), (4.3, 1.76, .64), colour)
    batch.box((0, 0, .93), (3.10, 1.66, .18), colour)
    # Sloped windscreen and rear screen; glazing is separate physical geometry.
    cabin = [(-1.35, -.75, .91), (1.21, -.75, .91), (.74, -.68, 1.48), (-.75, -.68, 1.48),
             (-1.35, .75, .91), (1.21, .75, .91), (.74, .68, 1.48), (-.75, .68, 1.48)]
    for face in ((0, 1, 2, 3), (4, 7, 6, 5), (1, 5, 6, 2), (0, 3, 7, 4)):
        batch.face([cabin[i] for i in face], palette['darkglass'])
    batch.face([cabin[i] for i in (3, 2, 6, 7)], colour)
    for side in (-1, 1):
        batch.box((0, side*.756, 1.2), (.055, .03, .50), palette['metal'])
        for xx in (-.62, .53):
            batch.box((xx, side*.90, .95), (.14, .05, .022), palette['steel'])
        batch.box((.91, side*.96, 1.01), (.25, .12, .12), colour)
        for xx in (-1.29, 1.29):
            for depth, radius, mat in ((.13, .35, palette['rubber']), (.016, .20, palette['steel'])):
                yy = side*(.89+depth/2)
                batch.pipe((xx, yy-depth/2, .39), (xx, yy+depth/2, .39), radius, mat, 16)
                batch.face([(xx+radius*math.cos(i*TAU/16), yy+side*depth/2, .39+radius*math.sin(i*TAU/16))
                            for i in range(16)], mat)
    for xx, mat in ((2.16, palette['pale']), (-2.16, palette['red'])):
        for yy in (-.58, .58):
            batch.box((xx, yy, .76), (.025, .37, .14), mat)
        batch.box((xx, 0, .53), (.028, .44, .12), palette['pale'])
    batch.box((2.16, 0, .70), (.025, .74, .21), palette['metal'])
    ca, sa = math.cos(angle), math.sin(angle)
    x, y, z = center
    batch.vertices[start:] = [(x+u*ca-v*sa, y+u*sa+v*ca, z+w) for u, v, w in batch.vertices[start:]]


def _parking(data, col, config, palette, clear):
    cars, markings = Batch(), Batch()
    occupied = []
    colours = [_material('Car paint ' + str(i), c, .27, .46) for i, c in enumerate(
        ((.28, .31, .34), (.68, .69, .64), (.06, .15, .20), (.35, .055, .027), (.024, .027, .031)))]
    by_surface = {}
    for surface in data.get('surfaces', []):
        if surface.get('tags', {}).get('amenity') != 'parking':
            continue
        center, length, width, angle = _oriented_bounds(surface)
        ca, sa = math.cos(angle), math.sin(angle)
        count = 0
        # Long street-side parking polygons retain their full mapped shape.
        for uidx in range(max(1, math.floor(length/5.8))):
            if len(occupied) >= config['max_parking_cars']:
                break
            u = (uidx-(max(1, math.floor(length/5.8))-1)/2)*5.8
            for side in (-1, 1):
                v = side*min(width/2-2.0, 4.0)
                x, y = center[0]+u*ca-v*sa, center[1]+u*sa+v*ca
                if not point_inside((x, y), surface['outer'], surface.get('holes', [])):
                    continue
                if not clear.rectangle((x, y), 5.2, 2.6, angle):
                    continue
                corners = [(x+du*ca-dv*sa, y+du*sa+dv*ca) for du in (-2.5, 2.5) for dv in (-1.2, 1.2)]
                if not all(point_inside(p, surface['outer'], surface.get('holes', [])) for p in corners):
                    continue
                if any(math.hypot(x-p[0], y-p[1]) < 5.2 for p in occupied):
                    continue
                z = clear.height((x, y))+.085
                for dy in (-1.30, 1.30):
                    markings.box((x-sa*dy, y+ca*dy, z+.055), (5.0, .065, .012), palette['white'], angle)
                markings.box((x+ca*2.46, y+sa*2.46, z+.055), (.065, 2.6, .012), palette['white'], angle)
                if (count+uidx) % 4 != 0:
                    _car(cars, (x, y, z), angle, colours[(len(occupied)+uidx) % len(colours)], palette)
                    occupied.append((x, y))
                    count += 1
        by_surface[surface['id']] = count
    _finish(cars, '全校园_地图停车区_独立车身轮胎玻璃', col, config['component_id'], by_surface, config['sources'],
            'Generic unbranded vehicles and quantity inferred; all positions inside mapped parking polygons and clear of roads/buildings/water/sports.')
    _finish(markings, '全校园_地图停车区_泊位标线', col, config['component_id'], by_surface, config['sources'],
            'Parking bay arrangement is inferred within authoritative mapped parking areas.')
    return {'cars': len(occupied), 'parking_surfaces': by_surface}


def _road_details(data, col, config, palette, clear):
    tactile, drains, crossings, shrubs = Batch(), Batch(), Batch(), Batch()
    tactile_segments = drains_count = crossing_count = hedge_count = 0
    crossing_centers = []
    rng = random.Random(285019)
    roads = [r for r in data.get('roads', []) if r.get('width', 0) >= 4 and
             r.get('tags', {}).get('highway') not in ('path', 'footway', 'pedestrian', 'steps')]
    for road in roads:
        width = road.get('width', 5.5)
        if road.get('tags', {}).get('bridge') in ('yes', 'viaduct'):
            continue
        for p, angle in _sample_line(road['points'], 4.5, 2.0):
            ca, sa = math.cos(angle), math.sin(angle)
            q = (p[0]-sa*(width/2+.93), p[1]+ca*(width/2+.93))
            # Only clear native sidewalk space; no decorative paving through a
            # building, the inferred running track, water or trees.
            if clear.rectangle(q, 3.45, config['tactile_width_m'], angle, roads=False):
                z = clear.height(q)+.126
                tactile.box((*q, z), (3.45, config['tactile_width_m'], .018), palette['tactile'], angle)
                for offset in (-.105, -.035, .035, .105):
                    tactile.box((q[0]-sa*offset, q[1]+ca*offset, z+.014), (3.37, .019, .018), palette['tactile'], angle)
                tactile_segments += 1
        for p, angle in _sample_line(road['points'], config['road_drain_spacing_m'], 12):
            ca, sa = math.cos(angle), math.sin(angle)
            q = (p[0]-sa*(width/2-.34), p[1]+ca*(width/2-.34))
            if clear.rectangle(q, .75, .38, angle, roads=False):
                z = clear.height(q)+.134
                drains.box((*q, z), (.79, .39, .034), palette['metal'], angle)
                for offset in (-.28, -.21, -.14, -.07, 0, .07, .14, .21, .28):
                    drains.box((q[0]+ca*offset, q[1]+sa*offset, z+.019), (.029, .29, .016), palette['darkstone'], angle)
                drains_count += 1
        for p, angle in _sample_line(road['points'], config['hedge_spacing_m'], 10):
            if hedge_count >= config['max_hedge_clusters']:
                break
            ca, sa = math.cos(angle), math.sin(angle)
            for side in (-1, 1):
                q = (p[0]-side*sa*(width/2+3.4), p[1]+side*ca*(width/2+3.4))
                if not clear.rectangle(q, 3.0, 1.30, angle):
                    continue
                if not any(point_inside(q, g['outer'], g.get('holes', [])) for g in data.get('greens', [])):
                    continue
                z = clear.height(q)
                for u in (-1.0, -.5, 0, .5, 1.0):
                    _ellipsoid(shrubs, (q[0]+u*ca, q[1]+u*sa, z+.39+rng.uniform(-.06, .08)),
                               (.61, .50, .40), palette['leaves'][hedge_count % 3], 10, 5)
                hedge_count += 1
                break
        # Place an inferred transverse crossing before mapped shared junctions.
        for p, nxt in zip(road['points'], road['points'][1:]):
            length = math.dist(p, nxt)
            if length < 14:
                continue
            angle = math.atan2(nxt[1]-p[1], nxt[0]-p[0])
            ca, sa = math.cos(angle), math.sin(angle)
            connected = False
            for other in roads:
                if other is road:
                    continue
                for a, b in zip(other['points'], other['points'][1:]):
                    oa = math.atan2(b[1]-a[1], b[0]-a[0])
                    if _distance_segment(p, a, b) < 1.2 and abs(math.sin(angle-oa)) > .6:
                        connected = True
                        break
                if connected:
                    break
            if not connected:
                continue
            q = (p[0]+ca*7.0, p[1]+sa*7.0)
            if not clear.rectangle(q, 3.4, width-.55, angle, roads=False):
                continue
            if any(math.dist(q, prev) < 12 for prev in crossing_centers):
                continue
            for i in range(5):
                offset = (i-2)*.70
                z = clear.height(q)+.141
                crossings.box((q[0]+ca*offset, q[1]+sa*offset, z), (.34, width-.55, .012), palette['white'], angle)
            crossing_count += 1
            crossing_centers.append(q)
    for batch, name in ((tactile, '全校园_人行路侧_实体盲道条纹'), (drains, '全校园_路沿排水口_格栅细部'),
                         (crossings, '全校园_地图交叉口_人行横道'), (shrubs, '全校园_地图绿地_道路低篱')):
        _finish(batch, name, col, config['component_id'], [r['id'] for r in roads], config['sources'],
                config['interpretation'])
    return {'tactile_segments': tactile_segments, 'road_drains': drains_count,
            'crosswalks': crossing_count, 'hedge_clusters': hedge_count}


def _bicycle_bays(data, col, config, palette, clear):
    batch = Batch()
    counts = {}
    colours = [_material('Bicycle paint ' + str(i), c, .4, .25)
               for i, c in enumerate(((.018, .29, .51), (.78, .28, .015), (.13, .37, .13)))]
    candidates = [b for b in data['buildings'] if b.get('tags', {}).get('building') in ('dormitory', 'residential')
                  or b.get('style_hint') in ('teaching', 'dining')]
    # Geographic staggering improves full-campus coverage instead of filling the
    # first residential precinct; stable IDs settle the deterministic order.
    candidates.sort(key=lambda b: (int((b['center'][1]+800)/190), b['center'][0], b['id']))
    centers = []
    existing = []
    for ob in bpy.context.scene.objects:
        if '共享单车停车带' in ob.name:
            corners = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
            existing.append((sum(c.x for c in corners)/8, sum(c.y for c in corners)/8))
    for b in candidates:
        if len(counts) >= config['max_bicycle_bays']:
            break
        for a, q in sorted(zip(b['outer'], b['outer'][1:]+b['outer'][:1]),
                           key=lambda pair: -math.dist(*pair)):
            length = math.dist(a, q)
            if length < 15:
                continue
            angle = math.atan2(q[1]-a[1], q[0]-a[0])
            ca, sa = math.cos(angle), math.sin(angle)
            # Polygons are CCW: their outside is the right side of each edge.
            cx, cy = a[0]+(q[0]-a[0])*.25+sa*3.8, a[1]+(q[1]-a[1])*.25-ca*3.8
            if not clear.rectangle((cx, cy), 6.6, 2.25, angle, trees=True):
                continue
            if any(math.hypot(cx-x, cy-y) < 90 for x, y in centers) or any(math.hypot(cx-x, cy-y) < 15 for x, y in existing):
                continue
            z = clear.height((cx, cy))
            batch.box((cx, cy, z+.095), (6.6, 2.25, .06), palette['pale'], angle)
            for i in range(config['bicycles_per_bay']):
                u = (i-(config['bicycles_per_bay']-1)/2)*1.05
                x, y = cx+ca*u, cy+sa*u
                start = len(batch.vertices)
                _bike(batch, x, y, angle+math.pi/2, colours[i % 3], palette['steel'], palette['rubber'])
                batch.vertices[start:] = [(vx, vy, vz+z+.06) for vx, vy, vz in batch.vertices[start:]]
                # Inferred low rack hoop, shaped as a bent steel three-piece bar.
                rx, ry = x+sa*.71, y-ca*.71
                batch.pipe((rx-ca*.28, ry-sa*.28, z+.15), (rx-ca*.28, ry-sa*.28, z+.60), .022, palette['steel'], 8)
                batch.pipe((rx+ca*.28, ry+sa*.28, z+.15), (rx+ca*.28, ry+sa*.28, z+.60), .022, palette['steel'], 8)
                batch.pipe((rx-ca*.28, ry-sa*.28, z+.60), (rx+ca*.28, ry+sa*.28, z+.60), .022, palette['steel'], 8)
            centers.append((cx, cy))
            counts[b['id']] = config['bicycles_per_bay']
            break
    _finish(batch, '全校园_教学与宿舍_单车泊位及轮辐车架', col, config['component_id'], counts, config['sources'],
            'Generic bicycle geometry with parking hoops; siting/count inferred from current map and checked against existing tree crowns and prior bays.')
    return {'bicycle_bays': len(counts), 'bicycles': sum(counts.values()), 'building_bindings': counts}


def _banks(data, col, config, palette, clear):
    reeds, benches, bins = Batch(), Batch(), Batch()
    rng = random.Random(665041)
    patches = seats = bin_count = 0
    anchors = []
    for water in data.get('waters', []):
        anchors.append(water['id'])
        ring = water['outer']+water['outer'][:1]
        for p, angle in _sample_line(ring, config['lake_reed_spacing_m'], 7):
            if patches >= config['max_lake_reed_patches']:
                break
            ca, sa = math.cos(angle), math.sin(angle)
            # Authoritative polygons are CCW; right side is the dry exterior.
            q = (p[0]+sa*1.12, p[1]-ca*1.12)
            if not clear.free(q, .35):
                continue
            z = clear.height(q)
            for i in range(17):
                u, v = rng.uniform(-.7, .7), rng.uniform(-.2, .2)
                x, y = q[0]+ca*u-sa*v, q[1]+sa*u+ca*v
                h = rng.uniform(.40, 1.04)
                aa = rng.random()*TAU
                for side in (-1, 1):
                    dx, dy = math.cos(aa)*.24*side, math.sin(aa)*.24*side
                    reeds.face([(x-.012, y, z+.06), (x+.012, y, z+.06),
                                (x+dx+.016, y+dy, z+h*.72), (x+dx, y+dy, z+h)], palette['leaves'][i % 3])
                if i % 3 == 0:
                    reeds.pipe((x, y, z+.05), (x+.04, y-.02, z+h), .009, palette['reeds'], 5)
                    reeds.pipe((x+.04, y-.02, z+h*.78), (x+.04, y-.02, z+h+.035), .024, palette['seedheads'], 6)
            patches += 1
        for p, angle in _sample_line(ring, 150, 36):
            ca, sa = math.cos(angle), math.sin(angle)
            q = (p[0]+sa*5.2, p[1]-ca*5.2)
            if not clear.rectangle(q, 2.5, 1.0, angle, trees=True):
                continue
            start = len(benches.vertices)
            _bench(benches, *q, angle, palette['steel'], palette['wood'])
            z = clear.height(q)+.08
            benches.vertices[start:] = [(x, y, h+z) for x, y, h in benches.vertices[start:]]
            seats += 1
            bx, by = q[0]+ca*2.20, q[1]+sa*2.20
            if clear.free((bx, by), .6, trees=True):
                bins.box((bx, by, z+.46), (.43, .47, .85), palette['metal'], angle)
                bins.box((bx, by, z+.90), (.47, .52, .08), palette['wood'], angle)
                bins.box((bx-sa*.25, by+ca*.25, z+.80), (.33, .018, .17), palette['darkstone'], angle)
                for u in (-.12, 0, .12):
                    bins.box((bx+ca*u-sa*.248, by+sa*u+ca*.248, z+.42), (.027, .025, .52), palette['steel'], angle)
                bin_count += 1
    for batch, name in ((reeds, '全校园_地图湖缘_芦苇叶片及穗头'), (benches, '全校园_湖畔_木条长椅'),
                         (bins, '全校园_湖畔_分类容器实体')):
        _finish(batch, name, col, config['component_id'], anchors, config['sources'],
                'Bank side derived from current water polygons; species, furniture design/count and exact locations inferred, outside protected sports and building footprints.')
    return {'reed_patches': patches, 'additional_benches': seats, 'refuse_bins': bin_count}


def enrich(campus_data):
    """Return JSON-safe statistics after adding the current authored site work."""
    config = json.loads(DESIGN.read_text(encoding='utf8'))
    # Validate both the native lettering and its target before deleting any site
    # work. Public users can update the existing author source without originals.
    _namewall_center(campus_data, config['south_namewall'])
    letter_source = _namewall_letter_source(config['south_namewall'])
    col = _owned_collection(ob for ob, _ in letter_source['letters'])
    clear = Clearance(campus_data)
    palette = {
        'stone': _material('Grey granite panels', (.25, .30, .32), .59, noise=.055),
        'darkstone': _material('Charcoal stone and joints', (.036, .045, .047), .67, noise=.07),
        'pale': _material('Pale stone paving', (.48, .49, .45), .74, noise=.08),
        'metal': _material('Charcoal structural metal', (.09, .11, .115), .37, .65),
        'steel': _material('Stainless steel', (.42, .46, .46), .28, .8),
        'red': _material('K vermilion entrance cladding', (.47, .085, .035), .48, .17),
        'glass': _glass('Entry clear architectural glass', (.16, .24, .25)),
        'darkglass': _glass('Vehicle glazing', (.019, .038, .049)),
        'white': _material('Weathered white marking', (.63, .65, .60), .83),
        'rubber': _material('Tyre rubber', (.012, .014, .014), .91),
        'wood': _material('Outdoor timber', (.24, .11, .044), .66, noise=.13),
        'tactile': _material('Ochre tactile paving', (.49, .34, .085), .84, noise=.05),
        'reeds': _material('Reed stems', (.30, .35, .075), .90),
        'seedheads': _material('Reed seed heads', (.18, .115, .052), .91),
        'leaves': [_material('Leaf variation ' + str(i), c, .86, noise=.07)
                   for i, c in enumerate(((.055, .14, .026), (.082, .19, .04), (.12, .235, .057)))],
        'water': _material('Namewall reflecting water', (.027, .075, .063), .13, .10),
    }
    water = palette['water']
    p = next(n for n in water.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    p.inputs['IOR'].default_value = 1.333
    p.inputs['Transmission Weight'].default_value = .34
    p.inputs['Coat Weight'].default_value = .55
    if not any(n.type == 'BUMP' for n in water.node_tree.nodes):
        noise = water.node_tree.nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 7.
        noise.inputs['Detail'].default_value = 2.
        geom = water.node_tree.nodes.new('ShaderNodeNewGeometry')
        bump = water.node_tree.nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = .14
        bump.inputs['Distance'].default_value = .014
        water.node_tree.links.new(geom.outputs['Position'], noise.inputs['Vector'])
        water.node_tree.links.new(noise.outputs['Fac'], bump.inputs['Height'])
        water.node_tree.links.new(bump.outputs['Normal'], p.inputs['Normal'])
    rules = config['ground_detail_rules']
    stats = {'south_gate': _south_gate(campus_data, col, config['south_namewall'], palette, clear, letter_source),
             'k_connection': _k_connection(campus_data, col, config['k_roof_connection'], palette)}
    stats.update(_parking(campus_data, col, rules, palette, clear))
    stats.update(_road_details(campus_data, col, rules, palette, clear))
    stats.update(_bicycle_bays(campus_data, col, rules, palette, clear))
    stats.update(_banks(campus_data, col, rules, palette, clear))
    stats['mesh_objects'] = sum(ob.type == 'MESH' for ob in col.all_objects)
    stats['curve_objects'] = sum(ob.type == 'CURVE' for ob in col.all_objects)
    stats['mesh_vertices'] = sum(len(ob.data.vertices) for ob in col.all_objects if ob.type == 'MESH')
    stats['mesh_faces'] = sum(len(ob.data.polygons) for ob in col.all_objects if ob.type == 'MESH')
    stats['design_source'] = DESIGN.relative_to(ROOT).as_posix()
    stats['design_sha256'] = hashlib.sha256(DESIGN.read_bytes()).hexdigest()
    stats['placement_notice'] = 'Map-bound and physically reasoned authored inference; source appearance does not establish surveyed accuracy.'
    col['design_source'] = stats['design_source']
    col['current_statistics'] = json.dumps(stats, ensure_ascii=False)
    print('ENRICH_CAMPUS_DONE ' + json.dumps(stats, ensure_ascii=False), flush=True)
    return stats
