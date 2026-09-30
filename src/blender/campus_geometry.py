"""Small deterministic mesh primitives for the evidence-driven campus builder.

Coordinates are metres. Details are batched by building so a whole campus does
not turn into hundreds of thousands of Blender objects.
"""
import math
import bpy
from mathutils import Vector
from mathutils.geometry import tessellate_polygon


def material(name, color, roughness=.65, metallic=0., noise=0., emission=0.):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (*color[:3], color[3] if len(color) > 3 else 1.)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = mat.diffuse_color
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    if emission:
        bsdf.inputs['Emission Color'].default_value = (*color[:3], 1)
        bsdf.inputs['Emission Strength'].default_value = emission
    if noise:
        geo = nodes.new('ShaderNodeNewGeometry')
        tex = nodes.new('ShaderNodeTexNoise')
        tex.inputs['Scale'].default_value = 2.2
        tex.inputs['Detail'].default_value = 3.
        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].position = .13
        ramp.color_ramp.elements[0].color = tuple(c*(1-noise) for c in color[:3])+(1,)
        ramp.color_ramp.elements[1].position = .88
        ramp.color_ramp.elements[1].color = tuple(min(1,c*(1+noise)) for c in color[:3])+(1,)
        bump=nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value=.16
        bump.inputs['Distance'].default_value=.025
        link=mat.node_tree.links
        link.new(geo.outputs['Position'],tex.inputs['Vector'])
        link.new(tex.outputs['Fac'],ramp.inputs['Fac'])
        link.new(ramp.outputs['Color'],bsdf.inputs['Base Color'])
        link.new(tex.outputs['Fac'],bump.inputs['Height'])
        link.new(bump.outputs['Normal'],bsdf.inputs['Normal'])
    return mat


class Batch:
    def __init__(self):
        self.vertices=[]
        self.faces=[]
        self.material_ids=[]
        self.materials=[]

    def mi(self,mat):
        if mat not in self.materials:
            self.materials.append(mat)
        return self.materials.index(mat)

    def face(self,points,mat):
        offset=len(self.vertices)
        self.vertices.extend(tuple(p) for p in points)
        self.faces.append(tuple(range(offset,offset+len(points))))
        self.material_ids.append(self.mi(mat))

    def box(self,center,size,mat,angle=0):
        x,y,z=center
        a,b,c=(v*.5 for v in size)
        ca,sa=math.cos(angle),math.sin(angle)
        vv=[]
        for dx,dy,dz in [(-a,-b,-c),(a,-b,-c),(a,b,-c),(-a,b,-c),(-a,-b,c),(a,-b,c),(a,b,c),(-a,b,c)]:
            vv.append((x+ca*dx-sa*dy,y+sa*dx+ca*dy,z+dz))
        offset=len(self.vertices)
        self.vertices.extend(vv)
        mid=self.mi(mat)
        for f in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]:
            self.faces.append(tuple(offset+i for i in f))
            self.material_ids.append(mid)

    def beam(self,start,end,width,height,mat):
        dx,dy=end[0]-start[0],end[1]-start[1]
        self.box(((start[0]+end[0])/2,(start[1]+end[1])/2,(start[2]+end[2])/2),
                 (math.hypot(dx,dy),width,height),mat,math.atan2(dy,dx))

    def cylinder(self,center,radius,depth,mat,segments=16,top_radius=None):
        if top_radius is None: top_radius=radius
        x,y,z=center
        bottom=[(x+radius*math.cos(i*2*math.pi/segments),y+radius*math.sin(i*2*math.pi/segments),z-depth/2) for i in range(segments)]
        top=[(x+top_radius*math.cos(i*2*math.pi/segments),y+top_radius*math.sin(i*2*math.pi/segments),z+depth/2) for i in range(segments)]
        self.face(list(reversed(bottom)),mat)
        self.face(top,mat)
        for i in range(segments): self.face([bottom[i],bottom[(i+1)%segments],top[(i+1)%segments],top[i]],mat)

    def pipe(self,start,end,radius,mat,segments=10):
        a,b=Vector(start),Vector(end)
        axis=(b-a).normalized()
        ref=Vector((0,0,1)) if abs(axis.z)<.9 else Vector((1,0,0))
        u=axis.cross(ref).normalized()*radius
        v=axis.cross(u).normalized()*radius
        aa=[a+u*math.cos(i*math.tau/segments)+v*math.sin(i*math.tau/segments) for i in range(segments)]
        bb=[p+b-a for p in aa]
        for i in range(segments): self.face([aa[i],aa[(i+1)%segments],bb[(i+1)%segments],bb[i]],mat)

    def extrude(self,outer,holes,z,height,wall,roof=None,triangles=None):
        roof=roof or wall
        for ring in [outer]+list(holes):
            for p,q in zip(ring,ring[1:]+ring[:1]):
                self.face([(p[0],p[1],z),(q[0],q[1],z),(q[0],q[1],z+height),(p[0],p[1],z+height)],wall)
        if triangles:
            for t in triangles: self.face([(p[0],p[1],z+height) for p in t],roof)
        elif not holes:
            vec=[Vector((p[0],p[1],z+height)) for p in outer]
            for t in tessellate_polygon([vec]):
                self.face([vec[i] for i in t] if isinstance(t[0],int) else t,roof)

    def object(self,name,collection,bevel=0):
        mesh=bpy.data.meshes.new(name)
        mesh.from_pydata(self.vertices,[],self.faces)
        for mat in self.materials: mesh.materials.append(mat)
        for p,mi in zip(mesh.polygons,self.material_ids): p.material_index=mi
        mesh.update()
        ob=bpy.data.objects.new(name,mesh)
        collection.objects.link(ob)
        if bevel:
            mod=ob.modifiers.new('Small real-world edge radius','BEVEL')
            mod.width=bevel
            mod.segments=2
        return ob


def point_inside(p,outer,holes=()):
    def inside(ring):
        hit=False
        x,y=p
        j=len(ring)-1
        for i in range(len(ring)):
            xi,yi=ring[i]; xj,yj=ring[j]
            if ((yi>y)!=(yj>y)) and x < (xj-xi)*(y-yi)/(yj-yi)+xi: hit=not hit
            j=i
        return hit
    return inside(outer) and not any(inside(h) for h in holes)


def signed_area(ring):
    return sum(p[0]*q[1]-q[0]*p[1] for p,q in zip(ring,ring[1:]+ring[:1]))*.5


def text_object(name,text,location,size,mat,collection,rotation=(math.pi/2,0,0),font=None):
    curve=bpy.data.curves.new(name,'FONT')
    curve.body=text
    curve.align_x='CENTER'
    curve.size=size
    curve.extrude=.018
    if font: curve.font=font
    curve.materials.append(mat)
    ob=bpy.data.objects.new(name,curve)
    collection.objects.link(ob)
    ob.location=location
    ob.rotation_euler=rotation
    if font:
        # Bake lettering outlines so asset files do not require a proprietary
        # Windows font installation. Preserve the words as editable metadata.
        bpy.context.view_layer.update()
        depsgraph=bpy.context.evaluated_depsgraph_get()
        mesh=bpy.data.meshes.new_from_object(ob.evaluated_get(depsgraph),depsgraph=depsgraph)
        baked=bpy.data.objects.new(name+' • outlined',mesh)
        collection.objects.link(baked)
        baked.matrix_world=ob.matrix_world.copy()
        baked['source_text']=text;baked['reference_font']=font.name
        bpy.data.objects.remove(ob,do_unlink=True)
        if curve.users==0:bpy.data.curves.remove(curve)
        ob=baked
    return ob
