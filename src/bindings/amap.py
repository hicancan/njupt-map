"""Every 高德 place observed around the campus, related to the authored map: each is a place, building or field the map
authors, the same place as another observation, or a thing the map does not author as a place (a road name, an
address, a business that has closed). Nothing here feeds the build; this only says how far the authored map covers what
高德 shows, and which observation each authored place answers to.

    uv run python -m src.bindings.amap          # writes bindings/amap.json
    uv run python -m src.bindings.amap --check  # fails if any observation is left unrelated
"""
from __future__ import annotations
import argparse, json, math, re, sys
from pathlib import Path
from shapely.geometry import Point, shape
from shapely.strtree import STRtree
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
OBSERVED = ROOT / 'observations' / 'providers' / 'amap' / '仙林' / 'places.jsonl'
OUT = ROOT / 'bindings' / 'amap.json'
METRIC = Transformer.from_crs('EPSG:4326', 'EPSG:32650', always_xy=True).transform

# What 高德 lists that the map does not author as a place: names of roads, crossings, addresses and districts are
# authored as ways and the campus itself; a business marked closed is no longer there.
NOT_PLACES = ('地名地址信息',)
CLOSED = re.compile(r'暂停营业|已关闭|停业|已搬迁')
# Names that stand for the campus as a whole rather than a place in it.
CAMPUS_NAMES = {'南京邮电大学', '南京邮电大学仙林校区', '南京邮电大学(仙林校区)', '南京邮电大学停车场'}


def wgs84(gcj: str) -> tuple[float, float]:
    """高德's GCJ-02 coordinate as WGS84, the authored map's frame."""
    lng, lat = map(float, gcj.split(','))
    a, ee = 6378245.0, 0.00669342162296594323
    def lat_shift(x, y):
        r = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        r += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        return r + (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    def lng_shift(x, y):
        r = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        r += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        return r + (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    dlat, dlng = lat_shift(lng - 105.0, lat - 35.0), lng_shift(lng - 105.0, lat - 35.0)
    rad = lat / 180.0 * math.pi; magic = 1 - ee * math.sin(rad) ** 2; root = math.sqrt(magic)
    dlat = dlat * 180.0 / ((a * (1 - ee)) / (magic * root) * math.pi)
    dlng = dlng * 180.0 / (a / root * math.cos(rad) * math.pi)
    return round(lng - dlng, 7), round(lat - dlat, 7)


def plain(name: str) -> str:
    """A name without the school's prefix or a branch in brackets: what the place is called on campus."""
    name = re.sub(r'^南京邮电大学(仙林校区)?[-—·]?|^\(仙林校区\)', '', name.strip())
    return re.sub(r'[（(][^)）]*[)）]', '', name).strip(' -—·')


def alike(observed_name: str, authored_name: str) -> bool:
    """Whether two names say the same place: the same, or one the other with a brand or building word around it."""
    a, b = plain(observed_name), plain(authored_name).split('·')[0]
    return a == b or (min(len(a), len(b)) >= 2 and (a in b or b in a))


def observed() -> list[dict]:
    return [json.loads(line) for line in OBSERVED.read_text(encoding='utf-8').splitlines() if line.strip()]


def authored(root: Path = ROOT) -> dict[str, list[dict]]:
    layers = {}
    for name in ('campuses', 'buildings', 'places', 'sports'):
        layers[name] = json.loads((root / 'map' / 'layers' / f'{name}.geojson').read_text(encoding='utf-8'))['features']
    return layers


def relate(rows: list[dict], layers: dict[str, list[dict]]) -> list[dict]:
    """Each observation's relation to the authored map, in observation order."""
    places = layers['places']
    point_of = {f['properties']['id']: shape(f['geometry']) for f in places}
    tree = STRtree([point_of[f['properties']['id']] for f in places]); ids = [f['properties']['id'] for f in places]
    names = {}
    for f in places + layers['buildings'] + layers['sports']:
        p = f['properties']
        for n in [p.get('name'), *(p.get('aliases') or [])]:
            if n: names.setdefault(n, []).append(f)
    areas = [(f, shape(f['geometry'])) for f in layers['buildings'] + layers['sports']]
    campus = layers['campuses'][0]['properties']['id']
    out, mapped = [], {}
    for row in rows:
        at = Point(*wgs84(row['location'])); name = plain(row['name'])
        record = {'poi': row['id'], 'name': row['name']}
        if row['type'].startswith(NOT_PLACES): record['excluded'] = '地名'
        elif CLOSED.search(row['name']): record['excluded'] = '已停业'
        elif row['name'] in CAMPUS_NAMES: record['map'] = campus
        else:
            near = [ids[i] for i in tree.query(at.buffer(0.00004))]  # about 4 m: authored from this observation
            same = [i for i in near if alike(name, i.split('/', 1)[1])]
            joined = re.sub(r'[()（）]', '', row['name'])  # 1号楼(公交站) is the stop 1号楼公交站
            named = [f for n in dict.fromkeys((name, row['name'], joined)) for f in names.get(n, []) if shape(f['geometry']).distance(at) < 0.0012]
            inside = [f for f, g in areas if g.covers(at) and f in named]
            if same: record['map'] = same[0]
            elif inside: record['map'] = inside[0]['properties']['id']
            elif named: record['map'] = named[0]['properties']['id']
            elif (twin := mapped.get(name)) and twin[1].distance(at) < 0.0006: record['same_as'] = twin[0]
            else: record['uncovered'] = True
        if 'map' in record: mapped.setdefault(name, (row['id'], at))
        out.append(record)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--check', action='store_true'); args = ap.parse_args()
    records = relate(observed(), authored())
    left = [r for r in records if r.get('uncovered')]
    if args.check:
        if left: sys.exit(f'{len(left)} 高德 places are not related to the authored map, e.g. {left[0]["name"]}')
        return
    OUT.write_text(json.dumps(sorted(records, key=lambda r: r['poi']), ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    counts = {k: sum(1 for r in records if k in r) for k in ('map', 'same_as', 'excluded', 'uncovered')}
    print(json.dumps({'observations': len(records), **counts}, ensure_ascii=False))


if __name__ == '__main__': main()
