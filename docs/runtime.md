# Browser runtime publishing

The GeoPackage remains the only editable spatial source. `src.runtime` creates disposable browser products under `build/runtime/`; its default GIS export never opens or overwrites authored Blender assets. An optional isolated native extractor reads one asset at a time without saving it.

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
- `campus-context.glb`: 373 canonical context features in seven material groups; 688,880 bytes for this source
- `context.local.geojson`: exact source-local context polygons and road centerlines, with `context_layer` provenance
- Optional `detail/buildings/<asset_id>.glb` and `.json`: authored exterior mesh plus an object/material/omission report, only after an explicit native extraction
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

## Campus context

`context_mesh_url` and `context_local_geojson_url` are manifest-relative resources. The seven source layers are boundary (1), roads (154), greens (196), waters (4), sports (10), surfaces (5), and context buildings (3). The GeoJSON retains exact canonical local geometry. Road GLB surfaces buffer the source centerlines with their declared widths; this does not turn them into surveyed road edges. Small, declared display-height offsets prevent z-fighting and do not represent terrain elevation. Display colors are neither textures nor measured vegetation types. No invented tree point or tree mesh is published; the source currently contains zero tree records.

Context nodes expose `extras.source_asset_id` and `extras.context_layer`, deliberately distinct from selectable registry-building `extras.asset_id`. Both 2D and 3D clients must use the same explicit east/north transform. The context resource is independent of the unchanged 475,324-byte all-building LOD1.

## Native assets and optimization boundary

The authored files require Blender 5.2. The optional pipeline uses an existing official Blender 5.2 `bpy` interpreter in an isolated subprocess. Do not install Blender into the locked GIS environment or use an older reader to rewrite native assets.

```powershell
uv run python -m src.runtime.native --bpy-python /path/to/bpy52/python --output build/native-exteriors --asset-id osm_way_223859810
uv run python -m src.runtime.export --native-detail build/native-exteriors --output build/runtime-detail-stage
```

Omit `--asset-id` to extract all canonical assets. Extraction is serial. Defaults require at least 3,500 MiB host `MemAvailable`, stop a process exceeding 1,500 MiB RSS, and impose a 180-second per-asset timeout. A failed resource gate stops before launching Blender. Coordinate with other memory-intensive work; do not lower budgets merely to bypass resource contention. Logs and elapsed/peak-memory observations stay outside deterministic publication files. `--pause-file <path>` lets a coordinator pause safely between assets while preserving staged work; the driver resumes when that marker is removed.

The worker appends only the catalog's exact collection as unlinked data. It never loads the campus scene, evaluates a dependency graph, queries evaluated bounding boxes, saves a `.blend`, or converts source files. Interior collections are excluded through `njupt_editable_interiors` metadata and `interior_role`, including renamed/nested objects. Only authored exterior base meshes are emitted. Curve/font objects, references, cameras, interiors, render-time bevel/subdivision modifiers and the source-helper-identified five-ring emblem are omitted. The report records these omissions; `LOD2` means this explicit runtime projection, not complete authored rendering fidelity.

Split normals, triangle material assignments, exact stable IDs and object transforms are preserved. Collection instance offsets and the current canonical GPKG anchor are each applied once. The GLB contains one exact-ID root in campus coordinates and exact-ID metadata on every child mesh. Verification independently decodes every published position, reverses `[E,up,-N]`, and checks bounds within 0.0002 m numerical tolerance. Bounds may exceed source footprints because authored canopies, stairs and other exterior details overhang them; none of these checks establishes real-world accuracy.

Materials retain authored Principled base color, roughness, metallic and core emission values. Linked procedural shader effects are explicitly approximated rather than falsely described as baked textures. No image, photograph, texture or external runtime dependency is embedded. Original high-detail interiors stay in authored files. The initial campus payload remains LOD1; load `buildings[].detail_mesh_url` only for a requested building, preserve its materials and hide that building's LOD1 while detail is present. Keep LOD1 available when optional detail fails or is absent.

Native inputs are checked against catalog SHA-256 before and after extraction. The bundle, all artifacts and identity/placement relationships are verified again during runtime integration. The regular exporter cannot silently start Blender. A context-only package explicitly reports `source.native_blender.status=not_requested`; do not infer that optional extraction or its visual QA has run merely because the tooling is present.

The derived tree material manifest was reconciled to committed LFS identity (`b0faefa374a7a14527b9179995480370dfc3126130eade1dc873229673765083`, 16,915,445 bytes). It is not part of this lightweight runtime and does not establish a fresh tree mesh-statistics measurement.

## Verified native projection checkpoint

The 2026-09-30 extraction completed all 129 source assets in 114.432 seconds of summed per-asset process time; maximum observed child RSS was 408,023,040 bytes (389.1 MiB). All native SHA-256 identities remained unchanged. Independent GLB decoding checked every stable ID, canonical anchor and bounds round-trip.

The unquantized on-demand files total 356,714,040 bytes, with median 2,385,552 bytes and maximum 7,499,088 bytes. These are 751 exterior meshes / 5,923,920 triangles; 3,999 interior objects and one source-helper-identified emblem were excluded. This is a selective-loading optimization, not a claim that uncompressed GLB storage is smaller than compressed `.blend` files. Do not load the complete detail collection into the browser at once. The 475,324-byte initial campus LOD1 and 688,880-byte optional context remain separate resources.

Khronos glTF Validator 2.0.0-dev.3.10 checked all 129 detail files: zero errors, zero warnings, one informational notice for two source-derived degenerate triangles in `osm_way_223859802`. No native mesh was rewritten to hide that source condition. Unused material slots are removed with primitive assignments remapped, preserving the used authored materials.

The library sample was visually inspected as an offline orthographic rendering of the actual exported GLB with authored base colors and a north-up 20 m scale / LOD1 overlay. Pale stone wings, glazing, roof details, crown and colored stair-riser geometry are retained. Source-authored stairs extend about 18.34 m west of the mapped shell; crown height is 27.85 m versus the source extrusion's 20.2 m. The common anchor is preserved. Such source differences are not registration errors or proof of measured dimensions. The check does not claim browser/full-PBR fidelity; browser integration must separately test lazy-load, disposal, picking and fallback behavior.

## Attribution

See [LICENSES.md](../LICENSES.md). OSM-derived spatial products retain ODbL obligations and © OpenStreetMap contributors attribution. Original work is attributed to `hicancan / njupt-map` under CC BY 4.0; exporter code is AGPL-3.0-or-later. Native files, restricted photographs, plan originals, school marks, textures and Poly Haven assets are not embedded in this runtime package. Distribution rights for a derived database and a produced visual work are not interchangeable.

## Classroom state overlays

`source-regions.json` is now the single current `njupt-indoor-region-catalog`
version 2. Each immutable source region includes its stable region ID, building
and floor identity, source-normalized polygon, label point and bounds. The
publisher validates finite normalized coordinates and closed polygons. The
frame remains `source_image_normalized_xy_down`; `metric_transform` is null.
These outlines are not surveyed classroom coordinates or an inferred BIM.

A consumer joins room state through an explicit region-to-space crosswalk, not
through label equality or proximity. A room can retain several source regions;
a region without a reviewed mapping stays unresolved. Dynamic state is owned
by the campus application's timestamped classroom API and is never written into
the geometry package. A missing observation remains unknown. The manifest's
`indoor_regions_url` identifies the catalog and the normal artifact hashes cover
its complete contents. Historical state queries must use their own time and
binding history; this static catalog does not infer occupancy, device locations,
energy consumption or electrical topology.
