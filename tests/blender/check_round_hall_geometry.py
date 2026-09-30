"""Retained geometry check. Run with Blender --background --factory-startup --python-exit-code 1 --python this_file. Does not save a Blender scene or render images."""
import sys,json,math
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'src/blender'))
import bpy
from campus_buildings import palette
from campus_landmark_forms import round_hall
canonical=json.loads((root/'build/map/campus.json').read_text(encoding='utf-8'))
b=next(x for x in canonical['buildings'] if x['id']=='osm_way_224950590')
col,stat=round_hall(b,bpy.context.scene.collection,palette(),None)
report={'status':'passed','stat':stat,'mesh_checks':[],'scope':'Generator geometry only; native scenes and render dependencies are checked separately.'}
hi=max(v.co.z for ob in col.objects if ob.type=='MESH' for v in ob.data.vertices)
assert abs(hi-stat['height'])<1e-4,(hi,stat['height'])
for ob in col.objects:
 if ob.type=='MESH':
  ob.data.calc_loop_triangles()
  assert all(math.isfinite(v) for p in ob.data.vertices for v in p.co)
  bad=sum(1 for p in ob.data.polygons if p.area<1e-10)
  report['mesh_checks'].append({'name':ob.name,'vertices':len(ob.data.vertices),'polygons':len(ob.data.polygons),'zero_area_faces':bad})
  assert not bad,(ob.name,bad)
# Include the outward corner of a tangent transom, not just its centre radius.
window_frame_outer=math.hypot(18.95*1.01+.05,math.tau*18.95/96/2)
rail_limit=math.pi-math.asin(10.7/20.34)
rail_inner=20.34*math.cos(rail_limit/112)-.03
clearance=rail_inner-window_frame_outer
assert clearance>1.10,clearance
report['gallery_clearance_with_chord_and_frame_corners_m']=clearance
report['measured_mesh_max_z_m']=hi
(root/'build/checks/refinement').mkdir(parents=True,exist_ok=True)
(root/'build/checks/refinement/round_hall_generator_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('ROUND_HALL_SMOKE_PASS',hi,'m maxZ; clear passage',clearance,'m')
