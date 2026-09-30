"""Audit source region identity without destroying valid multi-region rooms."""
from __future__ import annotations
from collections import defaultdict
import json
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
        for room in plan['rooms']:
            rid=room['region_id']
            if not rid or rid in seen: raise ValueError(f'Duplicate source region_id: {rid}')
            seen.add(rid)
            key=room.get('space_key') or None
            if key: families[key].append(rid)
            regions.append({'region_id':rid,'asset_id':plan['asset_id'],'floor_level':plan['floor'],
                            'source_observation_id':plan['source_id'],'source_observation_sha256':plan['source_sha256'],
                            'source_space_key':key,'raw_label':room.get('raw_label'),
                            'geometry_status':room['geometry_status'],
                            'coordinate_frame':plan['coordinate_frame'],
                            'identity_status':'source_region_not_physical_room_primary_key'})
    return {'schema_version':1,'region_count':len(regions),'floorplan_count':len(seen_floors),
            'regions':sorted(regions,key=lambda r:r['region_id']),
            'multi_region_space_keys':[{'space_key':k,'region_ids':sorted(v),'status':'retained_requires_semantic_review'}
                                     for k,v in sorted(families.items()) if len(v)>1],
            'note':'Duplicate room labels may denote legitimate multiple regions. No regions were merged or deleted; a physical room ID requires explicit mapping.'}
