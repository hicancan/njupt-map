"""South entrance, using official calligraphic outlines and photographed frames."""
from pathlib import Path
import math,json
import bpy
from campus_geometry import Batch,material

def gateway(b,parent,m,font):
    from campus_landmarks import new_asset
    col,stat=new_asset(b,parent,'south_gate')
    frame=Batch();joints=Batch();fixings=Batch()
    stone=material('Gate limestone • warm pale panels',(.61,.58,.49),.67,noise=.025)
    shade=material('Gate limestone joints',(.29,.28,.25),.8)
    metal=material('Gate title • brushed champagne gold',(.62,.40,.105),.26,.82)
    backing=material('Gate title • steel support',(.21,.23,.22),.4,.72)
    column=material('Gate columns • satin metal cladding',(.57,.59,.57),.32,.67)
    # Mapped roof span ~50.5m; front/back frame spacing follows the 20.5m roof.
    # Height 18m is community mapped, not a measurement. Pairing is photo-observed.
    for x in [-23.7,-10.0,10.0,23.7]:
        for y in [-8.65,8.65]:
            for dx in [-.47,.47]:
                frame.cylinder((x+dx,y,8.85),.24,17.7,column,24)
                frame.cylinder((x+dx,y,.13),.29,.26,column,24)
                for z in [2.8,5.6,8.4,11.2,14.0,16.8]:joints.cylinder((x+dx,y,z),.243,.024,shade,24)
    for y in [-9.1,9.1]:
        frame.box((0,y,17.62),(51.3,1.15,.72),stone)
        frame.box((0,y,18.01),(51.65,1.32,.13),stone)
        joints.box((0,y-.584,17.30),(51.2,.018,.033),shade)
        for x in range(-24,26,3):joints.box((x,y-.586,17.65),(.022,.018,.61),shade)
    for x in [-24.2,-12.3,0,12.3,24.2]:frame.box((x,0,17.65),(.53,19.5,.65),stone)
    for i in range(78):frame.box((-24.8+i*.645,0,17.66),(.075,18.0,.16),column)
    # Each character remains its own editable, closed, extruded outline.
    data=json.loads((Path(__file__).resolve().parents[2]/'projects/blender/identity/njupt_official_name.json').read_text(encoding='utf8'))
    ybase=max(g['bounds'][3] for g in data['glyphs'])
    for i,glyph in enumerate(data['glyphs']):
        curve=bpy.data.curves.new('Official calligraphy '+glyph['character'],'CURVE')
        curve.dimensions='2D';curve.resolution_u=2;curve.fill_mode='BOTH'
        curve.extrude=.070;curve.bevel_depth=.012;curve.bevel_resolution=2
        curve.materials.append(metal)
        mid=(glyph['bounds'][0]+glyph['bounds'][2])/2
        for ring in glyph['contours']:
            spline=curve.splines.new('POLY');spline.points.add(len(ring)-1)
            for point,(x,y) in zip(spline.points,ring):point.co=((x-mid)*.051,(ybase-y)*.051,0,1)
            spline.use_cyclic_u=True
        ob=bpy.data.objects.new('南门题字_'+glyph['character'],curve);col.objects.link(ob)
        ob.location=((i-2.5)*3.75,-9.80,18.18);ob.rotation_euler=(math.pi/2,0,0)
        ob['source_url']=data['source_url'];ob['source_type']='official vector outline; not a substitute typeface'
        for dx in [-.55,.55]:
            fixings.box(((i-2.5)*3.75+dx,-9.40,19.10),(.055,.065,1.95),backing)
            fixings.pipe(((i-2.5)*3.75+dx,-9.45,20.0),((i-2.5)*3.75+dx,-8.25,18.15),.035,backing,8)
    frame.object('South gate • paired columns and open stone frame',col,bevel=.035)
    joints.object('South gate • cladding joints and shadow reveals',col)
    fixings.object('South gate • letter mounting brackets',col)
    stat.update(height=22.1,levels=0,window_count=0,objects=len(col.objects),references=['observations/images/njupt/gallery-01.jpg','observations/documents/njupt/official-logo.ai'],confirmed=['Open double-depth frame','Paired slender columns','Gold calligraphic lettering outlines from official identity'],inferred=['Member sections and joint module','Letter mounting brackets and physical thickness','Letter installation spacing and height'])
    return col,stat
