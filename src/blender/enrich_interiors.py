"""Author editable interiors from registered plans and explicit reconstruction.

``enrich(building, collection)`` adds native, floor-separated geometry without
changing an existing envelope. ``show_interior`` provides a real inspection
mode: the opaque exterior is hidden, rather than claiming that furniture can
be seen through a closed mesh. Restricted photographs are never loaded here.
"""
from pathlib import Path
import json
import math

import bpy
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

from campus_geometry import Batch, material, point_inside, signed_area
from campus_buildings import classify

ROOT = Path(__file__).resolve().parents[2]
INTERIOR_MARKER = 'njupt_editable_interiors'
_DESIGN = None
_BINDINGS = None


def _sources():
    global _DESIGN, _BINDINGS
    if _DESIGN is None:
        _DESIGN = json.loads((ROOT/'projects/blender/design/interiors.json').read_text(encoding='utf8'))
        _BINDINGS = {x['asset_id']: x for x in json.loads((ROOT/'observations/bindings/assets.json').read_text(encoding='utf8'))['bindings']}
    return _DESIGN, _BINDINGS


def _palette():
    definitions = {
        'floor': ((.46,.48,.47), .28, 0),
        'floor_warm': ((.66,.59,.45), .38, 0),
        'wall': ((.81,.81,.76), .77, 0),
        'ceiling': ((.87,.88,.84), .85, 0),
        'oak': ((.46,.28,.13), .46, 0),
        'wood_light': ((.71,.56,.35), .48, 0),
        'metal': ((.32,.36,.39), .26, .82),
        'white': ((.88,.89,.86), .37, 0),
        'charcoal': ((.08,.10,.12), .65, 0),
        'blue': ((.20,.37,.60), .72, 0),
        'green': ((.47,.65,.14), .74, 0),
        'deepgreen': ((.025,.19,.12), .28, 0),
        'fabric': ((.22,.32,.39), .86, 0),
        'mattress': ((.70,.77,.79), .92, 0),
        'leaf': ((.055,.23,.08), .71, 0),
        'book_red': ((.44,.08,.055), .74, 0),
        'book_blue': ((.08,.19,.37), .70, 0),
    }
    m = {key: material('Interior · '+key, (*rgb,1), roughness=rough, metallic=metal)
         for key,(rgb,rough,metal) in definitions.items()}
    m['lamp'] = material('Interior · warm task light', (1,.78,.46,1), roughness=.3, emission=3.0)
    m['panel'] = material('Interior · ceiling light', (.89,.95,1,1), roughness=.28, emission=50.0)
    m['glass'] = material('Interior · clear glazing', (.82,.9,.94,1), roughness=.04)
    bsdf=next(n for n in m['glass'].node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    bsdf.inputs['Transmission Weight'].default_value=.95
    bsdf.inputs['IOR'].default_value=1.45
    for key in ('oak','wood_light','floor_warm'):
        mat=m[key];nodes=mat.node_tree.nodes
        if nodes.get('Authored interior grain'):continue
        tex=nodes.new('ShaderNodeTexNoise');tex.name='Authored interior grain'
        tex.inputs['Scale'].default_value=45 if key=='floor_warm' else 16
        tex.inputs['Detail'].default_value=2
        geo=nodes.new('ShaderNodeNewGeometry')
        scale=nodes.new('ShaderNodeVectorMath');scale.operation='MULTIPLY'
        scale.inputs[1].default_value=(.20,8.,1.) if key!='floor_warm' else (1.,1.,1.)
        bump=nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.001
        bsdf=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
        links=mat.node_tree.links
        links.new(geo.outputs['Position'],scale.inputs[0]);links.new(scale.outputs['Vector'],tex.inputs['Vector'])
        links.new(tex.outputs['Fac'],bump.inputs['Height']);links.new(bump.outputs['Normal'],bsdf.inputs['Normal'])
    return m


class Frame:
    """A local authoring frame computed from the authoritative current outline."""
    def __init__(self, polygon):
        edge=max(zip(polygon,polygon[1:]+polygon[:1]), key=lambda e: math.dist(*e))
        dx,dy=edge[1][0]-edge[0][0],edge[1][1]-edge[0][1]
        self.angle=math.atan2(dy,dx)
        # Stable orientation is convenient for cameras and furniture editing.
        if self.angle < -math.pi/2: self.angle+=math.pi
        if self.angle >= math.pi/2: self.angle-=math.pi
        self.c,self.s=math.cos(self.angle),math.sin(self.angle)
        projected=[self.inverse(p) for p in polygon]
        self.umin=min(p[0] for p in projected);self.umax=max(p[0] for p in projected)
        self.vmin=min(p[1] for p in projected);self.vmax=max(p[1] for p in projected)
        self.uc=(self.umin+self.umax)/2;self.vc=(self.vmin+self.vmax)/2
        self.length=self.umax-self.umin;self.width=self.vmax-self.vmin

    def inverse(self,p):
        return (p[0]*self.c+p[1]*self.s, -p[0]*self.s+p[1]*self.c)

    def point(self,u,v,z=0):
        return (u*self.c-v*self.s,u*self.s+v*self.c,z)

    def box(self,batch,u,v,z,a,b,h,mat):
        batch.box(self.point(u,v,z),(a,b,h),mat,self.angle)

    def rectangle(self,u,v,a,b):
        return [self.point(u+du,v+dv)[:2] for du,dv in [(-a/2,-b/2),(a/2,-b/2),(a/2,b/2),(-a/2,b/2)]]


def _inside_rect(frame,u,v,a,b,outer,holes,margin=.10):
    rectangle=frame.rectangle(u,v,a+margin*2,b+margin*2)
    if not all(point_inside(p,outer,holes) for p in rectangle):return False
    # A small void may fall entirely between the four corners. Check actual
    # overlap, rather than allowing a table to bridge an atrium or stair hole.
    return not any(abs(signed_area(_clip_convex(hole,rectangle)))>1e-6 for hole in holes)


def _triangles(ring):
    vv=[Vector((x,y,0)) for x,y in ring]
    return [[(vv[i].x,vv[i].y) for i in tri] for tri in tessellate_polygon([vv])]


def _clip_convex(subject, clip):
    """Clip a room polygon to one footprint triangle; no optional GIS runtime."""
    if signed_area(clip)<0: clip=list(reversed(clip))
    out=subject
    for a,b in zip(clip,clip[1:]+clip[:1]):
        incoming=out;out=[]
        if not incoming:break
        def cross(p):return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])
        def intersection(p,q):
            cp,cq=cross(p),cross(q);den=cp-cq
            t=cp/den if abs(den)>1e-12 else 0
            return (p[0]+t*(q[0]-p[0]),p[1]+t*(q[1]-p[1]))
        previous=incoming[-1];prior_in=cross(previous)>=-1e-8
        for current in incoming:
            current_in=cross(current)>=-1e-8
            if current_in != prior_in:out.append(intersection(previous,current))
            if current_in:out.append(current)
            previous=current;prior_in=current_in
    return out


def _room_face(batch,ring,z,mat,triangles):
    # Footprint triangles already exclude courtyards and light wells. Registering
    # a photograph does not allow a room plate to fill a real open courtyard.
    for triangle in triangles:
        clipped=_clip_convex(ring,triangle)
        if len(clipped)>=3 and abs(signed_area(clipped))>1e-5:
            batch.face([(x,y,z) for x,y in clipped],mat)


def _half_plane(polygon,a,b,inside=True):
    if not polygon:return []
    def distance(p):
        value=(b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])
        return value if inside else -value
    result=[];previous=polygon[-1];d0=distance(previous)
    for current in polygon:
        d1=distance(current)
        if (d0>=-1e-8)!=(d1>=-1e-8):
            t=d0/(d0-d1)
            result.append((previous[0]+t*(current[0]-previous[0]),previous[1]+t*(current[1]-previous[1])))
        if d1>=-1e-8:result.append(current)
        previous,d0=current,d1
    return result


def _without_openings(triangles,openings):
    pieces=list(triangles)
    for opening in openings:
        clip=opening if signed_area(opening)>0 else list(reversed(opening))
        next_pieces=[]
        for subject in pieces:
            remaining=subject
            for a,b in zip(clip,clip[1:]+clip[:1]):
                outside=_half_plane(remaining,a,b,False)
                if len(outside)>=3 and abs(signed_area(outside))>1e-5:next_pieces.append(outside)
                remaining=_half_plane(remaining,a,b,True)
                if not remaining:break
        pieces=next_pieces
    return pieces


def _library_plan(frame,floor):
    design,_=_sources()
    spec=next((p for p in design['special_designs']['osm_way_223859810'].get('official_floorplans',[]) if p['floor']==floor),None)
    if spec is None:return None
    def point(p):
        # Diagram bottom is the western entrance. Frame v may point west or
        # east depending on the current outline's longest edge.
        v=(frame.vmin+p[1]*frame.width) if frame.s>0 else (frame.vmax-p[1]*frame.width)
        return frame.point(frame.umin+p[0]*frame.length,v)[:2]
    return {'source_id':spec['source_id'],
            'rooms':[{**room,'polygon_local_m':[point(p) for p in room['polygon_layout_normalized']]} for room in spec['rooms']],
            'voids':[[point(p) for p in void['polygon_layout_normalized']] for void in spec.get('voids',[])],
            'stairs':[frame.inverse(point(p)) for p in spec.get('stairs_layout_normalized',[])],
            'elevators':[frame.inverse(point(p)) for p in spec.get('elevators_layout_normalized',[])]}


def _official_library_rooms(plan,z,fh,outer,holes,tris,batches,m,floor):
    records=[];count=0
    for index,spec in enumerate(plan['rooms']):
        ring=spec['polygon_local_m'];frame=Frame(ring)
        record={'room_id':f'library-{floor:02}-{index:02}','label':spec['label'],
                'source_id':plan['source_id'],'polygon_local_m':ring,
                'registration_status':'inferred_metric_registration_of_official_diagram','role':spec['role']}
        role=spec['role']
        room_kind='service' if role in ('service','reception','auditorium','stacks') else ('reading' if role in ('reading','study') else role)
        count+=_add_room(record,ring,z,fh,outer,holes,tris,batches,m,room_kind)
        if role in ('reading','stacks'):
            for i in range(max(1,int((frame.length-3)/4.8))):
                u=frame.umin+2.4+i*4.8;v=frame.vmax-.55
                if _inside_rect(frame,u,v,3.5,.8,ring,(),0) and _inside_rect(frame,u,v,3.5,.8,outer,holes,0):
                    _bookcase(batches['furniture'],frame,u,v,z,m,3.4);count+=1
        elif role=='reception':
            if _inside_rect(frame,frame.uc,frame.vc,min(6.,frame.length-.8),.9,outer,holes):
                frame.box(batches['furniture'],frame.uc,frame.vc,z+.55,min(6.,frame.length-.8),.8,1.1,m['white']);count+=1
        elif role=='auditorium':
            for i in range(max(1,int((frame.length-3)/1.1))):
                for j in range(max(1,int((frame.width-3)/.8))):
                    u=frame.umin+1.5+i*1.1;v=frame.vmin+1.5+j*.8
                    if _inside_rect(frame,u,v,.6,.65,outer,holes):_chair(batches['furniture'],frame,u,v,z,m,seat='blue');count+=1
        records.append(record)
    return count,records


def _register(ring,registration):
    width=registration['image_full_width_m']
    iw,ih=registration['image_dimensions_px']
    sx,sy=registration['local_xy_scale']
    a=math.radians(registration['rotation_z_degrees']);c,s=math.cos(a),math.sin(a)
    lx,ly,_=registration['local_location']
    result=[]
    for u,v in ring:
        x=(u-.5)*width*sx;y=(.5-v)*width*(ih/iw)*sy
        result.append((lx+c*x-s*y,ly+s*x+c*y))
    if len(result)>1 and math.dist(result[0],result[-1])<1e-8:result.pop()
    return result


def _chair(batch,frame,u,v,z,m,angle=0,seat='fabric'):
    a=frame.angle+angle;c,s=math.cos(a),math.sin(a)
    x,y,_=frame.point(u,v)
    def box(dx,dy,dz,w,d,h,mat):
        batch.box((x+c*dx-s*dy,y+s*dx+c*dy,z+dz),(w,d,h),mat,a)
    box(0,0,.45,.43,.45,.065,m[seat])
    box(0,.205,.73,.43,.055,.47,m[seat])
    for dx in (-.17,.17):
        for dy in (-.17,.17):box(dx,dy,.21,.031,.031,.42,m['metal'])


def _desk(batch,frame,u,v,z,m,width=1.15,depth=.64,cubicle=False):
    frame.box(batch,u,v,z+.755,width,depth,.065,m['white'] if cubicle else m['wood_light'])
    for du in (-width*.41,width*.41):
        for dv in (-depth*.38,depth*.38):frame.box(batch,u+du,v+dv,z+.365,.035,.035,.73,m['metal'])
    if cubicle:
        frame.box(batch,u,v+depth*.47,z+1.05,width,.035,.52,m['white'])
        frame.box(batch,u-width*.48,v,z+1.05,.035,depth,.52,m['white'])
        frame.box(batch,u,v+depth*.39,z+1.255,width*.82,.024,.025,m['lamp'])
    _chair(batch,frame,u,v-.62,z,m,angle=math.pi)
    # Authored tabletop detail remains editable mesh geometry, with no copied
    # photographs or commercial product textures.
    frame.box(batch,u-width*.18,v-.06,z+.804,.24,.30,.012,m['book_blue'])
    frame.box(batch,u-width*.18,v-.065,z+.813,.22,.27,.005,m['white'])
    frame.box(batch,u+width*.20,v+.10,z+.81,.29,.21,.012,m['charcoal'])
    frame.box(batch,u+width*.20,v+.19,z+.93,.29,.035,.23,m['metal'])
    frame.box(batch,u+width*.20,v+.168,z+.93,.26,.006,.20,m['blue'])


def _table(batch,frame,u,v,z,m):
    frame.box(batch,u,v,z+.78,1.55,.82,.075,m['wood_light'])
    for du in (-.52,.52):
        frame.box(batch,u+du,v,z+.38,.07,.56,.74,m['metal'])
        _chair(batch,frame,u+du,v-.66,z,m,angle=math.pi,seat='white')
        _chair(batch,frame,u+du,v+.66,z,m,seat='white')


def _bunk(batch,frame,u,v,z,m,inward=-1):
    frame.box(batch,u,v,z+1.75,2.03,.95,.075,m['metal'])
    frame.box(batch,u,v,z+1.83,1.95,.88,.10,m['mattress'])
    frame.box(batch,u-.71,v,z+1.90,.36,.65,.10,m['white'])
    for du in (-.95,.95):
        for dv in (-.43,.43):frame.box(batch,u+du,v+dv,z+1.13,.045,.045,2.26,m['metal'])
    frame.box(batch,u,v+inward*.45,z+2.03,1.95,.035,.09,m['metal'])
    frame.box(batch,u,v+inward*.45,z+2.22,1.95,.035,.045,m['metal'])
    for du in (-.95,-.32,.32,.95):frame.box(batch,u+du,v+inward*.45,z+2.12,.035,.035,.29,m['metal'])
    frame.box(batch,u+.28,v,z+.75,1.27,.58,.055,m['wood_light'])
    frame.box(batch,u-.75,v,z+.81,.40,.69,1.48,m['wood_light'])
    frame.box(batch,u-.74,v+inward*.365,z+.85,.29,.026,1.30,m['white'])
    for dz in (.31,.62,.93,1.24,1.55):frame.box(batch,u+.99,v+inward*.51,z+dz,.34,.025,.027,m['metal'])
    _chair(batch,frame,u+.22,v+inward*.57,z,m,angle=0 if inward>0 else math.pi)


def _bookcase(batch,frame,u,v,z,m,length=3.):
    frame.box(batch,u,v,z+1.24,length,.34,2.48,m['wood_light'])
    for level in range(5):
        zz=z+.15+level*.46
        frame.box(batch,u,v-.205,zz,length-.10,.45,.035,m['oak'])
        for i in range(max(4,int(length/.14))):
            frame.box(batch,u-length*.46+i*.14,v-.225,zz+.19,.065,.21,.33,m['book_red' if (i+level)%3 else 'book_blue'])


def _plant(batch,frame,u,v,z,m):
    x,y,_=frame.point(u,v)
    batch.cylinder((x,y,z+.19),.18,.38,m['white'],12,top_radius=.24)
    batch.cylinder((x,y,z+.42),.13,.075,m['charcoal'],10)
    for i in range(7):
        a=i*math.tau/7
        end=(x+.32*math.cos(a),y+.32*math.sin(a),z+.72+(i%2)*.15)
        batch.pipe((x,y,z+.38),end,.009,m['oak'],6)
        batch.box((end[0],end[1],end[2]+.025),(.24,.10,.055),m['leaf'],a)


def _stairs(batch,frame,u,v,z,fh,m):
    # Two opposed flights meet on a landing and reach the next floor exactly.
    steps=max(10,round(fh/.165));first=steps//2;rise=fh/steps;tread=.27
    startu=u-first*tread/2
    for i in range(first):
        frame.box(batch,startu+(i+.5)*tread,v-.68,z+(i+.5)*rise,tread,1.15,rise,m['floor'])
    midz=z+first*rise
    frame.box(batch,u+first*tread/2+.5,v,midz-.075,1.05,2.65,.15,m['floor'])
    for i in range(steps-first):
        frame.box(batch,u+first*tread/2-(i+.5)*tread,v+.68,midz+(i+.5)*rise,tread,1.15,rise,m['floor'])
    # The upper flight terminates inside the slab opening. Bridge from that
    # last riser to its outer edge; reaching the z datum alone is insufficient.
    landing=max(.25,2.7-first*tread/2)
    frame.box(batch,startu-landing/2,v,z+fh-.075,landing+.04,2.65,.15,m['floor'])
    for vv in (v-1.25,v+.04,v+1.25):
        a=frame.point(startu,vv,z+1.);b=frame.point(startu+first*tread,vv,midz+1.)
        batch.pipe(a,b,.022,m['metal'],8)
        for i in range(0,first+1,3):
            p=frame.point(startu+i*tread,vv,z+i*rise)
            batch.pipe(p,(p[0],p[1],p[2]+1),.017,m['metal'],8)


def _partition(batch,p,q,z,height,mat,door=False):
    length=math.dist(p,q)
    if length<.12:return
    if not door or length<1.7:
        batch.beam((*p,z+height/2),(*q,z+height/2),.12,height,mat);return
    ux,uy=(q[0]-p[0])/length,(q[1]-p[1])/length
    gap=min(1.15,length*.42);lo=(length-gap)/2;hi=(length+gap)/2
    a=(p[0]+ux*lo,p[1]+uy*lo);b=(p[0]+ux*hi,p[1]+uy*hi)
    batch.beam((*p,z+height/2),(*a,z+height/2),.12,height,mat)
    batch.beam((*b,z+height/2),(*q,z+height/2),.12,height,mat)
    if height>2.15:batch.beam((*a,z+(height+2.15)/2),(*b,z+(height+2.15)/2),.12,height-2.15,mat)


def _boundary_distance(point,outer,holes):
    def distance(p,a,b):
        dx,dy=b[0]-a[0],b[1]-a[1]
        t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/max(1e-12,dx*dx+dy*dy)))
        return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
    return min(distance(point,a,b) for r in [outer]+list(holes) for a,b in zip(r,r[1:]+r[:1]))


def _window_lining(p,q,z,fh,batches,m):
    length=math.dist(p,q)
    n=max(1,int(length/3.8));unit=length/n
    h=min(fh-.35,3.65);sill=min(.9,h*.27);top=min(2.5,h-.30)
    ux,uy=(q[0]-p[0])/max(length,1e-9),(q[1]-p[1])/max(length,1e-9)
    angle=math.atan2(uy,ux)
    for i in range(n):
        a=(p[0]+ux*i*unit,p[1]+uy*i*unit);b=(p[0]+ux*(i+1)*unit,p[1]+uy*(i+1)*unit)
        if unit<2.4 or h<2.5:_partition(batches['walls'],a,b,z,h,m['wall']);continue
        w=min(2.,unit-.75);cx=(a[0]+b[0])/2;cy=(a[1]+b[1])/2
        batches['walls'].beam((*a,z+sill/2),(*b,z+sill/2),.12,sill,m['wall'])
        batches['walls'].beam((*a,z+(top+h)/2),(*b,z+(top+h)/2),.12,h-top,m['wall'])
        wa=(cx-ux*w/2,cy-uy*w/2);wb=(cx+ux*w/2,cy+uy*w/2)
        _partition(batches['walls'],a,wa,z+sill,top-sill,m['wall'])
        _partition(batches['walls'],wb,b,z+sill,top-sill,m['wall'])
        batches['services'].box((cx,cy,z+(sill+top)/2),(w,.018,top-sill),m['glass'],angle)
        for f in (-.5,0,.5):batches['services'].box((cx+ux*w*f,cy+uy*w*f,z+(sill+top)/2),(.035,.06,top-sill),m['metal'],angle)
        for zz in (sill,top):batches['services'].box((cx,cy,z+zz),(w,.06,.035),m['metal'],angle)
        batches['services'].box((cx,cy,z+sill-.04),(w+.1,.28,.06),m['white'],angle)


def _add_room(room,ring,z,fh,outer,holes,tris,batches,m,kind='classroom',metadata=True):
    if len(ring)<3:return 0
    frame=Frame(ring);area=abs(signed_area(ring))
    if area<1:return 0
    _room_face(batches['floor'],ring,z+.015,m['floor_warm'] if kind=='dorm' else m['floor'],tris)
    _room_face(batches['ceiling'],ring,z+min(fh-.23,3.45),m['ceiling'],tris)
    # A courtyard-facing door is an explicit plausible design; door centres were
    # not measured from the evacuation photograph.
    target=min(holes,key=lambda h: min(math.dist(frame.point(frame.uc,frame.vc)[:2],p) for p in h)) if holes else [(0,0)]
    edges=list(zip(ring,ring[1:]+ring[:1]))
    door_i=min(range(len(edges)),key=lambda i: min(math.dist(((edges[i][0][0]+edges[i][1][0])/2,(edges[i][0][1]+edges[i][1][1])/2),p) for p in target))
    h=min(fh-.34,3.25)
    for i,(p,q) in enumerate(edges):
        # Short line segments are clipped to the common envelope, rather than
        # stretching the exterior to fit an approximate photograph alignment.
        for j in range(max(1,math.ceil(math.dist(p,q)/.40))):
            n=max(1,math.ceil(math.dist(p,q)/.40));t0=j/n;t1=(j+1)/n
            a=(p[0]+(q[0]-p[0])*t0,p[1]+(q[1]-p[1])*t0)
            b=(p[0]+(q[0]-p[0])*t1,p[1]+(q[1]-p[1])*t1)
            mid=((a[0]+b[0])/2,(a[1]+b[1])/2)
            if not point_inside(mid,outer,holes):continue
            if _boundary_distance(mid,outer,holes)<.65:continue
            edge_length=math.dist(p,q)
            if i==door_i and abs((j+.5)/n-.5)*edge_length<.60:
                if h>2.15:_partition(batches['walls'],a,b,z+2.15,h-2.15,m['wall'])
            else:_partition(batches['walls'],a,b,z,h,m['wall'])
    placed=0
    if kind=='dorm' and frame.length>3.8 and frame.width>2.5:
        for vv,inward in ((frame.vmin+.70,1),(frame.vmax-.70,-1)):
            if _inside_rect(frame,frame.uc,vv+inward*.15,2.4,1.5,ring,(),0) and _inside_rect(frame,frame.uc,vv+inward*.15,2.4,1.5,outer,holes,0):
                _bunk(batches['furniture'],frame,frame.uc,vv,z,m,inward);placed+=1
        frame.box(batches['services'],frame.uc,frame.vmax-.20,z+min(fh-.6,2.5),1.05,.25,.32,m['white'])
        for uu in (frame.uc-.85,frame.uc+.85):
            frame.box(batches['ceiling'],uu,frame.vc,z+min(fh-.26,3.42),1.20,.20,.03,m['panel'])
    elif area>=12 and kind not in ('service','stairs'):
        reading=kind=='reading'
        step_u,step_v=(2.8,3.2) if reading else (1.35,1.45)
        rows=min(32 if reading else 6,max(1,int((frame.length-2.5)/step_u)))
        columns=min(16 if reading else 5,max(1,int((frame.width-1.25)/step_v)))
        for row in range(rows):
            for col in range(columns):
                u=frame.umin+1.15+row*step_u;v=frame.vc+(col-(columns-1)/2)*step_v
                if _inside_rect(frame,u,v-.25,1.25,1.35,ring,(),0) and _inside_rect(frame,u,v-.25,1.25,1.35,outer,holes,0):
                    _desk(batches['furniture'],frame,u,v,z,m);placed+=1
        if kind=='classroom':frame.box(batches['services'],frame.umax-.10,frame.vc,z+1.57,.04,min(frame.width*.72,4.0),1.20,m['deepgreen'])
        # Ceiling services do not appear on the floor plan and are design.
        for uu in (frame.uc-1.5,frame.uc+1.5):
            if point_inside(frame.point(uu,frame.vc)[:2],outer,holes):frame.box(batches['ceiling'],uu,frame.vc,z+min(fh-.26,3.42),1.15,.16,.025,m['panel'])
    room['furniture_modules']=placed
    return placed


def _geometry(building,floor=1):
    cx,cy=building['center']
    volumes=building.get('upper_volumes',[])
    source=volumes[0] if volumes and floor>int(float(building.get('levels',5))) else building
    outer=[(x-cx,y-cy) for x,y in source['outer']]
    holes=[[(x-cx,y-cy) for x,y in r] for r in source.get('holes',[])]
    triangles=[[(x-cx,y-cy) for x,y in tri] for tri in source.get('roof_triangles',[])]
    if not triangles and not holes:triangles=_triangles(outer)
    return outer,holes,triangles


def _generic_rooms(frame,outer,holes,kind):
    rooms=[]
    # Room cells line the real solid wings. Courtyard gaps are never filled by
    # the bounding rectangle. A continuous clear band is reserved for movement.
    dorm=kind in ('dorm','staff_apartment')
    module=4.0 if dorm else 7.5
    depth=4.8 if dorm else 6.2
    for side in (-1,1):
        v=frame.vmin+depth/2+.35 if side<0 else frame.vmax-depth/2-.35
        start=frame.umin+.45+module/2
        for i in range(max(0,int((frame.length-.9)/module))):
            u=start+i*module
            if not _inside_rect(frame,u,v,module-.15,depth,outer,holes,.03):continue
            ring=frame.rectangle(u,v,module-.15,depth)
            rooms.append({'room_id':f'inferred-{side:+d}-{i:02d}','polygon_local_m':ring,'kind':'dorm' if dorm else 'classroom','status':'inferred_functional_layout'})
    # Deeper irregular wings can carry additional rooms on either side of the
    # courtyard. This supplements existing perimeter cells only when disjoint.
    if not rooms and frame.width>6:
        for i in range(max(1,int(frame.length/8.0))):
            u=frame.umin+4.+i*8.;v=frame.vc
            if _inside_rect(frame,u,v,7.4,min(6.,frame.width-1.0),outer,holes):
                rooms.append({'room_id':f'inferred-central-{i:02d}','polygon_local_m':frame.rectangle(u,v,7.4,min(6.,frame.width-1.0)),'kind':'classroom','status':'inferred_functional_layout'})
    return rooms


def _room_kind(label,area):
    if any(s in label for s in ('楼梯','电梯','stair','lift')):return 'stairs'
    if any(s in label for s in ('厕所','卫生','洗','水','配电')) or area<10:return 'service'
    return 'classroom'


def _circulation(frame,outer,holes,plan=None,registered=()):
    """Fit authored cores, using registered stair-room locations where available."""
    candidates=[]
    if plan:candidates.extend(plan['stairs'])
    for ring in registered:
        f=Frame(ring);candidates.append(frame.inverse(f.point(f.uc,f.vc)[:2]))
    if not candidates:
        candidates=[(u,v) for u in (frame.umin+5.2,frame.umax-5.2)
                    for v in (frame.vc,frame.vmin+5.,frame.vmax-5.)]
    result=[]
    for u,v in candidates:
        if not _inside_rect(frame,u,v,5.4,2.8,outer,holes):continue
        if any(math.hypot(u-a,v-b)<6 for a,b in result):continue
        result.append((u,v))
        if not plan and not registered and len(result)==2:break
    return result


def _canteen(frame,outer,holes,z,fh,batches,m):
    count=0
    columns=[]
    for i in range(max(1,int((frame.length-10)/8.8))):
        for j in range(max(1,int((frame.width-10)/9.0))):
            u=frame.umin+8+i*8.8;v=frame.vmin+7+j*9.0
            if _inside_rect(frame,u,v,.55,.55,outer,holes):columns.append((u,v))
    table_holes=holes+[frame.rectangle(u,v,.8,.8) for u,v in columns]
    for i in range(max(1,int((frame.length-7)/3.3))):
        u=frame.umin+4+i*3.3
        for j in range(max(1,int((frame.width-10)/2.5))):
            v=frame.vmin+5+j*2.5
            if _inside_rect(frame,u,v,2.0,2.0,outer,table_holes):
                _table(batches['furniture'],frame,u,v,z,m);count+=1
    # Continuous service side: observed stainless fronts, green piers, abstract
    # menu panels without copying commercial image/signage textures.
    v=frame.vmax-2.45
    for i in range(max(1,int((frame.length-9)/5.5))):
        u=frame.umin+5.5+i*5.5
        if not _inside_rect(frame,u,v,4.6,2.2,outer,holes):continue
        frame.box(batches['furniture'],u,v,z+.52,4.65,1.0,1.04,m['white'])
        frame.box(batches['furniture'],u,v,z+1.08,4.72,1.1,.09,m['metal'])
        frame.box(batches['furniture'],u,v+.44,z+1.30,4.5,.025,.30,m['metal'])
        frame.box(batches['walls'],u-2.50,v+.3,z+1.4,.32,1.1,2.8,m['deepgreen'])
        frame.box(batches['services'],u,v+.65,z+2.44,4.5,.11,.66,m['deepgreen' if i%2 else 'blue'])
        for j in range(4):frame.box(batches['services'],u-1.4+j*.92,v,z+1.18,.70,.50,.12,m['metal'])
    for i in range(max(1,int(frame.length/5.4))):
        u=frame.umin+3.+i*5.4
        for v in (frame.vc-4,frame.vc+4):
            if not point_inside(frame.point(u,v)[:2],outer,holes):continue
            zz=z+min(fh-.35,3.55)
            for dv in (-.6,.6):frame.box(batches['ceiling'],u,v+dv,zz,1.8,.035,.035,m['panel'])
            for du in (-.9,.9):frame.box(batches['ceiling'],u+du,v,zz,.035,1.2,.035,m['panel'])
    for u,v in columns:
        frame.box(batches['walls'],u,v,z+fh/2,.42,.42,fh,m['white'])
        frame.box(batches['walls'],u,v,z+.85,.46,.46,1.7,m['deepgreen'])
    for i in range(max(1,int(frame.length/5.4))):
        u=frame.umin+3+i*5.4
        if _inside_rect(frame,u,frame.vc,.15,max(1,frame.width-1),outer,holes):
            frame.box(batches['ceiling'],u,frame.vc,z+min(fh-.16,3.7),.12,frame.width-1,.22,m['white'])
    return count


def _library(frame,outer,holes,z,fh,batches,m,floor):
    count=0;zones=[];cameras=[]
    if floor!=1:
        for u in [frame.umin+7+i*5.6 for i in range(max(1,int((frame.length-14)/5.6)))]:
            for v in (frame.vmin+6,frame.vmax-6):
                if _inside_rect(frame,u,v,4.,1.,outer,holes):_bookcase(batches['furniture'],frame,u,v,z,m,3.8);count+=1
            for v in (frame.vc-5,frame.vc+5):
                if _inside_rect(frame,u,v,2.,2.,outer,holes):_table(batches['furniture'],frame,u,v,z,m);count+=1
        return count,zones,cameras
    u=frame.uc+frame.length*.08;v=frame.vc-frame.width*.21
    length=min(23.,frame.length*.29);width=min(9.0,frame.width*.25);height=min(fh-.4,3.65)
    if _inside_rect(frame,u,v,length,width,outer,holes):
        ring=frame.rectangle(u,v,length,width)
        _room_face(batches['floor'],ring,z+.026,m['floor'],_triangles(ring))
        _room_face(batches['ceiling'],ring,z+height,m['ceiling'],_triangles(ring))
        for side in (-1,1):
            frame.box(batches['walls'],u,v+side*width/2,z+height/2,length,.10,height,m['blue' if side<0 else 'green'])
            frame.box(batches['walls'],u,v+side*(width/2-.06),z+1.63,length,.025,1.05,m['white'])
            # Abstract exhibition relief: no unreviewed photographs are packed.
            for i in range(max(1,int(length/2))):
                frame.box(batches['services'],u-length/2+1+i*2,v+side*(width/2-.10),z+1.73,.72,.025,.48,m['charcoal'])
        for end in (-1,1):
            uu=u+end*length/2
            for side in (-1,1):frame.box(batches['walls'],uu,v+side*(width*.32),z+height/2,.14,width*.36,height,m['oak'])
            frame.box(batches['walls'],uu,v,z+height-.20,.18,width,.40,m['oak'])
            for j in range(6):
                for side in (-1,1):frame.box(batches['services'],uu,v+side*(width*.21+j*.13),z+height/2,.20,.06,height,m['wood_light'])
        # Two desk banks and a clear central aisle reproduce the observed long
        # blue/green room, with a distinct doorway at each longitudinal end.
        for i in range(max(1,int((length-3.2)/1.4))):
            uu=u-length/2+1.8+i*1.4
            for side in (-1,1):
                vv=v+side*2.15
                _desk(batches['furniture'],frame,uu,vv,z,m,1.2,.66,True);count+=1
        for du in range(-8,9,4):
            for dv in (-1.8,1.8):frame.box(batches['ceiling'],u+du,v+dv,z+height-.025,1.6,.055,.025,m['panel'])
        zones.append({'id':'blue_green_study','authored_floor':1,'observed_floor':None,'status':'video_informed_appearance_inferred_registration','polygon_local_m':ring,'two_end_openings':True})
        cameras.append({'id':'study','name':'INTERIOR_Library_BlueGreen','floor':1,'location':frame.point(u-length/2+2.4,v,z+1.58),'target':frame.point(u+length/2-.7,v,z+1.57),'lens':24,'ceilings':True})
        lounge_u=u+length/2+5.2
        if _inside_rect(frame,lounge_u,v,7.0,5.0,outer,holes):
            for i in range(5):_chair(batches['furniture'],frame,lounge_u-2+i*.82,v+1.8,z,m,seat='metal')
            _plant(batches['furniture'],frame,lounge_u+3,v+2,z,m)
            zones.append({'id':'waiting_lounge','authored_floor':1,'observed_floor':None,'opposite_study_exit':True})
    # Independent white-ceiling room, rather than calling it the blue/green room.
    wu=frame.uc-frame.length*.15;wv=frame.vc-frame.width*.21
    wl=min(16.,frame.length*.21);ww=min(10.,frame.width*.28)
    if _inside_rect(frame,wu,wv,wl,ww,outer,holes):
        ring=frame.rectangle(wu,wv,wl,ww)
        _add_room({},ring,z,fh,outer,holes,_triangles(outer),batches,m)
        for j in range(max(1,int(ww/2.2))):_bookcase(batches['furniture'],frame,wu+wl/2-.45,wv-ww/2+1+j*2.2,z,m,1.8)
        for i in range(max(1,int(wl/1.8))):
            for j in range(max(1,int(ww/1.8))):
                uu=wu-wl/2+.8+i*1.8;vv=wv-ww/2+.8+j*1.8
                frame.box(batches['ceiling'],uu,vv,z+min(fh-.26,3.42),.55,.55,.025,m['panel'])
        zones.append({'id':'white_ceiling_study','observed_floor':None,'authored_floor':1,'separate_room':True})
    # Reception counter and perforated oak backdrop, supported by the entry shot.
    ru=frame.uc-frame.length*.31;rv=frame.vc+frame.width*.08
    if _inside_rect(frame,ru,rv,11.,7.,outer,holes):
        frame.box(batches['furniture'],ru,rv,z+.56,6.8,.80,1.12,m['white'])
        frame.box(batches['furniture'],ru,rv-.43,z+.21,6.8,.045,.32,m['oak'])
        for i in range(17):frame.box(batches['walls'],ru-4+i*.50,rv+1.3,z+1.65,.08,.10,3.3,m['wood_light'])
        for j in range(7):frame.box(batches['walls'],ru,rv+1.3,z+.26+j*.46,8.2,.10,.07,m['wood_light'])
        for i in (-2,0,2):frame.box(batches['ceiling'],ru+i,rv,z+3.0,1.75,.11,.075,m['lamp'])
        _plant(batches['furniture'],frame,ru+4.7,rv+1.3,z,m)
        zones.append({'id':'entry_reception','observed_floor':1,'authored_floor':1})
        cameras.append({'id':'reception','name':'INTERIOR_Library_Reception','floor':1,'location':frame.point(ru,rv-5.5,z+1.58),'target':frame.point(ru,rv+.8,z+1.4),'lens':26,'ceilings':True})
    cu=frame.uc+frame.length*.29;cv=frame.vc+frame.width*.23
    if _inside_rect(frame,cu,cv,10.0,6.0,outer,holes):
        frame.box(batches['walls'],cu,cv+2,z+1.5,8.5,.17,3.,m['deepgreen'])
        frame.box(batches['furniture'],cu,cv,z+.55,7.9,.9,1.10,m['white'])
        frame.box(batches['furniture'],cu,cv,z+1.13,8.,1.,.065,m['wood_light'])
        frame.box(batches['furniture'],cu,cv-.49,z+.10,7.9,.026,.06,m['lamp'])
        frame.box(batches['furniture'],cu-1.3,cv,z+1.43,1.8,.60,.55,m['metal'])
        for i in range(3):frame.box(batches['furniture'],cu+.7+i*.8,cv,z+1.19,.6,.45,.10,m['wood_light'])
        zones.append({'id':'coffee_bakery','observed_floor':None,'authored_floor':1})
    su=frame.umax-4.5
    for vv in (frame.vc-3.,frame.vc+3.):
        if _inside_rect(frame,su,vv,2.,2.,outer,holes):_table(batches['furniture'],frame,su,vv,z,m);count+=1
    zones.append({'id':'window_seating','observed_floor':None,'authored_floor':1,'separate_from_counters':True})
    return count,zones,cameras


def enrich(building,collection,*,replace=False):
    """Add a current editable interior. Return serializable statistics and views."""
    existing=[c for c in collection.children if c.get(INTERIOR_MARKER)]
    if existing and not replace:raise ValueError('Interior source already exists; replacement must be an explicit edit: '+building['id'])
    for current in existing:
        children=list(current.children_recursive)
        for ob in list(current.all_objects):
            mesh=ob.data if ob.type=='MESH' else None
            bpy.data.objects.remove(ob,do_unlink=True)
            if mesh and mesh.users==0:bpy.data.meshes.remove(mesh)
        for child in reversed(children):bpy.data.collections.remove(child)
        bpy.data.collections.remove(current)
    design,bindings=_sources();ident=building['id'];name=building.get('name') or ident
    kind=classify(building)
    if ident=='osm_way_1454085437' or kind in ('gate',) or '连廊' in name or '看台' in name or '主席台' in name:
        return {'status':'open_structure_no_occupied_floor_invented','floors':0,'room_count':0,'furniture_modules':0,'objects':0}
    floorplans=[x for x in design['floorplans'] if x['asset_id']==ident]
    levels=max(1,int(float(building.get('levels') or round(float(building.get('height',4))/3.5))))
    if floorplans:levels=max(levels,max(x['floor'] for x in floorplans))
    height=float(building.get('height') or levels*3.5)
    # Registered storey z is owned by observation bindings, not a second height.
    plans={x['floor']:x for x in bindings.get(ident,{}).get('floorplans',[])}
    fh=height/max(1,int(float(building.get('levels') or levels)))
    if len(plans)>1:
        ordered=sorted(plans)
        fh=(plans[ordered[1]]['registration']['local_location'][2]-plans[ordered[0]]['registration']['local_location'][2])/(ordered[1]-ordered[0])
    interior=bpy.data.collections.new('INTERIOR · '+name);collection.children.link(interior)
    interior[INTERIOR_MARKER]=True;interior['asset_id']=ident
    interior['geometry_status']='registered schematic rooms plus explicitly inferred circulation, furniture and services'
    interior['design_source']='projects/blender/design/interiors.json'
    interior['display']='Use show_interior: hide exterior and isolate a floor. Default campus exterior renders suppress interiors.'
    interior['accuracy']='Photograph linework has approximate metric registration. Unobserved interiors are authored inference, not surveyed room dimensions.'
    interior.hide_render=True
    m=_palette();total_rooms=0;total_furniture=0;total_objects=0;cameras=[];all_zones=[]
    for floor in range(1,levels+1):
        outer,holes,tris=_geometry(building,floor)
        if not tris:continue
        frame=Frame(outer)
        z=float(plans[floor]['registration']['local_location'][2]) if floor in plans else (floor-1)*fh+.065
        fl=bpy.data.collections.new(f'{floor:02}F · occupied interior');interior.children.link(fl)
        fl['floor']=floor;fl['z_m']=z;fl['asset_id']=ident
        batches={k:Batch() for k in ('floor','walls','furniture','services','ceiling')}
        plan=next((x for x in floorplans if x['floor']==floor),None)
        official=_library_plan(frame,floor) if ident=='osm_way_223859810' else None
        registered_stairs=[]
        if plan:
            for raw in plan['rooms']:
                if _room_kind(raw.get('raw_label',''),100)=='stairs':
                    registered_stairs.append(_register(raw['polygon'],plans[floor]['registration']))
        cores=_circulation(frame,outer,holes,official,registered_stairs)
        openings=list(official['voids']) if official else []
        if floor>1:openings.extend(frame.rectangle(u,v,5.4,2.8) for u,v in cores)
        if official and floor>1:openings.extend(frame.rectangle(u,v,2.1,2.1) for u,v in official['elevators'])
        tris=_without_openings(tris,openings)
        furnishing_holes=holes+openings+[frame.rectangle(u,v,5.6,3.1) for u,v in cores]
        fl['floor_openings_local_m']=json.dumps(openings)
        fl['circulation_core_local_uv_m']=json.dumps(cores)
        fl['stairs_upper_landing']='Each ascending stair bridges its last riser to the next slab opening edge.'
        for tri in tris:batches['floor'].face([(x,y,z) for x,y in tri],m['floor'])
        for ri,ring in enumerate([outer]+holes):
            for p,q in zip(ring,ring[1:]+ring[:1]):
                # A visible inner lining remains after hiding the opaque exterior.
                _window_lining(p,q,z,fh,batches,m)
        room_records=[];floor_furniture=0;zones=[]
        if plan:
            registration=plans[floor]['registration']
            for raw in plan['rooms']:
                ring=_register(raw['polygon'],registration)
                room=dict(raw);room['polygon_asset_local_m']=ring;room['registration_status']='approximate_not_surveyed'
                room['furniture_status']='inferred_design';room['door_status']='inferred_not_measured'
                room_kind=_room_kind(raw.get('raw_label',''),abs(signed_area(ring)))
                before=len(batches['walls'].faces)
                floor_furniture+=_add_room(room,ring,z,fh,outer,furnishing_holes,tris,batches,m,room_kind)
                room['wall_face_range']=[before,len(batches['walls'].faces)]
                room_records.append(room)
                cx=sum(p[0] for p in ring)/len(ring);cy=sum(p[1] for p in ring)/len(ring)
                marker=bpy.data.objects.new('ROOM · '+raw['raw_label'],None);fl.objects.link(marker)
                marker.location=(cx,cy,z+.15);marker.empty_display_type='PLAIN_AXES';marker.empty_display_size=.25
                marker['room_id']=raw['region_id'];marker['source_id']=plan['source_id'];marker['space_key']=raw.get('space_key') or ''
                marker['geometry_status']=raw['geometry_status'];marker['registration_status']='approximate_not_surveyed'
                marker['footprint_local_m']=json.dumps(ring);marker['floor']=floor;marker.hide_render=True
                total_objects+=1
            fl['plan_source_id']=plan['source_id'];fl['plan_source_sha256']=plan['source_sha256']
        elif official:
            floor_furniture,room_records=_official_library_rooms(official,z,fh,outer,furnishing_holes,tris,batches,m,floor)
            fl['plan_source_id']=official['source_id']
            fl['registration_status']='inferred_metric_registration_of_official_diagram'
            for index,room in enumerate(room_records):
                ring=room['polygon_local_m'];center=Frame(ring)
                marker=bpy.data.objects.new('ROOM · '+room['label'],None);fl.objects.link(marker)
                marker.location=center.point(center.uc,center.vc,z+.15)
                marker['room_id']=room['room_id'];marker['source_id']=room['source_id'];marker['floor']=floor
                marker['registration_status']=room['registration_status'];marker.hide_render=True
                total_objects+=1
        elif ident=='osm_way_223859810':
            floor_furniture,zones,views=_library(frame,outer,furnishing_holes,z,fh,batches,m,floor);cameras.extend(views)
        elif kind=='dining' or ident=='njupt_k_dining_04':
            floor_furniture=_canteen(frame,outer,furnishing_holes,z,fh,batches,m)
            if floor==1:
                aisle=frame.vmin+6.25+max(0,int((frame.width/2-6.25)/2.5))*2.5
                cameras.append({'id':'dining','name':'INTERIOR_Canteen2' if ident=='osm_way_223859784' else 'INTERIOR_Dining','floor':floor,'location':frame.point(frame.umin+12,aisle,z+1.62),'target':frame.point(frame.umin+30,aisle,z+1.55),'lens':24,'ceilings':True})
        elif kind in ('gym','old_gym','new_gym') or '体育馆' in name:
            # Sports halls have occupied side facilities and an open central
            # multi-height hall; no fictional floor plate cuts through its court.
            if floor>1:
                bpy.data.collections.remove(fl);continue
            for vv in (frame.vmin+2.8,frame.vmax-2.8):
                for i in range(max(1,int((frame.length-12)/6.0))):
                    uu=frame.umin+6+i*6.
                    if _inside_rect(frame,uu,vv,5.6,4.0,outer,holes):
                        rr={'room_id':f'inferred-sports-{i}-{vv:.1f}','status':'inferred_changing_facility'}
                        ring=frame.rectangle(uu,vv,5.6,4.)
                        floor_furniture+=_add_room(rr,ring,z,fh,outer,furnishing_holes,tris,batches,m,'service');room_records.append(rr)
            interior['hall_void']='Upper slabs omitted to preserve multi-height playing hall.'
        else:
            for room in _generic_rooms(frame,outer,holes,kind):
                if any(abs(signed_area(_clip_convex(room['polygon_local_m'],frame.rectangle(u,v,5.8,3.2))))>.01 for u,v in cores):continue
                floor_furniture+=_add_room(room,room['polygon_local_m'],z,fh,outer,furnishing_holes,tris,batches,m,room['kind'])
                room_records.append(room)
                if floor==1 and room['kind']=='dorm' and not any(c['id']=='dorm' for c in cameras):
                    rf=Frame(room['polygon_local_m'])
                    cameras.append({'id':'dorm','name':'INTERIOR_Dorm','floor':1,
                                    'location':rf.point(rf.umin+.65,rf.vc,z+1.6),
                                    'target':rf.point(rf.umax-.25,rf.vc,z+1.5),'lens':21,'ceilings':True})
        # Circulation stair landings are fitted against the actual occupied wing.
        for uu,vv in cores:
            if floor<levels:_stairs(batches['services'],frame,uu,vv,z,fh,m)
            frame.box(batches['services'],uu, vv+1.7,z+1.1,1.05,.065,2.20,m['metal'])
            frame.box(batches['services'],uu+.75,vv+1.68,z+1.2,.10,.08,.30,m['charcoal'])
        if floor==(3 if ident=='osm_way_223859810' else 1):
            span=max(frame.length,frame.width)
            cameras.append({'id':'cutaway','name':'INTERIOR_Cutaway','floor':floor,
                            'location':frame.point(frame.uc-span*.40,frame.vc-span*.85,z+span*.86),
                            'target':frame.point(frame.uc,frame.vc,z+1),'lens':42,'ceilings':False})
        fl['room_design']=json.dumps(room_records,ensure_ascii=False)
        if zones:fl['special_zones']=json.dumps(zones,ensure_ascii=False);all_zones.extend(zones)
        fl['room_count']=len(room_records);fl['furniture_modules']=floor_furniture
        for role,batch in batches.items():
            if not batch.faces:continue
            ob=batch.object(f'INTERIOR · {floor:02}F · {role} · {name}',fl,bevel=.008 if role=='furniture' else 0)
            ob['interior_role']=role;ob['floor']=floor;ob['asset_id']=ident
            ob['design_status']='registered room boundaries with inferred openings and envelope lining' if role=='walls' and (plan or official) else 'inferred design'
            if role=='ceiling':ob.hide_render=True;ob.hide_viewport=True
            total_objects+=1
        total_rooms+=len(room_records);total_furniture+=floor_furniture
    for view in cameras:
        data=bpy.data.cameras.new(view['name']);ob=bpy.data.objects.new(view['name'],data);interior.objects.link(ob)
        ob.location=view['location'];ob.rotation_euler=(Vector(view['target'])-ob.location).to_track_quat('-Z','Y').to_euler()
        data.lens=view['lens'];data.clip_start=.05;data.clip_end=600
        ob['interior_floor']=view['floor'];ob['asset_id']=ident;ob['interior_camera_id']=view['id'];ob['requires_interior_inspection_mode']=True
        total_objects+=1
    interior['camera_specs']=json.dumps(cameras,ensure_ascii=False)
    interior['room_count']=total_rooms;interior['furniture_modules']=total_furniture
    bpy.context.view_layer.update()
    return {'status':'editable_source_authored','floors':len(interior.children),'registered_plan_floors':len(floorplans),
            'official_library_plan_floors':len(design['special_designs'][ident].get('official_floorplans',[])) if ident in design['special_designs'] else 0,'room_count':total_rooms,
            'furniture_modules':total_furniture,'objects':total_objects,'collection':interior.name,'camera_specs':cameras,'special_zones':all_zones,
            'default_campus_render_hidden':True,'inference_note':'Source room polygons preserve reviewed linework; metric registration, furniture and unseen spaces remain reconstruction.'}


def show_interior(collection,floor=1,ceilings=True,exterior=False):
    """Activate a saved-asset single floor, hiding its opaque external shell."""
    bpy.context.view_layer.update()
    interior=next((c for c in collection.children if c.get(INTERIOR_MARKER)),None)
    if interior is None:raise ValueError('No editable interior in '+collection.name)
    interior_objects=set(interior.all_objects)
    for ob in list(collection.all_objects):
        if ob not in interior_objects:
            if ob.get('interior_previous_hide_render') is None:
                ob['interior_previous_hide_render']=ob.hide_render
                ob['interior_previous_hide_viewport']=ob.hide_viewport
            ob.hide_render=bool(ob['interior_previous_hide_render']) if exterior else True
            ob.hide_viewport=bool(ob['interior_previous_hide_viewport']) if exterior else True
    interior.hide_render=False;interior.hide_viewport=False
    for fl in list(interior.children):
        active=floor is None or int(fl['floor'])==int(floor)
        fl.hide_render=not active;fl.hide_viewport=not active
        for ob in list(fl.objects):
            if ob.get('interior_role')=='ceiling':ob.hide_render=not ceilings;ob.hide_viewport=not ceilings
    return interior


def show_exterior(collection):
    """Restore exterior-source visibility after a temporary interior inspection."""
    for col in list(collection.children):
        if col.get(INTERIOR_MARKER):col.hide_render=True;col.hide_viewport=False
    for ob in list(collection.all_objects):
        if ob.get('interior_previous_hide_render') is not None:
            ob.hide_render=bool(ob['interior_previous_hide_render']);ob.hide_viewport=bool(ob['interior_previous_hide_viewport'])
            del ob['interior_previous_hide_render'];del ob['interior_previous_hide_viewport']
