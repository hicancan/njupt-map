# Authored campus map

`map/` is the complete public spatial source. It contains one canonical GeoJSON
text file per authored layer and `map/campus.qgs` for QGIS editing. Coordinates
are WGS84, rounded to seven decimals; features and object keys are sorted by
`properties.id` and enforced by `src/map/format_geojson.py`.

```text
map/
├─ campus.qgs
└─ layers/
   ├─ campuses.geojson buildings.geojson rooms.geojson
   ├─ floor_plates.geojson cores.geojson
   ├─ places.geojson entrances.geojson ways.geojson
   └─ greens.geojson waters.geojson sports.geojson surfaces.geojson
      context_buildings.geojson landscape_exclusions.geojson
```

Public ids use natural path segments: `仙林/教3`, `仙林/梅苑1栋`,
`仙林/教3/6`, `仙林/教3-601`. URLs keep the slash separators; clients must
not percent-encode `/` into `%2F`. Dorm names and their `group` (苑) are
authored attributes; a bare numeric building name is invalid.

Floors are not an authored layer. The build derives `仙林/<building>/<n>` for
`1..levels` from each building and reuses its footprint; a floor's parent is
implied by its id. Single-kind layers omit `kind`, and the build restores that
layer kind for client outputs. `parent` is the only containment field.
`walk=true`, `bike=true`, and `steps=false` are defaults and appear only for
exceptions.

Every building and place names one category from `src/map/vocabulary.py`, the
one closed list; each category belongs to a group (教学科研, 生活, 餐饮, 购物,
服务, 文体, 交通, 办公) and has a tier, the prominence a map gives it: 1 from
afar, 2 closer, 3 close up. The entities and tiles carry `category`, `group`
and `tier`; clients classify nothing themselves. Building `style_hint` follows
the category defaults in the same file and is stored only for overrides.

`places.geojson` is one layer of points, on campus and around it. A place's
containment is read from its geometry, never authored: its `parent` is the
building its point lies in, if any, and its id is under `仙林/` inside the
campus wall and under `周边/` outside it. Every place 高德 lists nearby is
authored here unless it is a road name, an address or a closed business;
`bindings/amap.json` says which authored id answers each 高德 place, and
`python -m src.bindings.amap --check` fails if one is left out.

`observations/` contains provider answers and other references. `bindings/`
contains only external id mappings, provenance and route-gate reports. Neither
is read by the authored build. Delete both directories and this still works
(`tests/test_isolation.py` builds a copy without them and compares the bytes):

```powershell
uv run python src/map/format_geojson.py --check
uv run python src/map/build_authored.py
```

The build reads only `map/layers/` and emits `build/space/仙林/entities.json`,
`network.json`, `indoor.json`, `basemap.pmtiles`,
`basemap-preview.png`, `basemap.geojson` and `checks.json`. The PMTiles archive
is a deterministic vector-tile rendering of authored campus/context geometry;
no external tile package is copied or consulted. The preview and context-margin
check prove that authored surrounding roads, buildings and water extend beyond
the campus boundary at client zooms. Walking and cycling
permissions, no-bike ways, entrances, dorm grouping, names and levels are
attributes of the authored layers. The high德 route gate is optional evidence:
when `observations/providers/amap/仙林/routes.jsonl` exists its report is written
to `bindings/route-gates.json`; it never changes the map.

Rooms, floor plates and cores (stairs, lifts, toilets) are authored from the 23
teaching-building evacuation plans and the four official library plans. A floor
plate's `parent` is its derived floor. Unlisted rooms are not invented here; downstream campus facts releases may add null-geometry room
nodes when a real teaching source lists them.

Provider names, branch qualifiers and ids never enter an authored id or name.
Ways with `kind: crossing` remain in
the network for routing but are omitted from PMTiles and the preview so
carriageway connectors do not render as ladder rungs.

The first release is intentionally manual: from a checkout with `gh` release
credentials, run `uv run python src/map/release.py` (defaults to
`map-v0.2.0`). It formats, builds, verifies, writes the manifest and archive,
then calls `gh release create`; this command is prepared but has not been run.
