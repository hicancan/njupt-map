"""Add optional, hidden plan photographs from accepted observation registrations.

The observation binding owns the approximate registration. This helper does not
invent another set of image bounds, room geometry, storey heights or north axes.
"""
from pathlib import Path
import hashlib, json, math
import bpy

ROOT=Path(__file__).resolve().parents[2]


def build_floorplan_references(building, collection):
    bindings=json.loads((ROOT/'observations/bindings/assets.json').read_text(encoding='utf-8'))['bindings']
    binding=next((item for item in bindings if item['asset_id']==building['id']), {})
    plans=binding.get('floorplans', [])
    if not plans:
        return {'reference_images':0, 'building_id':building['id']}
    sources=json.loads((ROOT/'observations/catalog.json').read_text(encoding='utf-8'))['sources']
    root=bpy.data.collections.new(building['name']+' · 楼层原图参考 / 默认隐藏 · 非实测')
    collection.children.link(root)
    root.hide_viewport=True
    root.hide_render=True
    root['binding_source']='observations/bindings/assets.json'
    root['purpose']='Optional registered research photographs; not measured interior geometry.'
    count=0
    unavailable=[]
    for plan in plans:
        source=sources[plan['source_id']]
        path=(ROOT/source['local_path']).resolve()
        if not path.is_file():
            unavailable.append(plan['source_id'])
            continue
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=source['sha256']:
            raise ValueError('Observation checksum changed: '+plan['source_id'])
        registration=plan['registration']
        if registration.get('coordinate_frame')!='asset_local_m':
            raise ValueError('Floorplan registration requires an explicit asset-local coordinate frame')
        image=bpy.data.images.load(str(path), check_existing=True)
        image['observation_id']=plan['source_id']
        image['source_project_path']=path.relative_to(ROOT).as_posix()
        image['source_sha256']=digest
        image['publication']='Optional local research reference; never pack into public artifacts.'
        floor=plan['floor']
        layer=bpy.data.collections.new(f'{floor:02}F · 原始疏散图 · 近似配准')
        root.children.link(layer)
        layer.hide_viewport=floor!=1
        layer.hide_render=True
        obj=bpy.data.objects.new(f'{building["name"]}_{floor:02}F_REFERENCE_APPROXIMATE',None)
        layer.objects.link(obj)
        obj.data=image
        obj.empty_display_type='IMAGE'
        obj.empty_display_size=registration['image_full_width_m']
        obj.empty_image_offset=(-.5,-.5)
        obj.empty_image_depth='FRONT'
        obj.empty_image_side='FRONT'
        obj.show_empty_image_orthographic=True
        obj.show_empty_image_perspective=True
        obj.color=(1,1,1,.60)
        obj.hide_render=True
        obj.location=registration['local_location']
        obj.rotation_euler=(0,0,math.radians(registration['rotation_z_degrees']))
        obj.scale=(*registration['local_xy_scale'],1)
        obj['floor']=floor
        obj['observation_id']=plan['source_id']
        obj['registration_status']='approximate_not_surveyed'
        obj['source_sha256']=digest
        obj['accuracy_warning']='Approximate photo registration; not surveyed room geometry.'
        count+=1
    return {'reference_images':count, 'building_id':building['id'], 'default_hidden':True,
            'registration_source':'observations/bindings/assets.json', 'unavailable_sources':unavailable}
