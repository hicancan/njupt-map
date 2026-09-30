"""Read-only validation of interior authoring and saved inspection cameras.

Without --authored, enrich representative originals in memory and leave files
unchanged. --authored validates every current native asset after authoring.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys

import bpy

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src/blender'))
from enrich_interiors import enrich, show_interior, show_exterior, _without_openings, _stairs, _palette, Frame
from campus_geometry import signed_area, Batch, point_inside


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authored',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    catalog=json.loads((ROOT/'projects/blender/buildings/catalog.json').read_text(encoding='utf8'))
    campus=json.loads((ROOT/'build/map/campus.json').read_text(encoding='utf8'))
    buildings={b['id']:b for b in campus['buildings']}
    ids=list(catalog) if args.authored else ['osm_way_223859810','osm_way_155434036','osm_way_223859784','njupt_k_dormitory_02','osm_way_1281082570','osm_way_1454085437']
    # Opening subtraction must preserve the rest of a slab without overlapping
    # fragments, including an opening crossing an existing triangle edge.
    pieces=_without_openings([[(0,0),(10,0),(0,10)]],[[(1,1),(3,1),(3,3),(1,3)]])
    assert abs(sum(abs(signed_area(p)) for p in pieces)-46)<1e-5
    stair=Batch();frame=Frame([(-4,-4),(4,-4),(4,4),(-4,4)])
    _stairs(stair,frame,0,0,0,4.04,_palette())
    tops=[[stair.vertices[i] for i in face] for face in stair.faces if all(abs(stair.vertices[i][2]-4.04)<1e-6 for i in face)]
    assert any(min(p[0] for p in face)<-2.70 and max(p[0] for p in face)>-1.62 for face in tops), 'Stair upper platform must bridge to the slab'
    rows=[]
    for ident in ids:
        path=ROOT/'projects/blender/buildings'/f'{ident}.blend'
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        bpy.ops.wm.open_mainfile(filepath=str(path),load_ui=False)
        col=bpy.data.collections[catalog[ident]['collection']]
        baseline=set(col.all_objects)
        existing=next((c for c in col.children if c.get('njupt_editable_interiors')),None)
        stats=(catalog[ident]['stats']['enrichment']['interior'] if existing else enrich(buildings[ident],col)) if not args.authored else None
        interior=next((c for c in col.children if c.get('njupt_editable_interiors')),None)
        if interior:
            specs=json.loads(interior['camera_specs'])
            assert len({s['id'] for s in specs})==len(specs)
            assert any(s['id']=='cutaway' for s in specs)
            for spec in specs:
                cam=bpy.data.objects[spec['name']]
                assert cam.type=='CAMERA' and cam['asset_id']==ident
                assert cam['interior_camera_id']==spec['id']
                assert all(math.isfinite(x) for x in cam.location)
                assert any(int(c['floor'])==spec['floor'] for c in interior.children)
            for fl in interior.children:
                assert math.isfinite(fl['z_m'])
                openings=json.loads(fl['floor_openings_local_m'])
                assert all(abs(signed_area(p))>.01 for p in openings)
                for ob in fl.objects:
                    if ob.type=='MESH':
                        assert all(math.isfinite(x) for v in ob.data.vertices for x in v.co)
                        if ob.get('interior_role')=='furniture':
                            for face in ob.data.polygons:
                                if min(ob.data.vertices[i].co.z for i in face.vertices)<fl['z_m']+1.25:
                                    assert not any(point_inside(face.center[:2],opening) for opening in openings), f'Unsupported furniture over floor opening: {ident}/{fl["floor"]}'
            show_interior(col,1,False,False)
            assert not interior.hide_render
            show_exterior(col)
            assert interior.hide_render
            if args.authored:assert bpy.data.texts.get('View interior.py')
            if ident=='osm_way_223859810':
                official=[c for c in interior.children if c.get('plan_source_id','').startswith('library-official-floor-')]
                assert len(official)==4
                assert any(s['id']=='study' for s in specs)
            if ident=='njupt_k_dormitory_02':assert any(s['id']=='dorm' for s in specs)
            if ident=='osm_way_223859784':assert any(s['id']=='dining' for s in specs)
        else:assert stats and stats['floors']==0 or args.authored and catalog[ident]['stats']['enrichment']['interior']['floors']==0
        assert baseline<=set(col.all_objects)
        assert hashlib.sha256(path.read_bytes()).hexdigest()==before
        rows.append({'id':ident,'source_unchanged':True,'interior':stats or catalog[ident]['stats']['enrichment']['interior']})
        print('INTERIOR_VALIDATED',ident,flush=True)
    output=ROOT/'build/checks'/('interior-source-validation.json' if args.authored else 'interior-enrichment-smoke.json')
    output.write_text(json.dumps({'status':'pass','assets':rows},ensure_ascii=False,indent=2),encoding='utf8')
    print('INTERIOR_VALIDATION_PASS',len(rows),flush=True)


if __name__=='__main__':main()
