"""Create an instancing-friendly CC0 tree derivative, keeping originals intact."""
import bpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'projects/blender/materials'
SOURCE = ROOT / 'jacaranda_tree' / 'jacaranda_tree_1k.blend'
DEST = Path(__file__).resolve().parents[2] / 'build/blender/jacaranda_campus_lod.blend'
DEST.parent.mkdir(parents=True,exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
with bpy.data.libraries.load(str(SOURCE), link=False) as (src, dst):
    dst.objects = ['jacaranda_tree_LOD1']
obj = dst.objects[0]
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
obj.name = 'Campus_Broadleaf_CC0'
mod = obj.modifiers.new('Campus shared LOD', 'DECIMATE')
mod.ratio = 0.12
mod.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=mod.name)
obj['source'] = 'https://polyhaven.com/a/jacaranda_tree'
obj['license'] = 'CC0-1.0'
obj['campus_species_status'] = 'Generic broadleaf visual surrogate; species is inferred.'
print('FINAL_TREE', len(obj.data.vertices), len(obj.data.polygons), tuple(obj.dimensions), flush=True)
for img in bpy.data.images:
    if img.source == 'FILE' and img.filepath:
        img.filepath = bpy.path.abspath(img.filepath)
bpy.ops.wm.save_as_mainfile(filepath=str(DEST), compress=True)
