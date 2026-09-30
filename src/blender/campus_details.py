"""Small, auditable ground-level details for the Xianlin campus scene.

Public API: build_details(data, collection, materials, font) -> JSON-safe stats.
All coordinates are world metres. The south entrance's objects are observed in
official gallery-01.jpg; their metre dimensions and positions are inferred.
Bike bays, wayfinding boards and library seats are explicitly generic inferred
furniture. No photograph is redistributed as a texture and no unlocated monument
is silently assigned a location.
"""
import math
import random
import bpy
import bmesh
from mathutils import Vector

from campus_geometry import Batch, material, point_inside, text_object


TAU = math.tau
ENTRANCE_SOURCE = 'observations/images/njupt/gallery-01.jpg'
LIBRARY_SOURCE = 'observations/images/njupt/guide-2020-13.png'


def _distance_segment(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    t = max(0., min(1., ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy or 1)))
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)


def _clear(data, x, y, sx, sy, road_clearance=.25):
    """Conservative sampled clearance, including mapped roadway half-width."""
    for dx in (-sx/2, 0, sx/2):
        for dy in (-sy/2, 0, sy/2):
            p = (x+dx, y+dy)
            for item in data.get('buildings', []) + data.get('waters', []):
                if point_inside(p, item['outer'], item.get('holes', [])):
                    return False
            for road in data.get('roads', []):
                pts = road['points']
                if any(_distance_segment(p, a, b) < road.get('width', 5.5)/2+road_clearance
                       for a, b in zip(pts, pts[1:])):
                    return False
    return True


def _tag(ob, evidence, note):
    ob['evidence_source'] = evidence
    ob['confidence'] = 'inferred_dimensions_and_placement'
    ob['modelling_note'] = note
    return ob


def _sphere(batch, center, radius, mat, segments=18, rings=10):
    x, y, z = center
    for j in range(rings):
        a, b = -math.pi/2+j*math.pi/rings, -math.pi/2+(j+1)*math.pi/rings
        for i in range(segments):
            c, d = i*TAU/segments, (i+1)*TAU/segments
            batch.face([(x+radius*math.cos(v)*math.cos(u),
                         y+radius*math.cos(v)*math.sin(u), z+radius*math.sin(v))
                        for u, v in ((c, a), (d, a), (d, b), (c, b))], mat)


def _ellipse_ring(batch, center, axes, width, z, height, mat, segments=64):
    x, y = center
    rx, ry = axes
    for i in range(segments):
        a, b = i*TAU/segments, (i+1)*TAU/segments
        q = [(x+r*math.cos(t), y+s*math.sin(t))
             for r, s, t in ((rx, ry, a), (rx, ry, b),
                             (rx-width, ry-width, b), (rx-width, ry-width, a))]
        batch.face([(u, v, z+height) for u, v in q], mat)
        batch.face([(q[0][0], q[0][1], z), (q[1][0], q[1][1], z),
                    (q[1][0], q[1][1], z+height), (q[0][0], q[0][1], z+height)], mat)


def _natural_stone(batch, x, y, mats):
    # Irregular, asymmetric closed rock: local front deliberately keeps a small
    # legible face for the observed red Tengfei inscription.
    rng = random.Random(1942)
    profile = [(0.24, 1.00, -.10), (.85, 1.04, -.10),
               (2.55, .90, -.35), (3.85, .64, -.53), (4.3, .15, -.57)]
    rings = []
    for z, scale, offset in profile:
        pts = []
        for i in range(16):
            t = i*TAU/16
            r = scale*(1+rng.uniform(-.055, .055))
            xx = x+2.6*r*math.cos(t)+offset
            yy = y+1.34*r*math.sin(t)
            if i in (11, 12, 13) and z <= 3.85:
                yy = y-1.23
            pts.append((xx, yy, z+rng.uniform(-.10, .10)))
        rings.append(pts)
    batch.face(list(reversed(rings[0])), mats[0])
    for a, b in zip(rings, rings[1:]):
        for i in range(16):
            j = (i+1) % 16
            mat = mats[rng.randrange(len(mats))]
            batch.face([a[i], a[j], b[j]], mat)
            batch.face([a[i], b[j], b[i]], mat)
    batch.face(rings[-1], mats[0])


def _flag_point(x, y, top, width, height, u, v):
    # A gentle standing wave gives readable cloth without physics dependencies.
    return (x-width*u, y+.22*math.sin(u*TAU*1.4+v*.65)*u,
            top-height*v-.13*u+.08*math.sin(u*TAU)*u)


def _flag(batch, x, y, top, width, height, cloth, gold=None):
    for i in range(20):
        for j in range(12):
            batch.face([_flag_point(x, y, top, width, height, u, v)
                        for u, v in ((i/20, j/12), ((i+1)/20, j/12),
                                     ((i+1)/20, (j+1)/12), (i/20, (j+1)/12))], cloth)
    if gold is None:
        return
    # Chinese flag's five stars are small actual geometry, not a raster texture.
    for u, v, radius in ((.16, .25, .105), (.32, .10, .037),
                          (.38, .22, .037), (.38, .38, .037), (.32, .50, .037)):
        points = []
        for k in range(10):
            a = -math.pi/2+k*math.pi/5
            rr = radius if k % 2 == 0 else radius*.40
            p = _flag_point(x, y, top, width, height,
                            u+rr*math.cos(a), v+rr*width/height*math.sin(a))
            points.append((p[0], p[1]-.014, p[2]))
        # Fan triangles avoid a concave polygon interpretation on the star.
        c = _flag_point(x, y, top, width, height, u, v)
        c = (c[0], c[1]-.016, c[2])
        for a, b in zip(points, points[1:]+points[:1]):
            batch.face([c, a, b], gold)


def _bench(batch, x, y, angle, steel, wood):
    ca, sa = math.cos(angle), math.sin(angle)
    def p(dx, dy, z):
        return (x+ca*dx-sa*dy, y+sa*dx+ca*dy, z)
    for dx in (-.75, .75):
        batch.box(p(dx, 0, .26), (.085, .45, .45), steel, angle)
        batch.box(p(dx, .19, .68), (.07, .07, .85), steel, angle)
    for dy in (-.18, -.06, .06, .18):
        batch.box(p(0, dy, .50), (1.92, .10, .055), wood, angle)
    for z in (.67, .82, .97):
        batch.box(p(0, .22, z), (1.92, .05, .12), wood, angle)


def _wheel(batch, cx, cy, cz, rubber, steel):
    # Wheel lies in bike-local XZ plane; y is the axle direction.
    for radius, tube, mat, sides in ((.34, .033, rubber, 8), (.304, .012, steel, 6)):
        for i in range(32):
            a, b = i*TAU/32, (i+1)*TAU/32
            for j in range(sides):
                c, d = j*TAU/sides, (j+1)*TAU/sides
                batch.face([(cx+(radius+tube*math.cos(v))*math.cos(u),
                             cy+tube*math.sin(v), cz+(radius+tube*math.cos(v))*math.sin(u))
                            for u, v in ((a, c), (b, c), (b, d), (a, d))], mat)
    batch.pipe((cx, cy-.045, cz), (cx, cy+.045, cz), .03, steel)
    for i in range(12):
        a = i*TAU/12
        batch.pipe((cx, cy+(.027 if i % 2 else -.027), cz),
                   (cx+.30*math.cos(a), cy, cz+.30*math.sin(a)), .0035, steel, 5)


def _bike(batch, x, y, angle, frame, steel, rubber):
    """Append one full-size bike, transforming new vertices only into the bay."""
    start = len(batch.vertices)
    rear, front = (-.56, 0, .375), (.61, 0, .375)
    seat, crank, head = (-.30, 0, .94), (-.02, 0, .40), (.34, 0, .94)
    for a, b, r in ((rear, seat, .022), (seat, crank, .029),
                     (crank, rear, .022), (seat, head, .029),
                     (head, crank, .036), (head, front, .022)):
        batch.pipe(a, b, r, frame)
    _wheel(batch, *rear, rubber, steel)
    _wheel(batch, *front, rubber, steel)
    batch.pipe(seat, (-.32, 0, 1.06), .023, steel)
    batch.box((-.35, 0, 1.075), (.28, .17, .065), rubber)
    batch.pipe(head, (.29, 0, 1.16), .022, steel)
    batch.pipe((.29, -.27, 1.16), (.29, .27, 1.16), .018, steel)
    for s in (-1, 1):
        batch.pipe((.29, s*.18, 1.16), (.29, s*.28, 1.16), .026, rubber)
        batch.pipe((crank[0], s*.12, crank[2]), (crank[0]+s*.14, s*.12, crank[2]), .012, steel)
        batch.box((crank[0]+s*.14, s*.16, crank[2]), (.09, .13, .032), rubber)
        # Two chain runs are visible on the drive side.
    for z in (.32, .46):
        batch.pipe((-.50, -.07, .375), (-.02, -.07, z), .006, steel, 5)
    # Curved rear mudguard, support stay, kickstand and basket wire mesh.
    for i in range(15):
        a, b = .05+i*math.pi/15, .05+(i+1)*math.pi/15
        batch.face([(-.56+.39*math.cos(t), dy, .375+.39*math.sin(t))
                    for t, dy in ((a, -.04), (b, -.04), (b, .04), (a, .04))], frame)
    batch.pipe((-.28, 0, .45), (-.40, .19, .035), .011, steel)
    batch.pipe((-.60, 0, .74), (-.30, 0, .90), .008, steel)
    for z in (.94, 1.17):
        for a, b in (((.50, -.18, z), (.82, -.18, z)),
                     ((.82, -.18, z), (.82, .18, z)),
                     ((.82, .18, z), (.50, .18, z)),
                     ((.50, .18, z), (.50, -.18, z))):
            batch.pipe(a, b, .008, steel, 6)
    for i in range(6):
        xx = .50+i*.064
        for yy in (-.18, .18):
            batch.pipe((xx, yy, .94), (xx, yy, 1.17), .0038, steel, 5)
    for i in range(6):
        yy = -.18+i*.072
        batch.pipe((.82, yy, .94), (.82, yy, 1.17), .0038, steel, 5)
        batch.pipe((.50, yy, .94), (.82, yy, .94), .0038, steel, 5)
    ca, sa = math.cos(angle), math.sin(angle)
    batch.vertices[start:] = [(x+ca*u-sa*v, y+sa*u+ca*v, z+.055)
                              for u, v, z in batch.vertices[start:]]


def build_details(data, collection, materials, font=None):
    """Build restrained south gate / library / teaching-entry detail groups."""
    steel = material('细节_不锈钢', (.42, .47, .49), .27, .82)
    rubber = material('细节_橡胶', (.017, .021, .023), .85)
    granite = material('细节_灰花岗岩', (.41, .42, .40), .78, noise=.11)
    darkstone = material('细节_深灰石基', (.19, .21, .21), .76, noise=.12)
    earth = material('细节_树池碎石', (.25, .24, .18), .95, noise=.25)
    wood = material('细节_户外木条', (.30, .13, .052), .67, noise=.10)
    red = material('细节_朱红', (.68, .026, .018), .63)
    blue = material('细节_校旗蓝', (.025, .14, .50), .66)
    white = materials['white']
    gold = material('细节_旗星黄', (.98, .67, .02), .63)
    stone_mats = [material('细节_腾飞黄蜡石_'+str(i), color, .88, noise=.12)
                  for i, color in enumerate(((.68, .49, .24), (.76, .58, .32),
                                              (.61, .44, .23), (.71, .53, .29)))]
    stats = {'detail_groups': [], 'bicycles': 0, 'flagpoles': 0, 'bollards': 0,
             'skipped_sites': [], 'note': 'Appearance observed where stated; all ground furniture coordinates and dimensions inferred, not surveyed.'}

    # The road data has two carriageways at x~125 and x~145. This narrow median
    # is clear of both: its stone corresponds to the official entrance photo.
    if _clear(data, 133.4, -670.5, 8.8, 24.0):
        b = Batch()
        b.face([(133.4+4.4*math.cos(i*TAU/64), -670.5+12*math.sin(i*TAU/64), .072)
                for i in range(64)], earth)
        _ellipse_ring(b, (133.4, -670.5), (4.4, 12), .24, .04, .17, granite)
        _tag(b.object('南门_窄中分岛_尺寸定位推断', collection), ENTRANCE_SOURCE,
             'Observed pale ochre Tengfei stone and kerbed planting island. No unlocated motto stone added; planting is supplied separately by landscape.')
        stone=Batch();_natural_stone(stone,133,-676,[stone_mats[1]])
        rock=stone.object('南门_腾飞自然石_照片推断造型',collection)
        bm=bmesh.new();bm.from_mesh(rock.data)
        bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=.0001)
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bm.to_mesh(rock.data);bm.free()
        for face in rock.data.polygons:face.use_smooth=True
        subdiv=rock.modifiers.new('Rounded natural erosion','SUBSURF');subdiv.levels=2;subdiv.render_levels=3
        tex=bpy.data.textures.new('Tengfei weathered surface','CLOUDS');tex.noise_scale=.19;tex.noise_depth=2
        dis=rock.modifiers.new('Weathered stone relief','DISPLACE');dis.texture=tex;dis.strength=.045;dis.mid_level=.5
        bpy.context.view_layer.update()
        evaluated=rock.evaluated_get(bpy.context.evaluated_depsgraph_get())
        bottom=min((evaluated.matrix_world@Vector(corner)).z for corner in evaluated.bound_box)
        rock.location.z+=.07-bottom
        _tag(rock,ENTRANCE_SOURCE,'Observed monument, smoothly eroded stone; exact shape and grain inferred.')
        for text, z in (('腾', 2.7), ('飞', 1.6)):
            ob = text_object('腾飞石_红色刻字_'+text, text, (132.65, -677.252, z+rock.location.z), 1.0, red, collection, font=font)
            if hasattr(ob.data,'extrude'):ob.data.extrude=.008
            _tag(ob, ENTRANCE_SOURCE, 'Observed inscription, recreated as outlined lettering; source text retained as metadata.')
        stats['detail_groups'].append({'id': 'south_entrance_stone', 'center': [133, -676], 'appearance': 'observed', 'placement': 'inferred'})
    else:
        stats['skipped_sites'].append('south_entrance_stone: mapped collision')

    if _clear(data, 166, -675, 12, 4):
        b = Batch()
        b.box((166, -675, .12), (12, 3.8, .24), granite)
        for i, (x, height, cloth) in enumerate(((162, 17.6, blue), (166, 19.1, red), (170, 17.6, white))):
            b.box((x, -675, .30), (1.0, 1.0, .32), darkstone)
            b.cylinder((x, -675, height/2+.35), .065, height, steel, 18, top_radius=.037)
            _sphere(b, (x, -675, height+.36), .11, steel, 12, 6)
            _flag(b, x, -675, height+.24, 3.05, 1.95, cloth, gold if i == 1 else None)
            stats['flagpoles'] += 1
        for x in (155.5, 159.0, 173.5, 177.0):
            b.box((x, -678.4, .36), (.8, .8, .64), granite)
            b.box((x, -678.4, .72), (.94, .94, .15), darkstone)
            b.box((x, -678.4, .81), (.73, .73, .05), earth)
        # Spherical granite bollards: photo-observed type, safe forecourt side.
        for x in (154, 158, 162, 166, 170, 174, 178, 182):
            if _clear(data, x, -681.5, .65, .65):
                b.cylinder((x, -681.5, .10), .29, .14, granite, 18)
                _sphere(b, (x, -681.5, .39), .30, granite)
                stats['bollards'] += 1
        _tag(b.object('南门_三旗杆与球形挡车柱_定位推断', collection), ENTRANCE_SOURCE,
             'Three poles, blue/red/white cloth and stone spheres observed. Exact positions, heights and neutral planter details inferred; university logos omitted because reference is illegible.')
        stats['detail_groups'].append({'id': 'south_entrance_flags', 'center': [166, -675], 'appearance': 'observed', 'placement': 'inferred'})
    else:
        stats['skipped_sites'].append('south_entrance_flags: mapped collision')

    # Editable, restrained library approach furniture. Keep the central lawn open.
    b = Batch()
    library_count = 0
    for x, y in ((128, -127), (128, -84)):
        if _clear(data, x, y, 2.5, 2.5):
            b.box((x, y, .33), (1.42, 1.42, .60), darkstone)
            for dx, dy, sx, sy in ((0, -.76, 1.65, .15), (0, .76, 1.65, .15),
                                   (-.76, 0, .15, 1.65), (.76, 0, .15, 1.65)):
                b.box((x+dx, y+dy, .71), (sx, sy, .20), granite)
            b.box((x, y, .62), (1.35, 1.35, .06), earth)
            library_count += 1
    for x, y in ((126, -132), (126, -79)):
        if _clear(data, x, y, 2.4, 1.1):
            _bench(b, x, y, math.pi/2, steel, wood)
            library_count += 1
    if library_count:
        _tag(b.object('图书馆_台阶两侧石花槽与座椅_推断', collection), LIBRARY_SOURCE,
             'Reference shows planted containers near stair. Exact container design/coordinates and benches are generic inferred furnishing. No vegetation duplicates generated.')
        stats['detail_groups'].append({'id': 'library_approach_furniture', 'count': library_count, 'appearance': 'partly_inferred', 'placement': 'inferred'})

    # An intentionally generic, clearly named guide board; no claim that its
    # typography/design is the actual physical NJUPT campus signage standard.
    for x, y, title, lines in ((153, -661, '仙林校区', '南京邮电大学'),
                               (128, -141, '图书馆', 'LIBRARY')):
        if not _clear(data, x, y, 1.7, .7):
            stats['skipped_sites'].append('guide_board '+title+': mapped collision')
            continue
        b = Batch()
        for dx in (-.64, .64):
            b.box((x+dx, y, 1.15), (.07, .07, 2.30), steel)
        b.box((x, y, 1.84), (1.60, .12, .90), blue)
        b.box((x, y-.071, 1.45), (1.60, .025, .09), gold)
        _tag(b.object('通用导向牌_'+title+'_推断', collection), 'generic_wayfinding',
             'Generic editable aid to campus legibility; not a surveyed sign or replicated brand standard.')
        _tag(text_object('导向牌标题_'+title, title, (x, y-.08, 1.88), .25, white, collection, font=font),
             'generic_wayfinding', 'Inferred generic sign design and position.')
        _tag(text_object('导向牌副题_'+title, lines, (x, y-.08, 1.60), .125, white, collection, font=font),
             'generic_wayfinding', 'Inferred generic sign design and position.')
        stats['detail_groups'].append({'id': 'guide_'+title, 'center': [x, y], 'appearance': 'inferred', 'placement': 'inferred'})

    bike_colors = [material('细节_共享单车_'+str(i), color, .35, .23)
                   for i, color in enumerate(((.015, .35, .63), (.87, .30, .025), (.20, .53, .16)))]
    for key, cx, cy in (('教2南侧', -30, -592.5), ('教3北侧', 30, -434.9)):
        # Seven bikes fit in a 6.7 x 2.0 m paved strip, outside traffic and doors.
        if not _clear(data, cx, cy, 7.5, 2.2, .12):
            stats['skipped_sites'].append(key+' bike bay: mapped collision')
            continue
        b = Batch()
        b.box((cx, cy, .035), (7.5, 2.2, .06), granite)
        for i in range(7):
            xx = cx-2.8+i*.90
            # Painted ends and stainless low hoops identify a tidy parking bay.
            b.box((xx, cy-1.02, .075), (.025, .12, .01), white)
            _bike(b, xx, cy, math.pi/2+(.03 if i % 2 else -.025), bike_colors[i % 3], steel, rubber)
            stats['bicycles'] += 1
        _tag(b.object(key+'_共享单车停车带_推断', collection), 'generic_bicycle_geometry',
             'Bike presence/count/brand/parking layout inferred, not observed in source photos. Full-size frame, wheels, spokes, chain, saddle, mudguard, basket and pedals; batch geometry.')
        stats['detail_groups'].append({'id': 'bicycle_bay_'+key, 'center': [cx, cy], 'bicycles': 7, 'appearance': 'generic', 'placement': 'inferred'})
    return stats
