import json
import math
import re
import sys
import unittest
from pathlib import Path
import mapbox_vector_tile
from pmtiles.reader import MmapSource, Reader
from shapely.geometry import Point, shape
from shapely.geometry import box
from src.map import build_authored

class AuthoredMapTest(unittest.TestCase):
    @staticmethod
    def _tile_bounds(z, x, y):
        n = 2**z
        def lonlat(tx, ty):
            lon = tx / n * 360 - 180
            lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
            return lon, lat
        west, north = lonlat(x, y)
        east, south = lonlat(x + 1, y + 1)
        return box(west, south, east, north)

    @staticmethod
    def _tile_xy(lon, lat, z):
        n = 2**z
        return ((lon + 180) / 360 * n,
                (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

    def test_authored_contract(self):
        layers=sorted(Path('map/layers').glob('*.geojson')); self.assertTrue(layers)
        features=[]
        for path in layers:
            data=json.loads(path.read_text(encoding='utf8'))
            self.assertEqual(data['type'],'FeatureCollection')
            self.assertNotEqual(path.stem,'floors')
            self.assertEqual(data['features'],sorted(data['features'],key=lambda f:f['properties']['id']))
            kinds={f['properties'].get('kind') for f in data['features'] if 'kind' in f['properties']}
            self.assertTrue(not kinds or len(kinds)>1)
            for f in data['features']:
                self.assertNotIn('id',f)
                p=f['properties']; self.assertIn('id',p)
                self.assertNotIn('floor_id',p); self.assertNotIn('parent_id',p)
                self.assertFalse('name' in p and p['name'] in (None,''))
                self.assertNotIn('walk',p if p.get('walk') is True else {})
                self.assertNotIn('bike',p if p.get('bike') is True else {})
                self.assertNotIn('steps',p if p.get('steps') is False else {})
            features.extend((path.stem,f) for f in data['features'])
        ids=[f['properties']['id'] for _,f in features]; self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(all('geometry_role' not in f['properties'] for _,f in features))
        self.assertFalse(any(re.search(r'~\d+',f['properties']['id']) for _,f in features))
        self.assertFalse(any('未命名' in f['properties']['id']+' '+str(f['properties'].get('name','')) for _,f in features))
        self.assertFalse(any('暂停营业' in f['properties']['id']+' '+str(f['properties'].get('name','')) for _,f in features))
        buildings={f['properties']['id']:shape(f['geometry']) for layer,f in features if layer=='buildings'}
        places=[f for layer,f in features if layer=='places']
        self.assertTrue(places)
        self.assertTrue(all(f['properties']['category'] in build_authored.CATEGORY_VOCAB for f in places))
        pairs={(f['properties'].get('parent'),f['properties']['name']) for f in places}
        self.assertEqual(len(pairs),len(places))
        for f in places:
            parent=f['properties'].get('parent')
            if parent:
                self.assertIn(parent,buildings)
                self.assertTrue(buildings[parent].covers(Point(f['geometry']['coordinates'])))
                self.assertNotEqual(f['properties'].get('name'), next(
                    b['properties'].get('name') for layer,b in features
                    if layer=='buildings' and b['properties']['id']==parent
                ))
        self.assertIn('仙林/一食堂', {f['properties']['id'] for _,f in features})
        self.assertIn('仙林/地理与生物信息学院', {f['properties']['id'] for _,f in features})
        self.assertTrue(any('地理与生物信息学院' in f['properties'].get('aliases',[]) for _,f in features if f['properties']['id']=='仙林/地理与生物信息学院'))

    def test_build_without_references_or_bindings(self):
        old_obs,old_out=build_authored.OBS,build_authored.OUT
        try:
            build_authored.OBS=Path(self.id()).parent/'no-observations.jsonl'
            build_authored.OUT=Path('build')/'test-authored-pure'
            sys.argv=['build_authored']; build_authored.main()
            checks=json.loads((build_authored.OUT/'checks.json').read_text(encoding='utf8'))
            self.assertTrue(checks['passed']); self.assertEqual(checks['route_gate']['status'],'skipped')
            self.assertTrue((build_authored.OUT/'basemap.geojson').is_file())
            self.assertTrue((build_authored.OUT/'basemap.pmtiles').is_file())
            self.assertTrue((build_authored.OUT/'basemap-preview.png').is_file())
            self.assertEqual((build_authored.OUT/'basemap.pmtiles').read_bytes()[:7],b'PMTiles')
            self.assertEqual(checks['basemap_context']['rendered_crossings'],0)
            entities=json.loads((build_authored.OUT/'entities.json').read_text(encoding='utf8'))
            self.assertTrue(any(item.get('aliases')==['图馆','仙林图书馆'] for item in entities))
            floors=[item for item in entities if item['kind']=='floor']
            self.assertEqual(len(floors),sum(int(f['properties']['levels']) for f in json.loads(Path('map/layers/buildings.geojson').read_text(encoding='utf8'))['features']))
            self.assertTrue(all('geometry' not in item for item in floors))
        finally:
            build_authored.OBS,build_authored.OUT=old_obs,old_out

    def test_basemap_has_continuous_campus_tiles_through_z18(self):
        output = build_authored.OUT / 'basemap.pmtiles'
        campus = shape(json.loads(Path('map/layers/campuses.geojson').read_text(encoding='utf8'))['features'][0]['geometry'])
        with output.open('rb') as source:
            reader = Reader(MmapSource(source))
            self.assertEqual(reader.header()['max_zoom'], 18)
            for z in range(12, 19):
                minx, miny, maxx, maxy = campus.bounds
                start = self._tile_xy(minx, miny, z)
                end = self._tile_xy(maxx, maxy, z)
                for x in range(math.floor(start[0]), math.floor(end[0]) + 1):
                    for y in range(math.floor(end[1]), math.floor(start[1]) + 1):
                        if not self._tile_bounds(z, x, y).intersects(campus):
                            continue
                        tile = reader.get(z, x, y)
                        self.assertIsNotNone(tile, f'missing campus tile z{z}/{x}/{y}')
                        layers = mapbox_vector_tile.decode(tile)
                        self.assertTrue(layers.get('campus', {}).get('features'), f'missing campus layer z{z}/{x}/{y}')
                        self.assertTrue(any(layers.get(name, {}).get('features') for name in ('greens', 'surfaces', 'ways', 'buildings')), f'missing ground layers z{z}/{x}/{y}')

if __name__=='__main__': unittest.main()
