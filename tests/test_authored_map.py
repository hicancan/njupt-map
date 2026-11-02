import json
import math
import unittest
from pathlib import Path
import mapbox_vector_tile
from pmtiles.reader import MmapSource, Reader
from shapely.geometry import shape
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
                        screen_layers = mapbox_vector_tile.decode(tile, default_options={'y_coord_down': True})
                        for feature in screen_layers.get('buildings', {}).get('features', []):
                            bid = feature.get('properties', {}).get('id')
                            if bid == '仙林/三食堂' and z == 14 and (x, y) == (13604, 6647):
                                cy = shape(feature['geometry']).centroid.y
                                self.assertLess(cy, 512, f'north building must sit near top of tile (got y={cy})')
                            if bid == '仙林/教1' and z == 14 and (x, y) == (13604, 6647):
                                cy = shape(feature['geometry']).centroid.y
                                self.assertGreater(cy, 2000, f'south building must sit in lower half of tile (got y={cy})')

if __name__=='__main__': unittest.main()
