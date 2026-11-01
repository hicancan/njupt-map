import json
import re
import sys
import unittest
from pathlib import Path
from shapely.geometry import Point, shape
from src.map import build_authored

class AuthoredMapTest(unittest.TestCase):
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

if __name__=='__main__': unittest.main()
