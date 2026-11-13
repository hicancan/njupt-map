import json
import unittest
from src.bindings import amap
from src.map import build_authored


class AmapBindingTest(unittest.TestCase):
    """Every place 高德 shows around the campus is answered for by the authored map, and only by ids it really has."""

    def test_every_observation_is_related(self):
        records = amap.relate(amap.observed(), amap.authored())
        left = [r['name'] for r in records if r.get('uncovered')]
        self.assertEqual(left, [], f'{len(left)} 高德 places not on the map')

    def test_written_binding_is_current_and_points_at_authored_ids(self):
        written = json.loads(amap.OUT.read_text(encoding='utf-8'))
        records = sorted(amap.relate(amap.observed(), amap.authored()), key=lambda r: r['poi'])
        self.assertEqual(written, records, 'bindings/amap.json is stale: run python -m src.bindings.amap')
        layers = amap.authored()
        ids = {f['properties']['id'] for fs in layers.values() for f in fs}
        pois = {r['poi'] for r in records}
        for record in written:
            if 'map' in record: self.assertIn(record['map'], ids)
            if 'same_as' in record: self.assertIn(record['same_as'], pois)

    def test_authored_layers_carry_no_provider_fields(self):
        for name in build_authored.LAYER_NAMES:
            text = (build_authored.AUTHOR / f'{name}.geojson').read_text(encoding='utf-8')
            for field in ('poi_id', 'amap', 'typecode', 'gcj'):
                self.assertNotIn(f'"{field}', text, f'{name} carries the provider field {field}')


if __name__ == '__main__': unittest.main()
