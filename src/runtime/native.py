"""Resource-bounded, serial read-only extraction of authored exterior artifacts.

Run with the locked map Python and the installed Blender 5.2 executable.
Native .blend files are never saved. Extraction is opt-in and refuses to start
below the requested free-memory threshold; each asset has timeout/RSS budgets.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import struct
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import time
import psutil
from .export import bounds, canonical, sha, write_json
from ..map.store import ROOT, SOURCE, load_campus

FORMAT = 'njupt-map-native-exteriors'
CATALOG = ROOT/'projects/blender/buildings/catalog.json'


def artifact_path(root, relative):
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or '..' in path.parts or '\\' in relative:
        raise ValueError('Unsafe native artifact path')
    result = root/relative
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError('Native artifact escapes package')
    return result


def available_memory_bytes():
    """Read the available-memory gate on Windows, Linux and macOS."""
    available = psutil.virtual_memory().available
    if available <= 0:
        raise RuntimeError('Cannot establish available host memory')
    return available


def process_rss_bytes(pid):
    try:
        return psutil.Process(pid).memory_info().rss
    except psutil.NoSuchProcess:
        return 0
    except psutil.AccessDenied as error:
        raise RuntimeError('Cannot monitor native subprocess memory') from error


def run_bounded(command, log_path, timeout_s=180, max_rss_bytes=1500*1024**2,
                min_available_bytes=3500*1024**2):
    if timeout_s <= 0 or max_rss_bytes <= 0 or min_available_bytes < 0:
        raise ValueError('Native subprocess resource budgets must be positive')
    if available_memory_bytes() < min_available_bytes:
        raise RuntimeError('Native extraction deferred: available memory is below configured safety threshold')
    started = time.monotonic()
    peak = 0
    env = {**os.environ, 'OMP_NUM_THREADS':'1', 'OPENBLAS_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1'}
    with log_path.open('wb') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env)
        try:
            while process.poll() is None:
                peak = max(peak, process_rss_bytes(process.pid))
                if available_memory_bytes() < 512*1024**2:
                    raise RuntimeError('Native extraction stopped: host memory reserve fell below 512 MiB')
                if peak > max_rss_bytes:
                    raise RuntimeError('Native extraction stopped at configured per-process RSS limit')
                if time.monotonic()-started > timeout_s:
                    raise RuntimeError('Native extraction exceeded per-asset timeout')
                time.sleep(.1)
            if process.returncode:
                raise RuntimeError(f'Native extraction exited {process.returncode}; inspect {log_path.name}')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return {'peak_rss_bytes':peak, 'duration_s':round(time.monotonic()-started,3)}


def verify_native_glb(content, building):
    """Independently check the exact semantic/placement contract of the simple writer."""
    if len(content) < 28 or struct.unpack_from('<4sII',content) != (b'glTF',2,len(content)):
        raise ValueError('Invalid native GLB header')
    size,kind=struct.unpack_from('<I4s',content,12)
    if kind != b'JSON':raise ValueError('Missing native GLB JSON')
    doc=json.loads(content[20:20+size])
    binary_size,binary_kind=struct.unpack_from('<I4s',content,20+size)
    binary=content[28+size:]
    if binary_kind != b'BIN\0' or len(binary) != binary_size:
        raise ValueError('Invalid native GLB binary')
    if any(doc.get(k) for k in ('images','textures','animations','skins','extensionsRequired')):
        raise ValueError('Unexpected native runtime dependencies')
    aid=building['asset_id']
    nodes=doc['nodes']
    roots=doc['scenes'][doc.get('scene',0)]['nodes']
    if len(roots) != 1:raise ValueError('Native detail must have one identity root')
    root=nodes[roots[0]]
    x,y,z=building['anchor_local_m']
    if root.get('name') != aid or root.get('extras',{}).get('asset_id') != aid or root.get('translation') != [x,z,-y]:
        raise ValueError('Native root identity or placement mismatch')
    children=root.get('children',[])
    if not children or set(children) != set(range(len(nodes)))-set(roots) or len(children) != len(set(children)):
        raise ValueError('Native detail hierarchy mismatch')
    bounds=[];triangle_count=0
    for index in children:
        node=nodes[index]
        if node.get('extras',{}).get('asset_id') != aid or any(key in node for key in ('children','matrix','rotation','scale','translation')):
            raise ValueError('Native mesh identity or transform mismatch')
        seen=set()
        for primitive in doc['meshes'][node['mesh']]['primitives']:
            position=primitive['attributes']['POSITION']
            indices=doc['accessors'][primitive['indices']]
            if indices['count']%3:raise ValueError('Incomplete native triangles')
            triangle_count+=indices['count']//3
            if position in seen:continue
            seen.add(position)
            accessor=doc['accessors'][position]
            if accessor['componentType'] != 5126 or accessor['type'] != 'VEC3':
                raise ValueError('Unsupported native position layout')
            view=doc['bufferViews'][accessor['bufferView']]
            offset=view.get('byteOffset',0)+accessor.get('byteOffset',0)
            values=struct.unpack_from('<'+'f'*(accessor['count']*3),binary,offset)
            if not all(math.isfinite(v) for v in values):raise ValueError('Non-finite native positions')
            # Decode the explicit glTF E/up/-N transform independently.
            bounds.append([min(values[0::3])+x, -max(values[2::3])+y, min(values[1::3])+z,
                           max(values[0::3])+x, -min(values[2::3])+y, max(values[1::3])+z])
    actual=[min(b[i] for b in bounds) for i in range(3)]+[max(b[i] for b in bounds) for i in range(3,6)]
    if any(abs(a-b)>0.0002 for a,b in zip(actual,building['bounds_local_m'])):
        raise ValueError('Native exported bounds do not round-trip')
    if triangle_count != building['triangles']:
        raise ValueError('Native triangle report mismatch')
    return doc


def verify_bundle(root):
    root = Path(root).resolve()
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != FORMAT or manifest.get('schema_version') != 1:
        raise ValueError('Unsupported native exterior package')
    content = {k:v for k,v in manifest.items() if k != 'version'}
    if manifest['version'] != hashlib.sha256(canonical(content)).hexdigest():
        raise ValueError('Native exterior package content identity mismatch')
    for relative, ref in manifest['artifacts'].items():
        path = artifact_path(root, relative)
        if path.stat().st_size != ref['bytes'] or sha(path) != ref['sha256']:
            raise ValueError(f'Native exterior artifact hash/size mismatch: {relative}')
    ids = [b['asset_id'] for b in manifest['buildings']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate native exterior asset ID')
    for building in manifest['buildings']:
        for key in ('mesh_url','report_url'):
            if building[key] not in manifest['artifacts']:
                raise ValueError('Native exterior references an unverified resource')
        reference=manifest['artifacts'][building['mesh_url']]
        if reference['bytes'] != building['bytes'] or reference['sha256'] != building['mesh_sha256']:
            raise ValueError('Native exterior descriptor/artifact mismatch')
        verify_native_glb(artifact_path(root,building['mesh_url']).read_bytes(),building)
    return manifest


def export_native(blender, output, source=SOURCE, asset_ids=None, timeout_s=180,
                  max_rss_bytes=1500*1024**2, min_available_bytes=3500*1024**2, pause_file=None):
    output = Path(output).resolve()
    source = Path(source).resolve()
    if ROOT == output or (ROOT in output.parents and not (ROOT/'build').resolve() in output.parents):
        raise ValueError('Native runtime output inside the repository must be under build/')
    if output == source or output in source.parents:
        raise ValueError('Native output cannot contain its source')
    if output.exists() and any(output.iterdir()):
        if not (output/'manifest.json').exists() or json.loads((output/'manifest.json').read_text(encoding='utf-8')).get('format') != FORMAT:
            raise ValueError('Refusing to replace unrecognized native output')
    # Validate every source/hash before the first subprocess.
    source_hash = sha(source)
    catalog_hash = sha(CATALOG)
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    campus = load_campus(source)
    buildings = {b['asset_id']:b for b in campus['buildings']}
    selected = sorted(asset_ids if asset_ids else buildings)
    if not selected or len(selected) != len(set(selected)) or not set(selected) <= set(buildings):
        raise ValueError('Native selection must contain unique canonical asset IDs')
    sources = {}
    for aid in selected:
        path = artifact_path(ROOT/'projects/blender/buildings', aid+'.blend')
        if sha(path) != catalog[aid]['sha256']:
            raise ValueError(f'Native source is unhydrated or differs from catalog: {aid}')
        sources[aid] = path
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-runtime-', dir=output.parent) as temporary:
        stage = Path(temporary)/'package'
        stage.mkdir()
        descriptors = []
        for aid in selected:
            if pause_file is not None and Path(pause_file).exists():
                print(json.dumps({'status':'paused_between_assets','next_asset_id':aid}),flush=True)
                while Path(pause_file).exists():
                    time.sleep(.5)
            building = buildings[aid]
            relative = f'buildings/{aid}.glb'
            request = {'asset_id':aid, 'source':str(sources[aid]), 'source_sha256':catalog[aid]['sha256'],
                'collection':catalog[aid]['collection'], 'output':str(stage/relative),
                'anchor_local_m':[*building['center'], building.get('base_z',0)],
                'source_bounds_local_m':bounds(building), 'source_spatial_signature':building['spatial_signature']}
            request_path = Path(temporary)/'request.json'
            write_json(request_path, request)
            # Logs/timings stay out of the deterministic publication.
            log_path = output.parent/f'{output.name}-{aid}.log'
            command = [str(blender), '--background', '--factory-startup', '--python-exit-code', '1',
                       '--python', str(ROOT/'src/runtime/native_worker.py'), '--', '--request', str(request_path)]
            budget = run_bounded(command,
                log_path, timeout_s, max_rss_bytes, min_available_bytes)
            report = json.loads((stage/relative).with_suffix('.json').read_text(encoding='utf-8'))
            descriptors.append({'asset_id':aid, 'mesh_url':relative,
                'report_url':str(PurePosixPath(relative).with_suffix('.json')), **report})
            print(json.dumps({'asset_id':aid, 'bytes':report['bytes'], 'triangles':report['triangles'], **budget}), flush=True)
        if sha(source) != source_hash or sha(CATALOG) != catalog_hash or any(sha(sources[aid]) != catalog[aid]['sha256'] for aid in selected):
            raise RuntimeError('An authored source changed during extraction')
        artifacts = {p.relative_to(stage).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size}
                     for p in sorted(stage.rglob('*')) if p.is_file()}
        producer_hash = hashlib.sha256(b''.join((ROOT/'src/runtime'/p).read_bytes()
            for p in ('native.py','native_worker.py','mesh.py'))).hexdigest()
        manifest = {'schema_version':1, 'format':FORMAT, 'source_gpkg_sha256':source_hash,
            'source_catalog_sha256':catalog_hash, 'producer_sha256':producer_hash,
            'buildings':descriptors, 'artifacts':artifacts,
            'policy':'Read-only base exterior meshes, no interior/scene evaluation, no textures, no native save'}
        manifest['version'] = hashlib.sha256(canonical(manifest)).hexdigest()
        write_json(stage/'manifest.json',manifest)
        verify_bundle(stage)
        if output.exists():
            shutil.rmtree(output)
        shutil.move(str(stage),str(output))
    return manifest


def integrate_native(root, output, descriptors, source_hash):
    root = Path(root).resolve()
    manifest = verify_bundle(root)
    if manifest['source_gpkg_sha256'] != source_hash or manifest['source_catalog_sha256'] != sha(CATALOG):
        raise ValueError('Native detail was generated from different canonical sources')
    by_id = {b['asset_id']:b for b in descriptors}
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    for item in manifest['buildings']:
        aid = item['asset_id']
        if aid not in by_id:
            raise ValueError('Native detail references an absent canonical building')
        target = by_id[aid]
        if (item['source_spatial_signature'] != target['spatial_signature']
                or item['anchor_local_m'] != target['center_local_m']
                or item['source_blend_sha256'] != catalog[aid]['sha256']):
            raise ValueError('Native detail identity/placement does not match canonical source')
        if sha(ROOT/'projects/blender/buildings'/f'{aid}.blend') != item['source_blend_sha256']:
            raise ValueError('Native source changed since extraction')
        target.update(detail_mesh_url='detail/'+item['mesh_url'], detail_mesh_sha256=item['mesh_sha256'],
            detail_bounds_local_m=item['bounds_local_m'], detail_geometry_status='authored_exterior_lod2',
            detail_source_blend_sha256=item['source_blend_sha256'], detail_bytes=item['bytes'],
            detail_triangles=item['triangles'], detail_report_url='detail/'+item['report_url'])
    for relative in [*manifest['artifacts'], 'manifest.json']:
        destination = output/'detail'/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(artifact_path(root,relative),destination)
    return {'status':'authored_exterior_lod2', 'package_version':manifest['version'],
        'building_count':len(manifest['buildings']), 'manifest_url':'detail/manifest.json',
        'source_files_unchanged':True, 'policy':manifest['policy']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender',type=Path,default=shutil.which('blender'),help='Installed Blender 5.2 executable; defaults to PATH')
    parser.add_argument('--output',type=Path,default=ROOT/'build/native-exteriors')
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--asset-id',action='append')
    parser.add_argument('--timeout-s',type=float,default=180)
    parser.add_argument('--pause-file',type=Path,help='Pause safely between assets while this coordinator-owned file exists')
    parser.add_argument('--max-rss-mib',type=int,default=1500)
    parser.add_argument('--min-available-mib',type=int,default=3500)
    args = parser.parse_args()
    if args.blender is None:
        parser.error('Blender not found; provide --blender with its executable path')
    export_native(args.blender,args.output,args.source,args.asset_id,args.timeout_s,
                  args.max_rss_mib*1024**2,args.min_available_mib*1024**2,args.pause_file)
