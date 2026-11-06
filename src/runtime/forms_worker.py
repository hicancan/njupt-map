"""One Blender process: write the exterior triangles of one building asset for src.runtime.forms.

Reads base meshes only; interiors are excluded by their authoring metadata, and nothing is saved.
"""
from __future__ import annotations
import json
import sys


def linear_to_srgb(value):
    return value * 12.92 if value <= .0031308 else 1.055 * value ** (1 / 2.4) - .055


def socket_colours(socket, seen):
    """Every colour feeding a shader input: procedural noise and ramps average out to what the eye reads."""
    if not socket.is_linked:
        return [list(socket.default_value)[:3]] if socket.type == 'RGBA' else []
    out = []
    for link in socket.links:
        node = link.from_node
        if node in seen:
            continue
        seen.add(node)
        if node.type == 'VALTORGB':
            out += [list(element.color)[:3] for element in node.color_ramp.elements]
        if node.type == 'RGB':
            out.append(list(node.outputs[0].default_value)[:3])
        for upstream in node.inputs:
            if upstream.type in ('RGBA', 'SHADER'):
                out += socket_colours(upstream, seen)
    return out


def colour(material):
    if material is None:
        return (.8, .8, .8, 1.)
    rgb, alpha = list(material.diffuse_color)[:3], float(material.diffuse_color[3])
    if material.use_nodes:
        bsdf = next((node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED'), None)
        if bsdf:
            found = socket_colours(bsdf.inputs['Base Color'], set())
            if found:
                rgb = [sum(values) / len(values) for values in zip(*found)]
            alpha *= float(bsdf.inputs['Alpha'].default_value) * (1 - float(bsdf.inputs['Transmission Weight'].default_value) * .85)
    return (*[linear_to_srgb(max(0., min(1., float(v)))) for v in rgb], alpha)


def main(request):
    import bpy
    import numpy as np
    from mathutils import Matrix
    with bpy.data.libraries.load(request['source'], link=False) as (src, dst):
        dst.collections = [request['collection']]
    collection = dst.collections[0]
    excluded = set()
    for child in (collection, *collection.children_recursive):
        if child.get('njupt_editable_interiors'):
            excluded.update(child.all_objects)
    excluded.update(o for o in collection.all_objects if o.get('interior_role') is not None)
    objects = [o for o in collection.all_objects if o not in excluded and o.type == 'MESH']
    offset = Matrix.Translation(-collection.instance_offset)
    matrices = {}

    def local(ob):
        if ob not in matrices:
            matrices[ob] = local(ob.parent) @ ob.matrix_parent_inverse @ ob.matrix_basis if ob.parent else ob.matrix_basis.copy()
        return matrices[ob]

    triangles, colours = [], []
    for ob in objects:
        mesh = ob.data
        mesh.calc_loop_triangles()
        if not mesh.loop_triangles:
            continue
        matrix = np.array(offset @ local(ob), dtype=np.float64)
        xyz = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get('co', xyz)
        xyz = xyz.reshape((-1, 3)).astype(np.float64) @ matrix[:3, :3].T + matrix[:3, 3]
        vertices = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get('vertices', vertices)
        slots = np.empty(len(mesh.loop_triangles), dtype=np.int32)
        mesh.loop_triangles.foreach_get('material_index', slots)
        palette = np.array([colour(m) for m in mesh.materials] or [colour(None)], dtype=np.float32)
        triangles.append(xyz[vertices].reshape((-1, 3, 3)).astype(np.float32))
        colours.append(palette[np.minimum(slots, len(palette) - 1)])
    np.savez_compressed(request['output'], triangles=np.concatenate(triangles), colours=np.concatenate(colours))


main(json.loads(sys.argv[sys.argv.index('--') + 1]))
