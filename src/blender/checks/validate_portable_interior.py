"""Read-only verification of embedded portable interior inspection controls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[3]
FILE = ROOT / 'build/blender/njupt-map.blend'


def digest():
    with FILE.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    before = digest()
    bpy.ops.wm.open_mainfile(filepath=str(FILE), load_ui=False)
    scene = bpy.context.scene
    original_camera = scene.camera
    instances = [o for o in scene.objects if o.get('asset_id') and o.instance_collection]
    cameras = 0
    for instance in instances:
        for interior in instance.instance_collection.children:
            if not interior.get('njupt_editable_interiors'):
                continue
            for spec in json.loads(interior['camera_specs']):
                matches = [o for o in interior.all_objects if o.type == 'CAMERA'
                           and o.get('asset_id') == instance['asset_id']
                           and o.get('interior_camera_id') == spec['id']]
                assert len(matches) == 1, (instance['asset_id'], spec['id'])
                assert matches[0].name == spec['name'], (matches[0].name, spec['name'])
                cameras += 1
    instance = next(o for o in instances if o['asset_id'] == 'osm_way_223859810')
    interior = next(c for c in instance.instance_collection.children if c.get('njupt_editable_interiors'))
    original_flags = {o.name: (o.hide_render, o.hide_viewport) for o in instance.instance_collection.all_objects}
    native = next(o for o in interior.all_objects if o.type == 'CAMERA'
                  and o.get('asset_id') == instance['asset_id']
                  and o.get('interior_camera_id') == 'cutaway')
    expected = instance.matrix_world @ native.matrix_world
    exec(compile(bpy.data.texts['View interior.py'].as_string(), 'View interior.py', 'exec'), {})
    assert scene.camera.name == 'Interior inspection'
    assert max(abs(scene.camera.matrix_world[i][j] - expected[i][j])
               for i in range(4) for j in range(4)) < 0.0001
    assert not interior.hide_render
    assert [int(c['floor']) for c in interior.children if not c.hide_render] == [3]
    assert all(o.hide_render for o in instance.instance_collection.all_objects
               if o not in set(interior.all_objects))
    exec(compile(bpy.data.texts['Restore exterior.py'].as_string(), 'Restore exterior.py', 'exec'), {})
    assert scene.camera == original_camera
    assert interior.hide_render
    assert all((o.hide_render, o.hide_viewport) == original_flags[o.name]
               for o in instance.instance_collection.all_objects
               if o not in set(interior.all_objects))
    assert digest() == before, 'Portable file changed during read-only inspection'
    report = {'status': 'pass', 'portable_sha256': before,
              'building_instances': len(instances), 'verified_native_camera_bindings': cameras,
              'library_floor': 3, 'embedded_controls_executed': True, 'file_unchanged': True}
    target = ROOT / 'build/checks/portable-interiors.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print('PORTABLE_INTERIORS_PASS ' + json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
