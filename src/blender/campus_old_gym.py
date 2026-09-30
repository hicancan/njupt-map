"""Old sports hall omitted by the original building-only OSM filter.

The five-ring facade looks toward local -X at 29.8 degrees map rotation.
Map footprint and official completion photographs constrain its silhouette;
the 22 metre hall height and unphotographed elevations remain estimates.
"""
import json
import math
from pathlib import Path

import bpy
from campus_geometry import Batch, material


def old_gym(b,parent,m,font):
    from campus_landmarks import new_asset
    col,stat=new_asset(b,parent,'old_gym')
    col['generated_by']='src/blender/campus_old_gym.py'
    col['evidence_revision']='2026-09-30'
    col['recovered_map_feature']='OSM way 223944208, leisure=stadium without building tag'
    body=Batch();trim=Batch();glazing=Batch();rings=Batch()
    a=math.radians(29.8);ca,sa=math.cos(a),math.sin(a)
    def p(x,y,z):return (ca*x-sa*y,sa*x+ca*y,z)
    def box(batch,x,y,z,dx,dy,dz,ma):batch.box(p(x,y,z),(dx,dy,dz),ma,a)
    def face(batch,vertices,ma):batch.face([p(*q) for q in vertices],ma)
    stone=material('Old gym | warm pale limestone',(.70,.65,.47),.75,noise=.022)
    joint=material('Old gym | fine stone joints',(.49,.48,.39),.8)
    sill=material('Old gym | pale window surrounds',(.82,.80,.68),.66)
    blue=material('Old gym | dark blue photographed letters',(.006,.045,.145),.32,.25)
    orange=material('Old gym | ochre entry reveal',(.91,.42,.023),.57)
    glass=material('Old gym | blue green glazing',(.028,.080,.079),.22,.40)
    shade=material('Old gym | deep aperture shadow',(.010,.016,.017),.8)
    frame=material('Old gym | bronze aluminium',(.18,.20,.18),.40,.65)
    roof=material('Old gym | muted blue standing seam roof',(.08,.23,.34),.48,.55)
    roof_edge=material('Old gym | roof metal edges',(.38,.48,.53),.40,.64)

    # Main hall: the map's huge unbroken plane is its five-ring facade, not a
    # generic office block with repeated window rows. South/rear wall positions
    # preserve the slightly skewed original map vertices.
    main=[(-35.31,-30.18),(33.21,-28.80),(32.34,12.35),(-35.57,12.29)]
    for i in range(3):
        q,r=main[i],main[i+1]
        face(body,[(*q,0),(*r,0),(*r,21.75),(*q,21.75)],stone)
    # Leave an actual aperture for the three low tall windows.
    u0,u1=-12.29,30.18
    def front_rect(ua,ub,z0,z1,ma,x=-35.57,depth=.42):
        box(body,x,-(ua+ub)/2,(z0+z1)/2,depth,ub-ua,z1-z0,ma)
    front_rect(u0,u1,5.3,22.0,stone)
    front_rect(u0,4.0,0,5.3,stone)
    front_rect(16.0,u1,0,5.3,stone)
    for j in range(3):
        u=6.0+j*4.0
        box(glazing,-35.38,-u,2.50,.055,3.43,4.75,glass)
        for du in [-1.78,1.78]:box(trim,-35.88,-u-du,2.66,.20,.38,5.34,sill)
        for z in [.14,5.15]:box(trim,-35.88,-u,z,.20,3.98,.28,sill)
        for k in range(1,7):box(trim,-35.45,-u-1.72+k*.49,2.50,.10,.046,4.75,frame)
        for z in [.92,1.72,2.52,3.32,4.12]:box(trim,-35.48,-u,z,.10,3.42,.065,frame)
    # Very fine limestone coursing, without a procedural texture replacing
    # architectural joints. The lower window opening remains clear.
    for k in range(1,24):
        z=k*.92
        if z<5.3:
            for ua,ub in [(u0,4.0),(16.0,u1)]:box(trim,-35.80,-(ua+ub)/2,z,.014,ub-ua,.015,joint)
        else:box(trim,-35.80,-(u0+u1)/2,z,.014,u1-u0,.015,joint)
    for u in [-9.4+i*4.15 for i in range(10)]:
        zlo=5.45 if 4<u<16 else .16
        box(trim,-35.795,-u,(zlo+21.8)/2,.012,.012,21.8-zlo,joint)

    # Main roof has the blue metal surface visible beside the new hall. The
    # low ridge is screened by its higher west-facing stone wall.
    for ya,yb,za,zb in [(-30.0,-8.7,21.65,22.13),(-8.7,12.3,22.13,21.65)]:
        face(body,[(-35.20,ya,za),(32.90,ya,za),(32.90,yb,zb),(-35.20,yb,zb)],roof)
        for x in [-34.7+i*.86 for i in range(79)]:
            trim.pipe(p(x,ya,za+.027),p(x,yb,zb+.027),.015,roof_edge,6)
    for y in [-30.0,12.4]:box(trim,-1.1,y,21.85,68.4,.25,.48,sill)

    # North long elevation is clearly visible at the far left of the new
    # gym's completion panorama: large high windows beneath the blue roof.
    for j in range(9):
        x=-31.0+j*7.35
        box(glazing,x,12.54,15.45,5.72,.075,7.0,glass)
        for dx in [-2.86,2.86]:box(trim,x+dx,12.61,15.45,.12,.10,7.1,frame)
        for k in range(1,5):box(trim,x-2.86+k*1.144,12.63,15.45,.070,.11,6.98,frame)
        for z in [11.96,13.70,15.45,17.20,18.94]:box(trim,x,12.64,z,5.72,.11,.08,frame)
        if j in [1,4,7]:
            box(glazing,x,12.58,2.24,3.0,.065,4.1,glass)
            for dx in [-1.5,0,1.5]:box(trim,x+dx,12.64,2.24,.075,.08,4.15,frame)

    # The narrow northern wing has a slanted leading edge in the OSM outline.
    # Reconstruct its strong white portal and recessed ochre glass/stone panel.
    aux=[(-32.70,21.07),(20.06,22.01),(32.10,23.56),(31.86,35.27),(-25.29,34.21)]
    for i in range(4):
        q,r=aux[i],aux[i+1]
        face(body,[(*q,0),(*r,0),(*r,14.6),(*q,14.6)],stone)
    face(body,[(*q,14.6) for q in aux],m['roof'])
    q,r=aux[4],aux[0];tx,ty=r[0]-q[0],r[1]-q[1];length=math.hypot(tx,ty)
    tx/=length;ty/=length;nx,ny=ty,-tx
    # This edge runs clockwise around the visible corner; outward is its
    # right normal. Its glass is 0.55m behind the outer stone frame.
    def ap(t,d,z):return p(q[0]+tx*t+nx*d,q[1]+ty*t+ny*d,z)
    def aperture_rect(ta,tb,za,zb,d,ma):
        trim.face([ap(ta,d,za),ap(tb,d,za),ap(tb,d,zb),ap(ta,d,zb)],ma)
    open_a=length*.45;open_b=length*.79
    for ta,tb,za,zb in [(0,open_a,0,14.6),(open_b,length,0,14.6),(open_a,open_b,12.95,14.6),(open_a,open_b,0,.38)]:
        aperture_rect(ta,tb,za,zb,0,stone)
    aperture_rect(open_a,open_b,.38,12.95,-.65,shade)
    aperture_rect(open_a+.15,open_b-.66,.45,11.35,-.61,orange)
    aperture_rect(open_a+.15,open_b-.66,11.35,12.78,-.59,glass)
    aperture_rect(open_b-.61,open_b-.12,.45,12.78,-.56,glass)
    for t in [open_a,open_b]:
        trim.face([ap(t,0,.38),ap(t,-.65,.38),ap(t,-.65,12.95),ap(t,0,12.95)],sill)
    for z in [.38,12.95]:
        trim.face([ap(open_a,0,z),ap(open_b,0,z),ap(open_b,-.65,z),ap(open_a,-.65,z)],sill)
    for z in [2.2,4.25,6.3,8.35,10.4]:
        trim.pipe(ap(open_a+.15,-.59,z),ap(open_b-.65,-.59,z),.022,joint,6)

    # A recessed, two-level glazed link closes the back of the U-shaped gap;
    # keeping this at x=20 preserves the open map notch rather than filling it.
    box(body,26.0,17.45,3.78,12.0,10.40,7.56,m['dark'])
    box(glazing,19.94,17.45,3.66,.09,10.12,7.1,glass)
    for y in [12.5+i*.71 for i in range(15)]:box(trim,19.82,y,3.7,.10,.055,7.0,frame)
    for z in [.24,1.38,2.52,3.66,4.8,5.94,7.1]:box(trim,19.81,17.45,z,.12,10.2,.06,frame)
    box(trim,19.80,17.45,3.60,.32,10.55,.43,stone)
    # Small service/stair tower is visible above the connector in the front
    # photograph; placement and openings away from that view are inferred.
    box(body,16.0,26.7,15.45,8.2,8.3,1.7,stone)
    for z in [8.4,10.5,12.6,14.7]:
        for yy in [25.5,25.9]:
            for zz in [z-.16,z+.16]:box(glazing,11.85,yy,zz,.08,.25,.25,glass)

    # Faithful five coloured circular outlines fixed onto the plain limestone
    # plane. Geometry lies in the facade plane, with thin physical depth.
    logo_colors=[('blue',(.012,.06,.21)),('black',(.006,.012,.012)),('red',(.64,.008,.01)),
                 ('yellow',(.92,.51,.005)),('green',(.002,.21,.095))]
    logo_centers=[(5.26,14.80),(9.77,14.80),(14.28,14.80),(7.52,12.91),(12.03,12.91)]
    for (name,color),(u,z) in zip(logo_colors,logo_centers):
        ma=material('Old gym | five-ring emblem '+name,color,.37,.15)
        radius=1.91
        for i in range(80):
            t0=math.tau*i/80;t1=math.tau*(i+1)/80
            rings.pipe(p(-35.92,-u-radius*math.cos(t0),z+radius*math.sin(t0)),
                       p(-35.92,-u-radius*math.cos(t1),z+radius*math.sin(t1)),.165,ma,8)

    # Actual source-photo characters, baked as curve outlines, not generic text.
    source=Path(__file__).resolve().parents[2]/'projects/blender/identity/njupt_old_gym_name.json'
    sign=json.loads(source.read_text(encoding='utf-8'))
    for glyph,u in zip(sign['glyphs'],[-7.40,-2.92,1.10]):
        coords=[q for poly in glyph['polygons'] for q in poly['outer']]
        xmid=(min(q[0] for q in coords)+max(q[0] for q in coords))/2
        ymin=min(q[1] for q in coords)
        curve=bpy.data.curves.new('Old gym photographed '+glyph['character'],'CURVE')
        curve.dimensions='2D';curve.fill_mode='BOTH';curve.extrude=.035;curve.bevel_depth=.005
        for polygon in glyph['polygons']:
            for ring in [polygon['outer']]+polygon['holes']:
                spline=curve.splines.new('POLY');spline.points.add(len(ring)-1)
                for point,(x,y) in zip(spline.points,ring):point.co=((x-xmid)*.082,(y-ymin)*.082,0,1)
                spline.use_cyclic_u=True
        curve.materials.append(blue)
        obj=bpy.data.objects.new('Old gym | photographed '+glyph['character'],curve);col.objects.link(obj)
        obj.location=p(-35.95,-u,16.99)
        obj.rotation_euler=(math.pi/2,0,a-math.pi/2)
        obj['source_reference']=sign['source'];obj['unverified']='source photo perspective, letter thickness'

    body.object('Old gym | large hall and lower offset wing',col,bevel=.022)
    trim.object('Old gym | stone portals joints and standing seams',col)
    glazing.object('Old gym | actual large window groups and recessed link',col)
    rings.object('Old gym | coloured five-ring facade emblem',col)
    stat.update(height=22.13,levels=2,window_count=12,objects=len(col.objects),
                references=['observations/images/njupt/construction_home_image_04.jpg',
                            'observations/images/njupt/construction_home_image_00.jpg',
                            'observations/images/njupt/construction_article_241104_image_01.jpg'],
                observed_features=['five-ring blank limestone face','three low grouped windows','ochre recessed portal',
                                   'blue roof','north large upper window groups','recessed glass link','distinct narrow northern wing'],
                inferred_features=['22m height from photograph width-to-height ratio','roof ridge height and seam pitch',
                                   'unseen rear openings','complete stair tower dimensions','link exact depth and height'],
                orientation='main five-ring facade local -X rotated +29.8deg from world X',
                visual_validation='pending scene render; photograph reconstruction is not measured survey')
    return col,stat
