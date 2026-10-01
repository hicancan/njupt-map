"""Audit source region identity without destroying valid multi-region rooms."""
from __future__ import annotations
from collections import defaultdict
import json
import math
from pathlib import Path


def audit_regions(path: Path):
    design=json.loads(path.read_text(encoding='utf8'))
    regions=[]
    seen=set()
    families=defaultdict(list)
    seen_floors=set()
    for plan in design['floorplans']:
        floor_key=(plan['asset_id'],plan['floor'])
        if floor_key in seen_floors: raise ValueError(f'Duplicate floor source: {floor_key}')
        seen_floors.add(floor_key)
        if plan['coordinate_frame'] != 'source_image_normalized_xy_down':
            raise ValueError(f'Unsupported indoor coordinate frame: {floor_key}')
        for room in plan['rooms']:
            rid=room['region_id']
            if not rid or rid in seen: raise ValueError(f'Duplicate source region_id: {rid}')
            seen.add(rid)
            key=room.get('space_key') or None
            if key: families[key].append(rid)
            polygon = room.get('polygon')
            label = room.get('label_point')
            def point_valid(point):
                return (isinstance(point, list) and len(point) == 2
                        and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                and math.isfinite(v) and 0 <= v <= 1 for v in point))
            if polygon is not None and (len(polygon) < 4 or polygon[0] != polygon[-1]
                                        or not all(point_valid(p) for p in polygon)):
                raise ValueError(f'Invalid normalized polygon: {rid}')
            if label is not None and not point_valid(label):
                raise ValueError(f'Invalid normalized label point: {rid}')
            bbox = ([min(p[0] for p in polygon), min(p[1] for p in polygon),
                     max(p[0] for p in polygon), max(p[1] for p in polygon)] if polygon else None)
            regions.append({'region_id':rid,'asset_id':plan['asset_id'],'floor_level':plan['floor'],
                            'source_observation_id':plan['source_id'],'source_observation_sha256':plan['source_sha256'],
                            'source_space_key':key,'raw_label':room.get('raw_label'),
                            'geometry_status':room['geometry_status'],
                            'coordinate_frame':plan['coordinate_frame'],
                            'floorplan_id': f"{plan['asset_id']}/floor/{plan['floor']}",
                            'polygon_normalized': polygon, 'label_point_normalized': label,
                            'bounds_normalized': bbox, 'metric_transform': None,
                            'geometry_binding': room.get('geometry_binding'),
                            'dynamic_state_binding': 'external_explicit_region_to_space_crosswalk',
                            'identity_status':'source_region_not_physical_room_primary_key'})
    return {'schema_version':2,'format':'njupt-indoor-region-catalog','region_count':len(regions),'floorplan_count':len(seen_floors),
            'regions':sorted(regions,key=lambda r:r['region_id']),
            'multi_region_space_keys':[{'space_key':k,'region_ids':sorted(v),'status':'retained_requires_semantic_review'}
                                     for k,v in sorted(families.items()) if len(v)>1],
            'note':'Duplicate room labels may denote legitimate multiple regions. No regions were merged or deleted; a physical room ID requires explicit mapping.'}


def public_regions(audit):
    """Publish identity and provenance, excluding unreviewed reference geometry.

    The authoring audit still validates the retained native design inputs.
    A floorplan's availability as a reference does not grant redistribution of
    traced coordinates; the browser publication therefore contains no traces.
    """
    identity_keys = ('region_id', 'asset_id', 'floor_level', 'floorplan_id',
                     'source_observation_id', 'source_observation_sha256',
                     'source_space_key', 'raw_label', 'identity_status',
                     'dynamic_state_binding')
    return {
        'schema_version': audit['schema_version'], 'format': audit['format'],
        'region_count': audit['region_count'], 'floorplan_count': audit['floorplan_count'],
        'regions': [{**{key: region[key] for key in identity_keys},
                     'geometry_status': 'not_published_reference_geometry'}
                    for region in audit['regions']],
        'multi_region_space_keys': audit['multi_region_space_keys'],
        'geometry_publication': 'metadata_only',
        'note': 'Stable source identities and provenance only. Reference-derived floorplan polygons, label coordinates and metric registration are not distributed.'
    }
