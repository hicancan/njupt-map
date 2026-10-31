# Authored campus map

`map/` is the complete public spatial source. It contains one canonical GeoJSON
text file per authored layer and `map/campus.qgs` for QGIS editing. Coordinates
are WGS84, rounded to seven decimals; features and object keys are sorted by
`id` and enforced by `src/map/format_geojson.py`.

```text
map/
├─ campus.qgs
└─ layers/
   ├─ campuses.geojson buildings.geojson floors.geojson rooms.geojson
   ├─ places.geojson entrances.geojson ways.geojson
   └─ greens.geojson waters.geojson sports.geojson surfaces.geojson
      context_buildings.geojson landscape_exclusions.geojson
```

Public ids use natural path segments: `仙林/教3`, `仙林/梅苑1栋`,
`仙林/教3/6`, `仙林/教3-601`. URLs keep the slash separators; clients must
not percent-encode `/` into `%2F`. Dorm names and their `group` (苑) are
authored attributes; a bare numeric building name is invalid.

`observations/` contains provider answers and other references. `bindings/`
contains only external id mappings, provenance and route-gate reports. Neither
is read by the authored build. Delete both directories and this still works:

```powershell
uv run python src/map/format_geojson.py --check
uv run python src/map/build_authored.py
```

The build reads only `map/layers/` and emits `build/space/仙林/places.json`,
`network.json`, `entities/space.json`, `basemap.pmtiles`,
`basemap-preview.png`, `basemap.geojson` and `checks.json`. The PMTiles archive
is a deterministic vector-tile rendering of authored campus/context geometry;
no external tile package is copied or consulted. The preview and context-margin
check prove that authored surrounding roads, buildings and water extend beyond
the campus boundary at client zooms. Walking and cycling
permissions, no-bike ways, entrances, dorm grouping, names and levels are
attributes of the authored layers. The high德 route gate is optional evidence:
when `observations/providers/amap/仙林/routes.jsonl` exists its report is written
to `bindings/route-gates.json`; it never changes the map.

The 642 reviewed room outlines are authored `rooms` features. Unreviewed rooms
are not invented here; later `njupt-data` releases may add null-geometry room
nodes when a real teaching source lists them.

Building process labels and legacy model names stay in `bindings/provenance.json`
and never enter an authored id or name. Ways with `kind: crossing` remain in
the network for routing but are omitted from PMTiles and the preview so
carriageway connectors do not render as ladder rungs.
