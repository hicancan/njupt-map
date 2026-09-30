"""Retained geometry check. Run with Blender --background --factory-startup --python-exit-code 1 --python this_file. Does not save a Blender scene or render images."""
import sys,json,math
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'src/blender'))
import bpy
from campus_buildings import palette
from campus_old_gym import old_gym
b=next(b for b in json.loads((root/'build/map/campus.json').read_text(encoding='utf-8'))['buildings'] if b['id']=='osm_way_223944208')
col,stat=old_gym(b,bpy.context.scene.collection,palette(),None)
report={'status':'passed','stat':stat,'mesh_checks':[],'sign_glyphs':[]}
for ob in col.objects:
 if ob.type=='MESH':
  ob.data.calc_loop_triangles()
  assert all(math.isfinite(v) for p in ob.data.vertices for v in p.co)
  bad=sum(1 for p in ob.data.polygons if p.area<1e-10)
  check={'name':ob.name,'vertices':len(ob.data.vertices),'polygons':len(ob.data.polygons),'zero_area_faces':bad}
  report['mesh_checks'].append(check)
  assert not bad,(ob.name,bad)
 elif ob.type=='CURVE':
  report['sign_glyphs'].append({'name':ob.name,'contours':len(ob.data.splines)})
assert len(report['sign_glyphs'])==3
(root/'build/checks/refinement').mkdir(parents=True,exist_ok=True)
(root/'build/checks/refinement/old_gym_generator_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('OLD_GYM_SMOKE_PASS',len(col.objects),'objects')
