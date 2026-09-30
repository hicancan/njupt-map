"""Evidence-aligned campus landscape for Blender, with explicit inferred details.

Public API: build_landscape(campus_dict, parent_collection) -> JSON-safe stats.
Coordinates: local metres, +X east / +Y north / ground Z=0.
Only Blender and Python's standard library are required. Generic tree geometry
and scanned PBR textures are CC0; their use does not prove local tree species.
"""
import math
import random
from pathlib import Path
from collections import defaultdict

import bpy
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

ASSETS = Path(__file__).resolve().parents[2] / 'projects/blender/materials'
TAU = 2 * math.pi


def _enum(owner, prop, value):
    valid = {item.identifier for item in owner.bl_rna.properties[prop].enum_items}
    if value in valid:
        setattr(owner, prop, value)


def _collection(name, parent):
    c = bpy.data.collections.new(name)
    parent.children.link(c)
    return c


def _mat(name, color, rough=.75, metal=0, noise=0):
    existing = bpy.data.materials.get(name)
    if existing:
        return existing
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    n = m.node_tree.nodes
    p = next(i for i in n if i.type == 'BSDF_PRINCIPLED')
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Roughness'].default_value = rough
    p.inputs['Metallic'].default_value = metal
    if noise:
        tex = n.new('ShaderNodeTexNoise')
        _enum(tex, 'noise_dimensions', '3D')
        _enum(tex, 'noise_type', 'FBM')
        tex.inputs['Scale'].default_value = 1.7
        tex.inputs['Detail'].default_value = 3
        ramp = n.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color = (*(v * (1 - noise) for v in color), 1)
        ramp.color_ramp.elements[1].color = (*(min(1, v * (1 + noise)) for v in color), 1)
        geom = n.new('ShaderNodeNewGeometry')
        m.node_tree.links.new(geom.outputs['Position'], tex.inputs['Vector'])
        m.node_tree.links.new(tex.outputs['Fac'], ramp.inputs['Fac'])
        m.node_tree.links.new(ramp.outputs['Color'], p.inputs['Base Color'])
        bump = n.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = .18
        bump.inputs['Distance'].default_value = .012
        m.node_tree.links.new(tex.outputs['Fac'], bump.inputs['Height'])
        m.node_tree.links.new(bump.outputs['Normal'], p.inputs['Normal'])
    return m


def _pbr(asset, name, tile, tint=None):
    m = _mat(name, (.28, .3, .23) if 'grass' in asset else (.25, .25, .25))
    n, links = m.node_tree.nodes, m.node_tree.links
    p = next(i for i in n if i.type == 'BSDF_PRINCIPLED')
    # UVs are world metres / tile size, avoiding one stretched texture per region.
    uv = n.new('ShaderNodeTexCoord')
    mapping = n.new('ShaderNodeVectorMath')
    _enum(mapping, 'operation', 'SCALE')
    mapping.inputs['Scale'].default_value = 1 / tile
    links.new(uv.outputs['UV'], mapping.inputs[0])
    maps = {'diff': 'Base Color', 'rough': 'Roughness', 'nor_gl': None}
    for key, socket in maps.items():
        f = ASSETS / asset / f'{asset}_{key}_2k.jpg'
        if not f.exists():
            continue
        image = bpy.data.images.load(str(f), check_existing=True)
        if key != 'diff':
            image.colorspace_settings.name = 'Non-Color'
        tex = n.new('ShaderNodeTexImage')
        tex.image = image
        links.new(mapping.outputs['Vector'], tex.inputs['Vector'])
        if key == 'nor_gl':
            normal = n.new('ShaderNodeNormalMap')
            normal.inputs['Strength'].default_value = .42
            links.new(tex.outputs['Color'], normal.inputs['Color'])
            links.new(normal.outputs['Normal'], p.inputs['Normal'])
        elif key == 'diff' and 'grass' in asset:
            # This scan is dry, sparse grass. Keep scanned fine reflectance detail
            # but remap it to a restrained maintained-campus-lawn palette.
            # Photographic evidence supports green lawn, not the dry scan's hue.
            bw=n.new('ShaderNodeRGBToBW')
            ramp=n.new('ShaderNodeValToRGB')
            ramp.color_ramp.elements[0].position=.018
            ramp.color_ramp.elements[0].color=(.022,.047,.011,1)
            ramp.color_ramp.elements[1].position=.29
            ramp.color_ramp.elements[1].color=(.12,.20,.047,1)
            mid=ramp.color_ramp.elements.new(.12)
            mid.color=(.053,.11,.023,1)
            links.new(tex.outputs['Color'],bw.inputs['Color'])
            links.new(bw.outputs['Val'],ramp.inputs['Fac'])
            geom=n.new('ShaderNodeNewGeometry')
            macro=n.new('ShaderNodeTexNoise')
            _enum(macro,'noise_dimensions','3D');_enum(macro,'noise_type','FBM')
            macro.inputs['Scale'].default_value=.035
            macro.inputs['Detail'].default_value=2
            macro_ramp=n.new('ShaderNodeValToRGB')
            macro_ramp.color_ramp.elements[0].color=(.52,.65,.44,1)
            macro_ramp.color_ramp.elements[1].color=(1,1,.91,1)
            mix=n.new('ShaderNodeMixRGB')
            _enum(mix,'blend_type','MULTIPLY')
            mix.inputs[0].default_value=.35
            links.new(geom.outputs['Position'],macro.inputs['Vector'])
            links.new(macro.outputs['Fac'],macro_ramp.inputs['Fac'])
            links.new(ramp.outputs['Color'],mix.inputs[1])
            links.new(macro_ramp.outputs['Color'],mix.inputs[2])
            links.new(mix.outputs['Color'],p.inputs[socket])
            m.diffuse_color=(.053,.11,.023,1)
            m['color_adjustment']='Dry scan hue remapped to maintained green lawn using official campus photo evidence; fine scan luminance/normal/roughness retained.'
        elif key == 'diff' and tint:
            mix = n.new('ShaderNodeMixRGB')
            _enum(mix, 'blend_type', 'MULTIPLY')
            mix.inputs[0].default_value = .65
            mix.inputs[2].default_value = (*tint, 1)
            links.new(tex.outputs['Color'], mix.inputs[1])
            links.new(mix.outputs['Color'], p.inputs[socket])
        else:
            links.new(tex.outputs['Color'], p.inputs[socket])
    m['source'] = 'https://polyhaven.com/a/' + asset
    m['license'] = 'CC0-1.0'
    return m


class Batch:
    """One mesh per material keeps large campus scenes practical to navigate."""
    def __init__(self, name, material, collection):
        self.name, self.mat, self.collection = name, material, collection
        self.verts, self.faces = [], []

    def face(self, pts):
        if len(pts) < 3:
            return
        start = len(self.verts)
        self.verts.extend(pts)
        self.faces.append(tuple(range(start, start + len(pts))))

    def box(self, center, dims, angle=0):
        x, y, z = center
        a, b, h = (v / 2 for v in dims)
        c, s = math.cos(angle), math.sin(angle)
        pts = [(x + u*c-v*s, y + u*s+v*c, z+w) for w in (-h,h) for u,v in ((-a,-b),(a,-b),(a,b),(-a,b))]
        start = len(self.verts)
        self.verts.extend(pts)
        for f in ((0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)):
            self.faces.append(tuple(start+i for i in f))

    def rod(self, a, b, radius=.04, sides=7, radius2=None):
        a, b = Vector(a), Vector(b)
        d = b-a
        if d.length < .001:
            return
        d.normalize()
        t = d.cross(Vector((0,0,1)))
        if t.length < .01:
            t = d.cross(Vector((0,1,0)))
        t.normalize()
        q = d.cross(t).normalized()
        start = len(self.verts)
        for p,r in ((a,radius),(b,radius if radius2 is None else radius2)):
            self.verts.extend(tuple(p + (t*math.cos(i*TAU/sides)+q*math.sin(i*TAU/sides))*r) for i in range(sides))
        self.faces.append(tuple(start+i for i in reversed(range(sides))))
        self.faces.append(tuple(start+sides+i for i in range(sides)))
        for i in range(sides):
            j=(i+1)%sides
            self.faces.append((start+i,start+j,start+sides+j,start+sides+i))

    def line(self, pts, width=.09, z=.16, closed=False):
        pts=list(pts)
        if closed and pts and pts[0]!=pts[-1]:
            pts.append(pts[0])
        for a,b in zip(pts,pts[1:]):
            dx,dy=b[0]-a[0],b[1]-a[1]
            length=math.hypot(dx,dy)
            if length < .001:
                continue
            nx,ny=-dy/length*width/2,dx/length*width/2
            za,zb=(z(a),z(b)) if callable(z) else (z,z)
            self.face([(a[0]+nx,a[1]+ny,za),(a[0]-nx,a[1]-ny,za),(b[0]-nx,b[1]-ny,zb),(b[0]+nx,b[1]+ny,zb)])

    def polygon(self, record, z=.02):
        triangles=record.get('triangles')
        if triangles:
            for tri in triangles:
                self.face([(p[0],p[1],z) for p in tri])
            return
        outer=_ring(record['outer'])
        if len(outer)<3:
            return
        try:
            vectors=[Vector((p[0],p[1],z)) for p in outer]
            tris=tessellate_polygon([vectors])
            for raw_tri in tris:
                # Blender 5.2 returns indices, older versions returned Vectors.
                tri=[vectors[v] if isinstance(v,int) else v for v in raw_tri]
                c=[sum(v[i] for v in tri)/3 for i in (0,1)]
                if not any(_inside(c,h) for h in record.get('holes',[])):
                    self.face([tuple(v) for v in tri])
        except ValueError:
            pass

    def finish(self, confidence='inferred finish applied to mapped geometry'):
        if not self.faces:
            return None
        mesh=bpy.data.meshes.new(self.name)
        mesh.from_pydata(self.verts,[],self.faces)
        mesh.materials.append(self.mat)
        mesh.update()
        uv=mesh.uv_layers.new(name='WorldMetres')
        for p in mesh.polygons:
            for li in p.loop_indices:
                v=mesh.vertices[mesh.loops[li].vertex_index].co
                uv.data[li].uv=(v.x,v.y)
        obj=bpy.data.objects.new(self.name,mesh)
        self.collection.objects.link(obj)
        obj['confidence']=confidence
        return obj


def _ring(pts):
    pts=[tuple(p[:2]) for p in pts]
    return pts[:-1] if len(pts)>2 and pts[0]==pts[-1] else pts


def _inside(pt, ring):
    x,y=pt[:2]
    hit=False
    for i in range(len(ring)):
        a,b=ring[i-1],ring[i]
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            hit=not hit
    return hit


def _in_record(pt,r):
    return _inside(pt,r['outer']) and not any(_inside(pt,h) for h in r.get('holes',[]))


def _dist_seg(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    dd=dx*dx+dy*dy
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/dd)) if dd else 0
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)


class Occupancy:
    def __init__(self, data):
        self.polys=defaultdict(list)
        self.roads=defaultdict(list)
        self.cell=32
        self.boundary=data['boundary']
        for category in ('buildings','context_buildings','waters','sports','surfaces'):
            for r in data.get(category,[]):
                if r.get('underground'):
                    continue
                margin=3.1 if 'buildings' in category else 1.0
                xs=[p[0] for p in r['outer']];ys=[p[1] for p in r['outer']]
                for i in range(math.floor((min(xs)-margin)/self.cell),math.floor((max(xs)+margin)/self.cell)+1):
                    for j in range(math.floor((min(ys)-margin)/self.cell),math.floor((max(ys)+margin)/self.cell)+1):
                        self.polys[i,j].append((r,margin,category))
        for r in data.get('roads',[])+data.get('tracks',[]):
            w=r.get('width',6)/2+1.3
            for a,b in zip(r.get('points',[]),r.get('points',[])[1:]):
                for i in range(math.floor((min(a[0],b[0])-w)/self.cell),math.floor((max(a[0],b[0])+w)/self.cell)+1):
                    for j in range(math.floor((min(a[1],b[1])-w)/self.cell),math.floor((max(a[1],b[1])+w)/self.cell)+1):
                        self.roads[i,j].append((a,b,w))

    def free(self,p,boundary=True,crown_radius=0):
        """Reject solids using the actual tree crown, including courtyard walls.

        The old fixed trunk buffer let large crowns penetrate facades and trees
        in courtyards penetrate the *inner* wall. Crown clearance is geometric
        collision protection, not evidence that inferred plant locations exist.
        """
        if boundary and not _in_record(p,self.boundary):
            return False
        key=(math.floor(p[0]/self.cell),math.floor(p[1]/self.cell))
        reach=math.ceil(crown_radius/self.cell)
        visited=set()
        for i in range(key[0]-reach,key[0]+reach+1):
            for j in range(key[1]-reach,key[1]+reach+1):
                for r,margin,category in self.polys[i,j]:
                    if id(r) in visited:continue
                    visited.add(id(r))
                    if category in ('buildings','context_buildings','sports') or r.get('crown_clearance'):
                        margin=max(margin,crown_radius+.4)
                    if _in_record(p,r):return False
                    for ring in [r['outer']]+r.get('holes',[]):
                        if any(_dist_seg(p,a,b)<margin for a,b in zip(ring,ring[1:]+ring[:1])):
                            return False
        return not any(_dist_seg(p,a,b)<w for a,b,w in self.roads[key])


def _offset(pts, amount):
    out=[]
    for i,p in enumerate(pts):
        prev=pts[max(0,i-1)];nxt=pts[min(len(pts)-1,i+1)]
        dx,dy=nxt[0]-prev[0],nxt[1]-prev[1]
        d=math.hypot(dx,dy) or 1
        out.append((p[0]-dy/d*amount,p[1]+dx/d*amount))
    return out


def _sample_line(pts, step, initial=0):
    carry=initial
    for a,b in zip(pts,pts[1:]):
        dx,dy=b[0]-a[0],b[1]-a[1]
        length=math.hypot(dx,dy)
        if length<.001:continue
        while carry<length:
            yield (a[0]+dx*carry/length,a[1]+dy*carry/length),math.atan2(dy,dx)
            carry+=step
        carry-=length


def _densify(pts,step=6):
    out=[]
    for a,b in zip(pts,pts[1:]):
        n=max(1,math.ceil(math.hypot(b[0]-a[0],b[1]-a[1])/step))
        out.extend((a[0]+(b[0]-a[0])*i/n,a[1]+(b[1]-a[1])*i/n) for i in range(n))
    return out+[tuple(pts[-1])] if pts else []


def _stadium(center,angle,radius,halfstraight=42.2):
    c,s=math.cos(angle),math.sin(angle)
    local=[]
    for side,start in ((1,-math.pi/2),(-1,math.pi/2)):
        for i in range(65):
            a=start+math.pi*i/64
            local.append((side*halfstraight+radius*math.cos(a),radius*math.sin(a)))
    pts=[(center[0]+u*c-v*s,center[1]+u*s+v*c) for u,v in local]
    return pts+[pts[0]]


def _willow_source():
    """Photo-supported drooping habit, not a claim of measured willow anatomy."""
    c=bpy.data.collections.new('垂柳母版_照片形态推断')
    bark=_mat('垂柳_灰褐树皮',(.12,.095,.062),.9,noise=.3)
    leaves=_mat('垂柳_嫩绿长叶',(.13,.26,.035),.74,noise=.16)
    p=next(n for n in leaves.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    p.inputs['Subsurface Weight'].default_value=.055
    trunk=Batch('垂柳_分枝',bark,c);foliage=Batch('垂柳_叶片',leaves,c)
    trunk.rod((0,0,0),(.18,.1,5.2),.26,10,.13)
    rng=random.Random(2741)
    for i in range(12):
        a=i*TAU/12+rng.uniform(-.1,.1)
        tip=(math.cos(a)*rng.uniform(2,3.4),math.sin(a)*rng.uniform(2,3.4),rng.uniform(6,8))
        trunk.rod((.18,.1,4.3),tip,.095,7,.035)
    for i in range(105):
        a=rng.random()*TAU;r=rng.uniform(1.4,4.2)
        h=rng.uniform(5.5,8.1)
        pts=[]
        for k in range(10):
            t=k/9
            rr=r*(.44+.66*t)
            pts.append((rr*math.cos(a),rr*math.sin(a),h-4.3*t*t))
        for a0,b0 in zip(pts,pts[1:]):trunk.rod(a0,b0,.014,4,.007)
        for k in range(38):
            t=(k+.5)/38
            rr=r*(.44+.66*t);z=h-4.3*t*t
            x,y=rr*math.cos(a),rr*math.sin(a)
            for side in (-1,1):
                aa=a+side*.65+rng.uniform(-.5,.5)
                length=rng.uniform(.17,.31);width=.035
                dx,dy=math.cos(aa)*length,math.sin(aa)*length
                nx,ny=-math.sin(aa)*width,math.cos(aa)*width
                foliage.face([(x,y,z),(x+dx*.5+nx,y+dy*.5+ny,z-.06),(x+dx,y+dy,z-.15),(x+dx*.5-nx,y+dy*.5-ny,z-.06)])
    trunk.finish('Inferred willow habit based on campus lake photograph')
    foliage.finish('Inferred willow leaf geometry')
    return c


def _oriented_bounds(record):
    pts=_ring(record['outer'])
    best=None
    for a,b in zip(pts,pts[1:]+pts[:1]):
        dx,dy=b[0]-a[0],b[1]-a[1]
        if dx*dx+dy*dy<1:continue
        angle=math.atan2(dy,dx)
        c,s=math.cos(angle),math.sin(angle)
        uv=[(x*c+y*s,-x*s+y*c) for x,y in pts]
        u0,u1=min(p[0] for p in uv),max(p[0] for p in uv)
        v0,v1=min(p[1] for p in uv),max(p[1] for p in uv)
        area=(u1-u0)*(v1-v0)
        if best is None or area<best[0]:best=(area,angle,u0,u1,v0,v1)
    _,angle,u0,u1,v0,v1=best
    if u1-u0 < v1-v0:
        angle+=math.pi/2
        c,s=math.cos(angle),math.sin(angle)
        uv=[(x*c+y*s,-x*s+y*c) for x,y in pts]
        u0,u1=min(p[0] for p in uv),max(p[0] for p in uv)
        v0,v1=min(p[1] for p in uv),max(p[1] for p in uv)
    c,s=math.cos(angle),math.sin(angle)
    return ((u0+u1)/2*c-(v0+v1)/2*s,(u0+u1)/2*s+(v0+v1)/2*c),u1-u0,v1-v0,angle


def _clipped_rectangle(batch,bounds,obstacles,z):
    """Exact planar scanline decomposition: rectangle minus mapped polygons.

    Supports holes and overlapping obstacles without external GIS dependencies.
    Splitting at both vertices and edge intersections keeps the boundary order
    constant within each horizontal slab; each accepted span is a trapezoid.
    """
    x0,y0,x1,y1=bounds
    relevant=[]
    for r in obstacles:
        xs=[p[0] for p in r['outer']];ys=[p[1] for p in r['outer']]
        if max(xs)>x0 and min(xs)<x1 and max(ys)>y0 and min(ys)<y1:
            relevant.append(r)
    edges=[((x0,y0),(x0,y1)),((x1,y0),(x1,y1))]
    levels={y0,y1}
    for r in relevant:
        for ring in [r['outer']]+r.get('holes',[]):
            pts=_ring(ring)
            for a,b in zip(pts,pts[1:]+pts[:1]):
                if y0<a[1]<y1:levels.add(a[1])
                if abs(a[1]-b[1])>1e-9 and max(a[1],b[1])>y0 and min(a[1],b[1])<y1:
                    edges.append((a,b))
    for i,(a,b) in enumerate(edges):
        dx,dy=b[0]-a[0],b[1]-a[1]
        for c,d in edges[:i]:
            ex,ey=d[0]-c[0],d[1]-c[1]
            det=dx*ey-dy*ex
            if abs(det)<1e-10:continue
            t=((c[0]-a[0])*ey-(c[1]-a[1])*ex)/det
            u=((c[0]-a[0])*dy-(c[1]-a[1])*dx)/det
            yy=a[1]+t*dy
            if 0<t<1 and 0<u<1 and y0<yy<y1:levels.add(yy)
    def ex(edge,y):
        a,b=edge
        return a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1])
    levels=sorted(levels)
    area=0
    for lo,hi in zip(levels,levels[1:]):
        if hi-lo<1e-8:continue
        mid=(lo+hi)/2
        cross=sorted((ex(e,mid),i,e) for i,e in enumerate(edges) if min(e[0][1],e[1][1])<mid<max(e[0][1],e[1][1]))
        for left,right in zip(cross,cross[1:]):
            xl,_,le=left;xr,_,re=right
            if xr-xl<1e-8:continue
            point=((xl+xr)/2,mid)
            if not x0<point[0]<x1 or any(_in_record(point,r) for r in relevant):continue
            pl0=max(x0,min(x1,ex(le,lo)));pl1=max(x0,min(x1,ex(le,hi)))
            pr0=max(x0,min(x1,ex(re,lo)));pr1=max(x0,min(x1,ex(re,hi)))
            batch.face([(pl0,lo,z),(pr0,lo,z),(pr1,hi,z),(pl1,hi,z)])
            area+=(pr0-pl0+pr1-pl1)/2*(hi-lo)
    return area


def _oriented_plaza(batch,center,bounds,angle,obstacles,z):
    """Clip a building-local rectangular apron, then return its world footprint.

    This shares the full polygon subtraction routine with the south forecourt:
    adjacent buildings, sports surfaces and water are not paved over. The returned
    record is also the tree crown exclusion, so rendering and occupancy agree.
    """
    ca,sa=math.cos(angle),math.sin(angle);cx,cy=center
    def to_local(p):
        x,y=p[0]-cx,p[1]-cy;return (x*ca+y*sa,-x*sa+y*ca)
    def to_world(p):return (cx+p[0]*ca-p[1]*sa,cy+p[0]*sa+p[1]*ca)
    transformed=[{'outer':[to_local(p) for p in r['outer']],'holes':[[to_local(p) for p in h] for h in r.get('holes',[])]} for r in obstacles]
    class TransformedBatch:
        def face(self,points):batch.face([(*to_world(p),p[2]) for p in points])
    area=_clipped_rectangle(TransformedBatch(),bounds,transformed,z)
    x0,y0,x1,y1=bounds
    return {'outer':[to_world(p) for p in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))],'holes':[],'crown_clearance':True},area


def _court(batch, lines, hardware, center, length, width, angle, kind, wood):
    c,s=math.cos(angle),math.sin(angle)
    def pt(x,y,z=.205):return (center[0]+x*c-y*s,center[1]+x*s+y*c,z)
    def line(points,w=.065):lines.line([pt(x,y) for x,y in points],w,.211)
    def circle(cx,cy,r,start=0,end=TAU):line([(cx+r*math.cos(start+(end-start)*i/64),cy+r*math.sin(start+(end-start)*i/64)) for i in range(65)])
    x,y=length/2,width/2
    batch.face([pt(-x,-y),pt(x,-y),pt(x,y),pt(-x,y)])
    line([(-x,-y),(x,-y),(x,y),(-x,y),(-x,-y)])
    line([(0,-y),(0,y)])
    if kind=='soccer':
        circle(0,0,9.15)
        for side in (-1,1):
            line([(side*x,-20.16),(side*(x-16.5),-20.16),(side*(x-16.5),20.16),(side*x,20.16)])
            line([(side*x,-9.16),(side*(x-5.5),-9.16),(side*(x-5.5),9.16),(side*x,9.16)])
            for gy in (-3.66,3.66):
                hardware.rod(pt(side*x,gy,.2),pt(side*x,gy,2.64),.045)
                hardware.rod(pt(side*x,gy,2.64),pt(side*(x+1.8),gy,.2),.028)
            hardware.rod(pt(side*x,-3.66,2.64),pt(side*x,3.66,2.64),.045)
            # Open white goal net strands, light enough for a campus-scale model.
            for gy in range(-3,4):hardware.rod(pt(side*(x+1.8),gy,.24),pt(side*x,gy,2.6),.008,4)
    elif kind=='basketball':
        circle(0,0,1.8)
        for side in (-1,1):
            line([(side*x,-2.45),(side*(x-5.8),-2.45),(side*(x-5.8),2.45),(side*x,2.45)])
            circle(side*(x-5.8),0,1.8)
            circle(side*(x-1.58),0,6.75,math.pi/2 if side>0 else -math.pi/2,math.pi*1.5 if side>0 else math.pi/2)
            p=pt(side*(x+1.2),0,1.8)
            hardware.rod(pt(side*(x+1.2),0,.2),pt(side*(x+1.2),0,3.5),.07)
            hardware.rod(pt(side*(x+1.2),0,3.5),pt(side*(x-1.0),0,3.5),.055)
            wood.box(pt(side*(x-1.0),0,3.55),(.075,1.8,1.05),angle)
            ring=[pt(side*(x-1.38)+.23*math.cos(i*TAU/20),.23*math.sin(i*TAU/20),3.25) for i in range(21)]
            for a,b in zip(ring,ring[1:]):hardware.rod(a,b,.016,5)
    elif kind in ('tennis','volleyball','handball'):
        if kind=='tennis':
            for yy in (-4.115,4.115):line([(-x,yy),(x,yy)])
            for xx in (-6.4,6.4):line([(xx,-4.115),(xx,4.115)])
            line([(-6.4,0),(6.4,0)])
        elif kind=='volleyball':
            for xx in (-3,3):line([(xx,-y),(xx,y)])
        else:circle(0,0,1.2)
        if kind!='handball':
            height=1.15 if kind=='tennis' else 2.63
            for yy in (-y-.5,y+.5):hardware.rod(pt(0,yy,.2),pt(0,yy,height),.045)
            hardware.rod(pt(0,-y-.5,height),pt(0,y+.5,height),.018)
            for k in range(int(width*3)+1):hardware.rod(pt(0,-y+k/3,height),pt(0,-y+k/3,height-.7),.006,4)


def _tree_source():
    f=ASSETS/'jacaranda_tree'/'jacaranda_campus_lod.blend'
    if not f.exists():f=ASSETS/'jacaranda_tree'/'jacaranda_tree_1k.blend'
    if not f.exists():return None
    with bpy.data.libraries.load(str(f),link=False) as (src,dst):
        wanted='Campus_Broadleaf_CC0' if 'Campus_Broadleaf_CC0' in src.objects else 'jacaranda_tree_LOD1'
        dst.objects=[wanted]
    obj=dst.objects[0]
    # Do not link the template into the scene; instances use its mesh datablock.
    for mat in obj.data.materials:
        if not mat or not mat.node_tree:continue
        mat['source']='https://polyhaven.com/a/jacaranda_tree'
    return obj


def build_landscape(data, collection):
    rng=random.Random(20260930)
    ground=_collection('01_地表与铺装',collection)
    roadcol=_collection('02_道路路缘与标线',collection)
    watercol=_collection('03_中博湖与水岸',collection)
    sportscol=_collection('04_体育场地与器械',collection)
    treecol=_collection('05_乔木_位置与树种含推断',collection)
    furniture=_collection('06_路灯座椅护栏_推断',collection)
    grass=_pbr('grass_ground','校园_真实草土_2K',2.51,(.62,.98,.44))
    asphalt=_pbr('asphalt_02','校园_风化沥青_2K',3.0,(.23,.25,.27))
    paving=_pbr('rock_tile_floor','校园_石材铺装_2K',1.96,(.64,.64,.60))
    backdrop=_mat('校外连续绿地_推断背景',(.027,.050,.016),.98,noise=.35)
    for node in backdrop.node_tree.nodes:
        if node.type=='TEX_NOISE':node.inputs['Scale'].default_value=.007
    backdrop['confidence']='Neutral inferred vegetated context only; no claim of surveyed external land cover.'
    curb=_mat('校园_混凝土路缘',(.45,.44,.4),.83,noise=.18)
    white=_mat('校园_标线与球架',(.78,.8,.75),.72)
    yellow=_mat('校园_道路黄线',(.75,.52,.07),.7)
    metal=_mat('校园_灯杆与栏杆',(.16,.19,.19),.39,.72)
    timber=_mat('校园_座椅木条',(.22,.09,.035),.65,noise=.23)
    red=_mat('校园_塑胶红跑道',(.31,.07,.038),.93,noise=.12)
    green_court=_mat('校园_球场墨绿丙烯酸',(.07,.22,.12),.9,noise=.1)
    blue_court=_mat('校园_球场蓝绿丙烯酸',(.025,.20,.22),.9,noise=.13)
    turf=_mat('校园_足球草坪',(.075,.20,.045),.97,noise=.26)
    water=_mat('校园_湖水',(.018,.105,.11),.16,.12)
    wp=next(n for n in water.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    wp.inputs['IOR'].default_value=1.333
    wp.inputs['Coat Weight'].default_value=.35
    wn=water.node_tree.nodes.new('ShaderNodeTexNoise')
    _enum(wn,'noise_dimensions','3D');_enum(wn,'noise_type','FBM')
    wn.inputs['Scale'].default_value=2.4
    wn.inputs['Detail'].default_value=2
    wt=water.node_tree.nodes.new('ShaderNodeTexCoord')
    wb=water.node_tree.nodes.new('ShaderNodeBump')
    wb.inputs['Strength'].default_value=.18;wb.inputs['Distance'].default_value=.055
    water.node_tree.links.new(wt.outputs['Object'],wn.inputs['Vector'])
    water.node_tree.links.new(wn.outputs['Fac'],wb.inputs['Height'])
    water.node_tree.links.new(wb.outputs['Normal'],wp.inputs['Normal'])
    bground=Batch('连续校园地表_无沙盘底座',grass,ground)
    bcontext=Batch('校外连续背景_深绿推断地表',backdrop,ground)
    bgreen=Batch('地图绿地_草土细节',grass,ground)
    bpave=Batch('广场与建筑周边铺装',paving,ground)
    broads=Batch('道路_真实沥青',asphalt,roadcol)
    bpaths=Batch('步道_石材',paving,roadcol)
    bcurb=Batch('路缘和湖岸压顶',curb,roadcol)
    bbridge=Batch('中博湖桥_白色混凝土栏杆与桥身',_mat('桥梁_浅灰白混凝土',(.53,.54,.50),.8,noise=.09),roadcol)
    bwhite=Batch('道路白色标线',white,roadcol)
    byellow=Batch('道路中央虚线',yellow,roadcol)
    bwater=Batch('水体_地图岸线',water,watercol)
    bred=Batch('运动区红色缓冲面',red,sportscol)
    bcourt=Batch('篮球与排球场地',blue_court,sportscol)
    btennis=Batch('网球场地',green_court,sportscol)
    bturf=Batch('足球草坪',turf,sportscol)
    bsline=Batch('体育场地线_按标准尺寸推断',white,sportscol)
    bpipe=Batch('运动器械',white,sportscol)
    bmetal=Batch('校园路灯与栏杆',metal,furniture)
    bwood=Batch('座椅木条与篮板',timber,furniture)
    blamp=Batch('路灯灯面',_mat('校园_磨砂灯面',(.9,.9,.8),.25),furniture)
    stats={'tree_instances':0,'inferred_trees':0,'mapped_trees':0,'willow_instances':0,'roads':len(data.get('roads',[])),'bridge_spans':0,'water_bodies':len(data.get('waters',[])),'sports_surfaces':len(data.get('sports',[])),'courts':0,'inferred_athletics_tracks':0,'street_lamps':0,'benches':0,'geometry_notes':['All tree species and unmapped placements are inferred.','Court subdivision, markings, furniture and road widths are not surveyed.','Ground datum is flat Z=0; inferred Ding hill relative rise 16m within mapped wood polygon, not OSM absolute ele=31m.','Bridge alignment and bridge=yes are mapped; low pale balustrade is photo-supported, dimensions/relative deck rise inferred.']}
    xs=[p[0] for p in data['boundary']['outer']];ys=[p[1] for p in data['boundary']['outer']]
    # A continuous exterior plane avoids the miniature display-base appearance.
    bcontext.face([(min(xs)-6000,min(ys)-6000,-.045),(max(xs)+6000,min(ys)-6000,-.045),(max(xs)+6000,max(ys)+6000,-.045),(min(xs)-6000,max(ys)+6000,-.045)])
    bground.polygon(data['boundary'],-.025)
    hill=next((g for g in data.get('greens',[]) if g.get('id')=='osm_way_224938414'),None)
    def elevation(x,y):
        if hill is None or not _in_record((x,y),hill):return 0
        # Absolute ele=31m does not define a relative rise. Keep this explicit.
        rr=((x-87.616)/190)**2+((y-164.056)/300)**2
        edge=min(_dist_seg((x,y),a,b) for a,b in zip(hill['outer'],hill['outer'][1:]+hill['outer'][:1]))
        return 16*math.exp(-1.8*rr)*min(1,edge/34)
    if hill:
        hx=[p[0] for p in hill['outer']];hy=[p[1] for p in hill['outer']]
        for x in range(math.floor(min(hx)),math.ceil(max(hx)),8):
            for y in range(math.floor(min(hy)),math.ceil(max(hy)),8):
                h=[elevation(x+dx,y+dy) for dx,dy in ((0,0),(8,0),(8,8),(0,8))]
                if max(h)>.02:
                    vs=[(x+dx,y+dy,hh-.025) for (dx,dy),hh in zip(((0,0),(8,0),(8,8),(0,8)),h)]
                    bground.face([vs[0],vs[1],vs[2]]);bground.face([vs[0],vs[2],vs[3]])
    for g in data.get('greens',[]):bgreen.polygon(g,.005)
    for g in data.get('surfaces',[]):bpave.polygon(g,.075)
    # Official gallery-19 shows a broad hard-paved forecourt below the library
    # stair. Rectangle edges are a modelling inference pending closer survey.
    library_plaza={'outer':[[112,-166],[148,-166],[148,-45],[112,-45]],'holes':[]}
    bpave.polygon(library_plaza,.092)
    stats['geometry_notes'].append('Library forecourt paving supported by gallery-19; x112..148/y-166..-45 perimeter is inferred.')
    south_plaza={'outer':[[103.8,-690],[177,-690],[177,-615],[103.8,-615]],'holes':[],'crown_clearance':True}
    stone_island={'outer':[(133.4+4.4*math.cos(i*TAU/64),-670.5+12*math.sin(i*TAU/64)) for i in range(64)],'holes':[]}
    grounded_buildings=[r for r in data.get('buildings',[]) if not r.get('underground') and r.get('min_height',0)<2.5]
    south_obstacles=grounded_buildings+data.get('waters',[])+[stone_island]
    stats['south_entrance_paving_m2']=round(_clipped_rectangle(broads,(103.8,-690,177,-615),south_obstacles,.065),2)
    stats['geometry_notes'].append('South entrance hard-paved forecourt observed in gallery-01; x103.8..177/y-690..-615 perimeter inferred. Grounded buildings/water and the unchanged Tengfei stone island are cut out. Elevated gateway roofs do not remove ground paving. Existing road markings remain above this surface.')
    specific_plazas=[]
    new_gym=next((b for b in data.get('buildings',[]) if b['id']=='osm_way_1281082570'),None)
    if new_gym:
        # The completion panorama shows continuous pale paving across both
        # entrances, with stairs reaching local +/-47m. The generated facade
        # projects beyond its simplified OSM outline; include that real extent.
        obstacles=[r for r in grounded_buildings if r['id']!=new_gym['id']]+data.get('waters',[])+data.get('sports',[])
        record,area=_oriented_plaza(bpave,new_gym['center'],(-60,-50.5,60,50.5),math.radians(29.8),obstacles,.085)
        record['id']='photo_new_gym_paved_apron';specific_plazas.append(record)
        stats['new_gym_paved_apron_m2']=round(area,2)
        stats['geometry_notes'].append('New gym completion panorama supports pale hardstanding, central court and both stair approaches. Local apron bounds +/-60m x +/-50.5m at 29.8deg are inferred; gym itself is not subtracted because the central court/undercroft must be paved. Adjacent buildings, mapped sports polygons and water are subtracted. Full apron participates in crown clearance.')
    canteen=next((b for b in data.get('buildings',[]) if b['id']=='njupt_k_dining_04'),None)
    if canteen:
        # Only the red entrance/outer-stair approach is demonstrated by the
        # completed photograph; retain the surrounding landscaped courtyards.
        angle=math.radians(18.5);ca,sa=math.cos(angle),math.sin(angle);cx,cy=canteen['center']
        local=[((p[0]-cx)*ca+(p[1]-cy)*sa,-(p[0]-cx)*sa+(p[1]-cy)*ca) for p in canteen['outer']]
        xmax=max(p[0] for p in local);ymin=min(p[1] for p in local);ymax=max(p[1] for p in local)
        splity=ymin+(ymax-ymin)*.47
        obstacles=[r for r in grounded_buildings if r['id']!=canteen['id']]+data.get('waters',[])+data.get('sports',[])
        record,area=_oriented_plaza(bpave,canteen['center'],(xmax-.4,splity-1.0,xmax+7.0,ymax+1.0),angle,obstacles,.083)
        record['id']='photo_fourth_canteen_entry_paving';specific_plazas.append(record)
        stats['fourth_canteen_entry_paving_m2']=round(area,2)
        stats['geometry_notes'].append('Fourth-canteen completion photograph shows stone entry paving. Only the red entrance and external-stair frontage receives a 7m local apron; precise limits are inferred. Remaining courtyard green space is retained.')
    # Paved building aprons are inference; keep the original footprint editable.
    for b in data.get('buildings',[]):
        if b.get('underground'):continue
        pts=_ring(b['outer'])
        for a,p in zip(pts,pts[1:]+pts[:1]):bpave.line([a,p],2.2,.045)
        for hole in b.get('holes',[]):bpave.polygon({'outer':hole},.05)
    for w in data.get('waters',[]):
        bwater.polygon(w,.045)
        ring=_ring(w['outer'])
        # Narrow stone bank cap follows real mapped edges, leaving lake shape intact.
        bcurb.line(ring,.68,.08,True)
        for a,b in zip(ring,ring[1:]+ring[:1]):
            bcurb.face([(a[0],a[1],-.5),(b[0],b[1],-.5),(b[0],b[1],.09),(a[0],a[1],.09)])
    # Athletics circuits are photo-supported but not mapped as tracks in OSM.
    inferred_tracks=[]
    for s in data.get('sports',[]):
        if s.get('sport')=='soccer':
            cc,ll,ww,aa=_oriented_bounds(s)
            radius=max(36.5,ww/2+1.5)
            outer=_stadium(cc,aa,radius+9.76)
            inferred_tracks.append({'outer':outer,'holes':[],'center':cc,'radius':radius,'angle':aa})
    occupancy_data=dict(data)
    occupancy_data['sports']=data.get('sports',[])+inferred_tracks
    occupancy_data['surfaces']=data.get('surfaces',[])+[library_plaza,south_plaza]+specific_plazas
    # The paired Yingyuan 55/52 low connecting entrance extends between two
    # existing OSM footprints. Match the generated link once, to protect it
    # from tree crowns without inventing another building asset.
    ya=(-265.9,414.0);yb=(-277.5,433.0)
    yl=math.dist(ya,yb);yn=((yb[1]-ya[1])/yl,-(yb[0]-ya[0])/yl)
    ying_link={'outer':[(p[0]+side*yn[0]*3.3,p[1]+side*yn[1]*3.3) for p,side in ((ya,-1),(yb,-1),(yb,1),(ya,1))],'holes':[]}
    occupancy_data['buildings']=data.get('buildings',[])+[ying_link]
    stats['geometry_notes'].append('Yingyuan 55/52 shared link is included in crown clearance; its measured footprint is not available.')
    occupancy=Occupancy(occupancy_data)
    roadside_candidates=[]
    for road in data.get('roads',[]):
        pts=_densify(road['points']);w=road.get('width',5.5);tags=road.get('tags',{})
        if len(pts)<2:continue
        pedestrian=tags.get('highway') in ('path','footway','pedestrian','steps')
        target=bpaths if pedestrian else broads
        z=.105 if pedestrian else .115
        target.line(pts,w,z)
        if w>=4:
            for side in (-1,1):
                curbline=_offset(pts,side*(w/2+.12))
                bcurb.line(curbline,.24,z+.12)
                if not pedestrian:bpaths.line(_offset(pts,side*(w/2+1)),1.65,.10)
        if not pedestrian and w>=6:
            for side in (-1,1):bwhite.line(_offset(pts,side*(w/2-.32)),.10,z+.008)
            for p,a in _sample_line(pts,8,1):
                q=(p[0]+2.7*math.cos(a),p[1]+2.7*math.sin(a))
                byellow.line([p,q],.11,z+.009)
        if w>=4:
            south_avenue=sum(p[1] for p in pts)/len(pts)<-410
            for p,a in _sample_line(pts,14 if south_avenue else 20,4):
                for side in (-1,1):
                    d=w/2+3.2
                    roadside_candidates.append((p[0]-side*math.sin(a)*d,p[1]+side*math.cos(a)*d))
            for p,a in _sample_line(pts,43,15):
                d=w/2+1.65
                x,y=p[0]-math.sin(a)*d,p[1]+math.cos(a)*d
                if not _in_record((x,y),data['boundary']):continue
                # Keep the photographed central stair-to-lawn approach clear.
                if 115<=x<=145 and -123<=y<=-89:continue
                if 125<=x<=148 and -686<=y<=-628:continue
                # Furniture should not intersect a building even when a source road is close.
                if any(_in_record((x,y),b) for b in data.get('buildings',[])):continue
                bmetal.rod((x,y,.16),(x,y,6.5),.075,8,.045)
                bcurb.box((x,y,.25),(.35,.35,.4))
                arm=(x+math.sin(a)*1.1,y-math.cos(a)*1.1,6.2)
                bmetal.rod((x,y,6.35),arm,.055,7)
                bmetal.box(arm,(.8,.24,.12),a+math.pi/2)
                blamp.box((arm[0],arm[1],arm[2]-.066),(.65,.20,.025),a+math.pi/2)
                stats['street_lamps']+=1
        if tags.get('bridge') in ('yes','viaduct'):
            # The main lake crossing is OSM way 226966740, bridge=yes. Keep the
            # mapped alignment; the official gallery-02 supports a pale parapet.
            # Raised asphalt/sidewalk strips cover the underlying flat road.
            def deck_z(p):
                end_distance=min(math.hypot(p[0]-pts[0][0],p[1]-pts[0][1]),math.hypot(p[0]-pts[-1][0],p[1]-pts[-1][1]))
                return .115+.72*min(1,end_distance/16)
            broads.line(pts,w,deck_z)
            bbridge.line(pts,w+3.65,lambda p:deck_z(p)-.17)
            for side in (-1,1):
                walk=_offset(pts,side*(w/2+.78))
                bpaths.line(walk,1.55,lambda p:deck_z(p)+.10)
                rail=_offset(pts,side*(w/2+1.63))
                bbridge.line(rail,.30,lambda p:deck_z(p)+.18)
                for a,b in zip(rail,rail[1:]):
                    # White stone-like coping and two clearly readable rails.
                    for h in (.64,1.15):bbridge.rod((*a,deck_z(a)+h),(*b,deck_z(b)+h),.075,6)
                for p,a in _sample_line(rail,2.7):
                    zz=deck_z(p)
                    bbridge.box((p[0],p[1],zz+.68),(.20,.20,1.04),a)
                    bbridge.box((p[0],p[1],zz+1.22),(.29,.29,.12),a)
                    # Narrow intermediate balusters make a solid-looking bridge
                    # parapet at useful ground-level viewing distances.
                for p,a in _sample_line(rail,.68,.34):
                    zz=deck_z(p)
                    bbridge.box((p[0],p[1],zz+.84),(.06,.055,.48),a)
            for p,a in _sample_line(pts,13,6):
                if any(_in_record(p,water) for water in data.get('waters',[])):
                    bbridge.box((p[0],p[1],deck_z(p)/2-.22),(1.0,w+2.5,deck_z(p)+.45),a)
            stats['bridge_spans']+=1
    # Individual court markings and equipment inside mapped sports precincts.
    court_sizes={'basketball':(28,15,32,19),'tennis':(23.77,10.97,34,17),'volleyball':(18,9,22,13),'handball':(40,20,42,22)}
    for s in data.get('sports',[]):
        kind=s.get('sport','unknown')
        center,L,W,angle=_oriented_bounds(s)
        if kind=='soccer':
            bturf.polygon(s,.18)
            _court(bturf,bsline,bpipe,center,min(105,L-3),min(68,W-3),angle,kind,bwood)
            stats['courts']+=1
        else:
            bred.polygon(s,.17)
            if kind not in court_sizes:continue
            l,w,sx,sy=court_sizes[kind]
            nx=max(1,int((L+.5)/sx));ny=max(1,int((W+.5)/sy))
            c,si=math.cos(angle),math.sin(angle)
            for ix in range(nx):
                for iy in range(ny):
                    u=(ix-(nx-1)/2)*sx;v=(iy-(ny-1)/2)*sy
                    cc=(center[0]+u*c-v*si,center[1]+u*si+v*c)
                    _court(btennis if kind=='tennis' else bcourt,bsline,bpipe,cc,min(l,L-2),min(w,W-2),angle,kind,bwood)
                    stats['courts']+=1
        # Sports-area chain-link approximation: perimeter bars and tension wire.
        if kind in ('tennis','basketball'):
            ring=_ring(s['outer']);ring.append(ring[0])
            for p,_ in _sample_line(ring,3.5):bmetal.rod((*p,.18),(*p,3.3),.04)
            for a,b in zip(ring,ring[1:]):
                for h in (.25,1.75,3.2):bmetal.rod((*a,h),(*b,h),.014,5)
    for tr in data.get('tracks',[]):
        pts=tr.get('points',tr.get('outer',[]));w=tr.get('width',8.5)
        if len(pts)<3:continue
        bred.line(pts,w,.18,True)
        lanes=max(4,round(w/1.22))
        for i in range(lanes+1):bsline.line(_offset(pts,-w/2+i*w/lanes),.06,.192,True)
    for tr in inferred_tracks:
        cc,aa,rr=tr['center'],tr['angle'],tr['radius']
        bred.line(_stadium(cc,aa,rr+4.88),9.76,.19,True)
        for i in range(9):bsline.line(_stadium(cc,aa,rr+1.22*i),.055,.203,True)
        for side in (-1,1):
            c,s=math.cos(aa),math.sin(aa)
            p0=(cc[0]-side*rr*s,cc[1]+side*rr*c)
            p1=(cc[0]-side*(rr+9.76)*s,cc[1]+side*(rr+9.76)*c)
            bsline.line([p0,p1],.12,.207)
        stats['inferred_athletics_tracks']+=1
    source=_tree_source()
    if source is None:
        raise RuntimeError('Missing verified Poly Haven tree: run src/blender/download_assets.ps1')
    tree_height=max(v[2] for v in source.bound_box)-min(v[2] for v in source.bound_box)
    tree_bottom=min(v[2] for v in source.bound_box)
    tree_radius=max(math.hypot(v.co.x,v.co.y) for v in source.data.vertices)
    stats['crown_collision_rejections']=0
    stats['tree_clearance_rule']='Actual scaled mesh XY radial crown extent + 0.4m against building exterior, courtyard walls and sports surfaces.'
    grid=defaultdict(list)
    def add_tree(p,height,kind='inferred'):
        sc=height/tree_height
        sx=sc*rng.uniform(.78,1.03);sy=sc*rng.uniform(.78,1.03)
        crown=tree_radius*max(sx,sy)
        if not occupancy.free(p,crown_radius=crown):
            stats['crown_collision_rejections']+=1
            return False
        if any(_in_record(p,r) for r in data.get('landscape_exclusions',[])):return False
        # Library stair/entrance exclusion includes crown clearance around the
        # photographed central approach, not just the trunk footprint.
        if 122 <= p[0] <= 158 and -132 <= p[1] <= -78:return False
        # South-gate masonry and sign approaches, with 3m crown clearance.
        if 122 <= p[0] <= 146 and -690 <= p[1] <= -647:return False
        if 154 <= p[0] <= 181 and -686 <= p[1] <= -659:return False
        if 105 <= p[0] <= 180 and -693 <= p[1] <= -617:return False
        key=(math.floor(p[0]/7),math.floor(p[1]/7))
        for i in range(key[0]-1,key[0]+2):
            for j in range(key[1]-1,key[1]+2):
                if any(math.hypot(p[0]-q[0],p[1]-q[1])<5.7 for q in grid[i,j]):return False
        ob=bpy.data.objects.new(f'乔木_{stats["tree_instances"]:04d}',source.data)
        treecol.objects.link(ob)
        ob.location=(p[0],p[1],elevation(*p)+.02-tree_bottom*sc)
        ob.scale=(sx,sy,sc)
        ob.rotation_euler.z=rng.random()*TAU
        ob['placement_evidence']=kind
        ob['species']='generic broadleaf surrogate; actual campus species unverified'
        ob['crown_collision_radius_m']=crown
        grid[key].append(p)
        stats['tree_instances']+=1
        stats['mapped_trees' if kind=='osm_tree' else 'inferred_trees']+=1
        return True
    willow=_willow_source()
    willow_radius=max(math.hypot(v.co.x,v.co.y) for ob in willow.objects if ob.type=='MESH' for v in ob.data.vertices)
    for water_rec in data.get('waters',[]):
        ring=_ring(water_rec['outer']);ring.append(ring[0])
        for p,a in _sample_line(ring,19,5):
            for side in (-1,1):
                q=(p[0]-math.sin(a)*side*3.4,p[1]+math.cos(a)*side*3.4)
                sc=rng.uniform(.95,1.4)
                if not occupancy.free(q,crown_radius=willow_radius*sc):
                    stats['crown_collision_rejections']+=1
                    continue
                if any(_in_record(q,r) for r in data.get('landscape_exclusions',[])):continue
                if 122<=q[0]<=158 and -132<=q[1]<=-78:continue
                if 122<=q[0]<=146 and -690<=q[1]<=-647:continue
                if 154<=q[0]<=181 and -686<=q[1]<=-659:continue
                if 105<=q[0]<=180 and -693<=q[1]<=-617:continue
                ob=bpy.data.objects.new(f'湖岸垂柳_{stats["willow_instances"]:03d}',None)
                _enum(ob,'instance_type','COLLECTION')
                ob.instance_collection=willow
                ob.location=(*q,.02)
                ob.scale=(sc,sc,sc)
                ob.rotation_euler.z=rng.random()*TAU
                ob['placement_evidence']='inferred lake bank; drooping habit visible in official gallery-02'
                ob['crown_collision_radius_m']=willow_radius*sc
                treecol.objects.link(ob)
                grid[math.floor(q[0]/7),math.floor(q[1]/7)].append(q)
                stats['willow_instances']+=1
                break
    for t in data.get('trees',[]):add_tree(t['point'],rng.uniform(8,13),'osm_tree')
    # Road rows follow mapped road alignments, with polygon collision checks.
    for p in roadside_candidates:add_tree(p,rng.uniform(9.3,11.1),'inferred roadside row')
    for g in data.get('greens',[]):
        dense=g.get('vegetation') in ('wood','forest','scrub','park')
        density=.85 if dense else .35
        spacing=12.3 if dense else 18.0
        x0=min(p[0] for p in g['outer']);x1=max(p[0] for p in g['outer'])
        y0=min(p[1] for p in g['outer']);y1=max(p[1] for p in g['outer'])
        for ix in range(int((x1-x0)/spacing)+1):
            for iy in range(int((y1-y0)/spacing)+1):
                if rng.random()>density:continue
                p=(x0+(ix+rng.uniform(-.28,.28))*spacing,y0+(iy+rng.uniform(-.28,.28))*spacing)
                if _in_record(p,g):add_tree(p,rng.uniform(9,15) if dense else rng.uniform(7.5,12),'inferred in mapped green')
    # Mapped green coverage is incomplete. Add sparse gap trees, never on solids.
    for x in range(math.floor(min(xs)),math.ceil(max(xs)),18):
        for y in range(math.floor(min(ys)),math.ceil(max(ys)),18):
            if rng.random()>.18:continue
            p=(x+rng.uniform(-4,4),y+rng.uniform(-4,4))
            add_tree(p,rng.uniform(8,12),'inferred unclassified open space')
    for w in data.get('waters',[]):
        ring=_ring(w['outer']);ring.append(ring[0])
        for p,a in _sample_line(ring,62,12):
            # Both possible bank sides tested; only actual dry open side accepted.
            for side in (-1,1):
                q=(p[0]-math.sin(a)*side*3,p[1]+math.cos(a)*side*3)
                if not occupancy.free(q):continue
                for dx in (-.70,.70):
                    xx=q[0]+math.cos(a)*dx;yy=q[1]+math.sin(a)*dx
                    bmetal.box((xx,yy,.32),(.075,.45,.6),a)
                for dy in (-.16,0,.16):
                    bwood.box((q[0]-math.sin(a)*dy,q[1]+math.cos(a)*dy,.66),(1.85,.13,.07),a)
                for zz in (.86,1.03):
                    bwood.box((q[0]+math.sin(a)*.23,q[1]-math.cos(a)*.23,zz),(1.85,.075,.13),a)
                stats['benches']+=1
                break
    batches=[bground,bcontext,bgreen,bpave,broads,bpaths,bcurb,bbridge,bwhite,byellow,bwater,bred,bcourt,btennis,bturf,bsline,bpipe,bmetal,bwood,blamp]
    for batch in batches:
        if batch in (bground,bcontext,bwater):continue
        # Dense road/curb geometry follows the inferred hill instead of piercing it.
        batch.verts=[(x,y,z+elevation(x,y)) for x,y,z in batch.verts]
    made=[b.finish() for b in batches]
    stats['batched_mesh_objects']=sum(o is not None for o in made)
    stats['shared_tree_vertices']=len(source.data.vertices)
    stats['shared_tree_polygons']=len(source.data.polygons)
    stats['asset_manifest']='projects/blender/materials/manifest.json'
    collection['landscape_evidence']='Mapped polygons and road alignments from OSM; surface finishes, tree species, exact plant/furniture positions and sports subdivisions inferred.'
    print('LANDSCAPE_DONE',stats,flush=True)
    return stats
