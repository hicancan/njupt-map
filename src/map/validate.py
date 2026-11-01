"""Validate the authored GeoJSON layer contract."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from shapely.geometry import shape
from .authored import ROOT, load_layers

def validate(root: Path = ROOT):
    layers = load_layers(root)
    errors=[]; ids=[]
    for name, features in layers.items():
        for feature in features:
            ident=(feature.get('properties') or {}).get('id')
            if not ident: errors.append(f'{name}: missing id')
            ids.append(ident)
            if feature.get('geometry'):
                g=shape(feature['geometry'])
                if g.is_empty or not g.is_valid: errors.append(f'{ident}: invalid geometry')
    if len(ids)!=len(set(ids)): errors.append('duplicate authored ids')
    return {'passed':not errors,'errors':errors,'counts':{name:len(features) for name,features in layers.items()}}

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--root',type=Path,default=ROOT); args=parser.parse_args()
    report=validate(args.root); print(json.dumps(report,ensure_ascii=False,indent=2)); raise SystemExit(0 if report['passed'] else 1)
