"""Acquire provider answers into observations/providers only.

This module deliberately has no writer for map/layers or build outputs. The
published authored map is edited in QGIS; provider answers are references used
for provenance and the optional route comparison gate.
"""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2]
OBS=ROOT/'observations'/'providers'
OVERPASS='https://overpass-api.de/api/interpreter'
AMAP='https://restapi.amap.com'

def write(path:Path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')

def request_json(url:str, *, data:bytes|None=None, headers:dict[str,str]|None=None):
    req=Request(url,data=data,headers=headers or {'User-Agent':'njupt-map observation acquisition'})
    with urlopen(req,timeout=180) as response:
        return json.loads(response.read().decode('utf-8'))

def acquire_osm(campus:str,bbox:tuple[float,float,float,float]):
    west,south,east,north=bbox
    query=f'[out:json][timeout:120];nwr({south},{west},{north},{east});out meta geom;'
    answer=request_json(OVERPASS,data=urlencode({'data':query}).encode(),headers={'User-Agent':'njupt-map observation acquisition'})
    write(OBS/'osm'/campus/'raw.json',answer)
    return {'elements':len(answer.get('elements',[]))}

def acquire_amap_places(campus:str,bbox:tuple[float,float,float,float]):
    key=os.environ['AMAP_KEY']; west,south,east,north=bbox
    query=urlencode({'key':key,'polygon':f'{west},{north}|{east},{south}','types':'010000|020000|030000|040000|050000|060000|070000|080000|090000|100000|110000|120000|130000|140000|150000|160000|170000|180000|190000|200000|970000|990000','page_size':25,'page_num':1,'show_fields':'business,navi,indoor,photos'})
    answer=request_json(f'{AMAP}/v5/place/polygon?{query}')
    rows=answer.get('pois') or []
    path=OBS/'amap'/campus/'places.jsonl'; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n' for r in sorted(rows,key=lambda r:r.get('id',''))),encoding='utf-8')
    return {'places':len(rows)}

def acquire(only:str,campus:str,bbox:tuple[float,float,float,float]):
    if only=='osm': return acquire_osm(campus,bbox)
    if only=='amap': return acquire_amap_places(campus,bbox)
    raise ValueError('only must be osm or amap; basemap acquisition is intentionally unsupported')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('only',choices=['osm','amap']); ap.add_argument('--campus',default='仙林'); ap.add_argument('--bbox',nargs=4,type=float,required=True); args=ap.parse_args()
    print(json.dumps(acquire(args.only,args.campus,tuple(args.bbox)),ensure_ascii=False))
if __name__=='__main__': main()
