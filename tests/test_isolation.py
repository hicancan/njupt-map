import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ('entities.json', 'network.json', 'indoor.json', 'basemap.geojson')


class IsolationTest(unittest.TestCase):
    """map/layers alone builds the map: without observations/ and bindings/ the derived files are the same bytes."""

    def test_build_needs_only_the_authored_layers(self):
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / 'map'
            for part in ('src', 'map'): shutil.copytree(ROOT / part, copy / part, ignore=shutil.ignore_patterns('__pycache__'))
            self.assertFalse((copy / 'observations').exists() or (copy / 'bindings').exists())
            subprocess.run([sys.executable, '-m', 'src.map.build_authored'], cwd=copy, check=True, capture_output=True)
            for name in DERIVED:
                self.assertEqual((copy / 'build/space/仙林' / name).read_bytes(), (ROOT / 'build/space/仙林' / name).read_bytes(), f'{name} depends on more than map/layers')


if __name__ == '__main__': unittest.main()
