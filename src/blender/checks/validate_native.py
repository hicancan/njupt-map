"""Validate native Blender sources, optional observations and shared dependencies.

Run in a fresh background Blender process with --python-exit-code 1.
--render writes two small representative frames without saving any source file.
"""
from pathlib import Path
import argparse, hashlib, json, math, sys, time
import bpy

ROOT = Path(__file__).resolve().parents[3]
PROJECT = ROOT / 'projects/blender'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def dependencies():
    result = {'libraries': [], 'images': [], 'fonts': [], 'optional_observations': 0}
    for library in bpy.data.libraries:
        path = Path(bpy.path.abspath(library.filepath, library=library.parent)).resolve()
        assert library.filepath.startswith('//'), f'Absolute library: {library.filepath}'
        assert path.is_relative_to(ROOT) and path.is_file(), f'Missing library: {path}'
        result['libraries'].append(path.relative_to(ROOT).as_posix())
    for image in bpy.data.images:
        if image.source in {'GENERATED', 'VIEWER'} or not image.filepath:
            continue
        path = Path(bpy.path.abspath(image.filepath, library=image.library)).resolve()
        optional = path.is_relative_to(ROOT/'observations')
        assert image.filepath.startswith('//'), f'Absolute image: {image.filepath}'
        assert path.is_relative_to(ROOT), f'Image outside repository: {path}'
        assert not optional or not image.packed_file, f'Restricted image embedded: {image.name}'
        assert optional or image.packed_file or path.is_file(), f'Missing render texture: {path}'
        result['optional_observations'] += int(optional)
        result['images'].append({'path': path.relative_to(ROOT).as_posix(),
                                 'packed': bool(image.packed_file), 'optional': optional,
                                 'available_locally': path.is_file()})
    for font in bpy.data.fonts:
        assert font.filepath == '<builtin>', f'External font binary: {font.filepath}'
        result['fonts'].append(font.name)
    for blocks in [bpy.data.objects, bpy.data.collections, bpy.data.scenes, bpy.data.images]:
        for block in blocks:
            for key in block.keys():
                value = block[key]
                if isinstance(value, str):
                    assert 'C:/Users/' not in value.replace('\\','/')
                    assert 'D:/code/' not in value.replace('\\','/'), f'Private metadata: {key}'
    return result


def render_samples(report):
    output = ROOT/'build/checks/refactor'
    output.mkdir(parents=True, exist_ok=True)
    for source, frame, camera, name in [
            (PROJECT/'campus.blend', 1, '01_全校鸟瞰', 'campus'),
            (PROJECT/'presentation/film.blend', 60, None, 'film-gate')]:
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
        scene = bpy.context.scene
        scene.frame_set(frame)
        if camera:
            scene.camera = bpy.data.objects[camera]
        else:
            plan=json.loads(scene['film_plan'])
            shot=plan['shots'][(frame-1)//120]
            scene.camera=bpy.data.objects[shot['camera']]
        scene.render.engine = 'CYCLES'
        preferences = bpy.context.preferences.addons['cycles'].preferences
        preferences.compute_device_type = 'OPTIX'
        preferences.refresh_devices()
        gpu = any(device.type=='OPTIX' for device in preferences.devices)
        for device in preferences.devices:
            device.use = device.type=='OPTIX' if gpu else device.type=='CPU'
        scene.cycles.device = 'GPU' if gpu else 'CPU'
        scene.cycles.samples = 8
        scene.cycles.use_denoising = True
        scene.render.resolution_x = 640
        scene.render.resolution_y = 360
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'PNG'
        scene.render.filepath = str(output/f'{name}.png')
        bpy.ops.render.render(write_still=True)
        report['renders'].append(scene.render.filepath)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    catalog = json.loads((PROJECT/'buildings/catalog.json').read_text(encoding='utf-8'))
    files = sorted((PROJECT/'buildings').glob('*.blend')) + sorted((PROJECT/'materials').rglob('*.blend'))
    files += [PROJECT/'campus.blend', PROJECT/'presentation/film.blend']
    before = {path: sha256(path) for path in files}
    report = {'status': 'running', 'blender': bpy.app.version_string, 'files': [], 'renders': []}
    started = time.time()
    for path in files:
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
        row = {'path': path.relative_to(ROOT).as_posix(), **dependencies()}
        if path.parent.name=='buildings':
            ident = path.stem
            assert ident in catalog
            collection = bpy.data.collections.get(catalog[ident]['collection'])
            assert collection is not None and collection.get('asset_id')==ident
            meshes = [obj for obj in collection.all_objects if obj.type=='MESH']
            assert meshes, f'Empty building: {ident}'
            assert any(scene.get('asset_id')==ident and any(obj.type=='MESH' for obj in scene.objects)
                       for scene in bpy.data.scenes), f'Building not directly editable: {ident}'
            assert all(all(math.isfinite(coordinate) for coordinate in corner)
                       for obj in meshes for corner in obj.bound_box), f'Invalid building: {ident}'
            row['asset_id'] = ident
            row['meshes'] = len(meshes)
        elif path.name in {'campus.blend','film.blend'}:
            instances = [obj for obj in bpy.context.scene.objects if obj.get('asset_id')]
            assert len(instances)==len(catalog), f'Instance count differs: {len(instances)}'
            assert {obj['asset_id'] for obj in instances}==set(catalog)
            assert all(obj.instance_collection and obj.instance_collection.library for obj in instances)
            row['building_instances'] = len(instances)
            references = [obj for collection in bpy.data.collections for obj in collection.objects
                          if obj.type=='EMPTY' and obj.empty_display_type=='IMAGE']
            assert all(obj.hide_render for obj in references), 'Observation could appear in output'
            row['hidden_reference_objects'] = len({obj.as_pointer() for obj in references})
        report['files'].append(row)
        print('VALIDATED', row['path'], flush=True)
    assert len(list((PROJECT/'buildings').glob('*.blend')))==len(catalog)
    if args.render:
        render_samples(report)
    assert all(sha256(path)==digest for path,digest in before.items()), 'Validation modified source'
    report.update(status='pass', building_assets=len(catalog), source_files_unchanged=True,
                  elapsed_seconds=round(time.time()-started,3))
    output=ROOT/'build/checks/blender/native.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
    print('NATIVE_VALIDATION_PASS', len(files), len(catalog), flush=True)


if __name__=='__main__':
    main()
