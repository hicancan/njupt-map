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
            self.assertEqual(data['features'],sorted(data['features'],key=lambda f:f['id']))
            features.extend((path.stem,f) for f in data['features'])
        ids=[f['id'] for _,f in features]; self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(all('geometry_role' not in f['properties'] for _,f in features))
        self.assertFalse(any(re.search(r'~\d+',f['id']) for _,f in features))
        self.assertFalse(any('未命名' in f['id']+' '+str(f['properties'].get('name','')) for _,f in features))
        self.assertFalse(any('暂停营业' in f['id']+' '+str(f['properties'].get('name','')) for _,f in features))
        buildings={f['id']:shape(f['geometry']) for layer,f in features if layer=='buildings'}
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
        self.assertIn('仙林/一食堂', {f['id'] for _,f in features})
        self.assertIn('仙林/建筑/103', {f['id'] for _,f in features})
        self.assertTrue(any('地理与生物信息学院' in f['properties'].get('aliases',[]) for _,f in features if f['id']=='仙林/建筑/103'))

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
            entities=json.loads((build_authored.OUT/'entities'/'space.json').read_text(encoding='utf8'))['items']
            self.assertTrue(any(item.get('aliases')==['图馆','仙林图书馆'] for item in entities))
        finally:
            build_authored.OBS,build_authored.OUT=old_obs,old_out

if __name__=='__main__': unittest.main()
