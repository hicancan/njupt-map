"""Repeatable visual inspections. Isolated studies expose geometry without trees.

Default: use the assembled master and retain all scene objects. --isolated
generates only the selected asset in a separate, unsaved Blender process.
"""
import argparse,json,math,sys,time
from pathlib import Path
import bpy
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/blender'))
from build_campus import setup_camera

VIEWS={
 'gate':('osm_way_1454085437',(20,-87,23),(0,0,11),48),
 'gate_front':('osm_way_1454085437',(0,-102,15),(0,0,12),54),
 'gate_ground':('osm_way_1454085437',(-14,-96,5.5),(5,-2,10),38),
 'library':('osm_way_223859810',(-174,-103,70),(0,0,12),51),
 'library_stairs':('osm_way_223859810',(-95,-27,11),(-34,0,8),39),
 'round_hall':('osm_way_224950590',(92,-57,31),(0,0,11),50),
 'gym':('osm_way_1281082570',(-112,164,70),(0,0,10),45),
 'gym_south':('osm_way_1281082570',(84,-120,69),(0,0,9),44),
 'teaching':('osm_way_223699451',(-67,-98,47),(0,0,10),42),
 'old_gym':('osm_way_223944208',(-141,-17,57),(0,0,10),46),
 'yingyuan':('osm_way_1173057035',(110,100,55),(0,0,10),45),
 'k_dining':('njupt_k_dining_04',(148,68,57),(0,0,10),45),
 'stand':('osm_way_223859827',(107,27,63),(0,0,8),47),
}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--isolated',action='store_true');parser.add_argument('--names',default='gate,library,round_hall,gym');parser.add_argument('--samples',type=int,default=48);parser.add_argument('--width',type=int,default=1800)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    data=json.loads((ROOT/'build/map/campus.json').read_text(encoding='utf8'))
    buildings={b['id']:dict(b) for b in data['buildings']}
    if not args.isolated:bpy.ops.wm.open_mainfile(filepath=str(ROOT/'projects/blender/campus.blend'))
    results=[]
    for key in args.names.split(','):
        ident,loc,target,lens=VIEWS[key];b=buildings[ident]
        if args.isolated:
            bpy.ops.wm.read_factory_settings(use_empty=True)
            from campus_buildings import palette,building_asset
            from campus_landmarks import make_landmark
            from campus_geometry import Batch,material
            mats=palette();font=None
            output=make_landmark(b,bpy.context.scene.collection,mats,font)
            if output is None:output=building_asset(b,bpy.context.scene.collection,mats,font,{})
            ground=Batch();ground.box((0,0,-.12),(2000,2000,.2),material('Review neutral ground',(.21,.23,.24),.9));ground.object('Review ground',bpy.context.scene.collection)
            world=bpy.data.worlds.new('Review daylight');world.use_nodes=True;bpy.context.scene.world=world
            wn=world.node_tree.nodes;bg=wn.get('Background');sky=wn.new('ShaderNodeTexSky');sky.sky_type='MULTIPLE_SCATTERING';sky.sun_elevation=.65;sky.sun_rotation=3.9;sky.sun_disc=False
            bg.inputs['Strength'].default_value=.14;world.node_tree.links.new(sky.outputs['Color'],bg.inputs['Color'])
            sun=bpy.data.lights.new('Review sun','SUN');sun.energy=3.2;sun.angle=.06
            so=bpy.data.objects.new('Review sun',sun);bpy.context.scene.collection.objects.link(so);so.rotation_euler=(.65,-.3,-.5)
            camloc=loc;camtarget=target
        else:
            cx,cy=b['center'];camloc=(loc[0]+cx,loc[1]+cy,loc[2]);camtarget=(target[0]+cx,target[1]+cy,target[2])
        scene=bpy.context.scene;scene.camera=setup_camera('Review '+key,camloc,camtarget,lens)
        scene.render.engine='CYCLES';prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.refresh_devices()
        for device in prefs.devices:device.use=device.type=='OPTIX'
        scene.cycles.device='GPU';scene.cycles.samples=args.samples;scene.cycles.use_denoising=True;scene.cycles.max_bounces=6
        scene.view_settings.view_transform='AgX';scene.view_settings.exposure=.65
        scene.render.resolution_x=args.width;scene.render.resolution_y=round(args.width*9/16);scene.render.resolution_percentage=100
        path=ROOT/'build/blender/renders/refinement'/((key+'_isolated' if args.isolated else key)+'.png');path.parent.mkdir(parents=True,exist_ok=True)
        scene.render.image_settings.file_format='PNG';scene.render.filepath=str(path)
        start=time.time();bpy.ops.render.render(write_still=True)
        results.append({'view':key,'file':str(path.relative_to(ROOT)),'isolated':args.isolated,'seconds':round(time.time()-start,2),'asset_id':ident})
        print('REVIEW_RENDER '+key,flush=True)
    print(json.dumps(results),flush=True)

if __name__=='__main__':main()
