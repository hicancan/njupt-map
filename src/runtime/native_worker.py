"""One read-only Blender asset extraction in an isolated Blender 5.2 process.

Never link the authored collection to an evaluated scene. Read base mesh data,
exclude interiors by authoring metadata, and omit expensive render modifiers.
This is an exterior LOD2 projection, not a lossless render export or BIM claim.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.runtime.mesh import MeshWriter


def excluded_interior_objects(collection):
    """Ownership metadata survives editable names and collection nesting."""
    excluded = set()
    for child in (collection, *collection.children_recursive):
        if child.get('njupt_editable_interiors'):
            excluded.update(child.all_objects)
    excluded.update(o for o in collection.all_objects if o.get('interior_role') is not None)
    return excluded


def pbr_projection(material):
    """Retain authored base PBR values, explicitly disclose shader approximation."""
    color = list(material.diffuse_color)
    roughness, metallic = .65, 0.
    emission = [0., 0., 0.]
    approximated = []
    if material.use_nodes:
        bsdf = next((n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf:
            color = list(bsdf.inputs['Base Color'].default_value)
            roughness = float(bsdf.inputs['Roughness'].default_value)
            metallic = float(bsdf.inputs['Metallic'].default_value)
            strength = float(bsdf.inputs['Emission Strength'].default_value)
            emission = [float(v)*strength for v in bsdf.inputs['Emission Color'].default_value[:3]]
            approximated = [s.name for s in bsdf.inputs if s.is_linked]
    color = [min(1., max(0., float(v))) for v in color]
    result = {'name': material.name, 'pbrMetallicRoughness': {'baseColorFactor': color,
              'metallicFactor': min(1., max(0., metallic)),
              'roughnessFactor': min(1., max(0., roughness))},
              'extras': {'source_material': material.name,
                 'projection': 'Authored Principled/default PBR values; procedural shader inputs are not baked',
                 'approximated_shader_inputs': approximated, 'textures_embedded': False}}
    if any(emission):
        # Keep core glTF emission in its supported 0..1 range; no extension needed.
        result['emissiveFactor'] = [min(1., max(0., v)) for v in emission]
    if color[3] < 1:
        result['alphaMode'] = 'BLEND'
    return result


def validate_output_path(value):
    output=Path(value).resolve()
    if output.suffix != '.glb':
        raise ValueError('Native extraction output must be a generated .glb')
    if ROOT == output or (ROOT in output.parents and not (ROOT/'build').resolve() in output.parents):
        raise ValueError('Native extraction cannot write inside authored source directories')
    return output


def extract(request):
    output=validate_output_path(request['output'])
    import bpy
    import numpy as np
    from mathutils import Matrix
    if bpy.app.version[:2] != (5, 2):
        raise ValueError(f'Expected Blender 5.2, got {bpy.app.version_string}')
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    source = Path(request['source'])
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_hash != request['source_sha256']:
        raise ValueError('Native source hash does not match current catalog')
    # No open_mainfile/depsgraph: append only the authored collection as unlinked data.
    with bpy.data.libraries.load(str(source), link=False) as (src, dst):
        if request['collection'] not in src.collections:
            raise ValueError('Catalog collection is absent from native source')
        dst.collections = [request['collection']]
    collection = dst.collections[0]
    if collection.get('asset_id') != request['asset_id']:
        raise ValueError('Native collection stable asset ID mismatch')
    excluded = excluded_interior_objects(collection)
    # Source helper explicitly owns this protected emblem as a separate mesh.
    # This exact binding is audited in campus_old_gym.py, not a display-name heuristic.
    identity_excluded = {o for o in collection.all_objects
        if collection.get('generated_by') == 'src/blender/campus_old_gym.py'
        and o.name == 'Old gym | coloured five-ring facade emblem'}
    objects = sorted((o for o in collection.all_objects if o not in excluded
        and o not in identity_excluded and o.type == 'MESH'), key=lambda o:o.name)
    if not objects:
        raise ValueError('Native asset has no exterior mesh')
    # Limit work before allocating export arrays. Base meshes avoid render-time bevel/subdivision growth.
    base_vertices = sum(len(o.data.vertices) for o in objects)
    if base_vertices > request.get('max_base_vertices', 1500000):
        raise ValueError(f'Exterior base mesh exceeds configured budget: {base_vertices}')
    materials = sorted({m for o in objects for m in o.data.materials if m}, key=lambda m:m.name)
    material_ids = {m:i for i,m in enumerate(materials)}
    fallback = len(materials)
    writer = MeshWriter([pbr_projection(m) for m in materials] + [
        {'name':'missing-native-material', 'pbrMetallicRoughness':
         {'baseColorFactor':[.6,.6,.6,1], 'metallicFactor':0, 'roughnessFactor':.8}}],
        generator='njupt-map authored exterior runtime/1')
    aid = request['asset_id']
    cx, cy, cz = request['anchor_local_m']
    root = writer.add_node({'name': aid, 'translation': [cx, cz, -cy],
        'extras': {'asset_id': aid, 'source_namespace':'njupt-map',
                  'geometry_status':'authored_exterior_lod2', 'measured':False,
                  'source_blend_sha256':source_hash}})
    # Collection instance offsets are applied once, then the GPKG anchor once.
    offset = Matrix.Translation(-collection.instance_offset)
    matrices = {}
    def local_matrix(ob):
        if ob in matrices:
            return matrices[ob]
        if ob.constraints:
            raise ValueError(f'Exterior object has unsupported transform constraints: {ob.name}')
        parent = local_matrix(ob.parent) if ob.parent else Matrix.Identity(4)
        matrices[ob] = parent @ ob.matrix_parent_inverse @ ob.matrix_basis if ob.parent else ob.matrix_basis.copy()
        return matrices[ob]
    all_bounds = []
    reports = []
    axis = np.array([[1.,0.,0.], [0.,0.,1.], [0.,-1.,0.]])
    for ob in objects:
        mesh = ob.data
        mesh.calc_loop_triangles()
        if len(mesh.loop_triangles) == 0:
            continue
        matrix = np.array(offset @ local_matrix(ob), dtype=np.float64)
        xyz = np.empty(len(mesh.vertices)*3, dtype=np.float32)
        mesh.vertices.foreach_get('co', xyz)
        xyz = xyz.reshape((-1,3)).astype(np.float64) @ matrix[:3,:3].T + matrix[:3,3]
        loop_vertex = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get('vertex_index', loop_vertex)
        used_xyz=xyz[loop_vertex]
        all_bounds.append([*used_xyz.min(axis=0), *used_xyz.max(axis=0)])
        normals = np.empty(len(mesh.corner_normals)*3, dtype=np.float32)
        mesh.corner_normals.foreach_get('vector', normals)
        if len(normals) != len(mesh.loops)*3:
            raise ValueError(f'Incomplete authored corner normals: {ob.name}')
        normals = normals.reshape((-1,3)).astype(np.float64) @ np.linalg.inv(matrix[:3,:3])
        lengths = np.linalg.norm(normals, axis=1)
        if np.any(lengths < 1e-8):
            raise ValueError('Native normals contain zero vectors')
        normals /= lengths[:,None]
        vertices = np.hstack((xyz[loop_vertex] @ axis.T, normals @ axis.T)).astype('<f4')
        # Exact split-vertex dedup preserves material boundaries and authored sharp normals.
        vertices, inverse = np.unique(vertices, axis=0, return_inverse=True)
        triangle_loops = np.empty(len(mesh.loop_triangles)*3, dtype=np.int32)
        mesh.loop_triangles.foreach_get('loops', triangle_loops)
        indices = inverse[triangle_loops].reshape((-1,3))
        if np.linalg.det(matrix[:3,:3]) < 0:
            indices = indices[:,[0,2,1]]
        mi = np.empty(len(mesh.loop_triangles), dtype=np.int32)
        mesh.loop_triangles.foreach_get('material_index', mi)
        primitives = []
        for slot in sorted(set(int(i) for i in mi)):
            mat = mesh.materials[slot] if slot < len(mesh.materials) else None
            primitives.append((material_ids.get(mat, fallback), indices[mi == slot].reshape(-1).tolist()))
        writer.add_mesh(ob.name, vertices[:,:3].reshape(-1), vertices[:,3:].reshape(-1), primitives,
            {'asset_id':aid, 'source_object':ob.name, 'geometry_status':'authored_exterior_lod2',
             'source_authoring_role':ob.get('authoring_role', 'preserved_native_exterior'),
             'render_modifiers_omitted':[{'type':m.type, 'name':m.name} for m in ob.modifiers],
             'measured':False}, parent=root)
        reports.append({'source_object':ob.name, 'base_vertices':len(mesh.vertices),
            'triangles':len(mesh.loop_triangles), 'runtime_vertices':len(vertices),
            'modifiers_omitted':[m.type for m in ob.modifiers]})
    minima = [min(b[i] for b in all_bounds)+[cx,cy,cz][i] for i in range(3)]
    maxima = [max(b[i+3] for b in all_bounds)+[cx,cy,cz][i] for i in range(3)]
    bounds = minima + maxima
    expected = request['source_bounds_local_m']
    # Deliberate overhangs/details need not equal footprint bounds. This catches missing/double placement.
    for i in range(2):
        width = expected[i+3]-expected[i]
        delta = abs((bounds[i]+bounds[i+3]-expected[i]-expected[i+3])/2)
        if delta > max(15., width*.35):
            raise ValueError(f'Native exterior and canonical anchor disagree on axis {i}: {delta} m')
    payload = writer.finish()
    if not all(math.isfinite(v) for v in bounds):
        raise ValueError('Non-finite native bounds')
    if len(payload) > request.get('max_glb_bytes', 20000000):
        raise ValueError(f'Exterior GLB exceeds per-asset byte budget: {len(payload)}')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    result = {'asset_id':aid, 'source_blend_sha256':source_hash, 'source_collection':request['collection'],
        'anchor_local_m':request['anchor_local_m'], 'bounds_local_m':bounds,
        'source_bounds_local_m':expected, 'source_spatial_signature':request['source_spatial_signature'],
        'mesh_sha256':hashlib.sha256(payload).hexdigest(), 'bytes':len(payload),
        'mesh_objects':len(reports), 'triangles':sum(r['triangles'] for r in reports),
        'base_vertices':base_vertices, 'runtime_vertices':sum(r['runtime_vertices'] for r in reports),
        'interior_objects_excluded':len(excluded), 'identity_meshes_excluded':len(identity_excluded),
        'non_mesh_objects_excluded':len([o for o in collection.all_objects if o not in excluded and o.type != 'MESH']),
        'materials':len(writer.doc['materials']), 'source_material_slots':len(materials), 'blender_version':bpy.app.version_string, 'objects':reports,
        'material_policy':'Preserve authored base PBR values; approximate procedural shaders without textures',
        'geometry_policy':'Preserve base exterior mesh and split normals; omit all interior data, fonts and render modifiers',
        'accuracy_note':'Authored/source-informed and inferred appearance; not surveyed or BIM-accurate'}
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError('Native source changed during extraction')
    output.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',',':'))+'\n', encoding='utf-8')
    print(json.dumps({'asset_id':aid, 'bytes':len(payload), 'triangles':result['triangles']}), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    extract(json.loads(args.request.read_text(encoding='utf-8')))
