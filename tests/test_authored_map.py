import json
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
            self.assertTrue((build_authored.OUT/'network.json').is_file())
            self.assertTrue((build_authored.OUT/'entities'/'space.json').is_file())
        finally:
            build_authored.OBS,build_authored.OUT=old_obs,old_out

if __name__=='__main__': unittest.main()
