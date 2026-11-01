"""Small deterministic glTF 2.0 writer; no native Blender files are opened.

Source-local axes E,N,up become glTF E,up,-N. Each building keeps a named
node and exact asset identity in extras, so optimization cannot lose picking IDs.
The outline and holes are preserved, while elevation remains source-inferred.
"""
from __future__ import annotations
import json
import math
import struct


def to_gltf(p):
    return [float(p[0]), float(p[2]), -float(p[1])]


def triangles(building):
    """Yield watertight source footprint volumes, including courtyard walls."""
    for part in [building, *building.get('upper_volumes', [])]:
        base = float(part.get('base_z', 0))
        bottom = base + float(part.get('min_height', 0))
        top = base + float(part['height'])
        if not math.isfinite(top) or top <= bottom:
            raise ValueError(f"Invalid source elevations: {part['asset_id']}")
        for triangle in part['roof_triangles']:
            # Shapely triangle orientation can vary. Explicitly orient +Z roof.
            a,b,c = triangle
            if (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]) < 0:
                b,c = c,b
            yield [[*a,top],[*b,top],[*c,top]]
            yield [[*c,bottom],[*b,bottom],[*a,bottom]]
        # polygon_fields orients exterior CCW, holes CW: these faces point out.
        for ring in [part['outer'], *part.get('holes', [])]:
            for a,b in zip(ring, ring[1:]+ring[:1]):
                yield [[*a,bottom],[*b,bottom],[*b,top]]
                yield [[*a,bottom],[*b,top],[*a,top]]


def building_mesh(building):
    cx,cy = building['center']
    anchor = [cx,cy,float(building.get('base_z',0))]
    positions=[]
    normals=[]
    for triangle in triangles(building):
        t=[to_gltf([p[i]-anchor[i] for i in range(3)]) for p in triangle]
        u=[t[1][i]-t[0][i] for i in range(3)]
        v=[t[2][i]-t[0][i] for i in range(3)]
        n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        length=math.sqrt(sum(x*x for x in n))
        if length <= 1e-12: raise ValueError(f"Degenerate source triangle: {building['asset_id']}")
        n=[x/length for x in n]
        positions.extend(t)
        normals.extend([n,n,n])
    return positions,normals,to_gltf(anchor)


def write_glb(buildings):
    """Return deterministic uncompressed GLB bytes with per-building nodes."""
    doc={'asset':{'version':'2.0','generator':'njupt-map runtime-export/1',
                  'copyright':'hicancan / njupt-map; © OpenStreetMap contributors'},
         'scene':0,'scenes':[{'nodes':[]}], 'nodes':[], 'meshes':[], 'accessors':[],
         'bufferViews':[], 'buffers':[],
         'materials':[{'name':'source-footprint-shell','pbrMetallicRoughness':
                       {'baseColorFactor':[0.44,0.60,0.74,1.0],'metallicFactor':0,'roughnessFactor':0.86}}]}
    binary=bytearray()
    for building in sorted(buildings,key=lambda b:b['asset_id']):
        positions,normals,anchor=building_mesh(building)
        attrs={}
        for semantic,values in [('POSITION',positions),('NORMAL',normals)]:
            offset=len(binary)
            binary.extend(struct.pack('<'+'f'*(len(values)*3),*(x for p in values for x in p)))
            view=len(doc['bufferViews'])
            doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(binary)-offset,'target':34962})
            accessor={'bufferView':view,'componentType':5126,'count':len(values),'type':'VEC3'}
            if semantic=='POSITION':
                accessor.update(min=[min(p[i] for p in values) for i in range(3)],
                                max=[max(p[i] for p in values) for i in range(3)])
            attrs[semantic]=len(doc['accessors'])
            doc['accessors'].append(accessor)
        mesh=len(doc['meshes'])
        doc['meshes'].append({'name':building['asset_id'], 'primitives':[{'attributes':attrs,'material':0,'mode':4}]})
        node=len(doc['nodes'])
        doc['nodes'].append({'name':building['asset_id'],'mesh':mesh,'translation':anchor,
            'extras':{'asset_id':building['asset_id'],'source_namespace':'njupt-map',
                      'geometry_status':'derived_footprint_extrusion','geometry_role':building['geometry_role'],
                      'height_source':building.get('height_source'),'measured_height':False,
                      'source_spatial_signature':building['spatial_signature']}})
        doc['scenes'][0]['nodes'].append(node)
    doc['buffers']=[{'byteLength':len(binary)}]
    json_bytes=json.dumps(doc,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    json_bytes += b' '*((-len(json_bytes))%4)
    binary += b'\0'*((-len(binary))%4)
    length=12+8+len(json_bytes)+8+len(binary)
    return struct.pack('<4sII',b'glTF',2,length)+struct.pack('<I4s',len(json_bytes),b'JSON')+json_bytes+struct.pack('<I4s',len(binary),b'BIN\0')+binary
