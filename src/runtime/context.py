"""Publish canonical campus context without invented survey observations."""
from __future__ import annotations
from shapely import constrained_delaunay_triangles
from shapely.geometry import LineString, Polygon, mapping
from .glb import to_gltf, triangles
from .mesh import MeshWriter

LAYERS = ('boundary', 'greens', 'waters', 'sports', 'surfaces', 'roads', 'context_buildings')
# Display-only palette/elevation offsets; these are not source spatial facts.
DISPLAY = {
    'boundary': ([.78, .81, .74, 1], -.12),
    'greens': ([.29, .48, .25, 1], -.06),
    'waters': ([.20, .47, .58, 1], -.035),
    'sports': ([.54, .34, .26, 1], -.025),
    'surfaces': ([.66, .64, .58, 1], -.015),
    'roads': ([.48, .50, .49, 1], -.005),
    'context_buildings': ([.64, .65, .62, 1], 0),
}


def context_products(data):
    materials = [{'name': f'context-{layer}', 'pbrMetallicRoughness':
        {'baseColorFactor': DISPLAY[layer][0], 'metallicFactor': 0, 'roughnessFactor': .94}}
        for layer in LAYERS]
    writer = MeshWriter(materials)
    features = []
    counts = {}
    for material, layer in enumerate(LAYERS):
        records = [data[layer]] if layer == 'boundary' else data[layer]
        counts[layer] = len(records)
        for record in sorted(records, key=lambda r: r['asset_id']):
            geometry = (LineString(record['points']) if layer == 'roads'
                        else Polygon(record['outer'], record.get('holes', [])))
            properties = {k: v for k, v in record.items()
                          if k not in {'outer', 'holes', 'triangles', 'roof_triangles', 'points'}}
            properties.update(context_layer=layer, measured=False,
                              geometry_status='source_community_mapping_not_surveyed')
            features.append({'type': 'Feature', 'id': record['asset_id'],
                             'geometry': mapping(geometry), 'properties': properties})
            if layer == 'context_buildings':
                faces = list(triangles(record))
            else:
                if layer == 'roads':
                    width = record.get('width')
                    if width is None or width <= 0:
                        raise ValueError(f"Road lacks positive source width: {record['asset_id']}")
                    geometry = geometry.buffer(width / 2, cap_style='flat', join_style='mitre')
                faces = []
                for triangle in constrained_delaunay_triangles(geometry).geoms:
                    p = list(triangle.exterior.coords)[:3]
                    if (p[1][0]-p[0][0])*(p[2][1]-p[0][1])-(p[1][1]-p[0][1])*(p[2][0]-p[0][0]) < 0:
                        p[1], p[2] = p[2], p[1]
                    faces.append([[x, y, DISPLAY[layer][1]] for x, y in p])
            positions = []
            normals = []
            import math
            for face in faces:
                t = [to_gltf(p) for p in face]
                u = [t[1][i]-t[0][i] for i in range(3)]
                v = [t[2][i]-t[0][i] for i in range(3)]
                n = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
                length = math.sqrt(sum(x*x for x in n))
                if length < 1e-12:
                    raise ValueError(f"Degenerate context face: {record['asset_id']}")
                positions.extend(x for p in t for x in p)
                normals.extend([x/length for x in n] * 3)
            writer.add_mesh(record['asset_id'], positions, normals,
                [(material, list(range(len(positions)//3)))],
                {'source_asset_id': record['asset_id'], 'context_layer': layer,
                 'source_namespace': 'njupt-map', 'geometry_status': 'derived_display_context',
                 'measured': False, 'display_elevation_offset_m': DISPLAY[layer][1],
                 'width_source': record.get('width_source')})
    geojson = {'type': 'FeatureCollection', 'name': 'campus-context',
        'coordinate_frame': 'campus_local_east_north_m', 'source_crs': data['metadata']['crs'],
        'origin_easting_northing': data['metadata']['origin_easting_northing'], 'features': features}
    return writer.finish(), geojson, {'counts': counts, 'measured_tree_count': len(data['trees']),
        'tree_geometry_included': False,
        'road_surface': 'Buffered canonical centerlines using source width; not a measured road-edge polygon',
        'elevations': 'Small display offsets prevent z-fighting; no terrain/survey elevations are inferred',
        'palette': 'Display-only colors; no image or texture is embedded'}
