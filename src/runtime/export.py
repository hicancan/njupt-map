"""Publish deterministic versioned lightweight campus artifacts from the GPKG.

This publishes files only under the requested local output directory. It does
not upload, deploy, modify native Blender, or infer new physical rooms/devices.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import shutil
import re

from shapely.geometry import Polygon,mapping
from pyproj import Transformer
from .glb import write_glb, triangles
from .semantics import audit_regions
from ..map.export import export as map_export
from ..map.store import ROOT,SOURCE


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(canonical(value)+b'\n')

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def source_revision():
    result=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True)
    return result.stdout.strip() if result.returncode==0 else None

def bounds(building):
    vertices=[p for t in triangles(building) for p in t]
    return [round(min(p[i] for p in vertices),6) for i in range(3)]+[round(max(p[i] for p in vertices),6) for i in range(3)]

def _export_runtime(source, output):
    output=Path(output).resolve()
    # Never generate inside native source directories, even through symlinks.
    for protected in (ROOT/'projects', ROOT/'observations', ROOT/'src', ROOT/'tests'):
        if output==protected.resolve() or protected.resolve() in output.parents:
            raise ValueError(f'Refusing runtime output inside authored source: {protected.name}')
    source=Path(source)
    before=sha(source)
    output.mkdir(parents=True,exist_ok=True)
    # Reuse the existing GIS exporter without bundling its Blender-oriented JSON.
    with tempfile.TemporaryDirectory(prefix='njupt-gis-export-') as tmp:
        exported=Path(tmp)
        data=map_export(source,exported)
        for geo in sorted(exported.glob('*.geojson')):
            target=output/geo.name if geo.name=='buildings.geojson' else output/'layers'/geo.name
            write_json(target,json.loads(geo.read_text(encoding='utf8')))
    buildings=sorted(data['buildings'],key=lambda b:b['asset_id'])
    ids=[b['asset_id'] for b in buildings]
    if len(set(ids))!=len(ids) or any(not re.fullmatch(r'[A-Za-z0-9_-]+',aid) for aid in ids):
        raise ValueError('Building IDs must be unique safe artifact identities')
    write_json(output/'buildings.local.geojson',{'type':'FeatureCollection','name':'buildings',
       'coordinate_frame':'campus_local_east_north_m','source_crs':data['metadata']['crs'],
       'origin_easting_northing':data['metadata']['origin_easting_northing'],
       'features':[{'type':'Feature','id':b['asset_id'],
                    'geometry':mapping(Polygon(b['outer'],b['holes'])),
                    'properties':{'asset_id':b['asset_id'],'name':b['name'],
                        'search_building_id':b.get('space_id'),'height_m':b['height'],
                        'base_z_m':b.get('base_z',0),'min_height_m':b.get('min_height',0),
                        'height_source':b.get('height_source'),'levels':b.get('levels'),
                        'geometry_role':b['geometry_role'],'source_url':b.get('source_url'),
                        'geometry_status':'derived_footprint','measured_height':False}}
                   for b in buildings]})
    (output/'campus-lod1.glb').write_bytes(write_glb(buildings))
    descriptors=[]
    inverse=Transformer.from_crs(data['metadata']['crs'],'EPSG:4326',always_xy=True)
    ox,oy=data['metadata']['origin_easting_northing']
    for b in buildings:
        relative=f"buildings/{b['asset_id']}.glb"
        path=output/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(write_glb([b]))
        descriptors.append({'asset_id':b['asset_id'],'name':b['name'],'search_building_id':b.get('space_id'),
           'map_feature_id':b.get('map_feature_id'),'center_local_m':[*b['center'],b.get('base_z',0)],
           'anchor_wgs84':list(inverse.transform(b['center'][0]+ox,b['center'][1]+oy)),
           'centroid_wgs84':list(inverse.transform(Polygon(b['outer'],b['holes']).centroid.x+ox,Polygon(b['outer'],b['holes']).centroid.y+oy)),
           'bounds_local_m':bounds(b),'base_z_m':b.get('base_z',0),'min_height_m':b.get('min_height',0),'height_m':b['height'],'height_source':b.get('height_source'),
           'levels':b.get('levels'),'levels_source':b.get('levels_source'),
           'geometry_role':b['geometry_role'],'geometry_status':'derived_footprint_extrusion',
           'confidence':'source_community_mapping_not_surveyed','measured_height':False,
           'source_url':b.get('source_url'),'spatial_signature':b['spatial_signature'],
           'node_name':b['asset_id'],'mesh_url':relative,'mesh_sha256':sha(path)})
    design=ROOT/'projects/blender/design/interiors.json'
    design_before=sha(design)
    region_audit=audit_regions(design)
    if sha(design)!=design_before:raise RuntimeError('Interior source changed during runtime export')
    write_json(output/'source-regions.json',region_audit)
    provenance={'source_namespace':'njupt-map','source_git_commit':source_revision(),
       'source_gpkg_sha256':before,'dataset_sha256':data['metadata']['dataset_sha256'],
       'source_interiors_sha256':design_before,
       'source_url':'https://github.com/hicancan/njupt-map',
       'toolchain':{'pipeline':'njupt-map-runtime-v1','python':'3.12','dependencies':'uv.lock',
                    'pipeline_sources_sha256':hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT/'src/runtime').glob('*.py')))).hexdigest()},
       'native_blender':'Preserved, not opened or re-exported; Blender 5.2 source is not supported by installed 4.3.2',
       'accuracy_note':data['metadata']['evidence_note'],
       'source_geometry_snapshot':data['metadata']['source_geometry_snapshot']}
    write_json(output/'ATTRIBUTION.json',{'materials':[
       {'scope':'map spatial database and footprint-derived GLB','license':'ODbL-1.0','attribution':'© OpenStreetMap contributors','url':'https://www.openstreetmap.org/copyright'},
       {'scope':'original authored source and region metadata','license':'CC-BY-4.0','attribution':'hicancan / njupt-map','url':'https://github.com/hicancan/njupt-map'},
       {'scope':'exporter source code','license':'AGPL-3.0-or-later','url':'https://github.com/hicancan/njupt-map'}],
       'excluded':'No native .blend, school marks, photographs, restricted floorplan originals, textures or Poly Haven assets are embedded.',
       'notice':'Preserve database obligations and attribution when distributing derivatives. Institutional endorsement and survey/BIM accuracy are not claimed.'})
    files={p.relative_to(output).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size}
           for p in sorted(output.rglob('*')) if p.is_file() and p.name!='manifest.json'}
    manifest={'schema_version':1,'format':'njupt-map-runtime','source':provenance,
       'coordinate_frame':{'source_crs':data['metadata']['crs'],'units':'m',
           'origin_easting_northing':data['metadata']['origin_easting_northing'],
           'origin_lonlat':data['metadata']['origin_lonlat'],'local_axes':['east','north','up'],
           'ground_elevation':data['metadata']['ground_elevation'],
           'local_to_projected':'[E+originE,N+originN,Z]',
           'local_to_gltf_matrix_column_major':[1,0,0,0,0,0,-1,0,0,1,0,0,0,0,0,1],
           'gltf_to_local':'[x,-z,y]'},
       'counts':{'buildings':len(buildings),'source_floorplans':region_audit['floorplan_count'],'observed_occupancy':0},
       'buildings':descriptors,'artifacts':files,
       'campus_mesh_url':'campus-lod1.glb','local_geojson_url':'buildings.local.geojson',
       'wgs84_geojson_url':'buildings.geojson',
       'limitations':['Footprints are source-derived, not survey measurements',
          'Height and storey count inherit source inference; no measured heights are asserted',
          'LOD1 is a lightweight extrusion, not a high-detail export of authored Blender',
          'No registered indoor metric coordinates, equipment installation or occupancy']}
    manifest['version']=hashlib.sha256(canonical(manifest)).hexdigest()
    if sha(source)!=before or sha(design)!=design_before: raise RuntimeError('Source changed during runtime export')
    write_json(output/'manifest.json',manifest)
    return manifest


def export_runtime(source=SOURCE, output=ROOT/'build/runtime'):
    """Build in staging; replace only a recognized generated output package."""
    output=Path(output).resolve()
    source=Path(source).resolve()
    if (ROOT in output.parents or output==ROOT) and not (ROOT/'build').resolve() in output.parents:
        raise ValueError('Runtime output inside the repository must be under build/')
    if output==source or output in source.parents:
        raise ValueError('Runtime output cannot contain the source file')
    if output.exists() and any(output.iterdir()):
        manifest=output/'manifest.json'
        if not manifest.exists() or json.loads(manifest.read_text()).get('format')!='njupt-map-runtime':
            raise ValueError('Refusing to replace an unrecognized output directory')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.runtime-build-',dir=output.parent) as tmp:
        stage=Path(tmp)/'runtime'
        manifest=_export_runtime(source,stage)
        if output.exists():shutil.rmtree(output)
        shutil.move(str(stage),str(output))
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=SOURCE)
    p.add_argument('--output',type=Path,default=ROOT/'build/runtime')
    a=p.parse_args()
    m=export_runtime(a.source,a.output)
    print(json.dumps({'version':m['version'],'buildings':len(m['buildings']),'output':str(a.output)}))
