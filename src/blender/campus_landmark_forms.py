"""Photo-constrained library and round hall, revision 2026-09-30.

All coordinates are local metres relative to canonical feature centres. The
visible morphology is reconstructed from photographs; unmeasured dimensions
remain hypotheses, enumerated in build/checks/refinement/library_round_audit.json.
This module deliberately does not call the generic window-with-sill generator.
"""
import json
import math
from pathlib import Path

import bpy
from campus_geometry import Batch, material, text_object
from campus_landmarks import new_asset

ROOT = Path(__file__).resolve().parents[2]


def _palette(m):
    return {
        **m,
        'cladding': material('Refined landmarks | pale stone', (.69, .69, .65), .69, noise=.026),
        'joint': material('Refined landmarks | stone joints', (.36, .38, .36), .86),
        'mullion': material('Refined landmarks | dark bronze aluminium', (.09, .115, .13), .32, .65),
        'blue': material('Library | saturated reflective blue', (.014, .058, .135), .19, .43),
        'blue_light': material('Library | soft blue reflection', (.019, .073, .154), .20, .43),
        'blue_dark': material('Library | blue shadow reflection', (.012, .046, .109), .18, .44),
        'hall_glass': material('Round hall | grey blue glazing', (.060, .107, .130), .19, .48),
        'hall_spandrel': material('Round hall | muted blue spandrel', (.065, .095, .13), .30, .30),
        'hall_coral': material('Round hall | coral crown panels', (.58, .115, .055), .65, noise=.018),
        'column': material('Round hall | satin metal column cladding', (.53, .55, .54), .37, .62),
        'rain_blue': material('Library | stair riser cyan paint', (.024, .38, .58), .73),
        'sign': material('Library | silver calligraphic lettering', (.76, .78, .74), .30, .62),
    }


def _flush_window(batch, centre, tangent, normal, z, width, height, glass, m, split=True):
    """Narrow flush glazing with thin frames, no invented projecting sill."""
    x,y=centre; ux,uy=tangent; nx,ny=normal
    angle=math.atan2(uy,ux)
    def rect(du,dn,dz,w,d,h,mat):
        batch.box((x+ux*du+nx*dn,y+uy*du+ny*dn,z+dz),(w,d,h),mat,angle)
    rect(0,.023,0,width+.10,.04,height+.1,m['dark'])
    rect(0,.052,0,width,.036,height,glass)
    for u in [-width/2,width/2]:rect(u,.086,0,.044,.055,height,m['mullion'])
    for zz in [-height/2,height/2]:rect(0,.086,zz,width,.055,.045,m['mullion'])
    if split:rect(0,.087,0,.043,.055,height,m['mullion'])
    rect(0,.09,height*.18,width,.055,.035,m['mullion'])


def _photo_sign(col,m):
    """Build actual observed calligraphic outlines, rather than substituting a font."""
    p=ROOT/'observations/spatial/derived/library_sign_contours.json'
    data=json.loads(p.read_text(encoding='utf-8'))
    for index,glyph in enumerate(data['glyphs']):
        height=3.22
        scale=height/glyph['source_pixel_height']
        xs=[p[0] for poly in glyph['polygons'] for p in poly['outer']]
        mid=(min(xs)+max(xs))/2
        curve=bpy.data.curves.new('Library photographed '+glyph['character'],'CURVE')
        curve.dimensions='2D';curve.fill_mode='BOTH';curve.resolution_u=1
        curve.extrude=.047;curve.bevel_depth=.01;curve.bevel_resolution=1
        for poly in glyph['polygons']:
            for ring in [poly['outer']]+poly['holes']:
                spl=curve.splines.new('POLY');spl.points.add(len(ring)-1)
                for q,(x,y) in zip(spl.points,ring):q.co=((x-mid)*scale,y*scale,0,1)
                spl.use_cyclic_u=True
        curve.materials.append(m['sign'])
        ob=bpy.data.objects.new('Library | photographed '+glyph['character']+' outline',curve)
        col.objects.link(ob)
        ob.location=(-36.92,(1-index)*8.6,23.00)
        ob.rotation_euler=(math.pi/2,0,-math.pi/2)
        ob['source_reference']=data['source']
        ob['reconstruction']='neutral-metal image silhouette; manually reviewed, perspective approximate'


def _riser_mural(batch,m):
    """36 physical treads; seven colour bands live only on vertical risers."""
    colors=[(.62,.035,.022),(.86,.24,.022),(.83,.63,.025),(.035,.34,.11),
            (.035,.35,.53),(.038,.14,.46),(.22,.038,.23)]
    mats=[material('Library | rainbow riser band %d'%i,c,.72) for i,c in enumerate(colors)]
    step_count=36;run=.4;rise=.15;width=27.7
    for i in range(step_count):
        x=-54.05+i*run;top=(i+1)*rise
        batch.box((x+run/2,0,top/2),(run,width,top),m['step'])
        batch.box((x-.009,0,top-rise/2),(.018,width,rise-.012),m['rain_blue'])
        t=(i+.5)/step_count
        # Photo-guided perspective ribbon; the exact students' artwork is not
        # claimed to be a measured orthographic texture or a new artwork design.
        full=22*(1-t)**1.18+4.5
        middle=-5.2*t+3.3*math.sin(math.pi*t)
        for j,ma in enumerate(mats):
            u=middle+full/2-full*(j+.5)/7
            a=max(-width/2,u-full/14);b=min(width/2,u+full/14)
            if b>a:batch.box((x-.021,(a+b)/2,top-rise/2),(.010,b-a,rise-.018),ma)
        # Thin exposed granite nosing; no rainbow paint on horizontal treads.
        batch.box((x+.018,0,top+.009),(.038,width,.018),m['step'])
    batch.box((-38.65,0,2.7),(2.0,width,5.4),m['step'])
    # Photo-visible cloud/dove motifs, represented as restrained riser geometry.
    # The white motifs are approximate contours, separately declared in audit.
    motifs=[(10.5,.28,1.5,.030),(8.5,.40,1.2,.026),(9.0,.64,2.0,.028),
            (10.0,.82,1.65,.022),(-10.2,.63,1.2,.022),(-10.6,.86,1.5,.025)]
    for uc,tc,wu,ht in motifs:
        for i in range(step_count):
            t=(i+.5)/step_count;dv=(t-tc)/ht
            if abs(dv)<1:
                w=wu*math.sqrt(1-dv*dv)
                batch.box((-54.05+i*run-.029,uc,(i+.5)*rise),(.006,w,rise-.03),m['white'])
    for u0,t0,scale in [(10,.47,.75),(8.1,.52,.60),(6.2,.58,.60),(4.8,.63,.55)]:
        for i in range(step_count):
            dt=(i/step_count-t0)*18
            if abs(dt)<.40:
                for s in [-1,1]:
                    du=s*(.25+max(0,dt)*1.2)*scale
                    batch.box((-54.05+i*run-.030,u0+du,(i+.5)*rise),(.006,.40*scale,rise-.025),m['white'])


def library(b,parent,m,font):
    col,stat=new_asset(b,parent,'library')
    col['generated_by']='src/blender/campus_landmark_forms.py'
    col['evidence_revision']='2026-09-30';col['stair_riser_count']=36
    m=_palette(m)
    body=Batch();trim=Batch();glazing=Batch();stairs=Batch()
    def box(u,v,z,w,d,h,ma):body.box((v,u,z),(d,w,h),ma)
    # The front outer wings are lower than the upper rear wings in gallery-19.
    # A continuous twenty-metre box erases this very recognizable roof step.
    # The narrow inner strips beside the atrium retain the taller front face.
    lower_roof=12.35
    for side in [-1,1]:
        box(side*37,0,lower_roof/2,36,68,lower_roof,m['cladding'])
        box(side*37,8,(lower_roof+20.2)/2,36,52,20.2-lower_roof,m['cladding'])
        box(side*25,-26,(lower_roof+20.2)/2,12,16,20.2-lower_roof,m['cladding'])
        box(side*43,-26,lower_roof+.045,23.4,15.5,.08,m['roof'])
        box(side*37,8,20.23,35.3,51.3,.10,m['roof'])
        box(side*25,-26,20.23,11.3,15.3,.10,m['roof'])
    box(0,23,10.1,38,19,20.2,m['cladding'])
    box(0,-23,10.1,38,19,20.2,m['cladding'])
    box(0,0,9.7,7.2,29,19.4,m['cladding'])
    # Tall front bookends, flush double slot windows, dressed stone joint grid.
    for side in [-1,1]:
        u=side*15.65
        box(u,-29.4,13.5,4.5,16.7,27,m['cladding'])
        for row in range(5):
            _flush_window(glazing,(-37.78,u),(0,1),(-1,0),2.9+row*4.55,1.9,3.55,m['blue_dark'],m)
        for z in range(1,27):trim.box((-37.8,u,z),(.022,4.5,.014),m['joint'])
        for du in [-1.35,0,1.35]:trim.box((-37.81,u+du,13.3),(.023,.012,26.3),m['joint'])
    # Main blue curtain wall. Deep dark backing ends below the open louver crown.
    box(0,-29.8,11.25,26.3,13.3,22.5,m['dark'])
    w=25.5;ncol=14;nrow=9;floor=2.45
    for row in range(nrow):
        z0=.6+row*floor
        for j in range(ncol):
            u=-w/2+(j+.5)*w/ncol
            ma=m[['blue','blue_light','blue_dark'][(j*7+row*5)%13//5]]
            glazing.box((-36.52,u,z0+floor/2),(.09,w/ncol-.037,floor-.037),ma)
    for j in range(ncol+1):glazing.box((-36.59,-w/2+j*w/ncol,11.63),(.09,.054,22.06),m['mullion'])
    for row in range(nrow+1):glazing.box((-36.60,0,.60+row*floor),(.09,w,.054),m['mullion'])
    # Photographed top-hung opening lights. They are real tilted faces with dark
    # openings and projected bottom rails, not black rectangles printed on glass.
    for j,row in [(1,3),(3,5),(5,4),(7,6),(9,2),(11,5),(4,7),(10,7)]:
        u=-w/2+(j+.5)*w/ncol;z=.60+row*floor+floor*.42
        ww=w/ncol-.13;hh=.82
        pts=[(-36.70,u-ww/2,z+hh/2),(-36.70,u+ww/2,z+hh/2),
             (-37.00,u+ww/2,z-hh/2),(-37.00,u-ww/2,z-hh/2)]
        glazing.face(pts,m['blue_dark'])
        for a,bb in zip(pts,pts[1:]+pts[:1]):glazing.pipe(a,bb,.032,m['mullion'],6)
    # Crown is structurally open: rear beam, oversailing front fascia, columns,
    # roof ribs and individual slats. There is no solid 3.8m black filler box.
    for v in [-39.0,-22.0]:box(0,v,27.35,40.5,1.0,1.0,m['cladding'])
    for u in [-19.7,19.7]:box(u,-30.5,27.35,1.05,18,1.0,m['cladding'])
    for u in [-13.0,-4.35,4.35,13.0]:box(u,-35.65,24.95,.46,1.0,4.25,m['cladding'])
    for j in range(13):box(-18+j*3,-30.5,27.07,.26,16.2,.28,m['cladding'])
    for z in [22.95+i*.28 for i in range(13)]:
        trim.box((-36.66,0,z),(.15,26.3,.072),m['slat'])
    for u in [-12.9,-8.7,-4.35,0,4.35,8.7,12.9]:
        trim.box((-36.56,u,24.65),(.10,.048,3.6),m['mullion'])
    _photo_sign(col,m)
    # Lower outer fore-wings, tall inner strips, and setback upper facade have
    # distinct window rhythms. Upper wings terminate in long louver bands.
    win=0
    for side in [-1,1]:
        for j in range(13):
            u=side*(20.1+j*2.66)
            inner=abs(u)<31
            for row in range(4 if inner else 3):
                z=2.4+row*3.83 if inner else 2.10+row*3.50
                _flush_window(glazing,(-34.055,u),(0,1),(-1,0),z,1.15,3.16 if inner else 2.90,m['blue_dark'],m)
                win+=1
            if not inner:
                _flush_window(glazing,(-18.055,u),(0,1),(-1,0),15.35,1.15,3.05,m['blue_dark'],m)
                win+=1
        u=side*37
        for v,uc,width in [(-34.06,side*25,10.8),(-18.06,side*43,22.8)]:
            trim.box((v,uc,18.55),(.07,width,1.72),m['dark'])
            for k in range(9):trim.box((v-.11,uc,17.83+k*.18),(.12,width,.060),m['slat'])
            for du in [-width/2,0,width/2]:trim.box((v-.12,uc+du,18.55),(.12,.065,1.7),m['mullion'])
        # Upper roof follows its L-shaped outline instead of spanning the
        # lower setback as a visually false floating beam.
        upper_ring=[(-34,side*19),(-34,side*31),(-18,side*31),(-18,side*55),
                    (34,side*55),(34,side*19)]
        for p,q in zip(upper_ring,upper_ring[1:]+upper_ring[:1]):
            body.beam((*p,20.65),(*q,20.65),.85,.9,m['cladding'])
        for p,q in [((-34,side*31),(-34,side*55)),((-34,side*55),(-18,side*55))]:
            body.beam((*p,lower_roof+.30),(*q,lower_roof+.30),.68,.60,m['cladding'])
        for zz in [1.0+i*1.06 for i in range(11)]:trim.box((-34.043,u,zz),(.02,35.7,.012),m['joint'])
        for zz in [12.6+i*1.06 for i in range(7)]:
            trim.box((-34.043,side*25,zz),(.02,11.8,.012),m['joint'])
            trim.box((-18.043,side*43,zz),(.02,23.8,.012),m['joint'])
        # Roof ribs lie on the photographed high rear plane.
        for v0 in [-8,26]:
            for j in range(9):box(u+(j-4)*3.9,v0,21.1,.22,15.3,.25,m['cladding'])
        # Visible roof service volumes remain modest and are marked inferred.
        for v0 in [-9,9]:
            box(u,v0,20.82,7.5,4.7,1.1,m['roofmetal'])
            for r in range(10):box(u+(r-4.5)*.62,v0,21.39,.08,4.5,.06,m['slat'])
    # Rear and end elevations follow the observed narrow vertical rhythm.
    for row in range(4):
        for j in range(28):
            _flush_window(glazing,(34.06,-52+j*3.85),(0,1),(1,0),2.6+row*4.15,1.45,3.05,m['blue_dark'],m)
            win+=1
    for side in [-1,1]:
        for j in range(16):
            v=-31+j*4.1
            for row in range(3 if v<-18 else 4):
                z=2.10+row*3.5 if v<-18 else 2.6+row*4.15
                _flush_window(glazing,(v,side*55.055),(1,0),(0,side),z,1.45,2.9 if v<-18 else 3.05,m['blue_dark'],m)
                win+=1
    # Courtyard glass makes the two interior voids spatially legible.
    for side in [-1,1]:
        for j in range(6):
            for row in range(4):
                _flush_window(glazing,(-11+j*4.4,side*18.94),(1,0),(0,-side),2.6+row*4.1,2.7,2.6,m['blue'],m)
    _riser_mural(stairs,m)
    for u in [-14.02,14.02]:
        stairs.pipe((-54.05,u,1.04),(-39.65,u,6.44),.048,m['frame'])
        stairs.pipe((-54.05,u,.56),(-39.65,u,5.96),.026,m['frame'])
        stairs.pipe((-39.65,u,6.44),(-36.85,u,6.44),.048,m['frame'])
        for i in range(0,37,3):
            x=-54.05+i*.4;z=min(5.4,i*.15)
            stairs.cylinder((x,u,z+.52),.033,1.04,m['frame'],10)
    # Raised entry door / slender steel-framed glass canopy, photo proportions.
    _flush_window(glazing,(-36.79,0),(0,1),(-1,0),6.87,5.4,2.92,m['blue_dark'],m)
    for u in [-2.7,-.9,.9,2.7]:glazing.box((-36.95,u,6.87),(.06,.055,2.92),m['frame'])
    for u in [-1.15,-.65,.65,1.15]:glazing.pipe((-37.015,u,6.60),(-37.015,u,7.3),.025,m['frame'],8)
    for j in range(13):
        u=(j-6)*2.10
        trim.box((-39.55,u,10.03),(5.65,.10,.18),m['frame'])
        for v in [-41.9,-39.55,-37.2]:glazing.box((v,u+1.03,10.14),(2.30,1.99,.045),m['glass3'])
        if j%2==0:trim.pipe((-37,u,11.0),(-41.9,u,10.03),.038,m['frame'],8)
    trim.box((-42.42,0,10.03),(.13,27.1,.20),m['frame'])
    # The photographed LIBRARY letters are serif, distinct from the calligraphy.
    serif_path=Path('C:/Windows/Fonts/times.ttf')
    serif=bpy.data.fonts.load(str(serif_path)) if serif_path.exists() else font
    text_object('Library | entrance serif lettering','LIBRARY',(-42.54,0,10.40),1.68,m['sign'],col,(math.pi/2,0,-math.pi/2),serif)
    body.object('Library | stone wings and open crown',col,bevel=.018)
    trim.object('Library | continuous louvers frames and stone joints',col)
    glazing.object('Library | blue curtain wall and opening lights',col)
    stairs.object('Library | 36 granite steps with painted risers',col)
    stat.update(height=27.85,levels=5,window_count=win+126,objects=len(col.objects),
                references=['observations/images/njupt/gallery-19.jpg','observations/images/njupt/guide-2020-13.png','observations/images/derived/rainbow_steps_2016.jpg'],
                observed_features=['36 risers in official text','riser-only mural in official text','photographed calligraphic sign outline','open crown','continuous wing louver bands','lower outer fore-wings and setback upper wings'],
                inferred_features=['meter dimensions','roof service volume dimensions','rear elevation spacing','courtyard internal wall dimensions','simplified rainbow/cloud/dove artwork'],
                visual_validation='pending full-scene rendered comparison; source correspondence is not survey validation')
    return col,stat


def _arc_slab(batch,cx,cy,r0,r1,a0,a1,z,h,mat,segments=64):
    """Annular sector with independent top/bottom surfaces, avoiding filled disks."""
    for i in range(segments):
        a=a0+(a1-a0)*i/segments;b=a0+(a1-a0)*(i+1)/segments
        ring=[(cx+r0*math.cos(a),cy+r0*math.sin(a)),(cx+r1*math.cos(a),cy+r1*math.sin(a)),
              (cx+r1*math.cos(b),cy+r1*math.sin(b)),(cx+r0*math.cos(b),cy+r0*math.sin(b))]
        surface=ring if r0>1e-8 else ring[:3]
        batch.face([(x,y,z+h) for x,y in surface],mat)
        batch.face([(x,y,z) for x,y in reversed(surface)],mat)
        for j in ([1,3] if r0>1e-8 else [1]):
            p,q=ring[j],ring[(j+1)%4]
            batch.face([(p[0],p[1],z),(q[0],q[1],z),(q[0],q[1],z+h),(p[0],p[1],z+h)],mat)
    # A closed annulus has no end cap; duplicate radial faces cause seams.
    if abs(a1-a0)<math.tau-1e-8:
        for a in [a0,a1]:
            batch.face([(cx+r0*math.cos(a),cy+r0*math.sin(a),z),(cx+r1*math.cos(a),cy+r1*math.sin(a),z),
                        (cx+r1*math.cos(a),cy+r1*math.sin(a),z+h),(cx+r0*math.cos(a),cy+r0*math.sin(a),z+h)],mat)


def round_hall(b,parent,m,font):
    col,stat=new_asset(b,parent,'round_hall')
    col['generated_by']='src/blender/campus_landmark_forms.py'
    col['evidence_revision']='2026-09-30'
    m=_palette(m);structure=Batch();glass=Batch();trim=Batch()
    # The lake side is a ground-level projecting curved terrace, not a solid
    # third-storey shelf. Its tall metal-clad columns are continuous to the roof.
    structure.cylinder((0,0,.28),20.75,.55,m['step'],128)
    _arc_slab(structure,10.7,0,0,22.4,-math.pi/2,math.pi/2,-.30,.78,m['step'],64)
    # The official aerial shows glazing below the lake-facing curved edge.
    # Remove the former full-height stone ring: actual window openings occupy
    # the middle band between a low sill and a shallow continuous lintel.
    plinth_sill_top=.72;plinth_lintel_bottom=1.80
    _arc_slab(structure,10.7,0,21.3,22.4,-math.pi/2,math.pi/2,.48,plinth_sill_top-.48,m['sand'],64)
    _arc_slab(structure,10.7,0,21.3,22.4,-math.pi/2,math.pi/2,plinth_lintel_bottom,1.98-plinth_lintel_bottom,m['cladding'],64)
    plinth_window_count=24;plinth_glass_radius=22.26
    for j in range(plinth_window_count):
        aa=-math.pi/2+j*math.pi/plinth_window_count
        bb=-math.pi/2+(j+1)*math.pi/plinth_window_count
        left_half=(.20 if j%4==0 else .030)/plinth_glass_radius
        right_half=(.20 if (j+1)%4==0 else .030)/plinth_glass_radius
        _arc_slab(glass,10.7,0,22.20,plinth_glass_radius,aa+left_half,bb-right_half,.75,1.02,m['blue_dark'],4)
    for j in range(plinth_window_count+1):
        aa=-math.pi/2+j*math.pi/plinth_window_count
        if j%4==0:
            half=.20/plinth_glass_radius
            _arc_slab(structure,10.7,0,21.3,22.4,max(-math.pi/2,aa-half),min(math.pi/2,aa+half),
                      plinth_sill_top,plinth_lintel_bottom-plinth_sill_top,m['cladding'],2)
        else:
            xx=10.7+22.30*math.cos(aa);yy=22.30*math.sin(aa)
            trim.box((xx,yy,1.26),(.055,.075,1.08),m['frame'],aa+math.pi/2)
    for z in [.746,1.774]:
        _arc_slab(trim,10.7,0,22.275,22.325,-math.pi/2,math.pi/2,z-.029,.058,m['frame'],96)
    _arc_slab(trim,10.7,0,21.15,22.65,-math.pi/2,math.pi/2,1.98,.15,m['cladding'],64)
    # A curved low glazed ground floor supports the drum; above are four glazed
    # storeys. Ground openings remain separate from the continuous upper facade.
    radius=19.9;segments=96;levels=5;fh=3.7
    glazing_radius=18.95
    railing_radius=20.34
    # The photographs show an exterior curved gallery between the glazing and
    # the balustrade. Its clear passage is >=1.10m at projecting window frames
    # and >=1.17m at the top-floor masonry piers; these are inferred dimensions.
    rail_limit=math.pi-math.asin(10.7/railing_radius)
    for level in range(levels):
        bottom=.60+level*fh
        structure.cylinder((0,0,bottom+.17),radius+.52,.34,m['cladding'],128)
        for j in range(segments):
            a=(j+.5)*math.tau/segments
            rr=radius-.11 if level==0 else glazing_radius
            x,y=rr*math.cos(a),rr*math.sin(a)
            # Opaque rectilinear western stair core occludes this section.
            if x<-16.8 and abs(y)<10.5:continue
            ang=a+math.pi/2;bay=math.tau*rr/segments
            if level==0 and x>4.5:
                # Photo-visible recessed lower open arcade, slender piers.
                if j%5==0:structure.box((x,y,bottom+1.85),(.5,.55,3.1),m['cladding'],ang)
                glass.box((x*.87,y*.87,bottom+1.7),(bay-.02,.06,2.70),m['hall_glass'],ang)
            else:
                glass.box((x,y,bottom+1.85),(bay-.045,.07,3.22),m['hall_glass'],ang)
                trim.box((x*1.008,y*1.008,bottom+1.85),(.045,.09,3.22),m['mullion'],ang)
                # Continuous lower spandrel and horizontal transoms.
                glass.box((x*1.004,y*1.004,bottom+.63),(bay-.025,.065,.62),m['hall_spandrel'],ang)
                for dz in [.32,.96,2.64,3.47]:trim.box((x*1.010,y*1.010,bottom+dz),(bay,.10,.05),m['frame'],ang)
        if level==levels-1:
            # The upper band is a sequence of grouped rectangular windows
            # separated by broad pale piers, rather than a continuous glass tube.
            for j in range(24):
                a=j*math.tau/24;rr=18.97;x,y=rr*math.cos(a),rr*math.sin(a)
                if x<-16.8 and abs(y)<10.5:continue
                structure.box((x,y,bottom+1.91),(.52,.32,3.14),m['cladding'],a+math.pi/2)
        if level>0:
            walking_z=bottom+.34
            # Slender metal rails sit on the structural slab, inside its edge.
            # Keep the western stair-core sector open instead of running a
            # railing through opaque walls. Curve subdivisions share end points.
            rail_segments=112
            for i in range(rail_segments):
                aa=-rail_limit+2*rail_limit*i/rail_segments
                bb=-rail_limit+2*rail_limit*(i+1)/rail_segments
                for dz,rr in [(1.06,.030),(.55,.015),(.14,.012)]:
                    trim.pipe((railing_radius*math.cos(aa),railing_radius*math.sin(aa),walking_z+dz),
                              (railing_radius*math.cos(bb),railing_radius*math.sin(bb),walking_z+dz),rr,m['frame'],8)
                if i%2==0:
                    xx=railing_radius*math.cos(aa);yy=railing_radius*math.sin(aa)
                    trim.cylinder((xx,yy,walking_z+.52),.024,1.04,m['frame'],8)
            for aa in [-rail_limit,rail_limit]:
                xx=railing_radius*math.cos(aa);yy=railing_radius*math.sin(aa)
                trim.cylinder((xx,yy,walking_z+.52),.024,1.04,m['frame'],8)
                for dz,rr in [(1.06,.030),(.55,.015)]:
                    trim.pipe((xx,yy,walking_z+dz),
                              (19.10*math.cos(aa),19.10*math.sin(aa),walking_z+dz),rr,m['frame'],8)
        # Silver floor edge with a restrained dark reveal under each projecting lip.
        _arc_slab(trim,0,0,radius+.35,radius+.71,0,math.tau,bottom+.03,.10,m['frame'],128)
        _arc_slab(trim,0,0,radius+.12,radius+.42,0,math.tau,bottom+.40,.065,m['mullion'],128)
    structure.cylinder((0,0,19.23),21.35,.74,m['cladding'],128)
    structure.cylinder((0,0,19.63),20.75,.08,m['roof'],128)
    # Western rectangular core and open elevated connecting frame.
    structure.box((-25,0,10.35),(14,20.6,20.7),m['cladding'])
    for y in [-10.34,10.34]:
        for x in [-28.5,-24,-19.5]:
            for row in range(5):
                _flush_window(glass,(x,y),(1,0),(0,1 if y>0 else -1),2.30+row*3.70,1.85,2.5,m['hall_glass'],m)
        for x in [-31.5,-18.5]:
            for z in range(2,20,3):
                for dx in [-.48,.48]:
                    for dz in [-.48,.48]:glass.box((x+dx,y*1.004,z+dz),(.36,.05,.36),m['hall_glass'])
    # Crown: offset coral service volume, expressed white cornice, and open
    # concrete beam frame across the western roof. The upper frame is not a disk.
    # A complete red service box rises well above the white crown frame. The
    # former 2.18m box left only a 0.46m visible stripe above that frame.
    crown_base=19.68;crown_top=23.33;crown_cap_top=23.51
    structure.box((-6,0,(crown_base+crown_top)/2),(17.5,20,crown_top-crown_base),m['hall_coral'])
    structure.box((-6,0,23.42),(18.1,20.55,.18),m['cladding'])
    for z in [20.04+i*.46 for i in range(8)]:
        for y in [-10.015,10.015]:trim.box((-6,y,z),(17.48,.014,.018),m['joint'])
        for x in [-14.765,2.765]:trim.box((x,0,z),(.014,20,.018),m['joint'])
    for y in [-12.0,12.0]:
        structure.box((-12.2,y,21.05),(42.0,.85,.70),m['cladding'])
        for x in [-32.4,-18.0,6.5]:structure.box((x,y,19.70),(.55,.55,2.4),m['cladding'])
    for x in [-32.4,-18,6.5]:structure.box((x,0,21.05),(.65,24.7,.70),m['cladding'])
    # Lakeward canopy = rectangular fascia around parallel open soffit ribs.
    # Tall round columns carry it from the plinth. Distinct from the western core.
    # Both rows stand outside the glass drum and inside the curved plinth.
    # Keeping an inner row at x=17.2 incorrectly embeds columns in five floors.
    for x in [22.0,30.2]:
        for y in [-9.0,-3.0,3.0,9.0]:
            structure.cylinder((x,y,9.58),.40,18.1,m['column'],32)
            structure.cylinder((x,y,.63),.48,.16,m['cladding'],32)
            for z in [3,6,9,12,15,18]:
                _arc_slab(trim,x,y,.399,.405,0,math.tau,z,.022,m['mullion'],24)
    for y in [-11.6,11.6]:structure.box((24.6,y,18.92),(20.4,.95,.92),m['cladding'])
    for x in [14.4,34.8]:structure.box((x,0,18.92),(.95,24.15,.92),m['cladding'])
    for j in range(15):structure.box((24.6,-10.8+j*1.54,18.74),(19.5,.18,.24),m['cladding'])
    # Terrace paving joints, steps, and lakefront edge drainage add physical scale.
    for y in range(-10,11,2):trim.box((25.8,y,.508),(13.2,.022,.016),m['joint'])
    for x in range(20,34,2):trim.box((x,0,.510),(.022,21.6,.016),m['joint'])
    for i in range(4):structure.box((22.3,-23.0-i*.33,.45-i*.11),(14,.34,.13),m['step'])
    # Curved building corners use real geometry with subtle bevelled slab edges.
    structure.object('Round hall | curved plinth drum and tall colonnade',col,bevel=.012)
    glass.object('Round hall | continuous segmented curtain wall',col)
    trim.object('Round hall | fine frames cornices and column joints',col)
    stat.update(height=crown_cap_top,levels=5,window_count=480+plinth_window_count,objects=len(col.objects),
                lake_plinth_facade={'kind':'openings between stone sill and lintel with segmented curved glass',
                                    'window_panes':plinth_window_count,'stone_pier_positions':7,
                                    'glass_outer_radius_m':plinth_glass_radius,'wall_outer_radius_m':22.4,
                                    'sill_top_m':plinth_sill_top,'lintel_bottom_m':plinth_lintel_bottom,
                                    'glass_bottom_m':.75,'glass_top_m':1.77,
                                    'source':'observations/images/njupt/gallery-02.jpg',
                                    'inferred':'Exact pane count, piers, frame sections and vertical dimensions'},
                gallery_geometry={'glazing_radius_m':glazing_radius,'railing_radius_m':railing_radius,
                                  'minimum_clear_width_m':1.10,'railing_height_m':1.06,
                                  'upper_pier_width_m':.52,'upper_pier_depth_m':.32,
                                  'upper_pier_grid_angle_deg':15.0,'crown_base_m':crown_base,
                                  'crown_top_m':crown_top,'crown_cap_top_m':crown_cap_top},
                references=['observations/images/njupt/gallery-01.jpg','observations/images/njupt/gallery-02.jpg','observations/images/njupt/gallery-07.jpg',
                            'observations/images/njupt/visiting_gallery_image_37.jpg','observations/images/njupt/visiting_gallery_image_43.jpg','observations/images/njupt/visiting_gallery_image_50.jpg'],
                observed_features=['low curved lake plinth','continuous round metal-clad columns','red crown above the white frame',
                                   'horizontal curtain-wall bands','wide top-floor white piers separating grouped windows',
                                   'external curved galleries with slender metal balustrades','glazed lake-side curved lower plinth'],
                inferred_features=['exact heights and radii','hidden floor arrangement','complete column count and spacing',
                                   'rear glazing spacing','balustrade pitch and gallery dimensions','lower plinth pane count and dimensions'],
                visual_validation='pending full-scene rendered comparison; source correspondence is not survey validation')
    return col,stat
