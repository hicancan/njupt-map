"""Bounded serialization stability without concealing source/geometry changes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from shapely import constrained_delaunay_triangles
from shapely.geometry import GeometryCollection, LineString, Polygon
from shapely.ops import unary_union

from src.map.precision import WGS84_DECIMAL_PLACES, wgs84_coordinates
from src.map.store import ROOT, load_campus
from src.runtime.context import surface_triangles
from src.runtime.mesh import MeshWriter
from src.runtime.provenance import canonical_json_sha256, pipeline_source_hashes, toolchain
from test_runtime import parse_glb


class ReproducibilityContracts(unittest.TestCase):
    def test_projection_rounding_absorbs_observed_tails_but_preserves_real_changes(self):
        for a, b in ((32.110643119196666, 32.11064311919666),
                     (118.92540580113469, 118.9254058011347),
                     (118.92298719893648, 118.92298719893651)):
            self.assertEqual(wgs84_coordinates(a), wgs84_coordinates(b))
            self.assertLessEqual(abs(wgs84_coordinates(a)-a), .5*10**-WGS84_DECIMAL_PLACES)
            self.assertNotEqual(wgs84_coordinates(a), wgs84_coordinates(a+1e-7))
        self.assertEqual(wgs84_coordinates(((32.110643119196666,), (118.92540580113469,))),
                         [[32.110643119], [118.925405801]])
        self.assertEqual(struct.pack('<d', wgs84_coordinates(-0.0)), struct.pack('<d', 0.0))
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaises(ValueError): wgs84_coordinates(value)

    def test_convex_quad_diagonal_is_independent_of_start_winding_and_geos_ties(self):
        ring = [(0., 0.), (6., 0.), (6., 2.), (0., 2.)]
        expected = surface_triangles(Polygon(ring))
        with patch('src.runtime.context.constrained_delaunay_triangles', side_effect=AssertionError('unnecessary GEOS tie')):
            for index in range(4):
                shifted = ring[index:] + ring[:index]
                self.assertEqual(surface_triangles(Polygon(shifted)), expected)
                self.assertEqual(surface_triangles(Polygon(list(reversed(shifted)))), expected)
        self.assertEqual(unary_union([Polygon(t) for t in expected]).symmetric_difference(Polygon(ring)).area, 0)

    def test_concavities_and_holes_are_not_replaced_by_convex_fans(self):
        shapes = [Polygon([(0, 0), (4, 0), (1, 1), (0, 4)]),
                  Polygon([(0, 0), (6, 0), (6, 6), (0, 6)],
                          [[(1, 1), (1, 3), (3, 3), (3, 1)]])]
        for shape in shapes:
            result = unary_union([Polygon(t) for t in surface_triangles(shape)])
            self.assertEqual(result.symmetric_difference(shape).area, 0)

    def test_geos_face_order_vertex_rotation_and_winding_do_not_change_output(self):
        shape = Polygon([(0, 0), (6, 0), (6, 6), (0, 6)],
                        [[(1, 1), (1, 3), (3, 3), (3, 1)]])
        expected = surface_triangles(shape)
        perturbed = []
        for triangle in reversed(constrained_delaunay_triangles(shape).geoms):
            points = list(triangle.exterior.coords)[:3]
            points = list(reversed(points[1:]+points[:1]))
            perturbed.append(Polygon(points))
        with patch('src.runtime.context.constrained_delaunay_triangles', return_value=GeometryCollection(perturbed)):
            self.assertEqual(surface_triangles(shape), expected)

    def test_every_road_surface_preserves_buffer_footprint_and_vertices(self):
        for road in load_campus()['roads']:
            geometry = LineString(road['points']).buffer(road['width']/2, cap_style='flat', join_style='mitre')
            triangles = surface_triangles(geometry)
            rebuilt = unary_union([Polygon(t) for t in triangles])
            self.assertLess(geometry.symmetric_difference(rebuilt).area, 1e-8, road['asset_id'])
            polygons = [geometry] if isinstance(geometry, Polygon) else list(geometry.geoms)
            vertices = {tuple(point) for p in polygons for ring in [p.exterior, *p.interiors] for point in ring.coords}
            self.assertTrue(all(point in vertices for triangle in triangles for point in triangle), road['asset_id'])

    def test_mesh_bounds_are_emitted_float32_and_negative_zero_is_canonical(self):
        def build(values):
            writer = MeshWriter([{'name': 'test'}])
            writer.add_mesh('sample', values, [0, 0, 1]*3, [(0, [0, 1, 2])], {})
            return writer.finish()
        a = [-0., -1e-100, 0., 1.100000000000001, 0., 0., 0., 1., 0.]
        b = [0., 0., -0., 1.1, 0., -0., -0., 1., -0.]
        self.assertEqual(build(a), build(b))
        self.assertEqual(build(np.asarray(a)), build(b))
        doc, binary = parse_glb(build(a))
        accessor = doc['accessors'][0]
        values = struct.unpack_from('<9f', binary, doc['bufferViews'][accessor['bufferView']]['byteOffset'])
        self.assertEqual(accessor['min'], [min(values[i::3]) for i in range(3)])
        self.assertEqual(accessor['max'], [max(values[i::3]) for i in range(3)])
        for value in values:
            if value == 0: self.assertEqual(struct.pack('<f', value), b'\0'*4)

    def test_mesh_normalization_does_not_mutate_input_or_accept_nonfinite_numpy(self):
        source = np.array([-0., 1., 2.], dtype=np.float32)
        before = source.tobytes()
        MeshWriter([]).accessor(source)
        self.assertEqual(source.tobytes(), before)
        for value in (np.array([0., np.nan, 0.]), np.array([0., np.inf, 0.])):
            with self.assertRaises(ValueError): MeshWriter([]).accessor(value)

    def test_text_canonical_identity_is_additional_to_exact_raw_identity(self):
        source = (ROOT/'projects/blender/design/interiors.json').read_bytes()
        lf = source.replace(b'\r\n', b'\n')
        crlf = lf.replace(b'\n', b'\r\n')
        self.assertNotEqual(hashlib.sha256(lf).hexdigest(), hashlib.sha256(crlf).hexdigest())
        for variant in (lf, crlf):
            self.assertEqual(canonical_json_sha256(source), canonical_json_sha256(variant))
        changed = json.loads(source)
        changed['floorplans'][0]['rooms'][0]['raw_label'] = 'genuine source edit'
        self.assertNotEqual(canonical_json_sha256(source), canonical_json_sha256(json.dumps(changed)))

    def test_pipeline_digest_covers_map_sources_and_keeps_raw_lf_hashes_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for directory in ('map', 'runtime'): (root/'src'/directory).mkdir(parents=True)
            path = root/'src/map/export.py'
            path.write_bytes(b'first\nsecond\n')
            a = pipeline_source_hashes(root)
            path.write_bytes(b'first\r\nsecond\r\n')
            b = pipeline_source_hashes(root)
            self.assertNotEqual(a['pipeline_sources_sha256'], b['pipeline_sources_sha256'])
            self.assertEqual(a['pipeline_sources_lf_sha256'], b['pipeline_sources_lf_sha256'])
            path.write_bytes(b'genuine code edit\n')
            c = pipeline_source_hashes(root)
            self.assertNotEqual(a['pipeline_sources_lf_sha256'], c['pipeline_sources_lf_sha256'])
            self.assertEqual(a['pipeline_sources'], ['src/map/export.py'])

    def test_toolchain_records_actual_libraries_and_lock_identity(self):
        import platform
        import pyproj
        import shapely
        info = toolchain(ROOT)
        self.assertEqual(info['python'], platform.python_version())
        self.assertEqual(info['geos'], shapely.geos_version_string)
        self.assertEqual(info['proj'], pyproj.proj_version_str)
        self.assertEqual(info['uv_lock_sha256'], hashlib.sha256((ROOT/'uv.lock').read_bytes()).hexdigest())
        self.assertIn('src/map/precision.py', info['pipeline_sources'])
        self.assertIn('src/runtime/provenance.py', info['pipeline_sources'])


if __name__ == '__main__': unittest.main()
