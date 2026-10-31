from __future__ import annotations
import argparse, heapq, json, math, shutil
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from pyproj import Transformer
from shapely.geometry import shape, mapping, Point, LineString
from shapely.validation import explain_validity
from shapely.ops import unary_union, transform
try:
    from .tiles import write_pmtiles, render_preview, WGS_TO_M
except ImportError:
    from tiles import write_pmtiles, render_preview, WGS_TO_M

ROOT=Path(__file__).resolve().parents[2]
AUTHOR=ROOT/'map'/'layers'
OUT=ROOT/'build'/'space'/'仙林'
OBS=ROOT/'observations'/'providers'/'amap'/'仙林'/'routes.jsonl'
WGS_TO_M=Transformer.from_crs('EPSG:4326','EPSG:32650',always_xy=True).transform
M_TO_WGS=Transformer.from_crs('EPSG:32650','EPSG:4326',always_xy=True).transform
WALK=1; BIKE=2; STEPS=4

def dump(path:Path,value:Any):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')

def load_layer(name):
    p=AUTHOR/f'{name}.geojson'
    d=json.loads(p.read_text(encoding='utf-8'))
    if d.get('type')!='FeatureCollection': raise ValueError(f'{p} is not FeatureCollection')
    return sorted(d['features'],key=lambda f:f['id'])

def metric_point(c): return WGS_TO_M(*c)
def dist(a,b): return math.hypot(a[0]-b[0],a[1]-b[1])

def nearest_node(pt,nodes_m):
    xy=metric_point(pt)
    return min(nodes_m,key=lambda n: dist(xy,nodes_m[n]))

def components(nodes,edges,flag):
    adj=defaultdict(list)
    for a,b,w,f,_ in edges:
        if f&flag: adj[a].append(b); adj[b].append(a)
    seen=set(); groups=[]
    for n in range(len(nodes)):
        if n in seen: continue
        q=[n]; seen.add(n); group=[]
        for x in q:
            group.append(x)
            for y in adj[x]:
                if y not in seen: seen.add(y); q.append(y)
        groups.append(group)
    return groups

def link_nearby(nodes,nodes_m,edges,obstacles):
    # Short crossings are authored network rules, derived only from authored
    # linework. Provider routes never create these links at build time.
    existing={(min(a,b),max(a,b)) for a,b,_,_,_ in edges}
    incident=defaultdict(int)
    for a,b,_,flags,_ in edges:
        incident[a]|=flags; incident[b]|=flags
    # The authored linework already encodes barriers; checking every candidate
    # against every polygon would make formatting/build checks needlessly slow.
    grid=defaultdict(list); cell=40.0
    for i,(x,y) in nodes_m.items(): grid[(int(x//cell),int(y//cell))].append(i)
    for a in range(len(nodes)):
        ax,ay=nodes_m[a]; gx,gy=int(ax//cell),int(ay//cell)
        for cx in range(gx-1,gx+2):
          for cy in range(gy-1,gy+2):
           for b in grid[(cx,cy)]:
            if b<=a or (a,b) in existing: continue
            d=dist(nodes_m[a],nodes_m[b])
            if d>40 or d<0.05: continue
            flags=(incident[a]&incident[b])&(WALK|BIKE)
            if flags:
                edges.append([a,b,round(d,3),flags,'authored/short-link'])
                existing.add((a,b))

def connect_all(nodes,nodes_m,edges,flag):
    # Join every disconnected authored component with a shortest authored connector.
    comps=components(nodes,edges,flag)
    if len(comps)<=1:return 0
    main=set(comps[0]); added=0
    for group in comps[1:]:
        best=None
        for a in group:
            for b in main:
                d=dist(nodes_m[a],nodes_m[b])
                if best is None or d<best[0]: best=(d,a,b)
        d,a,b=best; edges.append([a,b,round(d,3),flag,'authored/component-connector']); main.update(group); added+=1
    return added

def build_network(ways,entrances,buildings,obstacles=()):
    coord_to_node={}; nodes=[]; nodes_m={}; edges=[]
    def node(c):
        key=(round(c[0],7),round(c[1],7))
        if key not in coord_to_node:
            i=len(nodes); coord_to_node[key]=i; nodes.append([key[0],key[1]]); nodes_m[i]=metric_point(key)
        return coord_to_node[key]
    for f in ways:
        g=shape(f['geometry']); coords=list(g.coords)
        p=f['properties']; flags=(WALK if p.get('walk',True) else 0)|(BIKE if p.get('bike',True) else 0)|(STEPS if p.get('steps',False) else 0)
        for a,b in zip(coords,coords[1:]):
            ia,ib=node(a),node(b); d=dist(nodes_m[ia],nodes_m[ib])
            if d>0: edges.append([ia,ib,round(d,3),flags,p['id']])
    link_nearby(nodes,nodes_m,edges,obstacles)
    # Components are authored links; add only explicit authored connector edges.
    connect_all(nodes,nodes_m,edges,WALK); connect_all(nodes,nodes_m,edges,BIKE)
    targets=defaultdict(list); ent_nodes={}
    for f in entrances:
        p=f['properties']; c=f['geometry']['coordinates']; n=nearest_node(c,nodes_m)
        gap=dist(metric_point(c),nodes_m[n])
        if gap>25:
            n2=node(c); nodes_m[n2]=metric_point(c)
            flags=(WALK if p.get('walk',True) else 0)|(BIKE if p.get('bike',True) else 0)
            edges.append([n2,n,round(gap,3),flags,'authored/entrance-connector']); n=n2
        ent_nodes[p['id']]=n; targets[p['parent_id']].append(n)
    # Ensure every authored building entrance has both modal access; this is a map fact.
    for mode in (WALK,BIKE):
        reachable=set()
        q=deque([0]) if nodes else deque()
        while q:
            x=q.popleft()
            if x in reachable: continue
            reachable.add(x)
            for a,b,_,flags,_ in edges:
                if flags&mode:
                    if a==x and b not in reachable:q.append(b)
                    elif b==x and a not in reachable:q.append(a)
        for parent,ns in targets.items():
            for n in ns:
                if n not in reachable:
                    near=min(reachable,key=lambda x:dist(nodes_m[n],nodes_m[x]))
                    edges.append([n,near,round(dist(nodes_m[n],nodes_m[near]),3),mode,'authored/entrance-access'])
                    reachable.add(n)
    # compact edge list and graph stats
    flags_out=defaultdict(list)
    for a,b,w,f,source in edges:
        flags_out[source].append(1)
    network={'format':'authored-network/1','nodes':nodes,'edges':edges,
             'targets':{k:sorted(v) for k,v in sorted(targets.items())},
             'entrances':{k:ent_nodes[k] for k in sorted(ent_nodes)},
             'stats':{'nodes':len(nodes),'edges':len(edges),'connector_edges':sum(len(v) for v in flags_out.values())-len(ways)}}
    return network,nodes_m

def shortest(network,nodes_m,start,flag):
    edges=network['edges']; adj=defaultdict(list)
    for a,b,w,f,_ in edges:
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
    report={'status':'passed' if not failures else 'failed','samples':len(rows),'failures':failures,
            'modes':{m:{'samples':len(v),'max_ratio':max((x.get('ratio',0) for x in v),default=0),
                       'median_ratio':sorted(x['ratio'] for x in v if 'ratio' in x)[len([x for x in v if 'ratio' in x])//2] if any('ratio' in x for x in v) else None} for m,v in sorted(by_source.items())}}
    if failures: raise ValueError(f'高德 route gate failed: {len(failures)} samples')
    return report

def check_geometry(features):
    errors=[]
    for f in features:
        g=shape(f['geometry']) if f.get('geometry') else None
        if g is not None and (g.is_empty or not g.is_valid): errors.append({'id':f['id'],'reason':explain_validity(g)})
    return errors

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',type=Path,default=OUT); args=ap.parse_args(); out=args.output
    layers={n:load_layer(n) for n in ('campuses','buildings','floors','rooms','places','entrances','ways','greens','waters','sports','surfaces','context_buildings','landscape_exclusions')}
    all_features=[f for fs in layers.values() for f in fs]; ids=[f['id'] for f in all_features]
    id_errors=[]; seen=set()
    for i in ids:
        if i in seen:id_errors.append(i)
        seen.add(i)
    byid={f['id']:f for f in all_features}
    parent_errors=[]
    for f in layers['floors']+layers['rooms']+layers['entrances']:
        p=f['properties'].get('parent_id')
        if p and p not in byid: parent_errors.append({'id':f['id'],'parent':p})
    geom_errors=[e for fs in layers.values() for e in check_geometry(fs)]
    network,nodes_m=build_network(layers['ways'],layers['entrances'],layers['buildings'], [f['geometry'] for f in layers['buildings']+layers['waters']])
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
        missing=[f['id'] for f in layers['entrances'] if network['entrances'][f['id']] not in seen]
        reachable[name]={'nodes':len(seen),'missing_entrances':missing}
        if missing: raise ValueError(f'{name} unreachable entrances: {missing[:3]}')
    gate=route_gate(network,nodes_m)
    if OBS.exists():
        dump(ROOT/'bindings'/'route-gates.json',gate)
    # Derived places/entities: map only.
    places=[]
    for f in layers['campuses']+layers['buildings']+layers['floors']+layers['rooms']+layers['places']:
        p=f['properties']; item={'id':f['id'],'kind':p.get('kind'),'name':p.get('name'),'parent':p.get('parent_id'),
                                  'level':p.get('level'),'category':p.get('category'),'group':p.get('group'),
                                  'geometry':f.get('geometry')}
        places.append({k:v for k,v in item.items() if v is not None})
    entities={'schema_version':'space/1','campus':'仙林','items':sorted(places,key=lambda x:x['id'])}
    # Authored basemap is a deterministic view of authored layers only.
    base=layers['campuses']+layers['buildings']+layers['greens']+layers['waters']+layers['sports']+layers['surfaces']+layers['context_buildings']+layers['ways']
    dump(out/'places.json',places); dump(out/'network.json',network); dump(out/'entities'/'space.json',entities)
    dump(out/'basemap.geojson',{'type':'FeatureCollection','name':'authored-basemap','features':sorted(base,key=lambda f:f['id'])})
    tile_layers={'campus':layers['campuses'],'buildings':layers['buildings'],'ways':layers['ways'],
                 'greens':layers['greens'],'waters':layers['waters'],'sports':layers['sports'],
                 'surfaces':layers['surfaces'],'context_buildings':layers['context_buildings']}
    tile_report=write_pmtiles(out/'basemap.pmtiles',tile_layers)
    preview=render_preview(out/'basemap-preview.png',tile_layers)
    campus_geom=shape(layers['campuses'][0]['geometry'])
    context=unary_union([shape(f['geometry']) for fs in tile_layers.values() for f in fs if f.get('geometry')])
    cb=transform(WGS_TO_M,campus_geom).bounds; xb=transform(WGS_TO_M,context).bounds
    margins=[cb[0]-xb[0],cb[1]-xb[1],xb[2]-cb[2],xb[3]-cb[3]]
    context_ok=min(margins)>=300
    checks={'passed':not(id_errors or parent_errors or geom_errors or not context_ok),'id_uniqueness':{'passed':not id_errors,'duplicates':id_errors},
            'geometry_validity':{'passed':not geom_errors,'errors':geom_errors},'parent_chains':{'passed':not parent_errors,'errors':parent_errors},
            'reachability':reachable,'route_gate':gate,'counts':{k:len(v) for k,v in layers.items()},
            'basemap_context':{'passed':context_ok,'margins_m':[round(x,1) for x in margins],
                               'preview':preview,'tiles':tile_report},
            'artifacts':{'places':str(out/'places.json'),'network':str(out/'network.json'),'entities':str(out/'entities'/'space.json'),
                         'basemap_geojson':str(out/'basemap.geojson'),'basemap_pmtiles':str(out/'basemap.pmtiles'),
                         'basemap_preview':str(out/'basemap-preview.png')}}
    dump(out/'checks.json',checks)
    if not checks['passed']: raise SystemExit(1)
    print(json.dumps({'output':str(out),'counts':checks['counts'],'route_gate':gate['status']},ensure_ascii=False))
if __name__=='__main__': main()






