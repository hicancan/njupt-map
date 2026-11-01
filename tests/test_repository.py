"""Cross-engine contracts, independent of Blender and optional local originals."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import unittest

from src.map.authored import ROOT, load_authored


class RepositoryContracts(unittest.TestCase):
    def test_common_building_identity(self):
        map_ids = {item['id'] for item in load_authored()['buildings']}
        assets = json.loads((ROOT / 'projects/blender/buildings/catalog.json').read_text(encoding='utf-8'))
        observations = json.loads((ROOT / 'bindings/assets.json').read_text(encoding='utf-8'))
        binding_ids = [item['asset_id'] for item in observations['bindings']]
        self.assertEqual(len(binding_ids), len(set(binding_ids)))
        self.assertTrue(map_ids)
        self.assertTrue(assets)
        self.assertTrue(binding_ids)

    def test_current_source_has_no_parallel_spatial_store(self):
        for retired in ('assets', 'data', 'evidence', 'exports', 'renders', 'reports', 'scenes', 'scripts', 'specs', 'versions'):
            self.assertFalse((ROOT / retired).exists(), f'Retired root still exists: {retired}')
        for source in (ROOT / 'src').rglob('*.py'):
            body = source.read_text(encoding='utf-8')
            self.assertNotIn('data/canonical/', body, source)
            self.assertNotIn('specs/refinement_overrides', body, source)

    def test_document_links_resolve(self):
        documents = [ROOT / 'README.md', ROOT / 'LICENSES.md', *(ROOT / 'docs').glob('*.md')]
        for document in documents:
            for target in re.findall(r'\]\(([^\s)]+)\)', document.read_text(encoding='utf-8')):
                if '://' in target or target.startswith('#'):
                    continue
                target = target.split('#', 1)[0]
                self.assertTrue((document.parent / target).exists(), f'{document.name}: {target}')

    def test_native_binaries_use_lfs(self):
        if not (ROOT / '.git').exists():
            self.skipTest('Git attributes are checked in a repository checkout')
        files = ['projects/blender/campus.blend', 'README.assets/film.gif']
        result = subprocess.run(['git', 'check-attr', 'filter', '--', *files], cwd=ROOT,
                                check=True, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(len(result.stdout.splitlines()), len(files))
        self.assertTrue(all(line.endswith(': lfs') for line in result.stdout.splitlines()))


if __name__ == '__main__':
    unittest.main()
