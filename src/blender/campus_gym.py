"""New sports hall: northwest elevation constrained by official completion photo.

u follows the photo left-to-right, so u = -local X; v = local Y.
The photograph shows an open mechanical court, folded stone fascia, seven
inclined main-hall recesses and four smaller recesses in the auxiliary volume.
Dimensions and unseen southern facade remain inferred, not survey measurements.
"""
import math
import random
from campus_geometry import Batch, material, text_object


def gym(b,parent,m,font):
    from campus_landmarks import new_asset
    col,stat=new_asset(b,parent,'new_gym')
    body=Batch();skin=Batch();glass=Batch();metal=Batch();site=Batch()
    ang=math.radians(29.8);ca,sa=math.cos(ang),math.sin(ang)
    def p(u,v,z):return (-u*ca-v*sa,-u*sa+v*ca,z)
    def box(batch,u,v,z,w,d,h,ma):batch.box(p(u,v,z),(w,d,h),ma,ang)
    def face(batch,points,ma):batch.face([p(*q) for q in points],ma)
    limestone=[material('Gym limestone panel '+str(i),c,.70,noise=.014) for i,c in enumerate([
        (.65,.61,.48),(.68,.64,.51),(.71,.68,.55),(.63,.59,.46),(.73,.70,.59),(.67,.65,.54)])]
    stone=limestone[1]
    slate=material('Gym dark inset ribbon',(.035,.043,.043),.29,.33)
    glazing=[material('Gym glazing '+str(i),c,.18,.46) for i,c in enumerate([(.060,.107,.117),(.072,.126,.132),(.045,.080,.091)])]
    aluminium=material('Gym glazing mullions',(.30,.34,.34),.34,.72)
    blue=material('Gym blue name',(.008,.074,.19),.30,.50)
    roof=material('Gym zinc roof',(.39,.46,.50),.5,.57,noise=.015)
    # The solid envelopes stop behind glazing; windows are actual recesses.
    box(body,25.5,0,10.3,60,70,20.6,stone)
    box(body,-43.9,0,9.4,23.2,70,18.8,stone)
    # Roofs: two low slopes around their own centre ridges, open court retained.
    for u0,u1,h in [(-55.5,-32.3,19.0),(-4.5,55.5,20.6)]:
        for va,vb,za,zb in [(-37,0,h,h+.45),(0,36,h+.45,h)]:
            face(skin,[(u0,va,za),(u1,va,za),(u1,vb,zb),(u0,vb,zb)],roof)
        for u in [u0+.8+i*.85 for i in range(int((u1-u0-1)/.85))]:
            metal.pipe(p(u,-37,h+.035),p(u,0,h+.485),.018,aluminium,6)
            metal.pipe(p(u,0,h+.485),p(u,36,h+.035),.018,aluminium,6)
        for u in [u0,u1]:box(skin,u,-.5,h+.25,.28,75,.52,stone)
        box(skin,(u0+u1)/2,-37.3,h+.25,u1-u0,.28,.52,stone)
    facade_start=[(batch,len(batch.vertices),len(batch.faces)) for batch in [skin,glass,metal,site]]
    # Photo-reconstructed north facade panel grid. Exclude the reveal cells.
    # z=9.1..20.8, u=0..55.7. Recesses lower and narrower inside a sloping well.
    recesses=[(5.0+i*7.0,9.95,18.0) for i in range(7)]
    rng=random.Random(20260930)
    def tile_rect(u0,u1,z0,z1,v=39.1):
        if u1-u0<.005 or z1-z0<.005:return
        nz=max(1,math.ceil((z1-z0)/.62));nu=max(1,math.ceil((u1-u0)/1.9))
        for row in range(nz):
            za=z0+(z1-z0)*row/nz;zb=z0+(z1-z0)*(row+1)/nz
            for j in range(nu):
                a=u0+(u1-u0)*j/nu;bb=u0+(u1-u0)*(j+1)/nu
                face(skin,[(a,v,za),(bb,v,za),(bb,v,zb),(a,v,zb)],limestone[rng.randrange(len(limestone))])
    tile_rect(-1.7,55.7,9.0,9.95);tile_rect(-1.7,55.7,18.,20.85)
    # Individual bay panels around an inclined parallelogram opening.
    for i,(c,z0,z1) in enumerate(recesses):
        lo=-1.7 if i==0 else c-3.5;hi=55.7 if i==6 else c+3.5
        outer=[(c-2.85,z0),(c+2.85,z0),(c+4.75,z1),(c-.95,z1)]
        lotop=lo if i==0 else lo+1.9;hitop=hi if i==6 else hi+1.9
        face(skin,[(lo,39.1,z0),(outer[0][0],39.1,z0),(outer[3][0],39.1,z1),(lotop,39.1,z1)],stone)
        face(skin,[(outer[1][0],39.1,z0),(hi,39.1,z0),(hitop,39.1,z1),(outer[2][0],39.1,z1)],limestone[2])
        inner=[(c-.60,10.55),(c+.67,10.55),(c+1.26,13.25),(c-.01,13.25)]
        for j in range(4):
            k=(j+1)%4
            face(skin,[(outer[j][0],39.1,outer[j][1]),(outer[k][0],39.1,outer[k][1]),(inner[k][0],36.62,inner[k][1]),(inner[j][0],36.62,inner[j][1])],limestone[2 if j%2 else 0])
        face(glass,[(u,36.65,z) for u,z in inner],glazing[0])
        for j in range(4):metal.pipe(p(inner[j][0],36.72,inner[j][1]),p(inner[(j+1)%4][0],36.72,inner[(j+1)%4][1]),.038,aluminium,8)
    # Full-length ribbon glazing below the projecting limestone screen.
    def ribbon(u0,u1,z0,z1,v):
        count=max(1,round((u1-u0)/1.6))
        for j in range(count):
            a=u0+(u1-u0)*j/count;bb=u0+(u1-u0)*(j+1)/count
            box(glass,(a+bb)/2,v,(z0+z1)/2,bb-a-.06,.10,z1-z0,glazing[j%3])
            box(metal,a,v+.07,(z0+z1)/2,.055,.13,z1-z0,aluminium)
        for z in [z0,(z0+z1)/2,z1]:box(metal,(u0+u1)/2,v+.07,z,u1-u0,.13,.065,aluminium)
    ribbon(-1,55,5.8,9.0,37.5)
    ribbon(-52,-19,9.0,12.2,37.4)
    ribbon(-3,53,1.3,2.45,36.9)
    # The wide band descends diagonally across the central entrance.
    profile=[(-55.7,16.9),(-6.6,16.9),(-1.0,4.35),(56.8,4.35)]
    lower=[(-55.7,13.0),(-10.4,13.0),(-4.8,.35),(56.8,2.40)]
    for i in range(3):
        a,bb=profile[i],profile[i+1];c,d=lower[i],lower[i+1]
        face(skin,[(a[0],39.3,a[1]),(bb[0],39.3,bb[1]),(d[0],39.3,d[1]),(c[0],39.3,c[1])],stone)
        metal.pipe(p(a[0],39.36,a[1]),p(bb[0],39.36,bb[1]),.10,slate,8)
    tile_rect(-55.7,-7.0,17.35,20.2)
    # Glazed diagonal continuation, visible between the folded solid volumes.
    face(glass,[(-6.8,38.5,20.6),(-3.7,38.5,20.6),(1.0,38.5,7.0),(-1.3,38.5,7.0)],glazing[0])
    for t in [.25,.5,.75]:metal.pipe(p(-6.8+3.1*t,38.65,20.6),p(-1.3+2.3*t,38.65,7),.035,aluminium,6)
    # Four deeply recessed windows in the low leaning auxiliary hall facade.
    for i in range(4):
        c=-49+i*6.4;u0=c-3.2;u1=c+3.2
        outer=[(c-2.2,2.0),(c+2.35,2.0),(c+2.35,6.7),(c-2.2,6.7)]
        inner=[(c+.05,3.35),(c+1.33,3.35),(c+1.53,4.98),(c+.25,4.98)]
        def wallpoint(u,z):return(u,43-(z-.55)/6.9*3,z)
        for a,bb,za,zb in [(u0,u1,.55,2.0),(u0,u1,6.7,7.45),(u0,c-2.2,2.0,6.7),(c+2.35,u1,2.0,6.7)]:
            face(skin,[wallpoint(a,za),wallpoint(bb,za),wallpoint(bb,zb),wallpoint(a,zb)],stone)
        for j in range(4):
            k=(j+1)%4
            face(skin,[wallpoint(*outer[j]),wallpoint(*outer[k]),(inner[k][0],40.0,inner[k][1]),(inner[j][0],40.0,inner[j][1])],limestone[j%3])
        face(glass,[(u,40.04,z) for u,z in inner],glazing[0])
    # Central outdoor access stairs and landing, visible in the source photo.
    for i in range(31):box(site,-14.2,47-i*.42,(i+1)*.078,5.8,.425,(i+1)*.156,m['step'])
    box(site,-14.2,30.5,2.4,7.0,7.2,4.8,m['step'])
    box(glass,-14.2,27.1,6.35,6.5,.12,3.1,glazing[0])
    for u in [-17.2,-11.2]:
        metal.pipe(p(u,47,1),p(u,34.4,5.7),.045,aluminium)
        for i in range(0,31,3):metal.pipe(p(u,47-i*.42,i*.156),p(u,47-i*.42,i*.156+1),.027,aluminium)
    # The completed south-facing photo confirms the same major recess pattern.
    # Reflect geometric facade parts only (not roofs), preserving triangle winding.
    for batch,vstart,fstart in facade_start:
        offset=len(batch.vertices)
        for x,y,z in list(batch.vertices[vstart:]):
            u=-x*ca-y*sa;v=-x*sa+y*ca
            batch.vertices.append(p(u,-v,z))
        original=list(zip(batch.faces[fstart:],batch.material_ids[fstart:]))
        for f,mi in original:
            batch.faces.append(tuple(offset+i-vstart for i in reversed(f)))
            batch.material_ids.append(mi)
    # Mechanical court is inset between both halls. Equipment count inferred
    # from visible rooftop silhouettes; positions and plumbing are provisional.
    box(body,-18.4,0,.12,27.8,36,.24,m['step'])
    for v in [-24,24]:box(body,-18.4,v,12.0,27.8,11,.3,m['roof'])
    for u in [-31.9,-4.8]:
        box(body,u,0,10.0,.35,36,20.0,stone)
        for v in range(-16,18,3):
            for z in [3.1,7.2,11.3,15.4]:box(glass,u+(.21 if u< -10 else -.21),v,z,.06,2.55,2.45,glazing[1])
    for i in range(5):
        box(metal,-25+i*4.2,-23,14.0,2.6,3,2.3,m['roofmetal'])
        metal.cylinder(p(-25+i*4.2,-23,15.22),.74,.15,slate,20)
    for i in range(4):
        box(metal,-24+i*4.7,16,13.0,3.6,2.3,1.5,m['roofmetal'])
        metal.pipe(p(-24+i*4.7,15,14),p(-24+i*4.7,-21,14),.10,aluminium)
    # End-wall fenestration is still a restrained inferred continuation.
    for u in [-55.7,55.7]:
        for v in range(-32,34,4):
            box(glass,u,v,4.0,.12,3.6,2.0,glazing[1])
            box(metal,u,v,4,.17,.055,2.05,aluminium)
    if font:
        import bpy
        from pathlib import Path
        boldpath=Path('C:/Windows/Fonts/msyhbd.ttc')
        bold=bpy.data.fonts.load(str(boldpath)) if boldpath.exists() else font
        for label,u,v,rot in [('north',50,39.45,ang+math.pi),('south',-46,-39.45,ang)]:
            ob=text_object('Gym • '+label+' upper facade name','体 育 馆',p(u,v,18.05),1.9,blue,col,(math.pi/2,0,rot),bold)
            if ob.type=='MESH':
                for vertex in ob.data.vertices:vertex.co.x+=.20*vertex.co.y
            ob['lettering_status']='Approximate bold slanted blue lettering; not traced official artwork'
    body.object('Gym • unequal halls and open mechanical courtyard',col)
    skin.object('Gym • folded limestone and recessed window reveals',col,bevel=.018)
    glass.object('Gym • glazing inside physical openings',col)
    metal.object('Gym • roof seams frames and equipment',col)
    site.object('Gym • entry stair and terrace',col)
    stat.update(height=21.3,levels=4,objects=len(col.objects),window_count=22,references=['observations/images/njupt/construction_home_image_00.jpg','observations/images/njupt/construction_article_267603_image_00_original.jpg','observations/images/njupt/construction_article_241104_image_01.jpg'],confirmed=['Northwest facing front (local +Y), major hall at local -X','Seven inclined main openings and four auxiliary openings on each principal elevation','Continuous glazing, diagonal dark reveal and folded stone fascia','Open rooftop mechanical courtyard and two equipment platforms'],inferred=['Metric elevations and stone sizes','End-wall and courtyard opening spacing','Equipment dimensions and pipe layout'])
    return col,stat
