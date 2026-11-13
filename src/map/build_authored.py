from __future__ import annotations
import argparse, copy, heapq, json, math, re, shutil
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from pyproj import Transformer
from shapely.geometry import shape, mapping, Point, LineString, MultiPoint
from shapely.validation import explain_validity
from shapely.ops import unary_union, transform
from shapely.strtree import STRtree
try:
    from .tiles import write_pmtiles, render_preview, WGS_TO_M
    from .vocabulary import CATEGORIES, STYLE_DEFAULTS, group, tier
except ImportError:
    from tiles import write_pmtiles, render_preview, WGS_TO_M
    from vocabulary import CATEGORIES, STYLE_DEFAULTS, group, tier

ROOT=Path(__file__).resolve().parents[2]
AUTHOR=ROOT/'map'/'layers'
OUT=ROOT/'build'/'space'/'仙林'
OBS=ROOT/'observations'/'providers'/'amap'/'仙林'/'routes.jsonl'
WGS_TO_M=Transformer.from_crs('EPSG:4326','EPSG:32650',always_xy=True).transform
M_TO_WGS=Transformer.from_crs('EPSG:32650','EPSG:4326',always_xy=True).transform
WALK=1; BIKE=2; STEPS=4

LAYER_NAMES=('building_forms','campuses','buildings','rooms','floor_plates','cores','places','entrances','ways','greens','waters',
             'sports','surfaces','context_buildings','landscape_exclusions')
LAYER_KINDS={'campuses':'campus','buildings':'building','floors':'floor','rooms':'room','places':'place',
             'entrances':'entrance','greens':'greens','waters':'waters','sports':'sports',
             'surfaces':'surfaces','context_buildings':'context_buildings',
             'landscape_exclusions':'landscape_exclusions'}

def contained(layers):
    """Where each place stands, read from the geometry rather than authored: the building its point lies in, or none.
    A place inside the campus has an id under the campus (仙林/…); one outside it, under 周边/."""
    buildings=[(feature_id(f),shape(f['geometry'])) for f in layers['buildings']]
    tree=STRtree([g for _,g in buildings])
    parents={}
    for f in layers['places']:
        point=shape(f['geometry'])
        inside=[buildings[int(i)][0] for i in tree.query(point,predicate='covered_by')]
        if inside: parents[feature_id(f)]=sorted(inside)[0]
    return parents

def campus_of(layers):
    campus=layers['campuses'][0]
    return feature_id(campus),shape(campus['geometry'])

def dump(path:Path,value:Any):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8',newline='\n')

def load_layer(name):
    p=AUTHOR/f'{name}.geojson'
    d=json.loads(p.read_text(encoding='utf-8'))
    if d.get('type')!='FeatureCollection': raise ValueError(f'{p} is not FeatureCollection')
    if name=='floors': raise ValueError('floors is derived from buildings.levels')
    for f in d['features']:
        props=f.get('properties') or {}
        if 'id' not in props or 'id' in f: raise ValueError(f'{p}: id must live only in properties')
        if f.get('id') is not None: raise ValueError(f'{p}: top-level id is not authored')
    return sorted(d['features'],key=lambda f:f['properties']['id'])

def feature_id(feature):
    return feature['properties']['id']

def derive_floors(buildings):
    floors=[]
    for building in buildings:
        p=building['properties']; bid=feature_id(building)
        levels=int(p['levels'])
        for level in range(1,levels+1):
            floors.append({'type':'Feature','properties':{
                'id':f'{bid}/{level}','kind':'floor','name':f'{level}层',
                'parent':bid,'level':level},'geometry':copy.deepcopy(building['geometry'])})
    return floors

def metric_point(c): return WGS_TO_M(*c)
def dist(a,b): return math.hypot(a[0]-b[0],a[1]-b[1])

def nearest_node(pt,nodes_m):
    xy=metric_point(pt)
    return min(nodes_m,key=lambda n: dist(xy,nodes_m[n]))

SNAP_M=1.0
WALL_INSET_M=15.0
GATE_REACH_M=90.0
PUBLIC_KINDS={'secondary','tertiary','residential','unclassified'}
SNAP_DEG=1.2e-5

def metric_gap(line,point):
    near=line.interpolate(line.project(point))
    return dist(metric_point(near.coords[0]),metric_point(point.coords[0]))

def merge_points(points):
    """Map every point to one coordinate per junction drawn within SNAP_M."""
    unique=sorted(set(points)); geoms=[Point(c) for c in unique]
    tree=STRtree(geoms); parent=list(range(len(unique)))
    def root(i):
        while parent[i]!=i: parent[i]=parent[parent[i]]; i=parent[i]
        return i
    for i,p in enumerate(geoms):
        for j in tree.query(p,predicate='dwithin',distance=SNAP_DEG):
            j=int(j)
            if j>i and dist(metric_point(unique[i]),metric_point(unique[j]))<=SNAP_M: parent[root(j)]=root(i)
    return {c:unique[root(i)] for i,c in enumerate(unique)}

def cut_way(line,stops):
    """Split a way at its stops, passing through each stop's exact coordinate."""
    inner=sorted({(d,c) for d,c in stops if 1e-7<d<line.length-1e-7})
    if not inner: return [line]
    pieces=[]; current=[line.coords[0]]; along=0.0; coords=list(line.coords); at=0
    for a,b in zip(coords,coords[1:]):
        seg=dist(a,b)
        while at<len(inner) and inner[at][0]<=along+seg:
            stop=inner[at][1]; at+=1
            if stop!=current[-1]: current.append(stop); pieces.append(LineString(current)); current=[stop]
        if b!=current[-1]: current.append(b)
        along+=seg
    if len(current)>1: pieces.append(LineString(current))
    return pieces

def campus_wall(way_segments,junction,campus,gates):
    """A campus is walled from the public roads around it: nothing joins one except at a gate.
    Returns the test for one edge, given its way and the junction coordinates of its ends."""
    if campus is None:
        def open_ground(*_): return False
        open_ground.public=open_ground
        return open_ground
    campus_m=transform(WGS_TO_M,campus)
    inner=campus_m.buffer(-WALL_INSET_M)
    gate_points=[metric_point(c) for c in gates]
    def public(p,g): return p.get('kind') in PUBLIC_KINDS and not inner.contains(Point(metric_point(g.interpolate(.5,normalized=True).coords[0])))
    on_road=set()
    for g,p in way_segments:
        if public(p,g): on_road.update(junction[c] for c in (g.coords[0],g.coords[-1]))
    def at_gate(c): return any(dist(metric_point(c),gate)<=GATE_REACH_M for gate in gate_points)
    def walled(p,g,a,b):
        if public(p,g) or (a in on_road)==(b in on_road): return False
        road,other=(a,b) if a in on_road else (b,a)
        return campus_m.contains(Point(metric_point(other))) and not at_gate(road)
    walled.public=public
    return walled

def build_network(ways,entrances,buildings,obstacles=(),entities=(),campus=None,gates=()):
    coord_to_node={}; nodes=[]; nodes_m={}; edges=[]
    def node(c):
        key=(round(c[0],7),round(c[1],7))
        if key not in coord_to_node:
            i=len(nodes); coord_to_node[key]=i; nodes.append([key[0],key[1]]); nodes_m[i]=metric_point(key)
        return coord_to_node[key]
    # Linework meets at crossings and at T-junctions whose end sits a hair off the
    # other way.  Node both once at build time, so a junction is never lost to
    # coordinate rounding; anything wider than SNAP_M is authored as a way.
    geometries=[shape(f['geometry']) for f in ways]
    tree=STRtree(geometries)
    ends=[Point(c) for g in geometries for c in (g.coords[0],g.coords[-1])]
    end_tree=STRtree(ends)
    way_segments=[]
    for index,(f,g) in enumerate(zip(ways,geometries)):
        stops=[]
        for candidate_index in tree.query(g):
            if int(candidate_index)==index: continue
            intersection=g.intersection(geometries[int(candidate_index)])
            if intersection.is_empty: continue
            stack=[intersection]
            while stack:
                item=stack.pop()
                if item.geom_type=='Point': stops.append((g.project(item),g.interpolate(g.project(item)).coords[0]))
                elif item.geom_type in {'MultiPoint','GeometryCollection'}: stack.extend(item.geoms)
                elif item.geom_type in {'LineString','MultiLineString'}:
                    stack.extend(item.boundary.geoms if hasattr(item.boundary,'geoms') else [item.boundary])
        for end_index in end_tree.query(g,predicate='dwithin',distance=SNAP_DEG):
            end=ends[int(end_index)]
            if int(end_index)//2!=index and metric_gap(g,end)<=SNAP_M: stops.append((g.project(end),end.coords[0]))
        way_segments.extend((piece,f['properties']) for piece in cut_way(g,stops))
    junction=merge_points([c for g,_ in way_segments for c in (g.coords[0],g.coords[-1])])
    drawn=set()
    wall=campus_wall(way_segments,junction,campus,gates)
    for g,p in way_segments:
        coords=list(g.coords); coords[0]=junction[coords[0]]; coords[-1]=junction[coords[-1]]
        flags=(WALK if p.get('walk',True) else 0)|(BIKE if p.get('bike',True) else 0)|(STEPS if p.get('steps',False) else 0)
        if p.get('kind') in {'connector','access_connector'}: flags |= 8
        if wall.public(p,g): flags |= 16
        source=p.get('name') or None
        for a,b in zip(coords,coords[1:]):
            ia,ib=node(a),node(b); d=dist(nodes_m[ia],nodes_m[ib])
            pair=(min(ia,ib),max(ia,ib),flags)
            if wall(p,g,a,b): continue
            if ia!=ib and d>0 and pair not in drawn: drawn.add(pair); edges.append([ia,ib,round(d,3),flags,source])
    targets=defaultdict(list); ent_nodes={}
    for f in entrances:
        p=f['properties']; c=f['geometry']['coordinates']; n=nearest_node(c,nodes_m)
        ent_nodes[p['id']]=n; targets[p['parent']].append(n)

    route_nodes_m=dict(nodes_m)
    # Every published space entity gets a target in the same graph.  Contained
    # entities use the entrances of their ancestor building; independent
    # outdoor places get an authored point node connected to the nearest road.
    # This is deliberately a build-time fact rather than a client fallback.
    entity_by_id={feature_id(f):f for f in entities}
    building_ids={feature_id(f) for f in buildings}
    def ancestor_building(entity_id):
        current=entity_by_id.get(entity_id)
        seen=set()
        while current is not None:
            current_id=feature_id(current)
            if current_id in building_ids:
                return current_id
            if current_id in seen:
                raise ValueError(f'entity parent cycle: {current_id}')
            seen.add(current_id)
            parent=current['properties'].get('parent')
            current=entity_by_id.get(parent) if parent else None
        return None

    def point_target(feature):
        geometry=shape(feature.get('geometry')) if feature.get('geometry') else None
        if geometry is None or geometry.is_empty:
            raise ValueError(f'entity has no routable geometry: {feature_id(feature)}')
        point=geometry if geometry.geom_type=='Point' else geometry.representative_point()
        coordinate=(float(point.x),float(point.y))
        road=nearest_node(coordinate,nodes_m)
        # The target is deliberately the nearest authored road node.  The
        # previous build created a synthetic edge from every place centroid;
        # those edges looked like roads to wayfind and polluted instructions.
        return road

    all_entrance_nodes=sorted({n for ns in targets.values() for n in ns})
    for feature in entities:
        entity_id=feature_id(feature)
        kind=feature['properties'].get('kind')
        if kind=='entrance':
            target_nodes=[ent_nodes[entity_id]] if entity_id in ent_nodes else []
        elif kind=='campus':
            target_nodes=all_entrance_nodes
        else:
            building=ancestor_building(entity_id)
            if building is not None:
                target_nodes=targets.get(building,[])
            elif kind=='place':
                target_nodes=[point_target(feature)]
            else:
                target_nodes=[]
        if not target_nodes:
            raise ValueError(f'entity has no routable target: {entity_id}')
        targets[entity_id]=sorted(set(target_nodes))
    # Materialize the single wayfind graph contract. Each edge carries a small
    # two-point shape, so the router can return authored geometry without a
    # second linework file.
    names=[]; name_ids={}; compact=[]; shapes=[]
    for a,b,w,f,source in edges:
        if source is not None and source not in name_ids:
            name_ids[source]=len(names); names.append(source)
        compact.append([a,b,w,f,name_ids.get(source,-1)])
        shapes.append([nodes[a],nodes[b]])
    landmarks=[]; seen_landmarks=set()
    for feature in entities:
        props=feature.get('properties') or {}; label=(props.get('name') or '').strip()
        if props.get('kind') not in {'building','place'}:
            continue
        if not label or label in seen_landmarks: continue
        geometry=shape(feature.get('geometry')) if feature.get('geometry') else None
        if geometry is None or geometry.is_empty: continue
        point=geometry if geometry.geom_type=='Point' else geometry.representative_point()
        landmarks.append({'name':label,'at':[float(point.x),float(point.y)]}); seen_landmarks.add(label)
    network={'format':'wayfind-graph/1','nodes':nodes,'edges':compact,'shapes':shapes,'names':names,
             'flags':{'walk':WALK,'bike':BIKE,'steps':STEPS,'connector':8,'public':16},
             'targets':{k:sorted(v) for k,v in sorted(targets.items())},
             'entrances':{k:ent_nodes[k] for k in sorted(ent_nodes)},
             'landmarks':landmarks,
             'stats':{'nodes':len(nodes),'edges':len(edges),'connector_edges':sum(1 for edge in edges if edge[3] & 8)}}
    return network,nodes_m,route_nodes_m

def shortest(network,nodes_m,start,flag):
    edges=network['edges']; adj=defaultdict(list)
    for edge in edges:
        a,b,w,f=edge[:4]
        if f&flag: adj[a].append((b,w)); adj[b].append((a,w))
    d={start:0.0}; q=[(0.0,start)]
    while q:
        cost,x=heapq.heappop(q)
        if cost!=d[x]:continue
        for y,w in adj[x]:
            n=cost+w
            if n<d.get(y,float('inf')):d[y]=n;heapq.heappush(q,(n,y))
    return d

_DIST_CACHE={}
def route_distance(route,network,nodes_m):
    c1=route.get('origin'); c2=route.get('destination')
    if not c1 or not c2:return None
    n1=nearest_node(c1,nodes_m); n2=nearest_node(c2,nodes_m)
    mode=BIKE if route.get('mode')=='bicycling' else WALK
    key=(mode,n1)
    if key not in _DIST_CACHE: _DIST_CACHE[key]=shortest(network,nodes_m,n1,mode)
    d=_DIST_CACHE[key].get(n2)
    return d

def route_gate(network,nodes_m):
    if not OBS.exists(): return {'status':'skipped','reason':'observations absent','samples':0,'failures':[]}
    rows=[json.loads(x) for x in OBS.read_text(encoding='utf-8').splitlines() if x]
    by_source={}; failures=[]; ratios=[]
    for r in rows:
        paths=((r.get('answer') or {}).get('route') or {}).get('paths') or []
        provider=float(paths[0].get('distance',0)) if paths else 0
        ours=route_distance(r,network,nodes_m)
        item={'mode':r.get('mode'),'origin':r.get('origin'),'destination':r.get('destination'),'provider_m':provider,'authored_m':round(ours,3) if ours is not None else None}
        if ours is None or provider<=0: item['status']='unreachable'; failures.append(item)
        else:
            ratio=ours/provider; item['ratio']=round(ratio,4); ratios.append(ratio)
            item['status']='ok' if ratio<=1.3 else 'over-limit'
            if ratio>1.3: failures.append(item)
        by_source.setdefault(r.get('mode'),[]).append(item)
    # Provider traces are provenance observations, not the authored map's
    # build contract.  Keep the comparison report for review, but never make
    # an external provider's route length block a deterministic local build.
    report={'status':'observed' if failures else 'observed_match','samples':len(rows),'failures':failures,
            'modes':{m:{'samples':len(v),'max_ratio':max((x.get('ratio',0) for x in v),default=0),
                       'median_ratio':sorted(x['ratio'] for x in v if 'ratio' in x)[len([x for x in v if 'ratio' in x])//2] if any('ratio' in x for x in v) else None} for m,v in sorted(by_source.items())}}
    return report

def check_geometry(features):
    errors=[]
    for f in features:
        g=shape(f['geometry']) if f.get('geometry') else None
        if g is not None and (g.is_empty or not g.is_valid): errors.append({'id':feature_id(f),'reason':explain_validity(g)})
    return errors

def authored_errors(layers):
    errors=[]
    byid={feature_id(f):f for fs in layers.values() for f in fs}
    buildings={feature_id(f):shape(f['geometry']) for f in layers['buildings'] if f.get('geometry')}
    seen_names=set()
    bad_suffix=re.compile(r'~\d+|\-\d+$')
    provider_qualifier=re.compile(r'\((?:[^)]*(?:校区|南邮店|暂停营业|南京邮电大学)[^)]*)\)')
    for f in layers['ways']:
        if f['properties'].get('kind')=='crossing' and any(b.contains(shape(f['geometry']).interpolate(.5,normalized=True)) for b in buildings.values()):
            errors.append({'id':feature_id(f),'reason':'crossing through a building'})
    for layer, fs in layers.items():
        for f in fs:
            text=feature_id(f)+' '+str(f.get('properties',{}).get('name',''))
            if '~' in text and layer != 'rooms': errors.append({'id':feature_id(f),'reason':'counter suffix'})
            if bad_suffix.search(feature_id(f)) and layer in {'buildings','places'}: errors.append({'id':feature_id(f),'reason':'trailing counter'})
            if provider_qualifier.search(text): errors.append({'id':feature_id(f),'reason':'provider qualifier'})
            if '未命名' in text or '暂停营业' in text: errors.append({'id':feature_id(f),'reason':'placeholder or closed entity'})
    for f in layers['buildings']:
        category=f['properties'].get('category')
        if category is not None and category not in CATEGORIES: errors.append({'id':feature_id(f),'reason':f'category outside vocabulary: {category}'})
    campus_id,campus=campus_of(layers); parents=contained(layers)
    for f in layers['places']:
        p=f['properties']; category=p.get('category'); point=shape(f['geometry'])
        if 'parent' in p: errors.append({'id':feature_id(f),'reason':'parent is derived from geometry, not authored'})
        if point.geom_type!='Point': errors.append({'id':feature_id(f),'reason':'a place is a point'})
        if category not in CATEGORIES: errors.append({'id':feature_id(f),'reason':f'category outside vocabulary: {category}'})
        within=f'{campus_id}/' if campus.covers(point) else '周边/'
        if not feature_id(f).startswith(within): errors.append({'id':feature_id(f),'reason':f'a place here is under {within}'})
        parent=parents.get(feature_id(f))
        if parent:
            key=(parent,p.get('name'))
            if key in seen_names: errors.append({'id':feature_id(f),'reason':'two places of one name in one building'})
            seen_names.add(key)
        if any(seg in CATEGORIES for seg in feature_id(f).split('/')[1:]): errors.append({'id':feature_id(f),'reason':'category segment in id'})
    return errors

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,default=OUT); args=ap.parse_args(); out=args.output
    out.mkdir(parents=True, exist_ok=True)
    (out/'places.json').unlink(missing_ok=True)
    shutil.rmtree(out/'entities', ignore_errors=True)
    layers={n:load_layer(n) for n in LAYER_NAMES}
    layers['floors']=derive_floors(layers['buildings'])
    all_features=[f for fs in layers.values() for f in fs]; ids=[feature_id(f) for f in all_features]
    id_errors=[]; seen=set()
    for i in ids:
        if i in seen:id_errors.append(i)
        seen.add(i)
    byid={feature_id(f):f for f in all_features}
    parent_errors=[]
    for f in layers['rooms']+layers['floor_plates']+layers['cores']+layers['entrances']:
        p=f['properties'].get('parent')
        if p and p not in byid: parent_errors.append({'id':feature_id(f),'parent':p})
    geom_errors=[e for fs in layers.values() for e in check_geometry(fs)]
    authored_name_errors=authored_errors(layers)
    entity_features=[]; place_parents=contained(layers)
    for layer in ('campuses','buildings','floors','rooms','places','entrances'):
        for feature in layers[layer]:
            routed=copy.deepcopy(feature)
            routed['properties']=dict(routed.get('properties') or {})
            routed['properties']['kind']=LAYER_KINDS[layer]
            if layer=='places' and feature_id(feature) in place_parents: routed['properties']['parent']=place_parents[feature_id(feature)]
            entity_features.append(routed)
    network,nodes_m,route_nodes_m=build_network(
        layers['ways'],layers['entrances'],layers['buildings'],
        [f['geometry'] for f in layers['buildings']+layers['waters']],
        entities=entity_features,
        campus=shape(layers['campuses'][0]['geometry']),
        gates=[f['geometry']['coordinates'] for f in layers['places'] if f['properties'].get('name') in ('东门','西门','南门','北门')],
    )
    reachable={}
    for mode,name in ((WALK,'walking'),(BIKE,'bicycling')):
        seen=set(); q=deque([0])
        adj=defaultdict(list)
        for a,b,_,flags,_ in network['edges']:
            if flags&mode: adj[a].append(b);adj[b].append(a)
        while q:
            x=q.popleft()
            if x in seen:continue
            seen.add(x);q.extend(y for y in adj[x] if y not in seen)
        missing=[feature_id(f) for f in layers['entrances'] if network['entrances'][feature_id(f)] not in seen]
        reachable[name]={'nodes':len(seen),'missing_entrances':missing}
        if missing: raise ValueError(f'{name} unreachable entrances: {missing[:3]}')
    gate=route_gate(network,route_nodes_m)
    if OBS.exists():
        dump(ROOT/'bindings'/'route-gates.json',gate)
    # Derived places/entities: map only.
    places=[]; parents=contained(layers)
    entity_layers=(('campuses','campus'),('buildings','building'),('floors','floor'),('rooms','room'),('places','place'))
    for layer,kind in entity_layers:
      for f in layers[layer]:
        p=f['properties']; category=p.get('category')
        item={'id':feature_id(f),'kind':kind,'name':p.get('name'),'parent':parents.get(feature_id(f),p.get('parent')),
                                  'level':p.get('level'),'title':p.get('title'),'category':category,
                                  'group':group(category) if category else None,'tier':tier(category) if category else None,'aliases':p.get('aliases'),
                                  'geometry':None if kind=='floor' else f.get('geometry')}
        item['routing']={'type':'target','id':feature_id(f)}
        places.append({k:v for k,v in item.items() if v is not None})
    entities=sorted(places,key=lambda x:x['id'])
    # Authored basemap is a deterministic view of authored layers only.
    rendered_ways=[f for f in layers['ways'] if f['properties'].get('kind')!='crossing' and f['properties'].get('render',True)]
    def materialize(layer, feature):
        out=copy.deepcopy(feature); p=out['properties']; kind=LAYER_KINDS.get(layer)
        if kind and 'kind' not in p: p['kind']=kind
        if layer=='buildings' and 'style_hint' not in p:
            default=STYLE_DEFAULTS.get(p.get('category'))
            if default: p['style_hint']=default
        if layer=='ways':
            p.setdefault('walk',True); p.setdefault('bike',True); p.setdefault('steps',False)
        if layer in {'buildings','places'} and p.get('category'):
            p['group']=group(p['category']); p['tier']=tier(p['category'])
        if layer in {'buildings','places','waters','sports','context_buildings','ways','greens','surfaces'} and p.get('name'):
            p.setdefault('label',p['name'])
        return out
    rendered_ways=[materialize('ways',f) for f in rendered_ways]
    base=[materialize(layer,f) for layer,fs in (
        ('campuses',layers['campuses']),('buildings',layers['buildings']),('greens',layers['greens']),
        ('waters',layers['waters']),('sports',layers['sports']),('surfaces',layers['surfaces']),
        ('context_buildings',layers['context_buildings']),('places',layers['places'])) for f in fs]+rendered_ways
    for f in base: f.pop('id',None)
    base=sorted(base,key=feature_id)
    # The source way id is an authoring aid repeated on every segment; topology
    # clients only need endpoints, distance and modal flags.
    dump(out/'entities.json',entities); dump(out/'network.json',network)
    # Indoor shape of each floor: what is floor, and where the stairs, lifts and toilets are.
    indoor={}
    for f in layers['floor_plates']: indoor.setdefault(f['properties']['parent'],{'cores':[]})['plate']=f['geometry']
    for f in layers['cores']: indoor.setdefault(f['properties']['parent'],{'cores':[]})['cores'].append({'kind':f['properties']['kind'],'geometry':f['geometry']})
    dump(out/'indoor.json',indoor)
    dump(out/'basemap.geojson',{'type':'FeatureCollection','name':'authored-basemap','features':base})
    def one_label(features):
        # Many pieces can share a name; the largest speaks for them.
        largest={}
        for feature in features:
            name=feature['properties'].get('label')
            if name:
                area=transform(WGS_TO_M,shape(feature['geometry'])).area
                if area>largest.get(name,(0,))[0]: largest[name]=(area,feature['properties']['id'])
        keep={item[1] for item in largest.values()}
        for feature in features:
            if feature['properties'].get('label') and feature['properties']['id'] not in keep: feature['properties'].pop('label')
        return features
    tile_layers={'campus':[materialize('campuses',f) for f in layers['campuses']],
                 'buildings':[materialize('buildings',f) for f in layers['buildings']],
                 'ways':rendered_ways,
                 'greens':one_label([materialize('greens',f) for f in layers['greens']]),
                 'waters':one_label([materialize('waters',f) for f in layers['waters']]),
                 'sports':one_label([materialize('sports',f) for f in layers['sports']]),
                 'surfaces':one_label([materialize('surfaces',f) for f in layers['surfaces']]),
                 'context_buildings':one_label([materialize('context_buildings',f) for f in layers['context_buildings']]),
                 'places':[materialize('places',f) for f in layers['places']],
                 'building_forms':layers['building_forms']}
    tile_report=write_pmtiles(out/'basemap.pmtiles',tile_layers)
    preview=render_preview(out/'basemap-preview.png',tile_layers)
    campus_geom=shape(layers['campuses'][0]['geometry'])
    context=unary_union([shape(f['geometry']) for fs in tile_layers.values() for f in fs if f.get('geometry')])
    cb=transform(WGS_TO_M,campus_geom).bounds; xb=transform(WGS_TO_M,context).bounds
    margins=[cb[0]-xb[0],cb[1]-xb[1],xb[2]-cb[2],xb[3]-cb[3]]
    context_ok=min(margins)>=300
    entity_ids={item['id'] for item in entities}
    missing_targets=sorted(entity_ids-set(network['targets']))
    invalid_targets=sorted(entity_ids-{item['id'] for item in entities if item.get('routing',{}).get('id') in network['targets']})
    checks={'passed':not(id_errors or parent_errors or geom_errors or authored_name_errors or not context_ok or missing_targets or invalid_targets),'id_uniqueness':{'passed':not id_errors,'duplicates':id_errors},
            'geometry_validity':{'passed':not geom_errors,'errors':geom_errors},'parent_chains':{'passed':not parent_errors,'errors':parent_errors},'authored_invariants':{'passed':not authored_name_errors,'errors':authored_name_errors},
            'routing_targets':{'passed':not (missing_targets or invalid_targets),'missing':missing_targets,'invalid':invalid_targets},
            'reachability':reachable,'route_gate':gate,'counts':{k:len(v) for k,v in layers.items()},
            'basemap_context':{'passed':context_ok,'margins_m':[round(x,1) for x in margins],
                               'network_only_crossings':len(layers['ways'])-len(rendered_ways),'rendered_crossings':0,
                               'preview':preview,'tiles':tile_report},
            'artifacts':{'entities':str(out/'entities.json'),'network':str(out/'network.json'),
                         'basemap_geojson':str(out/'basemap.geojson'),'basemap_pmtiles':str(out/'basemap.pmtiles'),
                         'basemap_preview':str(out/'basemap-preview.png')}}
    dump(out/'checks.json',checks)
    if not checks['passed']: raise SystemExit(1)
    print(json.dumps({'output':str(out),'counts':checks['counts'],'route_gate':gate['status']},ensure_ascii=False))
if __name__=='__main__': main()









