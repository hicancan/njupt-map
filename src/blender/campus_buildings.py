"""Architectural generation constrained by observed campus footprints.

Exact plans/heights come from campus.json; unmeasured facade rhythms and roof
services are explicitly inferred, rather than claimed to be surveyed geometry.
"""
import math
import random
import hashlib
import bpy
from campus_geometry import Batch,material,point_inside,signed_area,text_object

YINGYUAN_IDS={'osm_way_'+str(i):n for i,n in zip(range(1173057031,1173057037),(50,53,54,51,55,52))}


def palette():
    return {
        'ivory':material('NJUPT • ivory mineral cladding',(.54,.54,.47),.76,noise=.06),
        'white':material('NJUPT • pale precast concrete',(.65,.66,.62),.7,noise=.05),
        'sand':material('NJUPT • warm limestone',(.48,.42,.30),.78,noise=.08),
        'legacywall':material('NJUPT • legacy academic warm facade',(.60,.49,.32),.78,noise=.06),
        'legacyred':material('NJUPT • legacy orange brick portals',(.44,.115,.035),.8,noise=.09),
        'gray':material('NJUPT • blue grey panels',(.31,.36,.37),.62,noise=.06),
        'red':material('NJUPT • terracotta vertical screens',(.39,.16,.09),.75,noise=.09),
        'dark':material('NJUPT • recessed shadow',(.033,.048,.053),.78),
        'frame':material('NJUPT • aluminium window frames',(.46,.49,.49),.35,.5),
        'roof':material('NJUPT • weathered roof membrane',(.22,.25,.24),.91,noise=.24),
        'roofmetal':material('NJUPT • standing seam zinc',(.38,.44,.48),.39,.65),
        'glass0':material('NJUPT • blue glazing 1',(.018,.045,.055),.16,.45),
        'glass1':material('NJUPT • blue glazing 2',(.022,.061,.068),.18,.45),
        'glass2':material('NJUPT • blue glazing 3',(.040,.085,.090),.23,.36),
        'glass3':material('NJUPT • pale sky glazing',(.055,.10,.12),.21,.38),
        'slat':material('NJUPT • charcoal louver',(.15,.18,.18),.63,.18),
        'gold':material('NJUPT • brass lettering',(.64,.38,.10),.27,.72),
        'step':material('NJUPT • granite steps',(.38,.39,.37),.87,noise=.15),
        'teachingtile':_tiled_wall('NJUPT • teaching ivory ceramic tile',(.60,.62,.57)),
        'dormtile':_tiled_wall('NJUPT • dormitory grey ceramic tile',(.48,.51,.47)),
        'academicbase':material('NJUPT • academic lower grey stone',(.26,.28,.27),.78,noise=.06),
        'yingwall':material('NJUPT • Yingyuan light grey cladding',(.61,.62,.59),.74,noise=.03),
        'yingband':material('NJUPT • Yingyuan charcoal floor ribbons',(.20,.22,.23),.73,noise=.035),
        'redscreen':material('NJUPT • materials research red fins',(.47,.095,.055),.57,.12),
        'kred':material('NJUPT • K group orange red panels',(.63,.12,.037),.72,noise=.025),
        'yellowrecess':material('NJUPT • Yingyuan warm recessed screen',(.40,.30,.15),.8),
    }


def _tiled_wall(name,color):
    """Metric triplanar ceramic joints; facade pixels are not photo textures."""
    mat=material(name,color,.73)
    if mat.get('metric_ceramic'):return mat
    n=mat.node_tree.nodes;link=mat.node_tree.links
    p=next(x for x in n if x.type=='BSDF_PRINCIPLED')
    geo=n.new('ShaderNodeNewGeometry');pos=n.new('ShaderNodeSeparateXYZ');nor=n.new('ShaderNodeSeparateXYZ')
    link.new(geo.outputs['Position'],pos.inputs[0]);link.new(geo.outputs['Normal'],nor.inputs[0])
    bricks=[]
    for axis in ('X','Y'):
        vector=n.new('ShaderNodeCombineXYZ');link.new(pos.outputs[axis],vector.inputs['X']);link.new(pos.outputs['Z'],vector.inputs['Y'])
        brick=n.new('ShaderNodeTexBrick');brick.offset=0;brick.offset_frequency=1
        brick.inputs['Scale'].default_value=1;brick.inputs['Brick Width'].default_value=.10;brick.inputs['Row Height'].default_value=.10
        brick.inputs['Mortar Size'].default_value=.0015;brick.inputs['Mortar Smooth'].default_value=.0008
        brick.inputs['Color1'].default_value=(*color,1);brick.inputs['Color2'].default_value=(*(c*.98 for c in color),1)
        brick.inputs['Mortar'].default_value=(*(c*.72 for c in color),1)
        link.new(vector.outputs[0],brick.inputs['Vector']);bricks.append(brick)
    absolute=n.new('ShaderNodeMath');absolute.operation='ABSOLUTE';link.new(nor.outputs['X'],absolute.inputs[0])
    mix=n.new('ShaderNodeMixRGB');link.new(absolute.outputs[0],mix.inputs[0]);link.new(bricks[0].outputs['Color'],mix.inputs[1]);link.new(bricks[1].outputs['Color'],mix.inputs[2])
    link.new(mix.outputs[0],p.inputs['Base Color'])
    bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.14;bump.inputs['Distance'].default_value=.0015
    link.new(mix.outputs[0],bump.inputs['Height']);link.new(bump.outputs[0],p.inputs['Normal'])
    mat['metric_ceramic']=True;mat['tile_size_status']='Approximate 100mm tile; photographic material family, not a measured module.'
    return mat


def classify(b):
    name=b.get('name','')
    tag=b.get('tags',{})
    x,y=b['center']
    if b['id'] in ['osm_way_'+str(n) for n in range(1173057050,1173057057)]:return 'legacy_academic'
    if '图书' in name or '档案' in name: return 'library'
    if '体育馆' in name: return 'gym'
    if '圆楼' in name: return 'round'
    if '学科' in name or '材料科学' in name: return 'science'
    if '食堂' in name or tag.get('amenity') in ['restaurant','canteen']: return 'dining'
    if tag.get('building') in ['dormitory','residential','apartments'] or name.isdigit(): return 'dorm'
    if '教' in name or '学院' in name or '实验' in name or '工程' in name or '文科' in name: return 'teaching'
    if '行政' in name: return 'admin'
    if b.get('area_m2',0)<100: return 'utility'
    return 'academic'


def window(batch,p,u,n,z,w,h,glass,m):
    x,y=p; ux,uy=u; nx,ny=n
    ang=math.atan2(uy,ux)
    def box(dx,dn,dz,sx,sy,sz,ma):
        batch.box((x+ux*dx+nx*dn,y+uy*dx+ny*dn,z+dz),(sx,sy,sz),ma,ang)
    box(0,.036,0,w+.16,.075,h+.16,m['dark'])
    box(0,.086,0,w,.048,h,glass)
    for dx in [-w/2,w/2]: box(dx,.14,0,.07,.11,h+.10,m['frame'])
    for dz in [-h/2,h/2]: box(0,.14,dz,w,.11,.07,m['frame'])
    box(0,.145,0,.055,.1,h,m['frame'])
    if h>1.9: box(0,.15,h*.23,w,.12,.05,m['frame'])
    box(0,.23,-h/2-.1,w+.24,.44,.14,m['white'])


def _profile(b,kind):
    ident=b['id']
    if ident.startswith('njupt_k_dormitory'):return 'k_dorm'
    if ident.startswith('njupt_k_dining'):return 'k_dining'
    if ident in YINGYUAN_IDS or 'yingyuan' in ident.lower() or '樱苑' in b.get('name',''):return 'yingyuan'
    if ident=='osm_way_1173059720':return 'materials'
    if kind=='legacy_academic':return 'legacy'
    if b.get('name') in ('教1','教2','教3','教4','教5'):return 'teaching'
    if kind=='dorm' and b.get('name','').split(' ')[0].isdigit():return 'east_dorm'
    if b.get('tags',{}).get('building')=='apartments':return 'staff_apartment'
    return 'unverified_'+kind


def _edges(outer,holes):
    for ri,ring in enumerate([outer]+holes):
        orient=(1 if signed_area(ring)>0 else -1)*(-1 if ri else 1)
        for ei,(p,q) in enumerate(zip(ring,ring[1:]+ring[:1])):
            ln=math.dist(p,q)
            if ln<.15:continue
            u=((q[0]-p[0])/ln,(q[1]-p[1])/ln)
            yield ri,ei,p,q,ln,u,(u[1]*orient,-u[0]*orient),math.atan2(u[1],u[0])


def _edgebox(batch,p,u,n,d,depth,z,width,thickness,height,mat):
    batch.box((p[0]+u[0]*d+n[0]*depth,p[1]+u[1]*d+n[1]*depth,z),(width,thickness,height),mat,math.atan2(u[1],u[0]))


def _glazed_bay(batch,p,u,n,d,z,w,h,m,panes=4,offset=.055,sill=True):
    """Broad classroom/ribbon glazing with individual mullions and transoms."""
    def box(dx,dn,dz,sx,sy,sz,mat):_edgebox(batch,p,u,n,d+dx,offset+dn,z+dz,sx,sy,sz,mat)
    box(0,0,0,w+.15,.085,h+.14,m['dark'])
    box(0,.035,0,w,.035,h,m['glass2'])
    for k in range(panes+1):box(-w/2+k*w/panes,.09,0,.052,.09,h+.05,m['frame'])
    for k in (-.5,.18,.5):box(0,.092,k*h,w+.10,.09,.047,m['frame'])
    if sill:box(0,.16,-h/2-.07,w+.20,.32,.10,m['white'])


def _yingyuan_end(body,detail,roof,p,u,n,length,height,levels,m):
    """Photo-backed end-wall stair tower, slot and projecting floor ribbons."""
    fh=height/levels;tower_w=min(5.6,length*.30);tower_d=length-tower_w/2-.4
    _edgebox(body,p,u,n,tower_d,.18,(height+1.9)/2,tower_w,.48,height+1.9,m['gray'])
    slot=tower_d+tower_w*.36
    _edgebox(detail,p,u,n,slot,.46,height*.52,.76,.035,height*.99,m['yellowrecess'])
    for zz in [k*.53+.45 for k in range(int(height/.53))]:
        _edgebox(detail,p,u,n,slot,.52,zz,.79,.11,.065,m['white'])
    for fl in range(1,levels):
        _edgebox(body,p,u,n,tower_d,.46,fl*fh+.10,tower_w+.50,.58,.29,m['yingband'])
    _edgebox(roof,p,u,n,tower_d,.02,height+1.96,tower_w+.18,2.35,.24,m['yingband'])
    # Open crown at the top of the slim grey stair tower.
    for d in (tower_d-tower_w/2+.10,tower_d+tower_w/2-.10):
        _edgebox(roof,p,u,n,d,.02,height+1.25,.19,2.16,1.35,m['gray'])
    clear=max(3.5,length-tower_w-1.4)
    for fl in range(levels):
        z=fh*(fl+.54)
        _glazed_bay(detail,p,u,n,clear/2+.35,z,clear-.6,fh*.67,m,panes=max(4,int(clear/.9)),sill=False)
        for k in range(max(3,int(clear/.9))):
            d=.7+k*(clear-.9)/max(1,int(clear/.9)-1)
            _edgebox(detail,p,u,n,d,.28,z,.06,.42,fh*.69,m['white'])
        _edgebox(body,p,u,n,clear/2+.35,.37,fl*fh+.14,clear+.5,.95,.24,m['yingband'])


def _yingyuan_link(body,detail,roof,cx,cy,m):
    a=(-265.9-cx,414.0-cy);b=(-277.5-cx,433.0-cy)
    ln=math.dist(a,b);u=((b[0]-a[0])/ln,(b[1]-a[1])/ln);n=(u[1],-u[0])
    for zz,th in ((.14,.28),(4.1,.28),(7.75,.26)):
        _edgebox(body,a,u,n,ln/2,0,zz,ln+1.0,5.4,th,m['yingband'] if zz<7 else m['white'])
    for side in (-1,1):
        _glazed_bay(detail,a,u,(n[0]*side,n[1]*side),ln/2,2.10,ln-.6,3.65,m,panes=14,offset=2.28,sill=False)
        _edgebox(body,a,u,n,ln/2,side*2.45,4.54,ln,.19,.68,m['white'])
    for j in range(6):
        for side in (-1,1):
            _edgebox(body,a,u,n,ln*j/5,side*2.16,5.95,.25,.27,3.5,m['white'])
    _edgebox(roof,a,u,n,ln/2,0,7.96,ln+1.50,6.55,.17,m['yellowrecess'])


def _clip_poly(poly,axis,limit,keep_lower=True):
    result=[]
    if not poly:return result
    for a,b in zip(poly,poly[1:]+poly[:1]):
        ina=(a[axis]<=limit+1e-7) if keep_lower else (a[axis]>=limit-1e-7)
        inb=(b[axis]<=limit+1e-7) if keep_lower else (b[axis]>=limit-1e-7)
        if ina:result.append(a)
        if ina!=inb:
            t=(limit-a[axis])/(b[axis]-a[axis]);result.append(tuple(a[k]+t*(b[k]-a[k]) for k in (0,1)))
    return result


def _fourth_canteen(b,parent,m,font):
    """Terraced white volume and red low entrance, read from 2025/2026 photos.

    The original mapped envelope is retained exactly. Sub-volume cut positions
    are explicitly inferred from matched construction and completion images.
    """
    ident=b['id'];name=b.get('name','第四食堂');cx,cy=b['center'];height=float(b.get('height',20.6));fh=height/5
    angle=math.radians(18.5);ca,sa=math.cos(angle),math.sin(angle)
    def local(p):
        x,y=p[0]-cx,p[1]-cy;return (ca*x+sa*y,-sa*x+ca*y)
    def world(p,z):return (ca*p[0]-sa*p[1],sa*p[0]+ca*p[1],z)
    outline=[local(p) for p in b['outer']]
    xmin=min(p[0] for p in outline);xmax=max(p[0] for p in outline);ymin=min(p[1] for p in outline);ymax=max(p[1] for p in outline)
    width=xmax-xmin;length=ymax-ymin
    # West spine is full height. The east side terraces down to the entrance.
    splitx=xmin+width*.53;splity=ymin+length*.47
    polygons=[(_clip_poly(outline,0,splitx),height,m['white']),
              (_clip_poly(_clip_poly(outline,0,splitx,False),1,splity),height,m['white']),
              (_clip_poly(_clip_poly(outline,0,splitx,False),1,splity,False),height*.59,m['white'])]
    col=bpy.data.collections.new(name+' | '+ident);parent.children.link(col)
    body=Batch();detail=Batch();roof=Batch();count=0
    def box(batch,x,y,z,w,d,h,mat):batch.box(world((x,y),z),(w,d,h),mat,angle)
    for poly,hh,mat in polygons:
        pp=[world(p,0)[:2] for p in poly]
        body.extrude(pp,[],.10,hh-.10,mat,m['roof'])
        for ri,ei,p,q,ln,u,n,aa in _edges(pp,[]):
            # Do not decorate internal interfaces where a higher volume touches.
            is_shared=(all(abs(localp[0]-splitx)<.01 for localp in (poly[ei],poly[(ei+1)%len(poly)])) or all(abs(localp[1]-splity)<.01 for localp in (poly[ei],poly[(ei+1)%len(poly)])))
            if is_shared:continue
            _edgebox(roof,p,u,n,ln/2,.03,hh+.23,ln+.1,.45,.43,m['white'])
            if ln<6:continue
            bays=max(2,int(ln/2.1));step=ln/bays
            for fl in range(max(2,round(hh/fh))):
                for k in range(bays):
                    z=fh*(fl+.55)
                    if z+fh*.35>hh:continue
                    _glazed_bay(detail,p,u,n,step*(k+.5),z,min(1.03,step*.56),fh*.72,m,panes=1,sill=False);count+=1
            # Thin but deep vertical pale fins create the characteristic tall
            # white facade grid rather than broad generic classroom windows.
            for k in range(bays+1):_edgebox(detail,p,u,n,k*step,.27,hh*.57,.18,.67,hh*.73,m['white'])
            for fl in range(1,max(2,round(hh/fh))):_edgebox(detail,p,u,n,ln/2,.25,fl*fh,ln,.56,.24,m['white'])
    # Red low entrance box along the east side at the terrace foot.
    entry_y=splity+(ymax-splity)*.52;entry_l=min(23,(ymax-splity)*.75);entry_z=fh*1.68
    ex=xmax-.95;box(body,ex,entry_y,entry_z/2,2.0,entry_l,entry_z,m['kred'])
    for zz in [i*.67+.45 for i in range(int(entry_z/.67))]:box(detail,ex+1.025,entry_y,zz,.035,entry_l-.05,.025,m['legacyred'])
    # Slanted white portal: four-sided members, not typography pasted to a wall.
    portal_l=entry_l*.55;py=entry_y+.6;front=ex+1.12
    p=(world((front,py-portal_l/2),0)[:2]);u=(-sa,ca);n=(ca,sa)
    _glazed_bay(detail,p,u,n,portal_l/2,2.2,portal_l-.8,4.2,m,panes=7,offset=.04,sill=False)
    for sign in (-1,1):
        y0=py+sign*portal_l/2; y1=py+sign*(portal_l/2-.65)
        quad=[world((front+.25,y0),.1),world((front+.25,y0+sign*.60),.1),world((front+.25,y1+sign*.60),5.3),world((front+.25,y1),5.3)]
        body.face(quad,m['white'])
        back=[(x-ca*.58,y-sa*.58,z) for x,y,z in quad]
        body.face(back,m['white'])
        for i in range(4):body.face([quad[i],quad[(i+1)%4],back[(i+1)%4],back[i]],m['white'])
    box(body,front+.1,py,5.20,.75,portal_l-.7,.65,m['white'])
    # Folded intermediate terrace parapet and the photographed external stair.
    ty=splity+(ymax-splity)*.13
    for i in range(30):
        yy=ty+i*.36;zz=(i+1)*.145
        box(body,xmax+.10,yy,zz/2,3.3,.37,zz,m['step'])
    for side in (-1,1):
        xx=xmax+.1+side*1.44
        aa=world((xx,ty),1.08);bb=world((xx,ty+29*.36),30*.145+1.08)
        detail.pipe(aa,bb,.035,m['frame'],8)
        for i in range(0,30,3):detail.pipe(world((xx,ty+i*.36),(i+1)*.145),world((xx,ty+i*.36),(i+1)*.145+1.08),.024,m['frame'],8)
    # Construction aerial shows roof service housings on the high west spine.
    for yy in (ymin+length*.18,ymin+length*.70):
        box(roof,xmin+width*.23,yy,height+1.10,width*.19,5.2,2.2,m['white'])
    obs=[]
    for nm,batch in [('Multiheight restaurant volumes',body),('Recessed glazing portal and stair',detail),('Terraces parapets and roof plant',roof)]:
        obs.append(batch.object(nm+' | '+name,col,bevel=.025 if batch is body else 0))
    sources=['observations/images/njupt/k_complete_20260901_image_00.png','observations/images/njupt/k_structure_2025_image_00.jpg','observations/images/njupt/canteen4_structure_2025_image_00.jpg']
    status='photo-informed multilevel reconstruction; internal volume boundaries, dimensions and hidden elevations inferred'
    features=['white tall narrow-window volume','stepped eastern terrace and low orange-red entrance','slanted white door surround','external stair with metal balustrade','roof service housings']
    col['asset_id']=ident;col['campus_name']=name;col['origin_local_m']=[cx,cy,0.];col['height_m']=height;col['levels']=5
    col['facade_profile']='k_dining';col['facade_status']=status;col['facade_evidence']=sources;col['observed_features']=features;col['generated_by']='src/blender/campus_buildings.py';col['revision']='2026-09-30 multiheight fourth canteen'
    return col,{'id':ident,'name':name,'kind':'dining','facade_profile':'k_dining','height':height,'levels':5,'window_count':count,'objects':len(obs),'roof_equipment':2,'center':[cx,cy],'facade_status':status,'facade_sources':sources,'observed_features':features}


def building_asset(b,parent,m,font=None,override=None):
    """Preserve footprint/plan topology while assigning evidence-specific facades.

    No unknown entrance is placed on the longest wall. No random roof service
    layout is created for a building without roof evidence. Sub-metre dimensions
    remain reconstruction estimates and are stored in the asset provenance.
    """
    ident=b['id'];name=b.get('name') or ('樱苑 '+str(YINGYUAN_IDS[b['id']])+' 栋' if b['id'] in YINGYUAN_IDS else ident);override=override or {}
    kind=override.get('kind',classify(b));profile=_profile(b,kind)
    if profile=='k_dining':return _fourth_canteen(b,parent,m,font)
    height=max(3.2,float(override.get('height',b.get('height',18))))
    levels=max(1,int(override.get('levels',b.get('levels',round(height/3.5)))))
    fh=height/levels;base_z=float(b.get('min_height',0));cx,cy=b['center']
    outer=[(p[0]-cx,p[1]-cy) for p in b['outer']]
    holes=[[(p[0]-cx,p[1]-cy) for p in r] for r in b.get('holes',[])]
    tris=[[(p[0]-cx,p[1]-cy) for p in t] for t in b.get('roof_triangles',[])]
    col=bpy.data.collections.new(name+' | '+ident);parent.children.link(col)
    body=Batch();detail=Batch();roof=Batch();count=0;roof_equipment=0
    wall=m['ivory'];sources=[];features=[]
    if profile=='teaching':
        wall=m['teachingtile'];sources=['observations/images/njupt/official-tour-2017-08.jpg','observations/catalog.json']
        features=['broad subdivided classroom glazing','small pale ceramic tiles','recessed floor reveals','plan-preserved courtyard and partial sixth floor']
    elif profile=='legacy':
        wall=m['legacywall'];sources=['observations/images/njupt/construction_home_image_03.jpg','observations/images/njupt/gallery-13.jpg']
        features=['two lower grey-stone storeys','pale warm upper walls','localized glazed portal; no repeated orange frames on every edge']
    elif profile=='materials':
        wall=m['white'];sources=['observations/images/njupt/construction_home_image_01.jpg','observations/images/njupt/gallery-17.jpg']
        features=['lower pale narrow-pier podium','upper red vertical screening and horizontal framing','mapped internal light court','photo-supported roof mechanical zone']
    elif profile=='yingyuan':
        wall=m['yingwall'];sources=['observations/images/njupt/construction_home_image_02.jpg','observations/images/njupt/gallery-16.jpg']
        features=['pale grey elevation','charcoal continuous floor ribbons','restrained metal window frames']
    elif profile=='east_dorm':
        wall=m['dormtile'];sources=['observations/images/njupt/dorm_renovation_2022_image_07.jpg','observations/images/njupt/dorm_renovation_2022_image_22.jpg']
        features=['grey ceramic material replaces uniformly tan walls','paired residential glazing family; window modules inferred','surface AC units and brackets are unsurveyed reconstruction detail']
    elif profile in ('k_dorm','k_dining'):
        wall=m['yingwall'];sources=['observations/images/njupt/k_complete_20260901_image_00.png','observations/images/njupt/k_inspection_20260901_image_00.png']
        features=['new-block grey/white residential envelope; observed detail palette','five storeys from project record']
    if profile=='k_dorm':features+=['recessed balcony openings and closely spaced pale piers','continuous dark horizontal slab edges','flat roofs with deep layered cornice']
    body.extrude(outer,holes,max(.08,base_z),height-base_z,wall,m['roof'],tris)
    all_edges=list(_edges(outer,holes))
    # Portal position is an explicit reconstruction estimate on the east-facing
    # long elevation; photo establishes its architecture, not its surveyed bay.
    portal_edge=None
    if profile=='legacy':
        candidates=[e for e in all_edges if e[0]==0 and e[4]>35]
        if candidates:portal_edge=max(candidates,key=lambda e:e[6][0]*.8-e[6][1]*.2)
    for edge in all_edges:
        ri,ei,p,q,length,u,n,angle=edge
        def box(batch,d,dep,z,w,t,h,mat):_edgebox(batch,p,u,n,d,dep,z,w,t,h,mat)
        if base_z<.7:box(body,length/2,.06,.28,length,.18,.5,m['gray'])
        # Different material proportions now carry building-family identity.
        if profile=='legacy':
            box(body,length/2,.04,min(2*fh,height)/2,length,.11,min(2*fh,height),m['academicbase'])
        for floor in range(1,levels):
            zz=floor*fh
            if zz<=base_z:continue
            if profile=='teaching':
                box(body,length/2,.045,zz,length,.12,.065,m['gray'])
                box(body,length/2,.045,zz+.14,length,.12,.035,m['gray'])
            elif profile=='yingyuan':
                box(body,length/2,.08,zz+.02,length,.20,.43,m['yingband'])
            elif profile in ('k_dorm','k_dining'):
                box(body,length/2,.07,zz,length,.17,.30,m['yingband'])
            elif profile!='materials':
                box(body,length/2,.055,zz,length,.13,.10,m['gray'] if profile=='legacy' else m['white'])
        box(body,length/2,0,height+.24,length+.08,.34,.46,wall)
        box(roof,length/2,.03,height+.51,length+.16,.46,.10,m['yingband'] if profile in ('legacy','yingyuan','k_dorm','k_dining') else m['white'])
        if length<4.2:continue
        if profile=='yingyuan' and ri==0 and 15<length<24:
            _yingyuan_end(body,detail,roof,p,u,n,length,height,levels,m)
            continue
        spacing=7.2 if profile=='teaching' else (3.65 if profile in ('east_dorm','k_dorm','staff_apartment') else 3.3)
        if profile=='materials':spacing=3.35
        bays=max(1,int((length-1.0)/spacing));actual=(length-1.1)/bays
        for floor in range(levels):
            zz=fh*(floor+.55)
            wh=min(fh*.62,2.5)
            if zz-wh/2<base_z:continue
            for j in range(bays):
                d=.55+actual*(j+.5)
                # The old wings have a clearly glassy vertical accent at one end,
                # not an orange rectangle at every corner and every side.
                in_portal=portal_edge==edge and d<min(7.8,length*.15)
                if in_portal:continue
                if profile=='k_dorm' and ri==0 and length>28:
                    # Balcony wall is set behind the front rail/column plane.
                    # Recess depth is estimated from the completed official photo.
                    ww=min(actual-.64,2.8)
                    _glazed_bay(detail,p,u,n,d,zz,ww*.73,wh,m,panes=2,offset=.03,sill=False)
                    _edgebox(detail,p,u,n,d,.89,floor*fh+.12,actual-.06,1.76,.20,m['yingband'])
                    _edgebox(detail,p,u,n,d,1.65,floor*fh+1.15,actual-.25,.075,.065,m['frame'])
                    for k in range(6):_edgebox(detail,p,u,n,d-actual*.43+k*actual*.172,1.65,floor*fh+.69,.036,.055,.91,m['frame'])
                elif profile=='teaching':
                    ww=min(actual-.60,6.3)
                    _glazed_bay(detail,p,u,n,d,zz,ww,wh,m,panes=max(4,round(ww/1.05)))
                elif profile=='materials':
                    if floor<2:
                        ww=min(actual*.42,1.4);wh=fh*.70
                    else:ww=min(actual*.71,2.6)
                    _glazed_bay(detail,p,u,n,d,zz,ww,wh,m,panes=2)
                else:
                    ww=min(actual*(.68 if profile in ('yingyuan','k_dorm') else .61),2.35)
                    window(detail,(p[0]+u[0]*d,p[1]+u[1]*d),u,n,zz,ww,wh,m['glass2'],m)
                count+=1
                if profile=='east_dorm' and floor>0:
                    # Plausible services remain inference: the cited closeups
                    # establish ceramic cladding, not these unit positions.
                    acd=d+ww*.42;acw=min(.70,actual-ww+.22)
                    box(detail,acd,.47,zz-wh*.40,acw,.40,.47,m['white'])
                    for k in range(6):box(detail,acd,.69,zz-wh*.40-.17+k*.06,acw*.79,.025,.014,m['slat'])
        if profile=='teaching':
            # Narrow structural strips at classroom modules, not white pylons
            # every two residential-sized windows.
            for j in range(bays+1):box(body,.55+j*actual,.10,(height+base_z)/2,.26,.24,height-base_z,wall)
            # The photographed upper teaching wing has an open roof-edge frame.
            # Retain the roof datum while making the projected eave read in silhouette.
            if ri==0 and length>34:
                box(roof,length/2,.39,height-.18,length+.3,.95,.22,wall)
                for j in range(bays+1):box(roof,.55+j*actual,.34,height-.79,.22,.34,1.12,wall)
        if profile=='k_dorm' and ri==0 and length>28:
            for j in range(bays+1):box(body,.55+j*actual,1.60,height/2,.20,.30,height,m['white'])
            for dz,depth,th in ((.30,1.85,.25),(.63,2.05,.18),(.90,2.15,.11)):
                box(roof,length/2,.63,height+dz,length+.55,depth,th,m['yingband'] if dz==.63 else m['white'])
        if profile=='materials' and ri==0 and length>27:
            z0=2*fh;z1=height-.45
            # Five thick red frame lines and slim red sun-screen blades can be
            # read in both official high-angle photographs. Counts estimated.
            for zz in (z0,z0+fh,z0+2*fh,z0+3*fh,z1):
                if zz<=z1+.1:box(body,length/2,.23,zz,length-.8,.44,.32,m['redscreen'])
            for d in (.55,length-.55):box(body,d,.26,(z0+z1)/2,.47,.52,z1-z0,m['redscreen'])
            number=max(2,round((length-1.4)/1.15))
            for j in range(number+1):box(detail,.70+j*(length-1.4)/number,.24,(z0+z1)/2,.10,.49,z1-z0,m['redscreen'])
        if profile=='yingyuan' and ri==0 and length<24:
            # End elevations in the official photograph are predominantly solid,
            # with corner tower bands. Keep addition within the footprint face.
            strip=min(3.4,length*.20)
            box(body,length-strip/2,.16,height/2,strip,.34,height,m['yingband'])
        if length>18:detail.cylinder((p[0]+u[0]*.22+n[0]*.25,p[1]+u[1]*.22+n[1]*.25,(height+base_z)/2),.047,height-base_z,m['frame'],8)
    if portal_edge:
        ri,ei,p,q,length,u,n,angle=portal_edge;pw=min(7.8,length*.15)
        _glazed_bay(detail,p,u,n,pw/2,height*.46,pw,height*.91,m,panes=5,sill=False)
        for zz in (2*fh,height*.85):
            _edgebox(body,p,u,n,pw/2,.28,zz,pw+.45,.40,.48,m['legacyred'])
        for d in (.02,pw-.02):
            _edgebox(body,p,u,n,d,.28,(2*fh+height*.85)/2,.47,.4,height*.85-2*fh,m['legacyred'])
    if profile=='k_dorm' and ident=='njupt_k_dormitory_06':
        # One restrained photographed accent, not a repeated feature assigned
        # to all six blocks. Matching this visible southern block to model 06
        # and the exact bay remain provisional until geolocated facade views.
        accent=max((e for e in all_edges if e[0]==0 and e[4]>28),key=lambda e:e[6][0]-e[6][1]*.7,default=None)
        if accent:
            ri,ei,p,q,ln,u,n,aa=accent;aw=min(11.8,ln*.29);ac=ln*.64;bottom=2*fh;top=4*fh
            for zz in (bottom,3*fh,top):_edgebox(body,p,u,n,ac,1.86,zz,aw+.6,.62,.42,m['kred'])
            for xx in (ac-aw/2,ac+aw/2):_edgebox(body,p,u,n,xx,1.86,(bottom+top)/2,.40,.62,top-bottom,m['kred'])
            for xx in (ac-aw/6,ac+aw/6):_edgebox(detail,p,u,n,xx,1.89,(bottom+top)/2,.14,.56,top-bottom,m['kred'])
            features.append('one two-storey orange balcony frame; assignment to model block 06 and bay position provisional')
    # Floor plans prove the teaching wings stop below the central sixth floor.
    for v in b.get('upper_volumes',[]):
        oo=[(p[0]-cx,p[1]-cy) for p in v['outer']];hh=[[(p[0]-cx,p[1]-cy) for p in h] for h in v.get('holes',[])]
        tt=[[(p[0]-cx,p[1]-cy) for p in t] for t in v.get('roof_triangles',[])]
        vz=v.get('base_z',height);vh=v.get('height',fh);body.extrude(oo,hh,vz,vh,wall,m['roof'],tt)
        for ri,ei,p,q,ln,u,n,ang in _edges(oo,hh):
            _edgebox(roof,p,u,n,ln/2,.01,vz+vh+.16,ln+.12,.40,.29,wall)
            nn=max(1,int((ln-.8)/7.2))
            if ln<4:continue
            for j in range(nn):
                _glazed_bay(detail,p,u,n,ln*(j+.5)/nn,vz+vh*.53,min(6.3,ln/nn-.6),vh*.59,m,panes=5);count+=1
    if profile=='materials':
        # Mechanical groups lie on the real solid roof, never in the courtyard.
        # Regular arrays replace random boxes; appearance is evidence-informed,
        # exact equipment positions and mechanical specification are estimated.
        for ri,ei,p,q,ln,u,n,angle in all_edges:
            if ri or ln<26:continue
            for j in range(2,max(3,int(ln/4.8)-1)):
                d=j*4.8;x=p[0]+u[0]*d-n[0]*3.8;y=p[1]+u[1]*d-n[1]*3.8
                if not all(point_inside((x+dx,y+dy),outer,holes) for dx,dy in ((-1.2,-.9),(1.2,-.9),(1.2,.9),(-1.2,.9))):continue
                roof.box((x,y,height+.67),(2.1,1.55,1.15),m['roofmetal'],angle)
                for ds in (-.47,.47):roof.cylinder((x+u[0]*ds,y+u[1]*ds,height+1.28),.38,.08,m['dark'],16)
                roof_equipment+=1
    if profile=='yingyuan':
        if ident=='osm_way_1173057035':
            # The paired 55/52 entrance and covered second-level link occur in
            # construction_home_image_02. Store once in asset 55, not duplicated.
            _yingyuan_link(body,detail,roof,cx,cy,m)
            features.append('paired 55/52 low glazed entrance and open covered link; approximate dimensions')
    obs=[]
    for meshname,batch in [('Architecture',body),('Windows and facade details',detail),('Roof services',roof)]:
        if batch.faces:obs.append(batch.object(meshname+' | '+name,col,bevel=.025 if meshname=='Architecture' else 0))
    status='photo-informed visible features; exact modules, hidden elevations and dimensions remain inferred' if sources else 'unverified conservative envelope; no surveyed facade evidence'
    col['asset_id']=ident;col['campus_name']=name;col['origin_local_m']=[cx,cy,0.];col['height_m']=height;col['levels']=levels
    col['height_evidence']=b.get('height_source','inferred');col['source_url']=b.get('source_url','')
    col['facade_status']=status;col['facade_profile']=profile;col['facade_evidence']=sources or ['No building-specific facade image linked']
    col['observed_features']=features or ['Mapped envelope only'];col['generated_by']='src/blender/campus_buildings.py'
    col['revision']='2026-09-30 evidence-specific families'
    return col,{'id':ident,'name':name,'kind':kind,'facade_profile':profile,'height':height,'levels':levels,'window_count':count,'objects':len(obs),'roof_equipment':roof_equipment,'center':[cx,cy],'facade_status':status,'facade_sources':sources,'observed_features':features}
