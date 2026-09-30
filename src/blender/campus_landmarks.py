"""Distinctive NJUPT landmarks, reconstructed from archived photo references.

Footprint placement is map-derived. Unmeasured dimensions and hidden details
remain documented approximations; this file is intentionally easy to revise.
"""
import math
import json
from pathlib import Path
import bpy
from campus_geometry import Batch,material,text_object,point_inside
from mathutils import Vector
from mathutils.geometry import tessellate_polygon
from campus_buildings import window


def new_asset(b,parent,kind):
    col=bpy.data.collections.new(b['name']+' | '+b['id'])
    parent.children.link(col)
    col['asset_id']=b['id']
    col['campus_name']=b['name']
    col['origin_local_m']=list(b['center'])+[0.]
    col['source_url']=b.get('source_url','')
    col['facade_status']='photo-reconstructed landmark; unmeasured dimensions and unseen details inferred'
    col['generated_by']='src/blender/campus_landmarks.py'
    return col,{'id':b['id'],'name':b['name'],'kind':kind,'center':b['center'],'facade_status':col['facade_status']}


def stand(b,parent,m,font):
    col,stat=new_asset(b,parent,'stadium_stand')
    mesh=Batch()
    cx,cy=b['center']
    ring=[(p[0]-cx,p[1]-cy) for p in b['outer']]
    # Follow the mapped concave stand without extruding it into an office block.
    longest=max(zip(ring,ring[1:]+ring[:1]),key=lambda pq:math.dist(*pq))
    ang=math.atan2(longest[1][1]-longest[0][1],longest[1][0]-longest[0][0])
    ca,sa=math.cos(ang),math.sin(ang)
    rr=[(x*ca+y*sa,-x*sa+y*ca) for x,y in ring]
    xmin,xmax=min(x for x,y in rr),max(x for x,y in rr)
    ymin,ymax=min(y for x,y in rr),max(y for x,y in rr)
    if xmax-xmin<ymax-ymin:
        ang+=math.pi/2;ca,sa=math.cos(ang),math.sin(ang)
        rr=[(x*ca+y*sa,-x*sa+y*ca) for x,y in ring]
        xmin,xmax=min(x for x,y in rr),max(x for x,y in rr)
        ymin,ymax=min(y for x,y in rr),max(y for x,y in rr)
    covered=b['id']=='osm_way_223859827'
    if covered:ymax=min(ymax,13.4)
    rows=max(4,min(28,int((ymax-ymin)/1.15)))
    sports=json.loads((Path(__file__).resolve().parents[2]/'build/map/campus.json').read_text(encoding='utf8'))['sports']
    pitch=min((s for s in sports if s.get('sport')=='soccer'),key=lambda s:math.dist(s['center'],b['center']))
    dx,dy=pitch['center'][0]-cx,pitch['center'][1]-cy
    field_y=-dx*sa+dy*ca
    seat=material('Track stands • deep red seating',(.40,.10,.065),.65)
    # Crop tiers to the actual concave mapped shape. Bounding-box tiers formerly
    # doubled some stand footprints and collided with correctly placed trees.
    triangles=tessellate_polygon([[Vector((x,y,0)) for x,y in rr]])
    def clip(poly,bound,keep_above):
        result=[]
        for a,bb in zip(poly,poly[1:]+poly[:1]):
            ia=(a[1]>=bound) if keep_above else (a[1]<=bound)
            ib=(bb[1]>=bound) if keep_above else (bb[1]<=bound)
            if ia:result.append(a)
            if ia!=ib:
                t=(bound-a[1])/(bb[1]-a[1]);result.append((a[0]+t*(bb[0]-a[0]),bound))
        return result
    seating_count=0
    for i in range(rows):
        y=ymin+(ymax-ymin)*(i+.5)/rows;z=.25+(i if field_y<0 else rows-1-i)*.36
        half=(ymax-ymin)/rows/2
        for tri in triangles:
            points=[rr[v] if isinstance(v,int) else (v.x,v.y) for v in tri]
            poly=clip(clip(points,y-half,True),y+half,False)
            if len(poly)>=3:
                world=[(ca*x-sa*yy,sa*x+ca*yy) for x,yy in poly]
                mesh.extrude(world,[],0,z,m['step'])
        for j in range(max(1,int((xmax-xmin)/.66))):
            x=xmin+.33+j*.66
            if j%17 in [0,1]:continue
            if not all(point_inside((x+dx,y+dy),rr) for dx in [-.25,.25] for dy in [-.23,.23]):continue
            if covered:mesh.box((ca*x-sa*y,sa*x+ca*y,z+.12),(.48,.44,.20),seat,ang)
            else:mesh.box((ca*x-sa*y,sa*x+ca*y,z+.035),(.49,.42,.06),seat if j%34<12 else m['white'],ang)
            seating_count+=1
    mesh.object('Stadium • tiered seating',col)
    if covered:
        structure=Batch();shell=Batch()
        def p(x,y,z):return(ca*x-sa*y,sa*x+ca*y,z)
        def box(x,y,z,w,d,h,ma):structure.box(p(x,y,z),(w,d,h),ma,ang)
        # The central rear projection is an entrance/service core, not seating.
        box(-1,23,4.5,21,19,9,m['white'])
        box(0,12,10.5,74,.30,4.0,m['red'])
        for x in range(-35,36,5):
            box(x,12.5,10.8,3.4,.12,3.0,m['glass0'])
            box(x,14,6.1,.42,.52,12.2,m['white'])
        # High wing-form metal canopy photographed above the western grandstand.
        # Curvature and span are photo-scaled assumptions, retained parametrically.
        def roof_z(x,y):
            t=(16-y)/26
            return 13.4+5.0*math.sin(t*math.pi/2)-.50*max(0,(t-.84)/.16)**2-.3*(x/46.)**2
        nx,ny=50,12
        for i in range(nx):
            a=-46+92*i/nx;bb=-46+92*(i+1)/nx
            for j in range(ny):
                ya=-10+26*j/ny;yb=-10+26*(j+1)/ny
                shell.face([p(a,ya,roof_z(a,ya)),p(bb,ya,roof_z(bb,ya)),p(bb,yb,roof_z(bb,yb)),p(a,yb,roof_z(a,yb))],m['roofmetal'])
                shell.face([p(a,yb,roof_z(a,yb)-.50),p(bb,yb,roof_z(bb,yb)-.50),p(bb,ya,roof_z(bb,ya)-.50),p(a,ya,roof_z(a,ya)-.50)],m['frame'])
        for x in range(-40,41,5):
            structure.pipe(p(x,13,9),p(x,13,roof_z(x,13)-.2),.14,m['frame'],12)
            for j in range(12):
                ya=-10+26*j/12;yb=-10+26*(j+1)/12
                structure.pipe(p(x,ya,roof_z(x,ya)-.60),p(x,yb,roof_z(x,yb)-.60),.11,m['frame'],10)
            structure.pipe(p(x,13,roof_z(x,13)-2.0),p(x,-7,roof_z(x,-7)-.65),.09,m['frame'],10)
        for x in range(-46,47,2):
            for j in range(12):
                ya=-10+26*j/12;yb=-10+26*(j+1)/12
                structure.pipe(p(x,ya,roof_z(x,ya)+.025),p(x,yb,roof_z(x,yb)+.025),.018,m['frame'],6)
        for y in [-10,16]:
            for i in range(50):
                a=-46+92*i/50;bb=-46+92*(i+1)/50
                shell.face([p(a,y,roof_z(a,y)),p(bb,y,roof_z(bb,y)),p(bb,y,roof_z(bb,y)-.50),p(a,y,roof_z(a,y)-.50)],m['white'])
        shell.object('West grandstand • curved silver canopy',col)
        structure.object('West grandstand • ribs red rear wall and entrance',col)
    stat.update(height=18.4 if covered else rows*.36,levels=1,window_count=0,objects=len(col.objects),seating_count=seating_count,tier_footprint='clipped to concave mapped polygon; seats face nearest mapped soccer field',references=['observations/images/njupt/construction_article_216691_image_00.jpg'],inferred=['row count and riser dimension','canopy curve, ribs and core elevations'] if covered else ['row count and riser dimension'])
    return col,stat


def make_landmark(b,parent,m,font):
    if b['id']=='osm_way_223859810':
        from campus_landmark_forms import library
        return library(b,parent,m,font)
    if b['id']=='osm_way_224950590':
        from campus_landmark_forms import round_hall
        return round_hall(b,parent,m,font)
    if b['id']=='osm_way_1454085437':
        from campus_gate import gateway
        return gateway(b,parent,m,font)
    if b['id']=='osm_way_1281082570':
        from campus_gym import gym
        return gym(b,parent,m,font)
    if b['id']=='osm_way_223944208':
        from campus_old_gym import old_gym
        return old_gym(b,parent,m,font)
    if b['name'] in ['看台','主席台']:return stand(b,parent,m,font)
    return None
