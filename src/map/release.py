from __future__ import annotations
import argparse, hashlib, json, subprocess, sys, tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def run_check(*args):
    subprocess.run([sys.executable,*args],cwd=ROOT,check=True)

def main():
    ap=argparse.ArgumentParser(description='Build, verify, package and publish one immutable authored-map release.')
    ap.add_argument('version',nargs='?',default='map-v0.2.0',help='map-vX.Y.Z (default: map-v0.2.0)')
    ap.add_argument('--output',type=Path,default=ROOT/'build'/'release')
    ap.add_argument('--dry-run',action='store_true',help='build and package without calling gh release create')
    args=ap.parse_args()
    version=args.version if args.version.startswith('map-v') else 'map-v'+args.version
    run_check('src/map/format_geojson.py','--check')
    run_check('src/map/build_authored.py')
    out=ROOT/'build'/'space'/'仙林'
    checks=json.loads((out/'checks.json').read_text(encoding='utf8'))
    if not checks.get('passed'): raise SystemExit('authored map checks failed')
    manifest={'map_version':version,'built_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'crs':'EPSG:4326','coordinates':'7-decimal WGS84','layers':{},'artifacts':{}}
    for p in sorted((ROOT/'map'/'layers').glob('*.geojson')): manifest['layers'][p.name]={'sha256':sha(p),'bytes':p.stat().st_size}
    release_files = ('entities.json', 'network.json', 'indoor.json', 'basemap.pmtiles')
    release_space = args.output / 'space' / '仙林'
    release_space.mkdir(parents=True, exist_ok=True)
    for name in release_files:
        source = out / name
        target = release_space / name
        target.write_bytes(source.read_bytes())
        manifest['artifacts'][name] = {'sha256': sha(target), 'bytes': target.stat().st_size}
    local_layers = args.output / 'map' / 'layers'
    local_layers.mkdir(parents=True, exist_ok=True)
    for layer in sorted((ROOT / 'map' / 'layers').glob('*.geojson')):
        (local_layers / layer.name).write_bytes(layer.read_bytes())
    qa_space = ROOT / 'build' / 'qa' / '仙林'
    qa_space.mkdir(parents=True, exist_ok=True)
    for name in ('basemap.geojson', 'basemap-preview.png', 'checks.json'):
        (qa_space / name).write_bytes((out / name).read_bytes())
    manifest['qa_artifacts'] = [f'build/qa/仙林/{name}' for name in ('basemap.geojson', 'basemap-preview.png', 'checks.json')]
    args.output.mkdir(parents=True,exist_ok=True); m=args.output/'manifest.json'; m.write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf8')
    archive=args.output/f'njupt-map-{version.removeprefix("map-")}.tar.gz'
    with tarfile.open(archive,'w:gz') as t:
        t.add(ROOT/'map',arcname='map'); t.add(release_space,arcname='space/仙林'); t.add(m,arcname='manifest.json')
    if not args.dry_run:
        subprocess.run(['gh','release','create',version,str(archive),str(m),'--title',version,'--notes','Authored NJUPT campus map','--latest'],cwd=ROOT,check=True)
    print(json.dumps({'version':version,'archive':str(archive),'manifest':str(m),'published':not args.dry_run},ensure_ascii=False))
if __name__=='__main__': main()
