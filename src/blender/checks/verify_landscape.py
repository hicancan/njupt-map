"""Real-data Blender smoke check including photo-inferred courtyard holes.

Run with Blender --background --factory-startup --python this_file.py.
No scene file is written and no existing scene is loaded.
"""
import bpy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src/blender'))
from campus_landscape import build_landscape

data = json.loads((ROOT / 'build/map/campus.json').read_text(encoding='utf-8'))
collection = bpy.data.collections.new('LandscapeVerification')
bpy.context.scene.collection.children.link(collection)
stats = build_landscape(data, collection)
assert stats['roads'] > 100 and stats['water_bodies'] == 4
assert stats['tree_instances'] > 1000
assert stats['inferred_athletics_tracks'] == 2
assert sum(len(b.get('holes', [])) for b in data['buildings']) >= 5
assert all(Path(bpy.path.abspath(image.filepath)).exists() for image in bpy.data.images
           if image.source == 'FILE' and image.filepath and not image.packed_file)
print('LANDSCAPE_VERIFICATION_OK', json.dumps(stats, ensure_ascii=False))
