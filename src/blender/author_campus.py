"""Explicitly enrich the current native sources without regenerating authored assets.

Run with Blender's Python after exporting the current map. --apply is required
for source changes; the default only reports the intended scope. Each completed
asset updates its catalog hash immediately, so interrupted work can be resumed
with --ids. Git/LFS owns history; no backup source directories are created.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys
import time
from array import array

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/blender'))
PROJECT = ROOT / 'projects/blender'
CATALOG = PROJECT / 'buildings/catalog.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + '.partial')
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    part.replace(path)


def validate_geometry(collection):
    meshes = [o for o in collection.all_objects if o.type == 'MESH']
    if not meshes:
        raise ValueError(f'Empty collection: {collection.name}')
    for obj in meshes:
        if not all(math.isfinite(v) for p in obj.bound_box for v in p):
            raise ValueError(f'Nonfinite geometry: {obj.name}')
    return {'mesh_objects': len(meshes),
            'vertices': sum(len(o.data.vertices) for o in meshes),
            'polygons': sum(len(o.data.polygons) for o in meshes)}


def save_native(path):
    # Assets stay at their current paths; optional image references keep the
    # correct base. Fonts used to bake lettering must not become dependencies.
    for font in list(bpy.data.fonts):
        if font.filepath != '<builtin>' and font.users == 0:
            bpy.data.fonts.remove(font)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.file.make_paths_relative()
    for attempt in range(3):
        try:
            bpy.ops.wm.save_as_mainfile(filepath=str(path), compress=True)
            break
        except RuntimeError as error:
            if 'Cannot change old file' not in str(error) or attempt==2:raise
            print(f'NATIVE_SAVE_RETRY {path.name} {attempt+1}',flush=True)
            time.sleep(1.5)


def update_source_references(collection):
    sources = json.loads((ROOT/'observations/catalog.json').read_text(encoding='utf8'))['sources']
    by_filename = {}
    for source in sources.values():
        path = source.get('local_path')
        if path:
            by_filename.setdefault(Path(path).name, set()).add(path)
    for block in [collection, *collection.children_recursive, *collection.all_objects]:
        for key in ('facade_evidence', 'facade_sources', 'references', 'evidence_source'):
            if block.get(key) is None:
                continue
            value = block[key]
            values = [value] if isinstance(value, str) else list(value)
            current = []
            for ref in values:
                options = by_filename.get(Path(str(ref).replace('\\', '/')).name, set())
                current.append(next(iter(options)) if len(options)==1 else ref)
            block[key] = current[0] if isinstance(value, str) else current


def interior_signature(collection):
    """Protect authored interior geometry, transforms and cameras during exterior work."""
    digest = hashlib.sha256()
    for interior in sorted((c for c in collection.children_recursive if c.get('njupt_editable_interiors')),
                           key=lambda c:c.name):
        for child in sorted((interior,*interior.children_recursive),key=lambda c:c.name):
            digest.update(repr((child.name,child.hide_render,child.hide_viewport,
                                child.get('floor'),child.get('z_m'))).encode())
        for ob in sorted(interior.all_objects,key=lambda o:o.name):
            digest.update(repr((ob.name,ob.type,tuple(tuple(row) for row in ob.matrix_world),
                                ob.hide_render,ob.hide_viewport,ob.get('asset_id'),
                                ob.get('interior_role'),ob.get('interior_camera_id'))).encode())
            if ob.type=='MESH':
                values=array('f',[0.])*(len(ob.data.vertices)*3)
                ob.data.vertices.foreach_get('co',values);digest.update(values.tobytes())
                indices=array('i',[0])*len(ob.data.loops)
                ob.data.loops.foreach_get('vertex_index',indices);digest.update(indices.tobytes())
                polygon_sizes=array('i',[0])*len(ob.data.polygons)
                ob.data.polygons.foreach_get('loop_total',polygon_sizes);digest.update(polygon_sizes.tobytes())
            elif ob.type=='CAMERA':
                digest.update(repr((ob.data.type,ob.data.lens,ob.data.ortho_scale,
                                    ob.data.clip_start,ob.data.clip_end,ob.data.dof.focus_distance)).encode())
    text=bpy.data.texts.get('View interior.py')
    if text:digest.update(text.as_string().encode('utf8'))
    return digest.hexdigest()


def author_assets(data, catalog, ids, report,replace_interiors=False,materials_only=False,exteriors_only=False):
    from enrich_exteriors import enrich as exterior
    from enrich_interiors import enrich as interior
    buildings = {b['id']: b for b in data['buildings']}
    for index, ident in enumerate(ids, 1):
        path = PROJECT / 'buildings' / f'{ident}.blend'
        before = digest(path)
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
        collection = bpy.data.collections.get(catalog[ident]['collection'])
        if collection is None or collection.get('asset_id') != ident:
            raise ValueError(f'Native asset identity differs: {ident}')
        if not materials_only and catalog[ident]['spatial_signature']!=buildings[ident]['spatial_signature']:
            raise ValueError(f'Mapped envelope changed; review and register the native geometry before detail authoring: {ident}')
        scene = bpy.context.scene
        row = {'id': ident, 'before_sha256': before}
        if materials_only:
            previous=catalog[ident]['stats']['enrichment']
            row['exterior']=previous['exterior'];row['interior']=previous['interior']
            if row['interior']['floors']:
                from enrich_interiors import _palette
                _palette()
        elif exteriors_only:
            before_interiors = interior_signature(collection)
            previous = catalog[ident]['stats']['enrichment']
            row['exterior'] = exterior(buildings[ident], collection, campus=data)
            row['interior'] = previous['interior']
            if interior_signature(collection)!=before_interiors:
                raise ValueError(f'Exterior details changed protected authored interiors: {ident}')
            row['interiors_preserved_sha256'] = before_interiors
        else:
            row['exterior'] = exterior(buildings[ident], collection, campus=data)
            row['interior'] = interior(buildings[ident], collection,replace=replace_interiors)
        update_source_references(collection)
        row['geometry'] = validate_geometry(collection)
        collection['authoring_revision'] = 'campus-wide-detail-and-interiors'
        scene['authoring_scope'] = 'Current editable exterior and interior; inferred dimensions recorded on collections.'
        if row['interior'].get('floors', 0) and not exteriors_only:
            text = bpy.data.texts.get('View interior.py') or bpy.data.texts.new('View interior.py')
            text.use_fake_user = True
            text.clear()
            text.write('''# Run in this building file. Change floor/ceilings below to inspect another level.
from pathlib import Path
import sys, bpy, json
root = Path(bpy.data.filepath).resolve().parents[3]
sys.path.insert(0, str(root / 'src/blender'))
from enrich_interiors import show_interior, show_exterior
asset = bpy.context.scene['asset_id']
col = next(c for c in bpy.context.scene.collection.children if c.get('asset_id') == asset)
interior = show_interior(col, floor=1, ceilings=False, exterior=False)
specs = json.loads(interior.get('camera_specs', '[]'))
if specs:
    view = next((s for s in specs if s.get('id') == 'cutaway'), specs[0])
    bpy.context.scene.camera = bpy.data.objects[view['name']]
# To restore the exterior view: show_exterior(col)
''')
        save_native(path)
        row['sha256'] = digest(path)
        record = catalog[ident]
        record['sha256'] = row['sha256']
        record['stats']['objects'] = len(collection.all_objects)
        record['stats']['enrichment'] = {key: row[key] for key in ('exterior', 'interior', 'geometry')}
        write_json(CATALOG, catalog)
        report['assets'][ident] = row
        write_json(ROOT / 'build/checks/authoring.json', report)
        print(f'AUTHORED {index}/{len(ids)} {ident} {json.dumps(row["geometry"])}', flush=True)


def add_scene_details(path, data, report, key):
    from enrich_campus import enrich
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    scene = bpy.context.scene
    before = digest(path)
    original_instances = {o['asset_id']: tuple(o.location) for o in scene.objects if o.get('asset_id')}
    moved_trees = fit_entry_landscape(data)
    result = enrich(data)
    result['entry_trees_relocated'] = moved_trees
    after_instances = {o['asset_id']: tuple(o.location) for o in scene.objects if o.get('asset_id')}
    if before and original_instances != after_instances:
        raise ValueError('Scene enrichment changed mapped building instances')
    scene['campus_detail_revision'] = 'campus-wide-detail-and-interiors'
    scene['georeference'] = json.dumps(data['metadata'], ensure_ascii=False)
    scene['design_inference_policy'] = 'Actively model plausible detail; observation-backed topology and inferred dimensions remain distinguishable in native metadata.'
    save_native(path)
    report[key] = {'before_sha256': before, 'sha256': digest(path), 'details': result}
    write_json(ROOT / 'build/checks/authoring.json', report)


def fit_entry_landscape(data):
    """Resolve collisions between inferred trees and the newly authored basin."""
    from campus_geometry import point_inside
    from campus_details import _distance_segment
    from enrich_campus import Clearance
    from mathutils import Vector
    design = json.loads((PROJECT/'design/campus.json').read_text(encoding='utf8'))['south_namewall']
    by_id = {b['id']: b for b in data['buildings']}
    anchors = [by_id[ident]['center'] for ident in design['anchor_ids']]
    x = sum(p[0] for p in anchors)/2 + design['offset_m'][0]
    y = sum(p[1] for p in anchors)/2 + design['offset_m'][1]
    xmin, xmax = x-17, x+17
    ymin, ymax = y-43, y+1.6
    scene = bpy.context.scene
    trees = [o for o in scene.objects if o.name.startswith(('乔木_', '湖岸垂柳_'))]
    radii = {o: float(o.get('crown_collision_radius_m', 3.6)) for o in trees}
    clear = Clearance(data)
    changed = []
    removed = []
    for ob in trees:
        px, py = ob.location.x, ob.location.y
        r = radii[ob]
        if math.hypot(max(xmin-px, 0, px-xmax), max(ymin-py, 0, py-ymax)) > r+1:
            continue
        candidates = []
        for distance in (18, 27, 36, 48, 62, 78):
            for i in range(24):
                angle = i*math.tau/24
                q = (px+distance*math.cos(angle), py+distance*math.sin(angle))
                if xmin-r-2 < q[0] < xmax+r+2 and ymin-r-2 < q[1] < ymax+r+2:
                    continue
                if not any(point_inside(q, g['outer'], g.get('holes', [])) for g in data['greens']):
                    continue
                if not clear.free(q, r+.4, trees=False):
                    continue
                if any(math.hypot(q[0]-other.location.x, q[1]-other.location.y) < r+radii[other]+.25
                       for other in trees if other != ob and other not in removed):
                    continue
                candidates.append((distance, q))
            if candidates:
                break
        if not candidates:
            changed.append({'object': ob.name, 'before_local_m': list(ob.location),
                            'action': 'removed_inferred_tree_from_paved_entry_clearance'})
            removed.append(ob)
            continue
        _, q = min(candidates)
        old = list(ob.location)
        ob.location = Vector((q[0], q[1], clear.height(q)))
        ob['placement_revision'] = 'Inferred tree moved outside authored namewall and reflecting-basin clearance.'
        changed.append({'object': ob.name, 'before_local_m': old, 'after_local_m': list(ob.location)})
    for ob in removed:
        bpy.data.objects.remove(ob, do_unlink=True)
    return changed


def update_authored_film():
    """Apply the current camera design to existing camera objects and animation."""
    from build_campus_film import pose, orient
    scene = bpy.context.scene
    current = json.loads(scene['film_plan'])
    design = json.loads((PROJECT/'presentation/camera_plan.json').read_text(encoding='utf8'))
    by_id = {shot['id']: shot for shot in current['shots']}
    for spec in design['shots']:
        old = by_id[spec['id']]
        cam = bpy.data.objects[old['camera']]
        first, last = old['frame_start'], old['frame_end']
        cam.data.lens = spec['lens']
        for frame in range(first-1, last+2):
            loc, target = pose(spec, (frame-first)/(last-first))
            cam.location = loc
            cam.rotation_quaternion = orient(loc, target, spec.get('roll_deg', 0))
            cam.data.dof.focus_distance = (target-loc).length
            cam.keyframe_insert('location', frame=frame)
            cam.keyframe_insert('rotation_quaternion', frame=frame)
            cam.data.dof.keyframe_insert('focus_distance', frame=frame)
        spec.update(camera=cam.name, frame_start=first, frame_end=last)
    scene['film_plan'] = json.dumps(design, ensure_ascii=False)
    scene.frame_set(1)
    scene.camera = bpy.data.objects[design['shots'][0]['camera']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--assets', action='store_true')
    parser.add_argument('--exteriors', action='store_true',help='Refresh only owned exterior details; preserve authored interiors and cameras.')
    parser.add_argument('--interior-materials',action='store_true',help='Refresh the authored interior palette while preserving all meshes and cameras.')
    parser.add_argument('--replace-interiors', action='store_true',help='Explicitly replace this tool\'s current interior source collections; keep exterior envelopes.')
    parser.add_argument('--campus', action='store_true')
    parser.add_argument('--presentation', action='store_true')
    parser.add_argument('--ids', help='Comma-separated common IDs; defaults to all mapped assets')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    data = json.loads((ROOT / 'build/map/campus.json').read_text(encoding='utf8'))
    exported = json.loads((ROOT/'build/map/export.json').read_text(encoding='utf8'))
    if (exported['source_file_sha256'] != digest(ROOT / 'projects/map/campus.gpkg') or
            exported['campus_json_sha256'] != digest(ROOT/'build/map/campus.json')):
        raise ValueError('Export is stale; export the current map before authoring')
    catalog = json.loads(CATALOG.read_text(encoding='utf8'))
    ids = args.ids.split(',') if args.ids else list(catalog)
    if not set(ids) <= set(catalog):
        raise ValueError('Unknown requested asset IDs')
    if not args.apply:
        print(json.dumps({'would_edit_assets': ids if args.assets else [],
                          'would_refresh_exteriors':ids if args.exteriors else [],
                          'would_refresh_interior_materials':ids if args.interior_materials else [],'would_edit_campus': args.campus,
                          'would_edit_presentation': args.presentation}, ensure_ascii=False))
        return
    if not (args.assets or args.exteriors or args.interior_materials or args.campus or args.presentation):
        parser.error('--apply requires an explicit source scope')
    if sum((args.assets,args.exteriors,args.interior_materials))>1:
        parser.error('Choose complete asset authoring, exterior details, or interior materials')
    if args.replace_interiors and not args.assets:parser.error('--replace-interiors requires --assets')
    path = ROOT / 'build/checks/authoring.json'
    report = json.loads(path.read_text(encoding='utf8')) if path.exists() else {'assets': {}}
    report.update(status='running', map_sha256=digest(ROOT / 'projects/map/campus.gpkg'))
    started = time.time()
    if args.assets or args.exteriors or args.interior_materials:
        author_assets(data, catalog, ids, report,args.replace_interiors,args.interior_materials,args.exteriors)
    if args.campus:
        add_scene_details(PROJECT / 'campus.blend', data, report, 'campus')
    if args.presentation:
        add_scene_details(PROJECT / 'presentation/film.blend', data, report, 'presentation')
        update_authored_film()
        bpy.context.scene['film_source_sha256'] = digest(PROJECT / 'campus.blend')
        save_native(PROJECT / 'presentation/film.blend')
        report['presentation']['sha256'] = digest(PROJECT / 'presentation/film.blend')
    report.update(status='pass', elapsed_seconds=round(time.time()-started, 2))
    write_json(path, report)
    print('AUTHORING_PASS', len(report['assets']), flush=True)


if __name__ == '__main__':
    main()
