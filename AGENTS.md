# njupt-map

Architecture as ontology. Invariants over ceremony.

## Role

njupt-map is the single source of truth for NJUPT campus space: a map we author
ourselves as if from zero. `map/layers/*.geojson` (sorted, fixed precision) is the
authored map and must build everything alone — network, places, aliases, space
entities and basemap tiles — with `observations/` and `bindings/` deleted.
`observations/` holds references (OSM, 高德 samples, official and club maps, floor
plans, photos); acquisition scripts write only there. `bindings/` is the only place
relating the authored map to the outside: external id maps, provenance and
comparisons such as the "never worse than 高德" route gate. No external ids,
provider fields, process labels or model numbers in authored layers. Public ids
read like 仙林/教3, 仙林/教3/6, 仙林/教3-601. Non-spatial facts (teaching, exams,
opening hours, school content) belong to njupt-data, which pins a njupt-map
release. The Blender projects are set aside and stay out of the data build.
