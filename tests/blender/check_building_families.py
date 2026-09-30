"""Retained geometry check. Run with Blender --background --factory-startup --python-exit-code 1 --python this_file. Does not save a Blender scene or render images."""
import bpy,sys,json,math
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'src/blender'))
from campus_buildings import palette,building_asset,_profile,classify
from campus_landscape import Occupancy
D=json.loads((root/'build/map/campus.json').read_text(encoding='utf-8'))
M=palette();results=[]
ids={'osm_way_223699451','osm_way_223699456','osm_way_1173057035','osm_way_1173057036','osm_way_1173059720','osm_way_1173057050','njupt_k_dormitory_01','njupt_k_dormitory_06','njupt_k_dining_04'}
for b in D['buildings']:
 if b['id'] not in ids:continue
 col,stat=building_asset(b,bpy.context.scene.collection,M,None)
 stat['vertices']=sum(len(o.data.vertices) for o in col.objects if o.type=='MESH')
 stat['finite_meshes']=all(all(math.isfinite(c) for c in v.co) for o in col.objects if o.type=='MESH' for v in o.data.vertices)
 stat['bounds_local']=[[min(v.co[a] for o in col.objects if o.type=='MESH' for v in o.data.vertices),max(v.co[a] for o in col.objects if o.type=='MESH' for v in o.data.vertices)] for a in (0,1,2)]
 results.append(stat)
profiles={}
for b in D['buildings']:profiles.setdefault(_profile(b,classify(b)),[]).append(b['id'])
report={'generator_smoke':results,'profile_assignment':profiles,'scope':'Only representative asset construction and finite meshes; rendering and whole-campus integration remain root tasks.'}
(root/'build/checks/refinement').mkdir(parents=True,exist_ok=True)
(root/'build/checks/refinement/building_family_smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
boundary={'outer':[[-100,-100],[100,-100],[100,100],[-100,100]],'holes':[]}
rect={'outer':[[0,0],[20,0],[20,20],[0,20]],'holes':[[[5,5],[15,5],[15,15],[5,15]]]}
occ=Occupancy({'boundary':boundary,'buildings':[rect]})
checks={'solid_rejected':not occ.free((2,2),crown_radius=1),'courtyard_clear_accepted':occ.free((10,10),crown_radius=1),'courtyard_crown_clash_rejected':not occ.free((10,10),crown_radius=5),'outside_large_crown_rejected':not occ.free((24,10),crown_radius=4),'outside_small_crown_accepted':occ.free((25,10),crown_radius=1)}
assert all(checks.values()),checks
report['occupancy_checks']=checks
(root/'build/checks/refinement/building_family_smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('ASSET_SMOKE_OK',[(r['id'],r['vertices']) for r in results])
