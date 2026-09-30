"""Build the editable, georeferenced NJUPT campus in a clean Blender process.

Example (PowerShell): blender --background --factory-startup --python src/blender/build_campus.py -- --preview
The interactive Blender session is never cleared by this script.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys
import time
import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/blender'))
from campus_geometry import Batch,material,text_object
from campus_buildings import palette,building_asset
from campus_landmarks import make_landmark


def collection(name,parent):
    col=bpy.data.collections.new(name)
    parent.children.link(col)
    return col


def setup_camera(name,location,target,lens=45):
    dat=bpy.data.cameras.new(name)
    ob=bpy.data.objects.new(name,dat)
    bpy.context.scene.collection.objects.link(ob)
    ob.location=location
    ob.rotation_euler=(Vector(target)-Vector(location)).to_track_quat('-Z','Y').to_euler()
    dat.lens=lens
    dat.clip_end=15000
    return ob


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview',action='store_true')
    parser.add_argument('--render',action='store_true')
    parser.add_argument('--camera',default='')
    parser.add_argument('--assemble',action='store_true',help='Assemble a generated candidate; never overwrite native projects')
    parser.add_argument('--skip-landscape',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'build/blender/campus.blend')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    for sub in ['build/blender/generated-assets','build/blender/renders','build/checks']:
        (ROOT/sub).mkdir(parents=True,exist_ok=True)
    if args.assemble:
        args.output=args.output.resolve()
        if not args.output.is_relative_to((ROOT/'build').resolve()):
            raise ValueError('Candidate assembly output must be inside build/. Native projects are edited explicitly in Blender.')
        build(args)
    else:
        bpy.ops.wm.open_mainfile(filepath=str(ROOT/'projects/blender/campus.blend'),load_ui=False)
    if args.render or args.preview:
        render(args)


def build(args):
    start=time.time()
    data=json.loads((ROOT/'build/map/campus.json').read_text(encoding='utf8'))
    scene=bpy.context.scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for col in list(bpy.data.collections):
        if col.name=='Collection' and not col.objects:bpy.data.collections.remove(col)
    scene.unit_settings.system='METRIC'
    scene.unit_settings.scale_length=1.
    scene['project']='NJUPT Xianlin • evidence-driven campus master'
    scene['georeference']=json.dumps(data.get('metadata',{}),ensure_ascii=False)
    scene['accuracy_notice']='Mapped footprints, source-driven corrections and explicitly inferred appearance; not a survey/BIM model.'
    scene['source_attribution']='© OpenStreetMap contributors / ODbL; Poly Haven shared materials and tree / CC0; campus photos used as reference.'
    materials=palette()
    fonts=[ROOT/'projects/blender/materials/fonts/NotoSansSC-Regular.otf']
    font=next((bpy.data.fonts.load(str(p)) for p in fonts if p.exists()),None)
    staging=collection('BUILD_STAGING',scene.collection)
    instances=collection('01 · 建筑资产 / linked buildings',scene.collection)
    stats=[]
    manifest_path=ROOT/'projects/blender/buildings/catalog.json'
    previous=json.loads(manifest_path.read_text(encoding='utf8')) if manifest_path.exists() else {}
    manifest=dict(previous)
    for i,b in enumerate(data['buildings']):
        print(f"BUILD {i+1}/{len(data['buildings'])}: {b['name']} {b['id']}",flush=True)
        asset_path=ROOT/'projects/blender/buildings'/f"{b['id']}.blend"
        prior=previous.get(b['id'],{})
        # Every existing native building is an authored source, regardless of hash.
        # A rebuild only links it. Missing buildings are generated as candidates.
        if asset_path.exists():
            with bpy.data.libraries.load(str(asset_path),link=True) as (src,dst):
                name=prior.get('collection')
                if name not in src.collections:
                    raise RuntimeError(f'{b["id"]}: catalog collection missing from native asset')
                dst.collections=[name]
            linked=dst.collections[0]
            inst=bpy.data.objects.new(b['name'] or b['id'],None)
            instances.objects.link(inst);inst.instance_type='COLLECTION';inst.instance_collection=linked
            inst.location=(*b['center'],float(b.get('base_z',0)))
            inst['asset_id']=b['id'];inst['asset_file']=asset_path.relative_to(ROOT).as_posix()
            stat=dict(prior.get('stats',{}));stat['preserved_authored_asset']=True;stats.append(stat)
            continue
        asset_path=ROOT/'build/blender/generated-assets'/f"{b['id']}.blend"
        result=make_landmark(b,staging,materials,font)
        if result is None:
            override={'kind':'science'} if b.get('style_hint')=='science' else {}
            result=building_asset(b,staging,materials,font,override)
        col,stat=result
        from floorplan_references import build_floorplan_references
        stat['floorplan_references']=build_floorplan_references(b,col)
        col['world_placement']=json.dumps({'center':b['center'],'crs':data.get('metadata',{}).get('crs','EPSG:32650'),'origin_lonlat':[118.925,32.115]})
        # Save the collection and its dependencies as an independently editable asset.
        col.use_fake_user=True
        # A real scene makes the file usable by File > Open as well as by linking.
        asset_scene=bpy.data.scenes.new(b['name']+' • editable building')
        asset_scene.collection.children.link(col)
        asset_scene.unit_settings.system='METRIC'
        asset_scene['asset_id']=b['id'];asset_scene['world_center_m']=b['center']
        asset_scene['editing']='Candidate source. Explicitly accept it into projects/blender/buildings and update catalog before linking.'
        for layer in asset_scene.view_layers:layer.update()
        print('SAVE ASSET SCENE '+b['id'],flush=True)
        bpy.data.libraries.write(str(asset_path),{asset_scene},path_remap='RELATIVE',fake_user=True,compress=True)
        print('REMOVE ASSET SCENE '+b['id'],flush=True)
        bpy.data.scenes.remove(asset_scene)
        saved_name=col.name
        staging.children.unlink(col)
        col.use_fake_user=False
        # Load it back as a linked collection. The master is assembled, not flattened.
        with bpy.data.libraries.load(str(asset_path),link=True) as (src,dst):dst.collections=[saved_name]
        linked=dst.collections[0]
        inst=bpy.data.objects.new(b['name'] or b['id'],None)
        instances.objects.link(inst)
        inst.instance_type='COLLECTION';inst.instance_collection=linked
        inst.location=(*b['center'],0)
        inst['asset_id']=b['id'];inst['asset_file']=str(asset_path.relative_to(ROOT))
        stat['asset_file']=str(asset_path.relative_to(ROOT)).replace('\\','/')
        stats.append(stat)
        manifest[b['id']]={'sha256':hashlib.sha256(asset_path.read_bytes()).hexdigest(),'collection':saved_name,'stats':stat}
        # Persist each completed asset transaction. A later failure must not make
        # our own just-generated files look like untracked manual modifications.
        checkpoint=ROOT/'build/blender/generated-assets/catalog.json.partial'
        checkpoint.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
        checkpoint.replace(ROOT/'build/blender/generated-assets/catalog.json')
        # Remove generated unlinked originals after the persistent linked file exists.
        child_collections=list(col.children_recursive)
        for ob in list(col.all_objects):bpy.data.objects.remove(ob,do_unlink=True)
        for child_col in reversed(child_collections):bpy.data.collections.remove(child_col)
        bpy.data.collections.remove(col)
    bpy.data.collections.remove(staging)
    (ROOT/'build/blender/generated-assets/catalog.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    # Root palette no longer needed in current scene if asset versions are linked.
    landscape_stats={}
    if not args.skip_landscape:
        print('BUILD LANDSCAPE',flush=True)
        from campus_landscape import build_landscape
        landscape_stats=build_landscape(data,collection('02 · 道路 地形 水体 植被 / landscape',scene.collection))
    from campus_details import build_details
    details_stats=build_details(data,collection('03 · 校园细部 / furniture and landmarks',scene.collection),materials,font)
    if font and font.users==0:bpy.data.fonts.remove(font)
    for library in list(bpy.data.libraries):
        if 'essentials_brushes' in library.filepath:bpy.data.libraries.remove(library,do_unlink=True)
    # Light and sky use physical scale. No theatrical depth of field hides defects.
    world=bpy.data.worlds.new('Nanjing clear daylight')
    scene.world=world;world.use_nodes=True
    wn=world.node_tree.nodes;wn.clear()
    out=wn.new('ShaderNodeOutputWorld');bg=wn.new('ShaderNodeBackground');sky=wn.new('ShaderNodeTexSky')
    sky.sky_type='MULTIPLE_SCATTERING';sky.sun_elevation=math.radians(36);sky.sun_rotation=math.radians(225)
    sky.sun_intensity=1.;sky.sun_disc=False;sky.altitude=30.;sky.air_density=1.;sky.aerosol_density=.65
    bg.inputs['Strength'].default_value=.065
    world.node_tree.links.new(sky.outputs['Color'],bg.inputs['Color']);world.node_tree.links.new(bg.outputs[0],out.inputs[0])
    sun=bpy.data.lights.new('Afternoon sun','SUN');sun.energy=5.;sun.angle=.02;sun.color=(1,.94,.85)
    sunob=bpy.data.objects.new('Afternoon sun',sun);scene.collection.objects.link(sunob)
    sunob.rotation_euler=(math.radians(48),math.radians(-30),math.radians(-105))
    cameras=[
        ('01_全校鸟瞰',(-1280,-1820,1450),(20,30,0),46),
        ('02_南门与中博湖',(495,-990,158),(106,-566,17),43),
        ('03_图书馆',(-50,-155,35),(184,-106,12),43),
        ('04_教学楼庭院',(-123,-660,75),(18,-530,11),38),
        ('05_体育馆与北区',(-370,160,200),(60,574,13),42),
        ('06_林荫大道',(138,-689,2.4),(135,-240,10),27),
    ]
    for c in cameras:setup_camera(*c)
    scene.camera=bpy.data.objects[cameras[0][0]]
    scene.render.engine='CYCLES'
    cp=bpy.context.preferences.addons['cycles'].preferences
    cp.compute_device_type='OPTIX';cp.refresh_devices()
    for dev in cp.devices:dev.use=dev.type=='OPTIX'
    scene.cycles.device='GPU'
    scene.cycles.samples=128
    scene.cycles.use_denoising=True
    scene.cycles.max_bounces=6
    scene.cycles.diffuse_bounces=3
    scene.cycles.glossy_bounces=3
    scene.render.resolution_x=2560;scene.render.resolution_y=1600
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.view_settings.view_transform='AgX'
    scene.view_settings.exposure=.80
    scene.render.film_transparent=False
    # Start the interactive editor in the master aerial camera.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                space=area.spaces.active
                space.clip_end=10000;space.lens=65
                space.camera=scene.camera
                space.region_3d.view_location=(20,30,0)
                space.region_3d.view_rotation=scene.camera.rotation_euler.to_quaternion()
                space.region_3d.view_distance=1800
                space.region_3d.view_perspective='PERSP'
                space.overlay.show_overlays=False
                space.shading.type='MATERIAL'
    scene['build_elapsed_seconds']=round(time.time()-start,2)
    report={'created_at':time.strftime('%Y-%m-%d %H:%M:%S'),'build_elapsed_seconds':round(time.time()-start,2),'buildings':stats,'landscape':landscape_stats,'details':details_stats,'georeference':data.get('metadata',{}),'object_count':len(scene.objects),'materials':len(bpy.data.materials),'notes':['Model includes explicit inferential geometry and material assumptions.','Photo-reference images are not embedded as facade textures.','Buildings are saved independently and linked into the master.']}
    (ROOT/'build/checks/build_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output),compress=True)
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output),compress=True)
    print('MASTER SAVED',flush=True)


def render(args):
    scene=bpy.context.scene
    prefs=bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type='OPTIX';prefs.refresh_devices()
    for device in prefs.devices:device.use=device.type=='OPTIX'
    scene.cycles.device='GPU'
    cams=sorted(o.name for o in scene.objects if o.type=='CAMERA')
    if args.camera:cams=[c for c in cams if args.camera in c]
    elif args.preview:cams=cams[:1]
    scene.cycles.samples=32 if args.preview else 128
    scene.render.resolution_x=1440 if args.preview else 2560
    scene.render.resolution_y=900 if args.preview else 1600
    for name in cams:
        scene.camera=bpy.data.objects[name]
        scene.render.filepath=str(ROOT/'build/blender/renders'/(name+('_preview' if args.preview else '')+'.png'))
        print('RENDER '+name,flush=True)
        bpy.ops.render.render(write_still=True)


if __name__=='__main__':main()
