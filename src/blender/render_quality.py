"""Render current authored exterior, interior and cutaway views, without saving sources."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys
import time

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src/blender'))
from build_campus import setup_camera

EXTERIORS = {
    'gate': ('osm_way_1454085437', (14, -108, 10), (0, 0, 11), 42),
    'entrance': ('osm_way_224938858', (45, -72, 5.5), (33, -4, 3.5), 40),
    'library': ('osm_way_223859810', (-142, -94, 56), (0, 0, 12), 47),
    'teaching': ('osm_way_223699451', (-75, -91, 40), (0, 0, 10), 40),
    'k_group': ('njupt_k_dormitory_02', (93, -134, 62), (15, 10, 10), 45),
    'gym': ('osm_way_1281082570', (94, -135, 70), (0, 0, 8), 44),
    'round_hall': ('osm_way_224950590', (90, -70, 30), (0, 0, 10), 48),
}
INTERIORS = {
    'library_inside': ('osm_way_223859810', 'study'),
    'library_cutaway': ('osm_way_223859810', 'cutaway'),
    'canteen_inside': ('osm_way_223859784', 'dining'),
    'teaching_cutaway': ('osm_way_155434036', 'cutaway'),
    'dorm_inside': ('njupt_k_dormitory_02', 'dorm'),
}


def lighting(scene, inside=False):
    world = bpy.data.worlds.new('Quality inspection daylight')
    world.use_nodes = True
    scene.world = world
    if inside:
        world.node_tree.nodes['Background'].inputs[0].default_value = (.7, .79, .92, 1)
        world.node_tree.nodes['Background'].inputs[1].default_value = .45
    else:
        nodes = world.node_tree.nodes
        sky = nodes.new('ShaderNodeTexSky')
        sky.sky_type = 'MULTIPLE_SCATTERING'
        sky.sun_elevation = math.radians(39)
        sky.sun_rotation = math.radians(225)
        sky.sun_disc = False
        world.node_tree.links.new(sky.outputs['Color'], nodes['Background'].inputs[0])
        nodes['Background'].inputs[1].default_value = .075
    light = bpy.data.lights.new('Quality daylight sun', 'SUN')
    light.energy = 2.2 if inside else 4.2
    light.angle = .035
    obj = bpy.data.objects.new(light.name, light)
    scene.collection.objects.link(obj)
    obj.rotation_euler = (.68, -.35, -.75)


def configure(scene, width, samples):
    scene.render.engine = 'CYCLES'
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'OPTIX'
    prefs.refresh_devices()
    for dev in prefs.devices:
        dev.use = dev.type == 'OPTIX'
    if not any(dev.use for dev in prefs.devices):
        raise RuntimeError('OptiX GPU unavailable')
    scene.cycles.device = 'GPU'
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = .025
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 8
    scene.cycles.diffuse_bounces = 4
    scene.cycles.glossy_bounces = 4
    scene.render.resolution_x = width
    scene.render.resolution_y = round(width * 9/16)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.exposure = .65


def interior_view(ident, key, catalog):
    from enrich_interiors import show_interior
    path = ROOT/'projects/blender/buildings'/f'{ident}.blend'
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    col = bpy.data.collections[catalog[ident]['collection']]
    interior = next((c for c in col.children if c.get('njupt_editable_interiors')), None)
    if interior is None:
        raise ValueError(f'No authored interior for {ident}')
    specs = json.loads(interior.get('camera_specs', '[]'))
    spec = next((s for s in specs if s['id'] == key), None)
    if spec is None:
        raise ValueError(f'No authored camera {key} for {ident}')
    show_interior(col, floor=spec.get('floor', 1), ceilings=spec.get('ceilings', False), exterior=False)
    scene = bpy.context.scene
    lighting(scene, inside=True)
    scene.camera = bpy.data.objects[spec['name']]
    return path, scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--views', default='overview,entrance,gate,library,teaching,k_group,gym,library_inside,canteen_inside,teaching_cutaway,dorm_inside')
    parser.add_argument('--width', type=int, default=3840)
    parser.add_argument('--samples', type=int, default=128)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    data = json.loads((ROOT/'build/map/campus.json').read_text(encoding='utf8'))
    buildings = {b['id']: b for b in data['buildings']}
    catalog = json.loads((ROOT/'projects/blender/buildings/catalog.json').read_text(encoding='utf8'))
    inputs=[ROOT/'projects/blender/campus.blend',ROOT/'projects/blender/buildings/catalog.json']
    inputs.extend(ROOT/'projects/blender/buildings'/f'{ident}.blend' for ident in catalog)
    snapshot={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    snapshot_hash=hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode('utf8')).hexdigest()
    (ROOT/'build/checks/quality-source-snapshot.json').write_text(json.dumps(snapshot,indent=2),encoding='utf8')
    reports = []
    output = ROOT/'build/blender/renders/quality'
    output.mkdir(parents=True, exist_ok=True)
    for key in args.views.split(','):
        if key in INTERIORS:
            ident, camera = INTERIORS[key]
            source, scene = interior_view(ident, camera, catalog)
        else:
            source = ROOT/'projects/blender/campus.blend'
            bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
            scene = bpy.context.scene
            if key == 'overview':
                scene.camera = bpy.data.objects['01_全校鸟瞰']
            elif key == 'entrance':
                letters = [o for o in scene.objects if o.name.startswith('低校名墙_实体书法_')]
                if len(letters) != 6:
                    raise ValueError('South namewall lettering is incomplete')
                x = sum(o.location.x for o in letters)/6
                y = sum(o.location.y for o in letters)/6
                scene.camera = setup_camera('Quality entrance', (x+.8, y-32, 3.6), (x, y, 1.6), 42)
            elif key == 'k_group':
                frame = bpy.data.objects['K组团_屋顶高跨_开放主梁与密排横梁']
                corners = [frame.matrix_world @ Vector(v) for v in frame.bound_box]
                center = sum(corners, Vector())/8
                scene.camera = setup_camera('Quality K connection', (center.x+14,center.y-20,6), (center.x,center.y,10), 24)
            else:
                ident, offset, target, lens = EXTERIORS[key]
                cx, cy = buildings[ident]['center']
                location = (cx+offset[0], cy+offset[1], offset[2])
                look = (cx+target[0], cy+target[1], target[2])
                scene.camera = setup_camera('Quality '+key, location, look, lens)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        configure(scene, args.width, args.samples)
        scene.render.filepath = str(output/(key+'.png'))
        started = time.time()
        print('QUALITY_RENDER '+key, flush=True)
        bpy.ops.render.render(write_still=True)
        if hashlib.sha256(source.read_bytes()).hexdigest() != before:
            raise ValueError('Rendering changed a native source')
        reports.append({'view': key, 'source': source.relative_to(ROOT).as_posix(),
                        'source_sha256': before,'source_project_snapshot_sha256':snapshot_hash, 'width': args.width, 'samples': args.samples,
                        'seconds': round(time.time()-started, 2),
                        'camera_location': list(scene.camera.location),
                        'path': scene.render.filepath.replace(str(ROOT), '').lstrip('/\\')})
        (ROOT/'build/checks/quality-renders.json').write_text(json.dumps(reports, indent=2), encoding='utf8')
    if any(hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=expected for path,expected in snapshot.items()):
        raise ValueError('A linked render source changed during the run')
    print('QUALITY_RENDER_PASS '+str(len(reports)), flush=True)


if __name__ == '__main__':
    main()
