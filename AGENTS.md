# njupt-map

Architecture as ontology. Invariants over ceremony.

- `observations/` contains real-world inputs and curated observations. Selected video frames, annotations and registration control points are persistent source work. Rendered model frames are outputs, not real-world observations.
- `projects/map/` owns the current campus spatial data and QGIS authoring project. `campus.gpkg` is the editable spatial source; exported JSON and GeoJSON belong in `build/`.
- `projects/blender/` owns the editable campus, per-building assets, materials, cameras, animation and presentation source work. Treat existing native assets as authored source, regardless of whether they originally came from code.
- `src/` operates on those sources. Code must not hide a second copy of shared heights, footprints, names or coordinate conventions.
- `build/` holds disposable outputs. Runtime code may consume explicitly generated inputs, but source facts must never depend on validation reports.
- Use a stable common object ID. Display names and third-party IDs are attributes, not matching heuristics for authored models.
- Map coordinates use the project's explicit CRS. Blender uses local metres with an explicit origin, axes and vertical datum. Update transforms by common ID; report footprint changes rather than silently destroying an authored mesh.
- Preserve hand-edited buildings, campus composition, cameras and animation. Generation defaults must not overwrite native source work. Explicitly requested replacements are normal Git changes, never timestamped backup directories.
- Keep exactly one current implementation and format. Delete replaced code and update its callers. Git/LFS carries history; no legacy adapters, old versions, compatibility aliases or archived source directories in the working tree.
- Public observation metadata records source, permissions and bindings. Unreviewed third-party originals and restricted floorplan photographs stay local and ignored by Git. Never publish embedded restricted originals in `.blend` or exported packages.
- Validate identity, coordinates, references and source protection after changes. Do not equate successful rendering with measured accuracy or complete photographic coverage.
- Use PowerShell 7 on Windows. Use the existing project uv environment; no bare package installation or workspace-local temporary environments.
