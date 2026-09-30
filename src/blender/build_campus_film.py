"""Render the authored njupt-map film or explicitly assemble a disposable candidate.

Blender --background --factory-startup --python src/blender/build_campus_film.py -- --storyboard
Blender --background --factory-startup --python src/blender/build_campus_film.py -- --render
"""
from pathlib import Path
from datetime import datetime,timezone
import uuid
import argparse,json,math,sys,time,hashlib
import bpy
from mathutils import Vector,Quaternion

ROOT=Path(__file__).resolve().parents[2]
PLAN=ROOT/'projects/blender/presentation/camera_plan.json'
FILM=ROOT/'projects/blender/presentation/film.blend'
MASTER=ROOT/'projects/blender/campus.blend'

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def source_snapshot():
    paths={'master':MASTER,'film_scene':Path(bpy.data.filepath),'camera_plan':PLAN,
           'asset_catalog':ROOT/'projects/blender/buildings/catalog.json',
           'audio':ROOT/'projects/blender/presentation/audio/njupt_campus_original_score_35s.wav'}
    assets=json.loads(paths['asset_catalog'].read_text(encoding='utf8'))
    paths.update({f'asset:{asset_id}':ROOT/'projects/blender/buildings'/f'{asset_id}.blend' for asset_id in sorted(assets)})
    result={}
    for key,path in paths.items():
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        stat=path.stat()
        result[key]={'path':path.relative_to(ROOT).as_posix(),'sha256':digest.hexdigest(),
                     'size_bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns}
    return result

def write_run_manifest(path,manifest):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')

def clear_sports_vegetation(scene):
    """Check actual sports footprints and canopy, with crown-sized clearance.

    The refined master already clips seating to its concave footprint and uses
    crown collision rejection. Retain a narrowly scoped film safety check; never
    reproduce the old oversized rectangular-stand mask.
    """
    sys.path.insert(0,str(ROOT/'src/blender'))
    from campus_landscape import _inside,_dist_seg,_oriented_bounds,_stadium
    data=json.loads((ROOT/'build/map/campus.json').read_text(encoding='utf8'))
    masks=[]
    for b in data['buildings']:
        if b['id'] not in {'osm_way_223859802','osm_way_223859827','osm_way_224940881'}:continue
        ring=[tuple(p[:2]) for p in b['outer']]
        if ring[0]==ring[-1]:ring.pop()
        masks.append((b['id'],ring))
        if b['id']!='osm_way_223859827':continue
        a,z=max(zip(ring,ring[1:]+ring[:1]),key=lambda pq:math.dist(*pq))
        angle=math.atan2(z[1]-a[1],z[0]-a[0]);c,s=math.cos(angle),math.sin(angle)
        cx,cy=b['center']
        # Match campus_landmarks.stand: photo-scaled roof, not full stand bbox.
        canopy=[(cx+x*c-y*s,cy+x*s+y*c) for x,y in [(-46,-10),(46,-10),(46,16),(-46,16)]]
        masks.append((b['id']+'_canopy',canopy))
    for record in data['sports']:
        if record.get('sport')!='soccer':continue
        center,length,width,angle=_oriented_bounds(record)
        masks.append((record['id'],_stadium(center,angle,max(36.5,width/2+1.5)+9.76)))
    hidden=[];checked=0;previously_hidden=0
    for ob in scene.objects:
        if not (ob.name.startswith(('乔木_','湖岸垂柳_')) or 'crown_collision_radius_m' in ob):continue
        if ob.hide_render:
            previously_hidden+=1
            continue
        checked+=1
        p=ob.matrix_world.translation
        radius=ob.get('crown_collision_radius_m')
        if radius is None:
            corners=[ob.matrix_world@Vector(v) for v in ob.bound_box]
            radius=max(math.hypot(v.x-p.x,v.y-p.y) for v in corners)
        for mask_id,ring in masks:
            if _inside(p,ring) or min(_dist_seg(p,a,b) for a,b in zip(ring,ring[1:]+ring[:1]))<radius+.4:
                ob.hide_render=True;ob.hide_set(True)
                hidden.append({'object':ob.name,'mask':mask_id,'xy':[round(p.x,3),round(p.y,3)],'crown_radius':round(radius,2)})
                break
    report={'schema_version':'2.0','checked_tree_count':checked,'previously_hidden_tree_count':previously_hidden,'hidden_tree_count':len(hidden),'reason':'Residual crown overlap check against actual concave seating footprints, photographed western canopy extent and athletics circuits. The refined master already rejects most overlaps. Any residual visibility correction is confined to the film copy.','clearance_m':.4,'trees':hidden,'masks':[{'id':key,'outer':ring} for key,ring in masks]}
    (ROOT/'build/checks/film').mkdir(parents=True,exist_ok=True)
    (ROOT/'build/checks/film/landscape_clearance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    scene['film_hidden_sports_trees']=len(hidden)
    print(f'FILM_LANDSCAPE_CLEARANCE hidden={len(hidden)}',flush=True)

def orient(location,target,roll=0):
    q=(Vector(target)-Vector(location)).to_track_quat('-Z','Y')
    return q@Quaternion((0,0,1),math.radians(roll))

def pose(shot,u):
    # A gentle 15% ease at both ends; the middle retains travelling momentum.
    # The slightly extended boundary poses give the shutter a valid trajectory.
    w=u+.024*math.sin(2*math.pi*(u-.5))
    loc=Vector(shot['start_location']).lerp(Vector(shot['end_location']),w)
    loc+=Vector(shot.get('arc',[0,0,0]))*math.sin(math.pi*u)
    target=Vector(shot['start_target']).lerp(Vector(shot['end_target']),w)
    return loc,target

def configure(scene,engine='CYCLES',samples=64,width=1920):
    scene.render.engine=engine
    scene.render.resolution_x=width;scene.render.resolution_y=round(width*9/16)
    scene.render.resolution_percentage=100
    scene.render.fps=24;scene.render.fps_base=1
    scene.render.image_settings.file_format='PNG'
    scene.render.image_settings.color_mode='RGB'
    scene.render.image_settings.color_depth='8'
    scene.render.image_settings.compression=15
    scene.render.film_transparent=False
    scene.render.use_motion_blur=True;scene.render.motion_blur_shutter=.40
    scene.render.use_persistent_data=True
    scene.view_settings.view_transform='AgX'
    scene.view_settings.exposure=.8
    if engine=='CYCLES':
        prefs=bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type='OPTIX';prefs.refresh_devices()
        for device in prefs.devices:device.use=device.type=='OPTIX'
        if not any(d.use for d in prefs.devices):raise RuntimeError('OPTIX GPU not found')
        scene.cycles.device='GPU'
        scene.cycles.samples=samples
        scene.cycles.use_adaptive_sampling=True
        scene.cycles.adaptive_threshold=.035
        scene.cycles.adaptive_min_samples=min(24,samples)
        scene.cycles.use_denoising=True
        scene.cycles.denoiser='OPENIMAGEDENOISE'
        scene.cycles.denoising_use_gpu=True
        scene.cycles.max_bounces=6;scene.cycles.diffuse_bounces=3;scene.cycles.glossy_bounces=3
        scene.cycles.transparent_max_bounces=12
    else:
        scene.eevee.taa_render_samples=samples
        scene.eevee.use_raytracing=True
        scene.eevee.use_fast_gi=True
        scene.eevee.shadow_ray_count=2
    return scene

def build(output):
    output=output.resolve()
    try:output.relative_to((ROOT/'build').resolve())
    except ValueError:raise ValueError('Candidate film output must be inside build/; native sources are protected')
    if output.suffix.lower()!='.blend':raise ValueError('Candidate film output must have the .blend extension')
    output.parent.mkdir(parents=True,exist_ok=True)
    source_hash=hashlib.sha256(MASTER.read_bytes()).hexdigest()
    bpy.ops.wm.open_mainfile(filepath=str(MASTER),load_ui=False)
    scene=bpy.context.scene
    clear_sports_vegetation(scene)
    plan=json.loads(PLAN.read_text(encoding='utf8'))
    scene.timeline_markers.clear()
    scene.frame_start=1;scene.frame_end=840
    shot_frames=120
    for i,shot in enumerate(plan['shots']):
        cd=bpy.data.cameras.new('FILM_'+shot['id']+'_'+shot['name'])
        cam=bpy.data.objects.new(cd.name,cd);scene.collection.objects.link(cam)
        cam.rotation_mode='QUATERNION'
        cd.type='PERSP';cd.lens=shot['lens'];cd.sensor_width=plan.get('sensor_width_mm',36);cd.clip_start=.5;cd.clip_end=12000
        cd.dof.use_dof=True;cd.dof.aperture_fstop=shot.get('fstop',8)
        cd.dof.aperture_blades=7
        for j in range(-1,shot_frames+2):
            frame=i*shot_frames+j+1
            loc,target=pose(shot,j/(shot_frames-1))
            cam.location=loc;cam.rotation_quaternion=orient(loc,target,shot.get('roll_deg',0))
            cd.dof.focus_distance=(target-loc).length
            cam.keyframe_insert('location',frame=frame)
            cam.keyframe_insert('rotation_quaternion',frame=frame)
            cd.dof.keyframe_insert('focus_distance',frame=frame)
        marker=scene.timeline_markers.new(shot['id']+' '+shot['name'],frame=i*shot_frames+1)
        marker.camera=cam
        shot['camera']=cam.name;shot['frame_start']=i*shot_frames+1;shot['frame_end']=(i+1)*shot_frames
    configure(scene)
    scene.frame_set(1);scene.camera=bpy.data.objects[plan['shots'][0]['camera']]
    scene['film_product']='njupt-map';scene['film_duration_seconds']=35
    scene['film_source_sha256']=source_hash
    scene['film_plan']=json.dumps(plan,ensure_ascii=False)
    scene.render.filepath=str(ROOT/'build/blender/renders/film/frames/frame_')
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    if hashlib.sha256(MASTER.read_bytes()).hexdigest()!=source_hash:raise RuntimeError('Source master changed')
    return plan

def set_frame(plan,frame):
    scene=bpy.context.scene;scene.frame_set(frame)
    shot=next((shot for shot in plan['shots'] if shot['frame_start']<=frame<=shot['frame_end']),None)
    if shot is None:raise ValueError(f'No authored shot covers frame {frame}')
    scene.camera=bpy.data.objects[shot['camera']]
    return shot

def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--storyboard',action='store_true');mode.add_argument('--benchmark',action='store_true')
    mode.add_argument('--render',action='store_true');mode.add_argument('--draft',action='store_true')
    p.add_argument('--assemble',action='store_true',help='Generate a candidate film in build/; preserve authored cameras and scene')
    p.add_argument('--output',type=Path,default=ROOT/'build/blender/film.blend')
    p.add_argument('--overwrite',action='store_true',help='Re-render existing frames after changing cameras, lighting or quality')
    p.add_argument('--engine',choices=['CYCLES','BLENDER_EEVEE'],default='CYCLES')
    p.add_argument('--samples',type=int,help='Override mode sample count (render: 64, storyboard: 20, draft: 16)')
    p.add_argument('--width',type=int,help='Override 16:9 image width (render: 1920, storyboard/draft: 960)')
    p.add_argument('--start',type=int,default=1);p.add_argument('--end',type=int,default=840)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if args.start<1 or args.end<args.start:p.error('--start and --end must define a positive, ordered frame range')
    if args.samples is not None and args.samples<1:p.error('--samples must be positive')
    if args.width is not None and args.width<16:p.error('--width must be at least 16 pixels')
    if args.assemble:
        output=args.output if args.output.is_absolute() else ROOT/args.output
        plan=build(output)
    else:
        bpy.ops.wm.open_mainfile(filepath=str(FILM),load_ui=False)
        plan=json.loads(bpy.context.scene['film_plan'])
    scene=bpy.context.scene
    if not (args.render or args.storyboard or args.benchmark or args.draft):
        print('FILM_SOURCE '+str(Path(bpy.data.filepath)),flush=True)
        return
    if args.end>scene.frame_end:p.error(f'--end exceeds the authored film end frame {scene.frame_end}')
    if args.storyboard:
        samples=args.samples or 20;width=args.width or 960
        frames=sorted({frame for shot in plan['shots'] for frame in
                       [shot['frame_start'],(shot['frame_start']+shot['frame_end'])//2,shot['frame_end']]
                       if args.start<=frame<=args.end})
        folder='preflight';prefix='board_'
    elif args.benchmark:
        samples=args.samples or 64;width=args.width or 1920
        frames=[frame for frame in [421,422,423] if args.start<=frame<=args.end]
        folder='preflight';prefix='bench_'+args.engine+'_'
    elif args.draft:
        samples=args.samples or 16;width=args.width or 960
        frames=list(range(args.start,args.end+1,4))
        folder='draft';prefix='draft_'
    else:
        samples=args.samples or 64;width=args.width or 1920
        frames=list(range(args.start,args.end+1))
        folder='frames';prefix='frame_'
    if not frames:p.error('The selected mode has no frames within --start/--end')
    configure(scene,args.engine,samples,width)
    (ROOT/'build/blender/renders/film'/folder).mkdir(parents=True,exist_ok=True)
    (ROOT/'build/checks/film').mkdir(parents=True,exist_ok=True)
    records=[]
    run_id=None;run_manifest=None;run_path=None
    if folder=='frames':
        run_id=str(uuid.uuid4())
        run_path=ROOT/'build/checks/film/runs'/f'{run_id}.json'
        run_manifest={'schema_version':'1.0','run_id':run_id,'status':'running','started_at_utc':utc_now(),
                      'source_provenance':source_snapshot(),'expected_frames':frames,
                      'settings':{'engine':scene.render.engine,'samples':samples,
                                  'width':scene.render.resolution_x,'height':scene.render.resolution_y,'fps':scene.render.fps},
                      'overwrite':args.overwrite,'rendered_frames':[]}
        write_run_manifest(run_path,run_manifest)
        run_manifest['assembled_from_master_sha256']=scene.get('film_source_sha256')
        write_run_manifest(run_path,run_manifest)
        print('FILM_RENDER_RUN '+json.dumps({'run_id':run_id,'manifest':str(run_path)}),flush=True)
    try:
        for index,frame in enumerate(frames):
            shot=set_frame(plan,frame)
            file=ROOT/'build/blender/renders/film'/folder/f'{prefix}{frame:04d}.png'
            if file.exists() and not (args.storyboard or args.benchmark or args.overwrite):
                print(f'SKIP {frame} existing',flush=True);continue
            start=time.time();scene.render.filepath=str(file)
            print(f'FILM_RENDER {frame}/{scene.frame_end} {shot["name"]}',flush=True)
            bpy.ops.render.render(write_still=True)
            elapsed=round(time.time()-start,3)
            record={'frame':frame,'shot':shot['id'],'seconds':elapsed,'path':str(file.relative_to(ROOT)),
                    'engine':args.engine,'samples':samples,'width':scene.render.resolution_x,
                    'run_id':run_id,'generated_at_utc':utc_now()}
            records.append(record)
            with (ROOT/'build/checks/film/render_times.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
            print(f'FILM_FRAME_DONE {frame} seconds={elapsed}',flush=True)
        if run_manifest is not None:
            current_sources=source_snapshot()
            if any(current_sources[key]['sha256']!=value['sha256'] for key,value in run_manifest['source_provenance'].items()):
                raise RuntimeError('Render input source changed during the run')
            run_manifest.update(status='completed' if len(records)==len(frames) else 'incomplete',
                                finished_at_utc=utc_now(),rendered_frames=[record['frame'] for record in records])
            write_run_manifest(run_path,run_manifest)
    except Exception as exc:
        if run_manifest is not None:
            run_manifest.update(status='failed',finished_at_utc=utc_now(),error=str(exc),
                                rendered_frames=[record['frame'] for record in records])
            write_run_manifest(run_path,run_manifest)
        raise
    print('FILM_RENDER_BATCH_DONE '+json.dumps({'frames':len(records),'seconds':sum(r['seconds'] for r in records)}),flush=True)

if __name__=='__main__':main()
