"""Read the authored GeoJSON map layers as the sole spatial source."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from shapely.geometry import shape,Polygon,LineString,Point
from shapely import constrained_delaunay_triangles
from shapely.ops import transform
from pyproj import Transformer
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'map'/'layers'
LAYER_NAMES=('campuses','buildings','rooms','places','entrances','ways','greens','waters','sports','surfaces','context_buildings','landscape_exclusions')
WGS_TO_M=Transformer.from_crs('EPSG:4326','EPSG:32650',always_xy=True).transform
M_TO_WGS=Transformer.from_crs('EPSG:32650','EPSG:4326',always_xy=True).transform
def source_digest(path:Path=SOURCE):
    path=Path(path); files=sorted(path.rglob('*.geojson')) if path.is_dir() else [path]; h=hashlib.sha256()
    for f in files: h.update((f.relative_to(path) if path.is_dir() else f.name).as_posix().encode()); h.update(f.read_bytes())
    return h.hexdigest()
def load_layers(root=ROOT):
    base=Path(root)/'map'/'layers'; out={}
    for name in LAYER_NAMES:
        d=json.loads((base/f'{name}.geojson').read_text(encoding='utf-8'))
        if d.get('type')!='FeatureCollection': raise ValueError(f'{name} is not FeatureCollection')
        out[name]=sorted(d['features'],key=lambda f:f['properties']['id'])
    return out
def _local(geom,origin): return transform(lambda x,y,z=None:(WGS_TO_M(x,y)[0]-origin[0],WGS_TO_M(x,y)[1]-origin[1]),geom)
def _poly_record(feature,origin):
    g=_local(shape(feature['geometry']),origin); p=feature['properties']
    if g.geom_type == 'MultiPolygon': g=max(g.geoms,key=lambda part: part.area)
    if not isinstance(g,Polygon) or g.is_empty or not g.is_valid: raise ValueError(f"Invalid polygon {p['id']}")
    cx,cy=g.centroid.coords[0]
    roof=[[[round(x,6),round(y,6)] for x,y in list(t.exterior.coords)[:3]] for t in constrained_delaunay_triangles(g).geoms]
    return {'id':p['id'],'asset_id':p['id'],'map_feature_id':p['id'],'space_id':p['id'],'name':p.get('name',p['id']),'outer':[[round(x,6),round(y,6)] for x,y in list(g.exterior.coords)[:-1]],'holes':[[[round(x,6),round(y,6)] for x,y in list(r.coords)[:-1]] for r in g.interiors],'roof_triangles':roof,'center':[round(cx,6),round(cy,6)],'height':float(p.get('height_m',1) or 1),'levels':int(p.get('levels',1) or 1),'min_height':float(p.get('min_height_m',0) or 0),'base_z':float(p.get('base_z_m',0) or 0),'height_source':p.get('height_source','authored'),'levels_source':'authored','geometry_role':'authored_footprint','style_hint':p.get('style_hint')}
def spatial_signature(building):
    payload={k:building.get(k) for k in ('outer','holes','height','levels','min_height','geometry_role','upper_volumes')}; return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
def load_authored(root=ROOT):
    root=Path(root)
    if root.name == 'layers': root=root.parent.parent
    layers=load_layers(root); campus=shape(layers['campuses'][0]['geometry']); c=_local(campus,[0,0]).centroid.coords[0]; origin=[round(c[0],3),round(c[1],3)]
    data={'metadata':{'crs':'EPSG:32650','origin_easting_northing':origin,'origin_lonlat':list(M_TO_WGS(*origin)),'ground_elevation':0,'evidence_note':'Authored GeoJSON layers','source_geometry_snapshot':'map/layers','dataset_sha256':''}}
    data['boundary']=_poly_record(layers['campuses'][0],origin); data['buildings']=[]
    for f in layers['buildings']:
        b=_poly_record(f,origin); b['spatial_signature']=spatial_signature(b); data['buildings'].append(b)
    for name in ('greens','waters','sports','surfaces','context_buildings','landscape_exclusions'): data[name]=[_poly_record(f,origin) for f in layers[name] if f.get('geometry')]
    data['roads']=[]
    for f in layers['ways']:
        if not f.get('geometry'): continue
        g=_local(shape(f['geometry']),origin)
        if isinstance(g,LineString): data['roads'].append({'asset_id':f['properties']['id'],'name':f['properties'].get('name',f['properties']['id']),'points':[[round(x,6),round(y,6)] for x,y in g.coords],'width':float(f['properties'].get('width_m',4) or 4)})
    data['pois']=[]
    for f in layers['places']:
        if not f.get('geometry'): continue
        g=_local(shape(f['geometry']),origin)
        if isinstance(g,Point): data['pois'].append({'asset_id':f['properties']['id'],'name':f['properties'].get('name',f['properties']['id']),'point':[round(g.x,6),round(g.y,6)]})
    data['trees']=[]; data['metadata']['counts']={k:len(v) for k,v in data.items() if isinstance(v,list)}; data['metadata']['dataset_sha256']=hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(); return data
