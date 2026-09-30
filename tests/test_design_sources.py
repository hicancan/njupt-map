"""Check durable interior linework identity and observation provenance."""
from pathlib import Path
import json
import math
import unittest

from src.map.store import load_campus

ROOT = Path(__file__).resolve().parents[1]


class DesignSourceTests(unittest.TestCase):
    def test_registered_rooms_keep_their_source_and_identity(self):
        design = json.loads((ROOT/'projects/blender/design/interiors.json').read_text(encoding='utf8'))
        sources = json.loads((ROOT/'observations/catalog.json').read_text(encoding='utf8'))['sources']
        bindings = {b['asset_id']: b for b in json.loads((ROOT/'observations/bindings/assets.json').read_text(encoding='utf8'))['bindings']}
        map_ids = {b['id'] for b in load_campus()['buildings']}
        room_ids = set()
        floors = set()
        for plan in design['floorplans']:
            aid, sid = plan['asset_id'], plan['source_id']
            self.assertIn(aid, map_ids)
            self.assertIn(sid, sources)
            self.assertEqual(plan['source_sha256'], sources[sid]['sha256'])
            self.assertIn(sid, {p['source_id'] for p in bindings[aid]['floorplans']})
            key = (aid, plan['floor'])
            self.assertNotIn(key, floors)
            floors.add(key)
            self.assertEqual(plan['coordinate_frame'], 'source_image_normalized_xy_down')
            for room in plan['rooms']:
                self.assertNotIn(room['region_id'], room_ids)
                room_ids.add(room['region_id'])
                self.assertGreaterEqual(len(room['polygon']), 3)
                self.assertTrue(all(len(p)==2 and all(math.isfinite(x) for x in p) for p in room['polygon']))
                self.assertTrue(room['geometry_status'])
        self.assertGreater(len(room_ids), 0)

    def test_site_component_references_are_current_sources(self):
        design = json.loads((ROOT/'projects/blender/design/campus.json').read_text(encoding='utf8'))
        sources = json.loads((ROOT/'observations/catalog.json').read_text(encoding='utf8'))['sources']
        map_ids = {b['id'] for b in load_campus()['buildings']}
        for key in ('south_namewall', 'k_roof_connection'):
            spec = design[key]
            self.assertTrue(spec['component_id'])
            self.assertLessEqual(set(spec['anchor_ids']), map_ids)
            self.assertLessEqual(set(spec['sources']), set(sources))


if __name__ == '__main__':
    unittest.main()
