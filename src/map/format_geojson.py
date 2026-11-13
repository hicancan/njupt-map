from __future__ import annotations
import argparse, json
from pathlib import Path
from shapely.geometry import shape
try:
    from .vocabulary import STYLE_DEFAULTS
except ImportError:
    from vocabulary import STYLE_DEFAULTS

ROOT=Path(__file__).resolve().parents[2]
DECIMALS=7

def round_coords(value):
    if isinstance(value,float): return round(value,DECIMALS)
    if isinstance(value,list): return [round_coords(x) for x in value]
    return value

def canonicalize(path:Path):
    original=path.read_bytes()
    data=json.loads(original.decode('utf-8'))
    if data.get('type')=='FeatureCollection':
        data['features']=sorted(data['features'],key=lambda f:f.get('properties',{}).get('id',''))
        for f in data['features']:
            if f.get('geometry'): f['geometry']['coordinates']=round_coords(f['geometry']['coordinates'])
    canonical=(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
    return original==canonical, canonical

def schema_errors(path:Path, data:dict):
    errors=[]; layer=path.stem
    if layer=='floors': errors.append('floors layer is derived and must not be authored')
    if data.get('type')!='FeatureCollection': return errors+['not a FeatureCollection']
    features=data.get('features') or []; ids=[]
    for index,f in enumerate(features):
        p=f.get('properties') or {}; fid=p.get('id'); ids.append(fid)
        if 'id' in f: errors.append(f'feature {index}: top-level id is forbidden')
        if not fid: errors.append(f'feature {index}: properties.id is required')
        for field in ('floor_id','parent_id'):
            if field in p: errors.append(f'{fid}: {field} is forbidden; use parent')
        if 'name' in p and p['name'] in (None,''): errors.append(f'{fid}: empty name must be omitted')
        if p.get('walk') is True: errors.append(f'{fid}: walk=true is the default and must be omitted')
        if p.get('bike') is True: errors.append(f'{fid}: bike=true is the default and must be omitted')
        if p.get('steps') is False: errors.append(f'{fid}: steps=false is the default and must be omitted')
        if layer=='buildings' and 'style_hint' in p and p['style_hint']==STYLE_DEFAULTS.get(p.get('category')):
            errors.append(f'{fid}: style_hint repeats the category default')
    if len(ids)!=len(set(ids)): errors.append(f'{path}: duplicate properties.id')
    kinds={f.get('properties',{}).get('kind') for f in features if 'kind' in (f.get('properties') or {})}
    if kinds and len(kinds)<=1: errors.append(f'{path}: constant kind belongs to the layer, omit it')
    return errors

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--check',action='store_true'); ap.add_argument('paths',nargs='*'); args=ap.parse_args()
    paths=[Path(x) for x in args.paths] or list((ROOT/'map'/'layers').glob('*.geojson'))
    bad=[]
    for p in sorted(paths):
        try:
            data=json.loads(p.read_text(encoding='utf8'))
            errors=schema_errors(p,data)
            same,canonical=canonicalize(p)
        except Exception as exc:
            errors=[f'{p}: {exc}']; same=False; canonical=b''
        if args.check:
            if errors or not same: bad.append(f'{p}: '+('; '.join(errors) if errors else 'non-canonical'))
        else: p.write_bytes(canonical)
    if bad:
        raise SystemExit('non-canonical GeoJSON: '+', '.join(bad))
if __name__=='__main__': main()
