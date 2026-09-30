"""Deterministic indexed glTF writer shared by derived runtime geometry.

Callers supply glTF-space data explicitly; this writer never reads authoring files.
"""
from __future__ import annotations
import json
import math
import struct


def encode_glb(doc, binary):
    doc['buffers'] = [{'byteLength': len(binary)}]
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    payload += b' ' * (-len(payload) % 4)
    binary = bytes(binary) + b'\0' * (-len(binary) % 4)
    return (struct.pack('<4sII', b'glTF', 2, 28 + len(payload) + len(binary))
            + struct.pack('<I4s', len(payload), b'JSON') + payload
            + struct.pack('<I4s', len(binary), b'BIN\0') + binary)


class MeshWriter:
    """Accept positions/normals and material-partitioned triangle indices."""
    def __init__(self, materials, generator='njupt-map runtime-export/1'):
        self.doc = {'asset': {'version': '2.0', 'generator': generator,
                    'copyright': 'hicancan / njupt-map; © OpenStreetMap contributors'},
                    'scene': 0, 'scenes': [{'nodes': []}], 'nodes': [], 'meshes': [],
                    'accessors': [], 'bufferViews': [], 'materials': materials}
        self.binary = bytearray()

    def accessor(self, values, components=3, indices=False):
        # array/numpy buffers can be supplied without Python-per-float copies.
        values = list(values) if not hasattr(values, 'tobytes') else values
        size = len(values)
        if size == 0 or size % components:
            raise ValueError('Empty or incomplete accessor')
        if indices:
            payload = struct.pack('<' + 'I' * size, *values)
        elif hasattr(values, 'astype'):
            payload = values.astype('<f4', copy=False).tobytes()
        else:
            if any(not math.isfinite(v) for v in values):
                raise ValueError('Non-finite mesh component')
            payload = struct.pack('<' + 'f' * size, *values)
        offset = len(self.binary)
        self.binary.extend(payload)
        view = len(self.doc['bufferViews'])
        self.doc['bufferViews'].append({'buffer': 0, 'byteOffset': offset,
                                       'byteLength': len(payload), 'target': 34963 if indices else 34962})
        acc = {'bufferView': view, 'componentType': 5125 if indices else 5126,
               'count': size // components, 'type': 'SCALAR' if components == 1 else 'VEC3'}
        if not indices:
            acc['min'] = [float(min(values[i::components])) for i in range(components)]
            acc['max'] = [float(max(values[i::components])) for i in range(components)]
        result = len(self.doc['accessors'])
        self.doc['accessors'].append(acc)
        return result

    def add_mesh(self, name, positions, normals, primitives, extras, translation=None, parent=None):
        if len(positions) != len(normals):
            raise ValueError('Position/normal count mismatch')
        attributes = {'POSITION': self.accessor(positions), 'NORMAL': self.accessor(normals)}
        mesh = {'name': name, 'primitives': []}
        for material, indices in primitives:
            if len(indices) % 3:
                raise ValueError('Incomplete triangle')
            if not indices:
                continue
            if min(indices) < 0 or max(indices) >= len(positions) // 3:
                raise ValueError('Index outside vertex range')
            mesh['primitives'].append({'attributes': attributes,
                'indices': self.accessor(indices, 1, True), 'material': material, 'mode': 4})
        if not mesh['primitives']:
            raise ValueError('Mesh has no triangles')
        node = {'name': name, 'mesh': len(self.doc['meshes']), 'extras': extras}
        if translation is not None:
            node['translation'] = translation
        self.doc['meshes'].append(mesh)
        return self.add_node(node, parent)

    def add_node(self, node, parent=None):
        index = len(self.doc['nodes'])
        self.doc['nodes'].append(node)
        if parent is None:
            self.doc['scenes'][0]['nodes'].append(index)
        else:
            self.doc['nodes'][parent].setdefault('children', []).append(index)
        return index

    def finish(self):
        return encode_glb(self.doc, self.binary)
