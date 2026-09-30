"""Canonical context projection and opt-in native extraction safeguards."""
from __future__ import annotations
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from shapely.geometry import shape, Polygon, LineString
from src.map.store import load_campus, ROOT
from src.runtime.context import context_products, LAYERS
from src.runtime.mesh import MeshWriter
from src.runtime.native import artifact_path, run_bounded, verify_bundle, verify_native_glb, FORMAT
from src.runtime.export import canonical
from src.runtime.native_worker import excluded_interior_objects, validate_output_path
from test_runtime import parse_glb


class ContextContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.campus = load_campus()
        cls.glb, cls.geo, cls.metadata = context_products(cls.campus)

    def test_exact_canonical_feature_geometry_and_no_invented_trees(self):
        features = self.geo['features']
        self.assertEqual(len(features),373)
        self.assertEqual(Counter(f['properties']['context_layer'] for f in features),
            {'boundary':1,'greens':196,'waters':4,'sports':10,'surfaces':5,'roads':154,'context_buildings':3})
        by_id = {f['id']:f for f in features}
        self.assertEqual(len(by_id),373)
        for layer in LAYERS:
            records = [self.campus[layer]] if layer == 'boundary' else self.campus[layer]
            for record in records:
                expected = LineString(record['points']) if layer == 'roads' else Polygon(record['outer'],record.get('holes',[]))
                self.assertTrue(expected.equals_exact(shape(by_id[record['asset_id']]['geometry']),1e-9))
        self.assertFalse(self.metadata['tree_geometry_included'])
        self.assertEqual(self.metadata['measured_tree_count'],0)
        self.assertTrue(all(not f['properties']['measured'] for f in features))

    def test_context_nodes_and_explicit_y_up_surface_normals(self):
        doc,binary = parse_glb(self.glb)
        self.assertEqual(len(doc['nodes']),373)
        self.assertNotIn('textures',doc)
        for node in doc['nodes']:
            self.assertNotIn('asset_id',node['extras']) # Context cannot impersonate pickable registry buildings.
            self.assertIn(node['extras']['context_layer'],LAYERS)
            primitive = doc['meshes'][node['mesh']]['primitives'][0]
            normal = doc['accessors'][primitive['attributes']['NORMAL']]
            view = doc['bufferViews'][normal['bufferView']]
            values = struct.unpack_from('<'+'f'*normal['count']*3,binary,view['byteOffset'])
            for i in range(0,len(values),3):
                self.assertAlmostEqual(sum(v*v for v in values[i:i+3]),1.,places=5)
                if node['extras']['context_layer'] != 'context_buildings':
                    self.assertAlmostEqual(values[i+1],1.,places=5)
        self.assertEqual(self.glb,context_products(self.campus)[0])

    def test_missing_road_width_rejected_instead_of_invented(self):
        campus = copy.deepcopy(self.campus)
        campus['roads'][0].pop('width')
        with self.assertRaisesRegex(ValueError,'source width'):context_products(campus)

    def test_mesh_writer_rejects_incomplete_or_nonfinite_values(self):
        writer=MeshWriter([])
        for value in ([0.,1.],[0.,float('nan'),0.]):
            with self.assertRaises(ValueError):writer.accessor(value)


class FakeObject:
    def __init__(self, **props):self.props=props
    def get(self,key):return self.props.get(key)

class FakeCollection(FakeObject):
    def __init__(self,objects,children=(),**props):
        super().__init__(**props)
        self.all_objects=objects
        self.children_recursive=children


class NativeToolingContracts(unittest.TestCase):
    def test_interior_exclusion_uses_metadata_not_editable_names(self):
        exterior=FakeObject(authoring_role='editable additive exterior detail')
        renamed_interior=FakeObject()
        role_interior=FakeObject(interior_role='walls')
        child=FakeCollection([renamed_interior],njupt_editable_interiors=True)
        root=FakeCollection([exterior,renamed_interior,role_interior],[child])
        self.assertEqual(excluded_interior_objects(root),{renamed_interior,role_interior})

    def test_native_worker_cannot_overwrite_authored_sources(self):
        for output in (ROOT/'projects/blender/test.glb',ROOT/'projects/blender/campus.blend',ROOT/'src/test.glb'):
            with self.assertRaises(ValueError):validate_output_path(output)
        self.assertEqual(validate_output_path(ROOT/'build/test.glb'),ROOT/'build/test.glb')

    def test_native_memory_gate_fails_before_starting_process(self):
        with tempfile.TemporaryDirectory() as tmp, patch('src.runtime.native.available_memory_bytes',return_value=10), patch('src.runtime.native.subprocess.Popen') as popen:
            with self.assertRaisesRegex(RuntimeError,'deferred'):
                run_bounded(['unused'],Path(tmp)/'log',min_available_bytes=100)
            popen.assert_not_called()

    def test_native_subprocess_timeout_and_completion(self):
        with tempfile.TemporaryDirectory() as tmp, patch('src.runtime.native.available_memory_bytes',return_value=10**12):
            result=run_bounded([sys.executable,'-c','print("bounded child")'],Path(tmp)/'log')
            self.assertGreaterEqual(result['duration_s'],0)
            with self.assertRaisesRegex(RuntimeError,'timeout'):
                run_bounded([sys.executable,'-c','import time; time.sleep(30)'],Path(tmp)/'timeout',timeout_s=.05)

    def test_native_glb_root_identity_and_transform_roundtrip(self):
        writer=MeshWriter([{'name':'test-material'}])
        root=writer.add_node({'name':'test-asset','translation':[11,3,-22],
                             'extras':{'asset_id':'test-asset'}})
        writer.add_mesh('authored-mesh',[0,0,0, 2,0,0, 0,0,-4], [0,1,0]*3,
                        [(0,[0,1,2])],{'asset_id':'test-asset'},parent=root)
        item={'asset_id':'test-asset','anchor_local_m':[11,22,3],
              'bounds_local_m':[11,22,3,13,26,3],'triangles':1}
        payload=writer.finish()
        self.assertEqual(verify_native_glb(payload,item)['nodes'][0]['name'],'test-asset')
        item['anchor_local_m'][0]+=11
        with self.assertRaisesRegex(ValueError,'placement'):verify_native_glb(payload,item)
        item['anchor_local_m'][0]-=11;item['bounds_local_m'][0]-=1
        with self.assertRaisesRegex(ValueError,'bounds'):verify_native_glb(payload,item)

    def test_artifact_path_and_content_identity_are_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path in ('../escape','/absolute','..\\escape',''):
                with self.assertRaises(ValueError):artifact_path(root,path)
            manifest={'schema_version':1,'format':FORMAT,'buildings':[],'artifacts':{}}
            manifest['version']=hashlib.sha256(canonical(manifest)).hexdigest()
            (root/'manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(verify_bundle(root),manifest)
            manifest['buildings'].append({'asset_id':'tampered'})
            (root/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'content identity'):verify_bundle(root)

if __name__ == '__main__':unittest.main()
