# Browser runtime publishing

The GeoPackage remains the only editable spatial source. `src.runtime` creates disposable browser products under `build/runtime/`; it never opens or overwrites authored Blender assets.

## Run

Use the existing locked project environment (PowerShell 7 on Windows):

```powershell
uv sync --locked
uv run python -m src.runtime.export
uv run python -m unittest discover -s tests -p 'test_*.py' -v
```

Only `projects/map/campus.gpkg` must be hydrated from LFS for geometry export. The pipeline also reads the existing textual `projects/blender/design/interiors.json` to audit region identity. It does not need the 621 MB authoring collection. An unwritable default uv cache can be redirected with `UV_CACHE_DIR` to an allowed cache directory.

## Published contract, version 1

- `manifest.json`: content-addressed version, all artifact SHA-256/byte lengths, source GPKG and semantic hashes, producer source digest, source commit, explicit coordinate transform, per-building bounds/provenance and lazy-loading paths
- `campus-lod1.glb`: all 129 source building footprints extruded into lightweight shells; one node per unchanged `asset_id`
- `buildings/<asset_id>.glb`: the same node for per-building lazy loading
- `buildings.local.geojson`: source footprints, holes, IDs and dimensions in campus-local east/north metres
- `buildings.geojson`: WGS84 longitude/latitude, suitable for GIS clients
- `layers/*.geojson`: source boundary, roads, landscape and context in WGS84
- `source-regions.json`: all 564 authored source region identities and seven multi-region label groups; no merging or deletion based on a duplicate label
- `ATTRIBUTION.json`: material-specific provenance, exclusions and license notices

The version is SHA-256 of canonical UTF-8 JSON (`sort_keys`, no ASCII escaping, compact separators) of the manifest with `version` omitted. Every file listed in `artifacts` is verified before platform import. Regeneration stages a fresh package and replaces only a recognized generated output directory, preventing stale files from becoming current resources. It performs no network publication.

## Coordinates and precision

Source CRS is EPSG:32650. Origin is `[681614.1962973196, 3554804.986814983]` metres, corresponding to `[118.925, 32.115]` longitude/latitude. Local `[E,N,Z]` uses grid east, grid north and up; ground `Z=0` is local and not a surveyed elevation.

- Projected: `[E+originE, N+originN, Z]`
- glTF: `[E,Z,-N]`, using glTF's Y-up convention
- glTF inverse: `[x,-z,y]`

Local JSON preserves the existing exporter’s six-decimal metre precision. GLB positions are float32 relative to each building anchor, with the node translation restoring campus coordinates. The axis change is a proper rotation. Tests invert every node transform and compare bounds within 0.0001 m. This numerical tolerance is not a real-world accuracy claim.

Exterior rings, courtyard holes, minimum heights and upper volumes are preserved. Constrained triangulation is inherited from the current map reader. Normals are flat-shaded and verified to be unit length. No polygon simplification changes the footprint. `LOD1` denotes a simple footprint extrusion, not a decimated copy of an authored facade mesh.

## Truth and identity

Geometry roles distinguish mapped outlines, roof proxies and plan-corrected footprints. `height_source` and `levels_source` are retained; dimensions are not promoted to site measurements. Only four buildings currently have explicit external `space_id` links. Other names, including repeated names, are never used to invent a match.

Source `region_id` is unique. A `space_key` can have multiple valid regions. `source-regions.json` reports this many-to-one relationship rather than declaring a physical room primary key. The downstream platform owns its registry, source reconciliation and device bindings. Source floorplan coordinates remain schematic, independently normalized frames without a metric campus transform. No room occupancy, hardware installation or safe switching state is published by this pipeline.

## Native assets and optimization boundary

The authored files require Blender 5.2; the available 4.3.2 reader could not open the audited samples. They are preserved byte-for-byte, not silently converted. This runtime release optimizes the initial browser payload through a lightweight derived shell and per-building loading. It makes no claim that high-detail native meshes, textures or furniture have been exported or benchmarked.

The derived tree material manifest was reconciled to the same committed LFS object identity (`b0faefa374a7a14527b9179995480370dfc3126130eade1dc873229673765083`, 16,915,445 bytes). That verifies pointer/manifest consistency; it does not claim a fresh mesh-statistics measurement.

## Attribution

See [LICENSES.md](../LICENSES.md). OSM-derived spatial products retain ODbL obligations and © OpenStreetMap contributors attribution. Original work is attributed to `hicancan / njupt-map` under CC BY 4.0; exporter code is AGPL-3.0-or-later. Native files, restricted photographs, plan originals, school marks, textures and Poly Haven assets are not embedded in this runtime package. Distribution rights for a derived database and a produced visual work are not interchangeable.
