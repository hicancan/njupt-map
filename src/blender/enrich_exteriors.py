"""Add editable close-range details to an existing native building asset.

Called in Blender after opening/appending the asset, not on a linked collection::

    stats = enrich(current_map_building, authored_collection, campus=current_map)

The current map is the only source of footprint/height/placement facts. Existing
pane geometry supplies the facade rhythm. Owned meshes are batched and replaced
idempotently; existing building geometry, cameras and source images are retained.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector

from campus_geometry import Batch, material, point_inside, signed_area
from campus_buildings import classify

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "projects/blender/design/exteriors.json"
PREFIX = "EXTERIOR::"
SPECIAL = {
    "osm_way_1454085437": "gate",
    "osm_way_223859810": "landmark",
    "osm_way_224950590": "landmark",
    "osm_way_1281082570": "landmark",
    "osm_way_223944208": "landmark",
    "osm_way_223859802": "stand",
    "osm_way_223859827": "stand",
    "osm_way_224940881": "stand",
    "osm_way_224990427": "passage",
    "osm_way_224990428": "passage",
}


def _palette():
    # Explicitly metric procedural surfaces; no observation image is packed.
    return {
        "seal": material("Exterior detail | black EPDM seals", (.015, .019, .019), .89),
        "metal": material("Exterior detail | brushed aluminium", (.38, .41, .40), .32, .72),
        "steel": material("Exterior detail | charcoal powder coated steel", (.10, .12, .12), .58, .45),
        "white": material("Exterior detail | pale equipment enamel", (.58, .61, .58), .57, .12),
        "glass": material("Exterior detail | entrance glazing", (.021, .061, .071), .16, .25),
        "stone": material("Exterior detail | fine granite", (.38, .39, .36), .83),
        "rubber": material("Exterior detail | equipment isolators", (.027, .031, .030), .93),
        "blind": material("Exterior detail | neutral indoor roller shade", (.30, .33, .30), .88),
        "light": material("Exterior detail | warm linear entry lights", (.9, .68, .37), .45, emission=.8),
        "red": material("Exterior detail | red moulded seat backs", (.40, .10, .065), .61),
    }


def _edges(outer, holes=()):
    for ri, ring in enumerate([outer, *holes]):
        orientation = (1 if signed_area(ring) > 0 else -1) * (-1 if ri else 1)
        for p, q in zip(ring, ring[1:] + ring[:1]):
            length = math.dist(p, q)
            if length < .12:
                continue
            u = ((q[0] - p[0]) / length, (q[1] - p[1]) / length)
            n = (u[1] * orientation, -u[0] * orientation)
            yield ri, p, q, length, u, n


def _edge_box(batch, p, u, n, d, depth, z, w, t, h, mat):
    batch.box((p[0] + u[0] * d + n[0] * depth,
               p[1] + u[1] * d + n[1] * depth, z),
              (w, t, h), mat, math.atan2(u[1], u[0]))


def _segment_distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    den = dx * dx + dy * dy
    t = min(1., max(0., ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / den)) if den else 0.
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _existing_objects(collection):
    # Interior display names are editable and have no ownership semantics.
    # Exclude descendants of the marked authoring root, including nested floor
    # and room collections; otherwise internal glazing creates exterior seals
    # that remain visible after the interior collection is hidden or replaced.
    excluded = set()
    for child in (collection, *collection.children_recursive):
        if (child.get("njupt_editable_interiors")
                or child.get("authoring_kind") == "current editable additive exterior refinement"
                or child.name.startswith(PREFIX)):
            excluded.update(child.all_objects)
    return [ob for ob in collection.all_objects
            if ob not in excluded and not ob.name.startswith(PREFIX)]


def _clear_owned(collection, ident):
    name = PREFIX + ident
    matches = [c for c in collection.children
               if c.get('asset_id') == ident
               and c.get('authoring_kind') == 'current editable additive exterior refinement']
    if len(matches)>1:
        raise ValueError(f'{ident}: multiple current owned exterior collections')
    owned = matches[0] if matches else None
    if owned:
        for ob in list(owned.all_objects):
            mesh = ob.data if ob.type == "MESH" else None
            bpy.data.objects.remove(ob, do_unlink=True)
            if mesh and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        collection.children.unlink(owned)
        bpy.data.collections.remove(owned)
    owned = bpy.data.collections.new(name)
    collection.children.link(owned)
    return owned


def _surface_finish(objects):
    """Small scale roughness variation without touching authored colour maps."""
    seen = set()
    count = 0
    for ob in objects:
        if ob.type != "MESH":
            continue
        for mat in ob.data.materials:
            if not mat or mat in seen or mat.library:
                continue
            seen.add(mat)
            if not mat.use_nodes or mat.get("exterior_finish_schema") == 1:
                continue
            nodes, links = mat.node_tree.nodes, mat.node_tree.links
            bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
            if not bsdf or bsdf.inputs["Roughness"].is_linked:
                continue
            roughness = float(bsdf.inputs["Roughness"].default_value)
            tex = nodes.new("ShaderNodeTexNoise")
            tex.name = "NJUPT_EXTERIOR_METRIC_ROUGHNESS"
            tex.inputs["Scale"].default_value = 38. if roughness < .5 else 6.
            tex.inputs["Detail"].default_value = 2.
            geo = nodes.new("ShaderNodeNewGeometry")
            geo.name = "NJUPT_EXTERIOR_SURFACE_POSITION"
            remap = nodes.new("ShaderNodeMapRange")
            remap.name = "NJUPT_EXTERIOR_RESTRAINED_ROUGHNESS"
            remap.inputs["To Min"].default_value = max(.06, roughness - .025)
            remap.inputs["To Max"].default_value = min(.98, roughness + .035)
            links.new(geo.outputs["Position"], tex.inputs["Vector"])
            links.new(tex.outputs["Fac"], remap.inputs["Value"])
            links.new(remap.outputs["Result"], bsdf.inputs["Roughness"])
            mat["exterior_finish_schema"] = 1
            mat["surface_finish_status"] = "Metric procedural roughness; authored colour/texture and reflectance retained."
            count += 1
    return count


def _is_glazing(mat):
    name = mat.name.lower() if mat else ""
    return (any(s in name for s in ("glazing", "reflection", "reflective blue"))
            and not any(s in name for s in ("mullion", "frame", "metal")))


def _pane_details(objects, edges, batch, mats, ident, gasket_width):
    """Follow native panes, including authored rotations and courtyard faces."""
    seen = set()
    panes = 0
    blind_count = 0
    for ob in objects:
        if ob.type != "MESH" or not any(_is_glazing(m) for m in ob.data.materials):
            continue
        mesh = ob.data
        normal_matrix = ob.matrix_world.to_3x3().inverted().transposed()
        for poly in mesh.polygons:
            if not _is_glazing(mesh.materials[poly.material_index]):
                continue
            normal = (normal_matrix @ poly.normal).normalized()
            if abs(normal.z) > .18 or poly.area < .35:
                continue
            points = [ob.matrix_world @ mesh.vertices[i].co for i in poly.vertices]
            center = sum(points, Vector()) / len(points)
            nearest = min(edges, key=lambda e: _segment_distance(center, e[1], e[2]))
            # Only the outer face of a glass box, never its duplicated rear face.
            if normal.x * nearest[5][0] + normal.y * nearest[5][1] < .65:
                continue
            u = (-normal.y, normal.x)
            width = max(p.x * u[0] + p.y * u[1] for p in points) - min(p.x * u[0] + p.y * u[1] for p in points)
            height = max(p.z for p in points) - min(p.z for p in points)
            if width < .42 or height < .72 or width > 9.5 or height > 8.5:
                continue
            key = tuple(round(v, 3) for v in (*center, normal.x, normal.y))
            if key in seen:
                continue
            seen.add(key)
            n = (normal.x, normal.y)
            p = (center.x, center.y)
            # Narrow EPDM seals are smaller than the authored aluminium frame.
            for dx in (-width / 2 + .017, width / 2 - .017):
                _edge_box(batch, p, u, n, dx, .006, center.z, gasket_width, .010, height - .03, mats["seal"])
            for dz in (-height / 2 + .017, height / 2 - .017):
                _edge_box(batch, p, u, n, 0, .006, center.z + dz, width - .03, .010, gasket_width, mats["seal"])
            # A restrained minority of upper floor panes receives a roller shade
            # and opening handle; the selection remains stable across reruns.
            token = hashlib.sha256((ident + repr(key)).encode()).digest()[0]
            if token % 17 == 0 and center.z > 4. and width < 3.2:
                shade_h = min(.28, height * .14)
                _edge_box(batch, p, u, n, 0, .009, center.z + height / 2 - shade_h / 2 - .025,
                          width - .08, .014, shade_h, mats["blind"])
                blind_count += 1
            if width < 3.2 and height < 3.8:
                dx = width / 2 - .11
                _edge_box(batch, p, u, n, dx, .055, center.z - .05, .022, .018, .12, mats["metal"])
            panes += 1
    return panes, blind_count


def _blocked(point, b, campus, radius=.25):
    if not campus:
        return False
    wx, wy = point[0] + b["center"][0], point[1] + b["center"][1]
    for item in campus.get("buildings", []) + campus.get("waters", []):
        if item["id"] == b["id"]:
            continue
        if any(point_inside((wx + dx, wy + dy), item["outer"], item.get("holes", []))
               for dx, dy in ((0, 0), (radius, 0), (-radius, 0), (0, radius), (0, -radius))):
            return True
    return False


def _entrance(b, edges, campus, batch, mats, ground):
    candidates = []
    for edge in edges:
        ri, p, q, length, u, n = edge
        if ri or length < 4.0:
            continue
        width = min(4.5, length * .44)
        # The entry can slide along its chosen wall to avoid a concave corner,
        # adjacent asset, water or narrow inter-building gap.
        for fraction in (.5, .34, .66):
            d = length * fraction
            checkpoints = [(p[0] + u[0] * (d + dx) + n[0] * dep,
                            p[1] + u[1] * (d + dx) + n[1] * dep)
                           for dx in (-width / 2, 0, width / 2) for dep in (.5, 1.9)]
            if any(point_inside(v, b["_outer"], b["_holes"]) or _blocked(v, b, campus) for v in checkpoints):
                continue
            midpoint = (p[0] + u[0] * d + b["center"][0], p[1] + u[1] * d + b["center"][1])
            distances = []
            for road in (campus or {}).get("roads", []):
                for a, bb in zip(road["points"], road["points"][1:]):
                    distances.append(_segment_distance(midpoint, a, bb) - float(road.get("width", 3.)) / 2)
            score = min(distances, default=15.) + abs(fraction - .5) * 4. - min(length, 45.) * .04
            candidates.append((score, edge, d, width))
    if not candidates:
        return None
    _, edge, d, width = min(candidates, key=lambda c: c[0])
    ri, p, q, length, u, n = edge
    door_h = min(2.55, float(b["height"]) * .70)
    door_w = min(width - .48, 3.2)
    z0 = ground + .18
    def box(dx, dep, z, w, t, h, mat):
        _edge_box(batch, p, u, n, d + dx, dep, z, w, t, h, mat)
    # Two lightweight leaves, metal frame and real projecting pull handles.
    box(0, .19, z0 + door_h / 2, door_w + .14, .055, door_h + .12, mats["steel"])
    for sign in (-1, 1):
        box(sign * door_w / 4, .24, z0 + door_h / 2, door_w / 2 - .085, .036, door_h - .14, mats["glass"])
        box(sign * .035, .30, z0 + door_h / 2, .035, .060, door_h - .04, mats["metal"])
        for dz in (-.30, .30):
            box(sign * .20, .40, z0 + 1.25 + dz, .035, .18, .030, mats["metal"])
        aa = (p[0] + u[0] * (d + sign * .20) + n[0] * .49,
              p[1] + u[1] * (d + sign * .20) + n[1] * .49)
        batch.pipe((*aa, z0 + .95), (*aa, z0 + 1.55), .022, mats["metal"], 8)
    # A thin canopy and two low risers make the threshold physically readable.
    for i in range(2):
        box(0, .38 + i * .37, ground + .06 * (2 - i), width + .30, 1.50 - i * .42, .12 * (2 - i), mats["stone"])
    box(0, .62, z0 + door_h + .30, width + .42, 1.60, .11, mats["metal"])
    box(0, .52, z0 + door_h + .222, width - .45, .028, .023, mats["light"])
    for dx in (-width / 2 + .20, width / 2 - .20):
        aa = (p[0] + u[0] * (d + dx) + n[0] * .07,
              p[1] + u[1] * (d + dx) + n[1] * .07, z0 + door_h + .85)
        bb = (aa[0] + n[0] * 1.22, aa[1] + n[1] * 1.22, z0 + door_h + .35)
        batch.pipe(aa, bb, .019, mats["steel"], 6)
    return {"edge_midpoint_local_m": [round(p[0] + u[0] * d, 4), round(p[1] + u[1] * d, 4)],
            "outward_axis": list(n), "width_m_inferred": round(width, 3),
            "placement_status": "Inferred road-facing entry; current map obstacle check passed. Not a surveyed doorway."}


def _rainwater(b, edges, batch, mats, ground):
    count = 0
    height = float(b["height"])
    for ri, p, q, length, u, n in edges:
        if length < 9. or (ri and length < 24.):
            continue
        # The existing generation often already has a pipe at edge start.
        # Our service shoe and end pipe use the opposite end of the wall.
        d = length - .32
        xx, yy = p[0] + u[0] * d + n[0] * .25, p[1] + u[1] * d + n[1] * .25
        bottom = ground + .30
        if height - bottom < 2.:
            continue
        batch.pipe((xx, yy, bottom), (xx, yy, height - .08), .048, mats["white"], 8)
        batch.pipe((xx, yy, bottom), (xx + n[0] * .26, yy + n[1] * .26, bottom - .20), .049, mats["white"], 8)
        for zz in range(2, max(3, int(height)), 3):
            _edge_box(batch, p, u, n, d, .22, zz, .13, .085, .027, mats["steel"])
        # Recessed roof-edge collection head and a downpipe collar.
        _edge_box(batch, p, u, n, d, .24, height - .13, .24, .28, .31, mats["metal"])
        count += 1
        if count >= 10:
            break
    return count


def _roof_height(point, b):
    z = float(b["height"])
    for volume in b.get("upper_volumes", []):
        outer = [(p[0] - b["center"][0], p[1] - b["center"][1]) for p in volume["outer"]]
        holes = [[(p[0] - b["center"][0], p[1] - b["center"][1]) for p in ring] for ring in volume.get("holes", [])]
        if point_inside(point, outer, holes):
            z = max(z, float(volume.get("base_z", z)) + float(volume.get("height", 0)))
    return z


def _roof_services(b, edges, batch, mats, native):
    count = 0
    locations = []
    occupied = []
    # Read existing plant/crowns from native roof-height geometry, so added
    # mechanical detail cannot occupy the same place as an authored housing.
    for ob in native:
        if ob.type != "MESH":
            continue
        for poly in ob.data.polygons:
            if poly.area < .20:
                continue
            points = [ob.matrix_world @ ob.data.vertices[i].co for i in poly.vertices]
            if min(p.z for p in points) < float(b["height"]) + .65:
                continue
            occupied.append((min(p.x for p in points), max(p.x for p in points),
                             min(p.y for p in points), max(p.y for p in points)))
    # Tangent-aligned plant candidates lie 3.2m behind a mapped outside edge.
    for ri, p, q, length, u, n in sorted(edges, key=lambda e: -e[3]):
        if ri or length < 14.:
            continue
        for fraction in (.27, .73):
            d = length * fraction
            x, y = p[0] + u[0] * d - n[0] * 3.2, p[1] + u[1] * d - n[1] * 3.2
            footprint = [(x + u[0] * du + n[0] * dn, y + u[1] * du + n[1] * dn)
                         for du, dn in ((-1.4, -1.0), (1.4, -1.0), (1.4, 1.0), (-1.4, 1.0))]
            if not all(point_inside(v, b["_outer"], b["_holes"]) for v in footprint):
                continue
            xmin, xmax = min(v[0] for v in footprint) - .25, max(v[0] for v in footprint) + .25
            ymin, ymax = min(v[1] for v in footprint) - .25, max(v[1] for v in footprint) + .25
            if any(xmin < xx1 and xmax > xx0 and ymin < yy1 and ymax > yy0 for xx0, xx1, yy0, yy1 in occupied):
                continue
            datums = [_roof_height(v, b) for v in footprint]
            if max(datums) - min(datums) > .05 or any(math.dist((x, y), v) < 5. for v in locations):
                continue
            z = datums[0] + .12
            angle = math.atan2(u[1], u[0])
            def box(dx, dy, zz, w, d, h, mat):
                batch.box((x + u[0] * dx + n[0] * dy, y + u[1] * dx + n[1] * dy, zz), (w, d, h), mat, angle)
            for dx in (-.95, .95):
                box(dx, 0, z + .10, .12, 1.42, .20, mats["steel"])
                for dy in (-.53, .53):
                    box(dx, dy, z + .23, .14, .14, .06, mats["rubber"])
            box(0, 0, z + .72, 2.5, 1.4, .92, mats["white"])
            for dx in (-.63, .63):
                xx, yy = x + u[0] * dx, y + u[1] * dx
                batch.cylinder((xx, yy, z + 1.205), .40, .075, mats["steel"], 16)
                batch.cylinder((xx, yy, z + 1.248), .13, .019, mats["metal"], 12)
                for theta in (0, math.pi / 3, 2 * math.pi / 3):
                    batch.pipe((xx - .33 * math.cos(theta), yy - .33 * math.sin(theta), z + 1.251),
                               (xx + .33 * math.cos(theta), yy + .33 * math.sin(theta), z + 1.251), .009, mats["metal"], 4)
            for j in range(8):
                box(0, .716, z + .38 + j * .07, 2.28, .018, .025, mats["steel"])
            # Insulated paired service lines and a small weatherproof isolator.
            box(1.30, 0, z + .70, .16, .40, .37, mats["steel"])
            for dn in (-.07, .07):
                aa = (x + u[0] * 1.30 + n[0] * dn, y + u[1] * 1.30 + n[1] * dn, z + .43)
                bb = (x + u[0] * 2.30 + n[0] * dn, y + u[1] * 2.30 + n[1] * dn, z + .43)
                batch.pipe(aa, bb, .045, mats["rubber"], 6)
            locations.append((x, y))
            count += 1
            if count >= (1 if float(b.get("area_m2", 0)) < 700 else 2):
                return count
    return count


def _service_panel(edges, batch, mats, ground):
    """Small utility assets also receive a physical, editable detail pass."""
    edge = max((e for e in edges if e[0] == 0), key=lambda e: e[3])
    _, p, q, length, u, n = edge
    width = min(.62, length * .40)
    if width < .20:
        raise ValueError("Native footprint is too small for an inferred utility access panel")
    d = length / 2
    _edge_box(batch, p, u, n, d, .065, ground + 1.05, width + .07, .07, .92, mats["steel"])
    _edge_box(batch, p, u, n, d, .11, ground + 1.05, width, .028, .85, mats["white"])
    for j in range(8):
        _edge_box(batch, p, u, n, d, .13, ground + .83 + j * .056, width - .10, .030, .019, mats["steel"])
    _edge_box(batch, p, u, n, d + width * .36, .15, ground + 1.10, .025, .028, .095, mats["metal"])
    return 1


def _gate_details(objects, batch, mats):
    centers = set()
    for ob in objects:
        if ob.type != "MESH":
            continue
        for poly in ob.data.polygons:
            mat = ob.data.materials[poly.material_index]
            if not mat or "Gate columns" not in mat.name or len(poly.vertices) < 12:
                continue
            points = [ob.matrix_world @ ob.data.vertices[v].co for v in poly.vertices]
            if max(v.z for v in points) > .04:
                continue
            center = sum(points, Vector()) / len(points)
            centers.add((round(center.x, 3), round(center.y, 3)))
    for x, y in sorted(centers):
        batch.box((x, y, .055), (.70, .70, .075), mats["metal"])
        for dx in (-.255, .255):
            for dy in (-.255, .255):
                batch.cylinder((x + dx, y + dy, .112), .032, .044, mats["steel"], 6)
    return len(centers)


def _stand_details(b, objects, edges, campus, batch, mats):
    # Seat backs are inferred furnishings attached to native seat tops, not a
    # generic facade or an invented office roof on a sports stand.
    pitch = min((s for s in (campus or {}).get("sports", []) if s.get("sport") == "soccer"),
                key=lambda s: math.dist(s["center"], b["center"]), default=None)
    field = ((pitch["center"][0] - b["center"][0], pitch["center"][1] - b["center"][1]) if pitch else (0., 0.))
    seats = 0
    top_vertices = []
    for ob in objects:
        if ob.type != "MESH" or "tiered seating" not in ob.name:
            continue
        top_vertices += [ob.matrix_world @ v.co for v in ob.data.vertices]
        for poly in ob.data.polygons:
            mat = ob.data.materials[poly.material_index]
            if not mat or "deep red seating" not in mat.name or poly.normal.z < .9 or not .16 < poly.area < .26:
                continue
            points = [ob.matrix_world @ ob.data.vertices[v].co for v in poly.vertices]
            if max(v.z for v in points) - min(v.z for v in points) > .01:
                continue
            center = sum(points, Vector()) / len(points)
            toward = Vector((field[0] - center.x, field[1] - center.y, 0)).normalized()
            longest = max(zip(points, points[1:] + points[:1]), key=lambda pq: (pq[1] - pq[0]).length)
            uu = (longest[1] - longest[0]).normalized()
            normal = Vector((-uu.y, uu.x, 0))
            if normal.dot(toward) > 0:
                normal *= -1
            batch.box((center.x + normal.x * .18, center.y + normal.y * .18, center.z + .21),
                      (.44, .055, .40), mats["red"], math.atan2(uu.y, uu.x))
            seats += 1
    rails = 0
    for ri, p, q, length, u, n in edges:
        if ri or length < 5.:
            continue
        middle = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        if (field[0] - middle[0]) * n[0] + (field[1] - middle[1]) * n[1] > 0:
            continue
        for j in range(max(2, math.ceil(length / 1.8))):
            d = .25 + (length - .5) * j / max(1, math.ceil(length / 1.8) - 1)
            x, y = p[0] + u[0] * d - n[0] * .15, p[1] + u[1] * d - n[1] * .15
            nearby = [v.z for v in top_vertices if math.hypot(v.x - x, v.y - y) < 1.4]
            z = max(nearby, default=.3)
            batch.pipe((x, y, z), (x, y, z + 1.05), .024, mats["steel"], 6)
            if j:
                for dz in (.54, 1.05):
                    batch.pipe((prev[0], prev[1], prev[2] + dz), (x, y, z + dz), .026, mats["steel"], 6)
            prev = (x, y, z)
            rails += 1
    return seats, rails


def enrich(building, collection, campus=None):
    """Return counts and provenance after modifying only this loaded local asset."""
    if collection.library:
        raise ValueError("Open or append the local native asset before enrichment; linked collections are protected.")
    ident = building["id"]
    if collection.get("asset_id") != ident:
        raise ValueError(f"Asset identity mismatch: {ident} != {collection.get('asset_id')}")
    config = json.loads(DESIGN.read_text(encoding="utf8"))
    b = dict(building)
    cx, cy = b["center"]
    b["_outer"] = [(p[0] - cx, p[1] - cy) for p in b["outer"]]
    b["_holes"] = [[(p[0] - cx, p[1] - cy) for p in ring] for ring in b.get("holes", [])]
    edges = list(_edges(b["_outer"], b["_holes"]))
    if not edges:
        raise ValueError(f"{ident}: footprint has no valid edges")
    kind = classify(b)
    profile = SPECIAL.get(ident, kind if kind in config["profiles"] else "regular")
    rules = config["profiles"][profile]
    native = _existing_objects(collection)
    owned = _clear_owned(collection, ident)
    mats = _palette()
    glazing, service, entry, special = Batch(), Batch(), Batch(), Batch()
    stat = {"asset_id": ident, "profile": profile, "native_objects_preserved": len(native),
            "materials_refined": _surface_finish(native), "pane_details": 0, "roller_shades": 0,
            "rainwater_pipes": 0, "roof_units": 0, "entrance": None,
            "gate_base_plates": 0, "seat_backs": 0, "railing_posts": 0}
    stat["pane_details"], stat["roller_shades"] = _pane_details(native, edges, glazing, mats, ident, config["glass_gasket_m"])
    ground = max(.02, float(b.get("min_height", 0.)))
    if rules["rainwater"]:
        stat["rainwater_pipes"] = _rainwater(b, edges, service, mats, ground)
    if rules["entrance"] and ground < .7:
        stat["entrance"] = _entrance(b, edges, campus, entry, mats, ground)
    if rules["roof_services"]:
        stat["roof_units"] = _roof_services(b, edges, service, mats, native)
    if profile == "gate":
        stat["gate_base_plates"] = _gate_details(native, special, mats)
    if profile == "stand":
        stat["seat_backs"], stat["railing_posts"] = _stand_details(b, native, edges, campus, special, mats)
    stat["utility_service_panels"] = 0
    if not any(batch.faces for batch in (glazing, service, entry, special)):
        stat["utility_service_panels"] = _service_panel(edges, service, mats, ground)
    # Landmark curved panes can lack suitable mapped normal matches, but native
    # material refinement still improves those assets without changing shapes.
    meshes = []
    for role, batch in (("native pane seals and hardware", glazing), ("rainwater and roof service detail", service),
                        ("inferred entry doors canopy and threshold", entry), ("structure and seating detail", special)):
        if batch.faces:
            ob = batch.object(PREFIX + ident + "::" + role, owned)
            ob["asset_id"] = ident
            ob["authoring_role"] = "editable additive exterior detail"
            ob["dimension_status"] = config["dimension_status"]
            meshes.append(ob)
    stat["added_objects"] = len(meshes)
    stat["added_vertices"] = sum(len(o.data.vertices) for o in meshes)
    stat["added_faces"] = sum(len(o.data.polygons) for o in meshes)
    if not meshes and not stat["materials_refined"] and not any(mat and mat.get("exterior_finish_schema") for ob in native if ob.type == "MESH" for mat in ob.data.materials):
        raise ValueError(f"{ident}: no exterior improvement applied")
    stat["geometry_status"] = "Preserved native envelope; millimetre details, furnishing and service layout inferred. Pane placement inherited from authored mesh."
    stat["design_source"] = DESIGN.relative_to(ROOT).as_posix()
    owned["asset_id"] = ident
    owned["authoring_kind"] = "current editable additive exterior refinement"
    owned["inference_status"] = stat["geometry_status"]
    owned["stats_json"] = json.dumps(stat, ensure_ascii=False)
    collection["exterior_refinement_schema"] = 1
    collection["exterior_refinement_json"] = json.dumps(stat, ensure_ascii=False)
    return stat
