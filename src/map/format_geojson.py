from __future__ import annotations
import argparse, json
from pathlib import Path
from shapely.geometry import shape

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
        data['features']=sorted(data['features'],key=lambda f:f['id'])
        for f in data['features']:
            if f.get('geometry'): f['geometry']['coordinates']=round_coords(f['geometry']['coordinates'])
    canonical=(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
    return original==canonical, canonical

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--check',action='store_true'); ap.add_argument('paths',nargs='*'); args=ap.parse_args()
    paths=[Path(x) for x in args.paths] or list((ROOT/'map'/'layers').glob('*.geojson'))
    bad=[]
    for p in sorted(paths):
        same,canonical=canonicalize(p)
        if args.check:
            if not same: bad.append(str(p))
        else: p.write_bytes(canonical)
    if bad:
        raise SystemExit('non-canonical GeoJSON: '+', '.join(bad))
if __name__=='__main__': main()
