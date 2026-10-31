import json
import re
import sys
import unittest
from pathlib import Path

from src.map import build_authored

class AuthoredMapTest(unittest.TestCase):
    def test_layer_contract(self):
        layers=sorted(Path('map/layers').glob('*.geojson')); self.assertTrue(layers)
        ids=[]
        for path in layers:
            data=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(data['type'],'FeatureCollection')
            self.assertEqual(data['features'],sorted(data['features'],key=lambda f:f['id']))
            ids.extend(f['id'] for f in data['features'])
        self.assertEqual(len(ids),len(set(ids)))
        rooms=json.loads(Path('map/layers/rooms.geojson').read_text(encoding='utf-8'))['features']
        self.assertEqual(len(rooms),642)
        self.assertTrue(all(f['id'].startswith('仙林/') for f in rooms))
        buildings=json.loads(Path('map/layers/buildings.geojson').read_text(encoding='utf-8'))['features']
        self.assertTrue(all(not re.fullmatch(r'\d+', f['properties'].get('name','')) for f in buildings))
        self.assertTrue(all(not re.search(r'模型|未命名|组团', f['id']+' '+str(f['properties'].get('name'))) for f in buildings))
        self.assertTrue(all('geometry_role' not in f['properties'] for path in layers for f in json.loads(path.read_text(encoding='utf-8'))['features']))
        dorms=[f for f in buildings if f['properties'].get('style_hint')=='dormitory' and re.search(r'苑\d+栋',f['properties'].get('name',''))]
        self.assertTrue(dorms)
        self.assertTrue(all(f['properties'].get('group') for f in dorms))
        allowed={'食堂','图书馆','教学楼','超市','快递','打印','体育','校医院','公交站','宿舍','学院','停车场','道路','校园服务'}
        places=json.loads(Path('map/layers/places.geojson').read_text(encoding='utf-8'))['features']
        self.assertTrue(all(f['properties']['category'] in allowed for f in places))
        self.assertTrue(all('/place/' not in f['id'] for f in places))
        ways=json.loads(Path('map/layers/ways.geojson').read_text(encoding='utf-8'))['features']
        self.assertEqual(sum(bool(f['properties'].get('render') is False) for f in ways), 5)
        provenance=json.loads(Path('bindings/provenance.json').read_text(encoding='utf-8'))['features']
        self.assertTrue(any('provider_name' in row and 'provider_category' in row for row in provenance))

    def test_build_without_references_or_bindings(self):
        old_obs,old_out=build_authored.OBS,build_authored.OUT
        try:
            build_authored.OBS=Path(self.id()).parent/'no-observations.jsonl'
            build_authored.OUT=Path('build')/'test-authored-pure'
            sys.argv=['build_authored']
            build_authored.main()
            checks=json.loads((build_authored.OUT/'checks.json').read_text(encoding='utf-8'))
            self.assertTrue(checks['passed'])
            self.assertEqual(checks['route_gate']['status'],'skipped')
            self.assertTrue((build_authored.OUT/'basemap.geojson').is_file())
            self.assertTrue((build_authored.OUT/'basemap.pmtiles').is_file())
            self.assertTrue((build_authored.OUT/'basemap-preview.png').is_file())
            self.assertEqual((build_authored.OUT/'basemap.pmtiles').read_bytes()[:7], b'PMTiles')
            self.assertEqual(json.loads((build_authored.OUT/'checks.json').read_text(encoding='utf-8'))['basemap_context']['rendered_crossings'], 0)
            self.assertTrue((build_authored.OUT/'network.json').is_file())
            self.assertTrue((build_authored.OUT/'entities'/'space.json').is_file())
        finally:
            build_authored.OBS,build_authored.OUT=old_obs,old_out

if __name__=='__main__': unittest.main()
