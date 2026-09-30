"""Verify semantic source filtering without loading or saving native assets.

blender --background --factory-startup --python-exit-code 1 --python src/blender/checks/validate_exterior_source_filter.py
"""
from pathlib import Path
import sys

import bpy

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src/blender"))
from enrich_exteriors import _existing_objects, _clear_owned


def collection(name, parent):
    item = bpy.data.collections.new(name)
    parent.children.link(item)
    return item


def mesh_object(name, owner):
    data = bpy.data.meshes.new(name)
    data.from_pydata([(0., 0., 0.), (1., 0., 0.), (1., 0., 1.), (0., 0., 1.)], [], [(0, 1, 2, 3)])
    item = bpy.data.objects.new(name, data)
    owner.objects.link(item)
    return item


def main():
    source = collection("Filter check · authored asset", bpy.context.scene.collection)
    envelope = collection("Facade renamed freely", source)
    shell = mesh_object("Native outer shell", envelope)
    # Even a former interior-looking name remains native when no semantic
    # authoring collection owns it. Display names must not decide ownership.
    named_native = mesh_object("INTERIOR::hand-edited exterior window", envelope)
    interior = collection("Rooms renamed freely", source)
    interior["njupt_editable_interiors"] = True
    floor = collection("First level renamed freely", interior)
    room = collection("Deep nested room renamed freely", floor)
    internal_glass = mesh_object("Clear pane with no ownership in its name", room)
    direct_internal = mesh_object("Direct interior object", interior)
    # A second link at the asset root cannot make an interior object an exterior.
    source.objects.link(internal_glass)
    additive = collection("Detail collection renamed freely", source)
    additive["authoring_kind"] = "current editable additive exterior refinement"
    additive['asset_id'] = 'synthetic-common-id'
    detail = mesh_object("Prior gasket renamed freely", additive)
    prefix_collection = collection("EXTERIOR::generated ownership", source)
    prefix_detail = mesh_object("Unnamed old additive detail", prefix_collection)
    prefix_object = mesh_object("EXTERIOR::generated object", source)
    expected = {shell, named_native}
    assert set(_existing_objects(source)) == expected
    assert not ({internal_glass, direct_internal, detail, prefix_detail, prefix_object}
                & set(_existing_objects(source)))
    assert set(_existing_objects(interior)) == set()
    replacement = _clear_owned(source, 'synthetic-common-id')
    assert bpy.data.collections.get('Detail collection renamed freely') is None
    assert replacement in list(source.children)
    assert shell in set(source.all_objects) and internal_glass in set(interior.all_objects)
    print("EXTERIOR_SOURCE_FILTER_OK renamed interior root, nested grandchild, shared link, "
          "renamed additive marker and native envelope verified", flush=True)


if __name__ == "__main__":
    main()
