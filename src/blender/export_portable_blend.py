"""Create an editable public snapshot of the linked campus.

Run only after the final master has finished saving (no rendering is performed):
  blender --background --factory-startup --python-exit-code 1 \
    --python src/blender/export_portable_blend.py

The source master and asset files are opened read-only and fingerprinted before
and after. Only build/blender/njupt-map.blend and its JSON report are
written. Buildings remain distinct collection instances; shared tree meshes
are never realized, duplicated, or joined. Rerunning replaces the snapshot.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import bpy

ROOT = Path(__file__).resolve().parents[2]
TASK_TEMP = ROOT/'build/blender/_work/export'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(path):
    path = Path(path).resolve()
    stat = path.stat()
    return {'path': str(path), 'bytes': stat.st_size,
            'mtime_ns': stat.st_mtime_ns, 'sha256': sha256(path)}


def primitive(value):
    if hasattr(value, 'to_dict'):
        return primitive(value.to_dict())
    if hasattr(value, 'to_list'):
        return primitive(value.to_list())
    if isinstance(value, dict):
        return {str(k): primitive(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [primitive(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def metadata(block):
    return {key: primitive(block[key]) for key in block.keys()}


def reachable_objects(scene):
    seen = {}
    pending = list(scene.objects)
    while pending:
        obj = pending.pop()
        pointer = obj.as_pointer()
        if pointer in seen:
            continue
        seen[pointer] = obj
        if obj.instance_type == 'COLLECTION' and obj.instance_collection:
            pending.extend(obj.instance_collection.all_objects)
    return list(seen.values())


def reachable_datablocks(scene):
    dependencies = defaultdict(set)
    for dependency, users in bpy.data.user_map().items():
        for user in users:
            dependencies[user].add(dependency)
    seen = set()
    pending = [scene]
    while pending:
        block = pending.pop()
        if block in seen:
            continue
        seen.add(block)
        pending.extend(dependencies.get(block, ()))
    return seen


def packed(block):
    return bool(getattr(block, 'packed_file', None) or
                getattr(block, 'packed_files', []))


def building_instances(scene):
    return [obj for obj in scene.objects
            if obj.get('asset_id') and obj.instance_type == 'COLLECTION']


def tree_signature(scene):
    trees = [obj for obj in scene.objects
             if obj.name.startswith('乔木_') and obj.type == 'MESH']
    meshes = {obj.data.as_pointer(): obj.data for obj in trees}
    return {'object_instances': len(trees), 'unique_meshes': len(meshes),
            'unique_mesh_vertices': sum(len(mesh.vertices) for mesh in meshes.values()),
            'unique_mesh_polygons': sum(len(mesh.polygons) for mesh in meshes.values())}


def viewport_signature():
    """Preserve the user's saved opening workspace and 3D view, not factory UI."""
    records=[]
    for screen in sorted(bpy.data.screens,key=lambda item:item.name):
        for index,area in enumerate(screen.areas):
            if area.type!='VIEW_3D':continue
            space=area.spaces.active
            region=space.region_3d
            if not region:continue
            records.append({'screen':screen.name,'area_index':index,
                'view_perspective':region.view_perspective,
                'view_location':[round(v,6) for v in region.view_location],
                'view_rotation':[round(v,6) for v in region.view_rotation],
                'view_distance':round(region.view_distance,6),
                'view_camera_offset':[round(v,6) for v in region.view_camera_offset],
                'view_camera_zoom':round(region.view_camera_zoom,6),
                'shading':space.shading.type,'overlay_visible':space.overlay.show_overlays,
                'floor_grid_visible':space.overlay.show_floor,
                'axis_x_visible':space.overlay.show_axis_x,'axis_y_visible':space.overlay.show_axis_y})
    return {'active_screen':bpy.context.screen.name if bpy.context.screen else None,
            'active_workspace':bpy.context.workspace.name if bpy.context.workspace else None,
            'view3d_areas':records}


def verify_scene(expected_ids, original_scene_metadata, original_asset_metadata,
                 original_tree_signature, floorplans_expected, original_viewport=None):
    scene = bpy.context.scene
    errors = []
    instances = building_instances(scene)
    ids = [str(obj['asset_id']) for obj in instances]
    if set(ids) != expected_ids or len(ids) != len(expected_ids):
        errors.append({'issue': 'building_instance_mismatch', 'actual': len(ids),
                       'missing': sorted(expected_ids - set(ids)),
                       'extra': sorted(set(ids) - expected_ids)})
    if not scene.objects:
        errors.append({'issue': 'empty_scene'})
    if len(bpy.data.libraries):
        errors.append({'issue': 'external_libraries_remain',
                       'libraries': [lib.filepath for lib in bpy.data.libraries]})
    assets = []
    for obj in instances:
        asset_id = str(obj['asset_id'])
        collection = obj.instance_collection
        if not collection or collection.library:
            errors.append({'issue': 'building_collection_not_local', 'id': asset_id})
            continue
        record = {'id': asset_id, 'instance': obj.name, 'collection': collection.name,
                  'mesh_objects': sum(o.type == 'MESH' for o in collection.all_objects),
                  'local': True}
        assets.append(record)
        if not record['mesh_objects']:
            errors.append({'issue': 'building_geometry_missing', 'id': asset_id})
        old = original_asset_metadata[asset_id]
        if metadata(obj) != old['instance'] or metadata(collection) != old['collection']:
            errors.append({'issue': 'building_metadata_changed', 'id': asset_id})
    for key, value in original_scene_metadata.items():
        if key not in scene or primitive(scene[key]) != value:
            errors.append({'issue': 'scene_metadata_changed', 'key': key})
    objects = reachable_objects(scene)
    references = [obj for obj in objects
                  if obj.type == 'EMPTY' and obj.empty_display_type == 'IMAGE'
                  and obj.get('registration_status') == 'approximate_not_surveyed']
    if len(references) != floorplans_expected:
        errors.append({'issue': 'floorplan_reference_count', 'actual': len(references),
                       'expected': floorplans_expected})
    floorplans = []
    for obj in references:
        image = obj.data
        row = {'object': obj.name, 'image': image.name if image else None,
               'packed': bool(image and packed(image)),
               'source_sha256': obj.get('source_sha256'),
               'floor': obj.get('floor'), 'hidden_from_render': obj.hide_render}
        floorplans.append(row)
        if row['packed'] or not row['hidden_from_render']:
            errors.append({'issue': 'restricted_floorplan_embedded_or_visible', 'object': obj.name})
    images = []
    for image in bpy.data.images:
        if not image.users or image.source in ('VIEWER', 'GENERATED'):
            continue
        optional = image.get('source_project_path','').startswith('observations/')
        images.append({'name': image.name, 'source': image.source, 'users': image.users,
                       'packed': packed(image), 'optional_local_reference':optional,
                       'size_px': list(image.size)})
        if optional and packed(image):
            errors.append({'issue': 'restricted_image_embedded', 'image': image.name})
        if not optional and not packed(image):
            errors.append({'issue': 'image_not_packed', 'image': image.name})
    fonts = []
    for font in bpy.data.fonts:
        if not font.users or font.filepath == '<builtin>':
            continue
        fonts.append({'name': font.name, 'packed': packed(font), 'users': font.users})
        errors.append({'issue': 'external_font_dependency', 'font': font.name})
    linked = [block.name_full for block in reachable_datablocks(scene)
              if getattr(block, 'library', None)]
    if linked:
        errors.append({'issue': 'reachable_linked_datablocks', 'names': linked})
    trees = tree_signature(scene)
    if trees != original_tree_signature:
        errors.append({'issue': 'shared_tree_geometry_changed',
                       'before': original_tree_signature, 'after': trees})
    viewport=viewport_signature()
    if original_viewport is not None and viewport!=original_viewport:
        errors.append({'issue':'opening_viewport_changed','before':original_viewport,'after':viewport})
    return {'errors': errors, 'scene': scene.name, 'scene_object_count': len(scene.objects),
            'reachable_object_count': len(objects), 'external_library_count': len(bpy.data.libraries),
            'building_instance_count': len(instances), 'local_building_collections': len(assets),
            'building_records': assets, 'floorplan_reference_count': len(references),
            'floorplan_images': floorplans, 'file_images': images, 'file_image_count': len(images),
            'packed_file_image_count': sum(row['packed'] for row in images),
            'fonts': fonts, 'tree_sharing': trees,
            'opening_viewport':viewport,'opening_viewport_preserved':viewport==original_viewport,
            'scene_metadata_preserved': not any(e['issue'] == 'scene_metadata_changed' for e in errors),
            'asset_metadata_preserved': not any(e['issue'] == 'building_metadata_changed' for e in errors)}


def main():
    global TASK_TEMP
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--master', type=Path, default=ROOT/'projects/blender/campus.blend')
    parser.add_argument('--output', type=Path, default=ROOT/'build/blender/njupt-map.blend')
    parser.add_argument('--report', type=Path, default=ROOT/'build/checks/portable_export_validation.json')
    parser.add_argument('--expected-buildings', type=int, default=0)
    parser.add_argument('--expected-floorplans', type=int, default=23)
    parser.add_argument('--temp-dir', type=Path, default=TASK_TEMP,
                        help='Process-local working directory for Blender exporter')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    TASK_TEMP = args.temp_dir.resolve()
    if not args.expected_buildings:
        canonical=json.loads((ROOT/'build/map/campus.json').read_text(encoding='utf8'))
        args.expected_buildings=len({b['id'] for b in canonical['buildings']})
    master, output, report_path = args.master.resolve(), args.output.resolve(), args.report.resolve()
    if output == master or master.parent == output.parent:
        raise ValueError('Portable output must be separate from the source master directory.')
    if not output.is_relative_to((ROOT/'build').resolve()):
        raise ValueError('Portable snapshots must be written inside build/.')
    if output.suffix.lower() != '.blend':
        raise ValueError('Portable output must have a .blend extension.')
    TASK_TEMP.mkdir(parents=True, exist_ok=True)
    # These overrides affect only this Blender exporter process, never user env.
    os.environ['TEMP'] = str(TASK_TEMP)
    os.environ['TMP'] = str(TASK_TEMP)
    started = time.time()
    report = {'schema_version': '1.0', 'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'blender_version': bpy.app.version_string, 'master': str(master),
              'portable': str(output), 'source_files_read_only': True, 'status': 'running'}
    sources = {}
    try:
        sources[str(master)] = fingerprint(master)
        bpy.ops.wm.open_mainfile(filepath=str(master), load_ui=True)
        bpy.context.preferences.filepaths.temporary_directory = str(TASK_TEMP)
        scene = bpy.context.scene
        instances = building_instances(scene)
        if len(instances) != args.expected_buildings:
            raise RuntimeError(f'Expected {args.expected_buildings} building instances, found {len(instances)}')
        expected_ids = {str(obj['asset_id']) for obj in instances}
        if len(expected_ids) != args.expected_buildings:
            raise RuntimeError('Duplicate building asset IDs in source master.')
        original_scene_metadata = metadata(scene)
        original_tree_signature = tree_signature(scene)
        original_viewport=viewport_signature()
        original_asset_metadata = {}
        loaded = {}
        appended_records = []
        for index, obj in enumerate(sorted(instances, key=lambda ob: str(ob['asset_id'])), 1):
            old_collection = obj.instance_collection
            if not old_collection or not old_collection.library:
                raise RuntimeError(f'Expected linked building collection: {obj.name}')
            asset_id = str(obj['asset_id'])
            original_asset_metadata[asset_id] = {'instance': metadata(obj),
                                                'collection': metadata(old_collection)}
            library = old_collection.library
            source = Path(bpy.path.abspath(library.filepath, library=library.parent)).resolve()
            sources.setdefault(str(source), fingerprint(source))
            key = (str(source), old_collection.name)
            if key not in loaded:
                with bpy.data.libraries.load(str(source), link=False) as (available, destination):
                    if old_collection.name not in available.collections:
                        raise RuntimeError(f'Collection {old_collection.name} absent from {source.name}')
                    destination.collections = [old_collection.name]
                local = destination.collections[0]
                if not local or local.library:
                    raise RuntimeError(f'Append did not produce local collection: {asset_id}')
                loaded[key] = local
            obj.instance_collection = loaded[key]
            appended_records.append({'id': asset_id, 'source_file': str(source),
                                     'source_collection': key[1], 'local_collection': loaded[key].name})
            print(f'PORTABLE APPEND {index}/{len(instances)} {asset_id}', flush=True)
        report['appended_assets'] = appended_records

        # Refuse to discard linked data if any live scene dependency still uses it.
        live_linked = [block.name_full for block in reachable_datablocks(scene)
                       if getattr(block, 'library', None)]
        if live_linked:
            raise RuntimeError('Live scene dependencies remain linked after append: '+repr(live_linked[:20]))
        report['removed_libraries'] = [lib.filepath for lib in bpy.data.libraries]
        for name in [lib.name for lib in bpy.data.libraries]:
            library = bpy.data.libraries.get(name)
            if library:
                bpy.data.libraries.remove(library, do_unlink=True)
        bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        if bpy.data.libraries:
            raise RuntimeError('External libraries remain after orphan cleanup.')

        # Embed only redistributable CC0 textures. Research photographs remain
        # hidden external references, including in this public standalone file.
        for image in bpy.data.images:
            if image.users and image.source not in ('VIEWER', 'GENERATED'):
                observation_path=image.get('source_project_path','')
                if observation_path.startswith('observations/'):
                    image.filepath='//'+os.path.relpath(ROOT/observation_path,output.parent).replace('\\','/')
                    if packed(image):
                        image.unpack(method='REMOVE')
                    continue
                image_path=Path(bpy.path.abspath(image.filepath)).resolve()
                if not image_path.is_relative_to(ROOT/'projects/blender/materials'):
                    raise RuntimeError('Image redistribution not declared: '+image.name)
                if not packed(image):
                    image.pack()
                if not packed(image):
                    raise RuntimeError('Failed to pack image: '+image.name)
                image.filepath='//'+os.path.relpath(image_path,output.parent).replace('\\','/')
        scene['portable_export'] = json.dumps({'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'source_master_sha256': sources[str(master)]['sha256'],
                'source_master': 'projects/blender/campus.blend',
                'editable_local_collections': len(loaded), 'packed_cc0_textures': True,
                'optional_research_images_embedded': False}, ensure_ascii=False)
        before_save = verify_scene(expected_ids, original_scene_metadata, original_asset_metadata,
                                   original_tree_signature, args.expected_floorplans, original_viewport)
        if before_save['errors']:
            report['validation_before_save'] = before_save
            raise RuntimeError('Portable validation failed before save; see JSON report.')
        output.parent.mkdir(parents=True, exist_ok=True)
        # A reproducible export need not leave .blend1/.blend2 snapshots alongside it.
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(output), compress=True,relative_remap=False)
        print('PORTABLE SAVED; reopening for independent persistence check', flush=True)
        bpy.ops.wm.open_mainfile(filepath=str(output), load_ui=True)
        final = verify_scene(expected_ids, original_scene_metadata, original_asset_metadata,
                             original_tree_signature, args.expected_floorplans, original_viewport)
        report['validation_after_reopen'] = final
        if final['errors']:
            raise RuntimeError('Portable validation failed after reopen; see JSON report.')
        report['output_file'] = fingerprint(output)
        report['status'] = 'pass'
    except Exception as exc:
        report['status'] = 'failed'
        report['exception'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        source_changes = []
        for path, before in sources.items():
            after = fingerprint(path)
            if after != before:
                source_changes.append({'before': before, 'after': after})
        report['source_fingerprints'] = list(sources.values())
        report['source_changes'] = source_changes
        report['source_unchanged'] = not source_changes
        if source_changes:
            report['status'] = 'failed'
        report['elapsed_seconds'] = round(time.time()-started, 3)
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PORTABLE REPORT', report['status'], str(report_path), flush=True)
        if source_changes:
            raise RuntimeError('Source master or asset changed during export; export cannot be certified.')


if __name__ == '__main__':
    main()
