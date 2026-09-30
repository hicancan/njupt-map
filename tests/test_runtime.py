"""Browser publish invariants: identity, coordinates, source protection and holes."""
from __future__ import annotations
import copy
from collections import Counter
from unittest.mock import patch
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import unittest

from shapely.geometry import Polygon
from shapely.ops import unary_union
from src.map.store import ROOT, SOURCE, load_campus
from src.runtime.export import export_runtime, canonical
from src.runtime.glb import building_mesh, triangles, write_glb
from src.runtime.semantics import audit_regions


def parse_glb(content):
    magic,version,length=struct.unpack_from('<4sII',content)
    if (magic,version,length)!=(b'glTF',2,len(content)):raise ValueError('Invalid GLB header')
    size,kind=struct.unpack_from('<I4s',content,12)
    if kind!=b'JSON':raise ValueError('Missing JSON chunk')
    doc=json.loads(content[20:20+size])
    binary_size,binary_kind=struct.unpack_from('<I4s',content,20+size)
    if binary_kind!=b'BIN\0':raise ValueError('Missing binary chunk')
    binary=content[28+size:]
    if len(binary)!=binary_size:raise ValueError('Wrong binary size')
    return doc,binary


class RuntimeContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='njupt-runtime-test-')
        cls.output=Path(cls.tmp.name)/'runtime'
        cls.before=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        cls.manifest=export_runtime(output=cls.output)
        cls.campus=load_campus()
        cls.by_id={b['asset_id']:b for b in cls.campus['buildings']}

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_export_hashes_identity_and_source_unchanged(self):
        m=self.manifest
        self.assertEqual(m['counts']['buildings'],129)
        self.assertEqual(m['version'],hashlib.sha256(canonical({k:v for k,v in m.items() if k!='version'})).hexdigest())
        self.assertEqual(self.before,hashlib.sha256(SOURCE.read_bytes()).hexdigest())
        self.assertEqual(self.before,m['source']['source_gpkg_sha256'])
        for name,ref in m['artifacts'].items():
            content=(self.output/name).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(),ref['sha256'])
            self.assertEqual(len(content),ref['bytes'])
        self.assertEqual({b['asset_id'] for b in m['buildings']},set(self.by_id))

    def test_deterministic_regeneration_removes_stale_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'runtime'
            a=export_runtime(output=output)
            first={p.relative_to(output).as_posix():p.read_bytes() for p in output.rglob('*') if p.is_file()}
            (output/'stale.txt').write_text('old generated resource')
            b=export_runtime(output=output)
            self.assertEqual(a,b)
            self.assertEqual(first,{p.relative_to(output).as_posix():p.read_bytes() for p in output.rglob('*') if p.is_file()})

    def test_output_cannot_overwrite_authored_source_or_unknown_directory(self):
        for output in [ROOT,ROOT/'projects/runtime',ROOT/'observations/runtime',ROOT/'src/runtime']:
            with self.assertRaises(ValueError):export_runtime(output=output)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'important.txt').write_text('authored')
            with self.assertRaises(ValueError):export_runtime(output=p)
            self.assertEqual((p/'important.txt').read_text(),'authored')

    def test_local_coordinates_match_source_exact_export_precision(self):
        g=json.loads((self.output/'buildings.local.geojson').read_text())
        for feature in g['features']:
            b=self.by_id[feature['id']]
            source=Polygon(b['outer'],b['holes'])
            published=Polygon(feature['geometry']['coordinates'][0],feature['geometry']['coordinates'][1:])
            self.assertLess(source.symmetric_difference(published).area,1e-9)
            self.assertEqual(len(published.interiors),len(source.interiors))
        m=self.manifest['coordinate_frame']
        self.assertEqual(m['source_crs'],'EPSG:32650')
        self.assertEqual(m['gltf_to_local'],'[x,-z,y]')

    def test_glb_every_node_maps_roundtrip_and_bounds(self):
        doc,binary=parse_glb((self.output/'campus-lod1.glb').read_bytes())
        self.assertEqual(len(doc['nodes']),129)
        self.assertEqual({n['name'] for n in doc['nodes']},set(self.by_id))
        descriptors={b['asset_id']:b for b in self.manifest['buildings']}
        for node in doc['nodes']:
            aid=node['extras']['asset_id'];self.assertEqual(aid,node['name'])
            primitive=doc['meshes'][node['mesh']]['primitives'][0]
            positions=doc['accessors'][primitive['attributes']['POSITION']]
            view=doc['bufferViews'][positions['bufferView']]
            floats=struct.unpack_from('<'+'f'*(positions['count']*3),binary,view['byteOffset'])
            tx,ty,tz=node['translation']
            points=[[floats[i]+tx,-(floats[i+2]+tz),floats[i+1]+ty] for i in range(0,len(floats),3)]
            bounds=[min(p[i] for p in points) for i in range(3)]+[max(p[i] for p in points) for i in range(3)]
            for actual,expected in zip(bounds,descriptors[aid]['bounds_local_m']):self.assertAlmostEqual(actual,expected,places=4)
            self.assertEqual(positions['count']%3,0)
            self.assertFalse(node['extras']['measured_height'])
            # Independent per-building lazy-load GLB retains the same node identity.
            single,_=parse_glb((self.output/descriptors[aid]['mesh_url']).read_bytes())
            self.assertEqual([n['name'] for n in single['nodes']],[aid])

    def test_courtyard_roof_preserved_and_all_normals_unit_length(self):
        for b in self.campus['buildings']:
            positions,normals,_=building_mesh(b)
            self.assertEqual(len(positions),len(normals))
            for n in normals:self.assertAlmostEqual(sum(x*x for x in n),1.0,places=6)
            height=b.get('base_z',0)+b['height']
            roof=[Polygon([[p[0],p[1]] for p in t]) for t in triangles(b) if all(p[2]==height for p in t)]
            area=unary_union(roof)
            for hole in b['holes']:self.assertLess(area.intersection(Polygon(hole)).area,0.002)

    def test_each_extruded_volume_is_closed(self):
        for building in self.campus['buildings']:
            for part in [building, *building.get('upper_volumes', [])]:
                edges=Counter()
                for triangle in triangles({**part,'upper_volumes':[]}):
                    for a,b in zip(triangle,triangle[1:]+triangle[:1]):
                        edges[tuple(sorted((tuple(a),tuple(b))))]+=1
                self.assertTrue(edges)
                self.assertTrue(all(count==2 for count in edges.values()),building['asset_id'])

    def test_unsafe_asset_identity_cannot_become_an_output_path(self):
        data=copy.deepcopy(self.campus)
        data['buildings'][0]['asset_id']='../../authored'
        with tempfile.TemporaryDirectory() as tmp:
            with patch('src.runtime.export.map_export',return_value=data):
                with self.assertRaisesRegex(ValueError,'safe artifact identities'):
                    export_runtime(output=Path(tmp)/'runtime')

    def test_region_semantics_retains_multi_regions_and_rejects_duplicate_ids(self):
        p=ROOT/'projects/blender/design/interiors.json'
        report=audit_regions(p)
        self.assertEqual(report['region_count'],564)
        self.assertEqual(report['floorplan_count'],23)
        self.assertEqual(len(report['multi_region_space_keys']),7)
        self.assertEqual(max(len(x['region_ids']) for x in report['multi_region_space_keys']),3)
        design=json.loads(p.read_text())
        design['floorplans'][0]['rooms'].append(copy.deepcopy(design['floorplans'][0]['rooms'][0]))
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'design.json';source.write_text(json.dumps(design))
            with self.assertRaisesRegex(ValueError,'Duplicate source region_id'):audit_regions(source)

    def test_derived_material_manifest_matches_committed_lfs_identity(self):
        if not (ROOT/'.git').exists():self.skipTest('Requires source checkout')
        manifest=json.loads((ROOT/'projects/blender/materials/manifest.json').read_text())
        for asset in manifest['derived_assets']:
            path='projects/blender/materials/'+asset['path']
            pointer=subprocess.run(['git','show','HEAD:'+path],cwd=ROOT,check=True,capture_output=True,text=True).stdout
            match=re.fullmatch(r'version https://git-lfs.github.com/spec/v1\noid sha256:([a-f0-9]{64})\nsize ([0-9]+)\n',pointer)
            self.assertIsNotNone(match,path)
            self.assertEqual(asset['sha256'],match[1])
            self.assertEqual(asset['size'],int(match[2]))

if __name__=='__main__':unittest.main()
