from __future__ import annotations
import argparse, hashlib, json, tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('version',help='X.Y.Z'); ap.add_argument('--output',type=Path,default=ROOT/'build'/'release'); args=ap.parse_args()
    version=args.version if args.version.startswith('map-v') else 'map-v'+args.version
    out=ROOT/'build'/'space'/'仙林'
    if not (out/'checks.json').is_file(): raise SystemExit('run src/map/build_authored.py first')
    manifest={'map_version':version,'built_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'crs':'EPSG:4326','coordinates':'7-decimal WGS84','layers':{},'artifacts':{}}
    for p in sorted((ROOT/'map'/'layers').glob('*.geojson')): manifest['layers'][p.name]={'sha256':sha(p),'bytes':p.stat().st_size}
    for p in sorted(out.rglob('*')):
        if p.is_file(): manifest['artifacts'][p.relative_to(out).as_posix()]={'sha256':sha(p),'bytes':p.stat().st_size}
    args.output.mkdir(parents=True,exist_ok=True); m=args.output/'manifest.json'; m.write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf8')
    archive=args.output/f'njupt-map-{version}.tar.gz'
    with tarfile.open(archive,'w:gz') as t:
        t.add(ROOT/'map',arcname='map'); t.add(out,arcname='space/仙林'); t.add(m,arcname='manifest.json')
    print(json.dumps({'version':version,'archive':str(archive),'manifest':str(m)},ensure_ascii=False))
if __name__=='__main__': main()
