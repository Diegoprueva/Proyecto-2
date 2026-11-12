# -*- coding: utf-8 -*-
"""
============================================================
ZOOLOGICO NICOLAS BRAVO - MODULO 04 - VEGETACION
============================================================
Genera:
  - PASTO_BASE: capa de pasto procedural sobre la base de 01 (por debajo
    de explanadas y caminos, así que no los tapa).
  - Árboles (latifolia, copa ancha, conífera), arbustos (con y sin flor)
    y mechones de pasto, como instancias de pocas mallas (liviano).

REGLAS DE COLOCACION (nada se coloca...)
  - fuera del contorno de 01 o muy cerca de su borde,
  - encima de superficies de 02 (explanadas) ni a menos de SURFACE_MARGIN,
  - sobre caminos de 03 ni a menos de la holgura de cada especie
    (se mide desde el BORDE real del camino: eje de CAMINO_xxx menos su semiancho),
  - dentro de objetos de colecciones 05_, 06_, 07_, 08_ (si ya existen) ni
    de las zonas de MANUAL_EXCLUSIONS.

ORDEN RECOMENDADO
  01 -> 02 -> 03 -> 08 -> 05 -> 06 -> 07 -> 04   (la vegetación al final, para
  esquivar edificios y recintos). Si ejecutas 04 antes que 05/06, vuelve a
  ejecutar 04 después: es seguro repetirlo (solo reconstruye 04_VEGETACION).

Usa solo la API de datos (sin bpy.ops). Pensado para Blender 3.x/4.x.
Resultado reproducible: cambia SEED para otra distribución.
============================================================
"""

import bpy
import bmesh
import math
import random
from mathutils import Vector, kdtree

# ============================================================
# 1. CONFIGURACION (editar aquí)
# ============================================================
COLLECTION_NAME = "04_VEGETACION"
BASE_COLLECTION = "01_BASE_TERRENO"
BASE_OBJECT_NAME = "BASE_ZOOLOGICO_NICOLAS_BRAVO"
SURFACE_COLLECTION = "02_SUPERFICIES"
ROADS_COLLECTION = "03_CAMINOS"
OBSTACLE_PREFIXES = ("05_", "06_", "07_", "08_")  # colecciones que se esquivan
MAX_OBSTACLE_SIZE = 80.0                     # ignora objetos mayores (vallas perimetrales)

FALLBACK_OUTLINE = [
    (-35, 80), (30, 65), (22, 40), (70, 25), (70, -15), (20, -40),
    (12, -65), (-5, -90), (-75, -88), (-75, -48), (-5, -45), (-5, -5),
    (-65, 0), (-65, 30), (-45, 65),
]
FALLBACK_TOP_Z = 1.5

SEED = 7
MAX_OBJECTS = 4000
PROTOTYPE_VARIANTS = 4        # variantes de forma por especie
TREE_DENSITY = 0.95
TRUNK_SEGMENTS = 8

# --- Pasto base ---
GRASS_OVERLAY = True
GRASS_LIFT = 0.01             # altura sobre la base (menor que explanada y caminos)
PRESERVE_EXISTING_INSTANCES = True

# --- Árboles a lo largo de caminos ---
ROADSIDE_TYPES = ("principal", "secundario")
ROADSIDE_SPACING = 14.0
ROADSIDE_OFFSET = 2.6         # distancia del borde del camino al tronco

# --- Cinturón verde perimetral ---
PERIMETER_SPACING = 9.0
PERIMETER_DEPTH = (2.0, 6.0)  # distancia hacia adentro desde el contorno

# --- Bosquetes ---
GROVE_COUNT = 8
GROVE_RADIUS = (6.0, 10.0)
GROVE_TREE_SPACING = 4.5

# --- Arbustos y pasto ---
SHRUB_ROAD_SPACING = 7.0
SHRUB_ROAD_PROB = 0.55
SHRUB_ROAD_OFFSET = 1.4
SHRUB_FREE_COUNT = 120
TUFT_COUNT = 500

# --- Holguras (m) ---
ROAD_CLEAR_TREE = 1.8
ROAD_CLEAR_SHRUB = 0.9
ROAD_CLEAR_TUFT = 0.6
SURFACE_MARGIN = 2.0
OBSTACLE_MARGIN = 2.5
OUTLINE_MARGIN = 1.5

# Zonas donde NO habrá vegetación: (x_min, y_min, x_max, y_max, "nombre")
MANUAL_EXCLUSIONS = [
    # (10, 10, 20, 18, "RECINTO_LEONES"),
]

# Escalas aleatorias (min, max)
SCALE_TREE = (0.8, 1.25)
SCALE_SHRUB = (0.7, 1.3)
SCALE_TUFT = (0.8, 1.5)

# ============================================================
# 2. MATERIALES SIMPLES (nombre: (color, rugosidad))
# ============================================================
MATERIALES = {
    "Veg_Tronco":     ((0.20, 0.12, 0.07), 0.95),
    "Veg_Follaje_A":  ((0.10, 0.28, 0.07), 0.90),
    "Veg_Follaje_B":  ((0.17, 0.35, 0.09), 0.90),
    "Veg_Follaje_C":  ((0.09, 0.24, 0.10), 0.90),
    "Veg_Conifera":   ((0.04, 0.19, 0.09), 0.90),
    "Veg_Flor":       ((0.85, 0.22, 0.42), 0.60),
    "Veg_Mechon":     ((0.16, 0.34, 0.08), 0.90),
}

WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)


# ============================================================
# 3. GEOMETRIA 2D (funciones puras)
# ============================================================
def point_seg_dist(p, a, b):
    abx, aby = b[0] - a[0], b[1] - a[1]
    l2 = abx * abx + aby * aby
    u = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / l2))
    return math.hypot(p[0] - (a[0] + abx * u), p[1] - (a[1] + aby * u))


def point_in_poly(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def dist_to_poly_edges(p, poly):
    return min(point_seg_dist(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def signed_area(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def perimeter_points(outline, spacing, depth_range, rng):
    """Puntos a lo largo del contorno, desplazados hacia el INTERIOR."""
    area = signed_area(outline)
    pts = []
    n = len(outline)
    for i in range(n):
        a, b = outline[i], outline[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        if area > 0:      # antihorario: interior a la izquierda
            nx, ny = -dy / L, dx / L
        else:             # horario: interior a la derecha
            nx, ny = dy / L, -dx / L
        d = rng.uniform(0, spacing)
        while d < L:
            t = d / L
            depth = rng.uniform(*depth_range)
            pts.append((a[0] + dx * t + nx * depth, a[1] + dy * t + ny * depth))
            d += spacing * rng.uniform(0.8, 1.2)
    return pts


class Placer:
    """Rejilla espacial para evitar que dos plantas se solapen."""

    def __init__(self, cell=4.0):
        self.cell = cell
        self.grid = {}

    def _key(self, x, y):
        return (int(math.floor(x / self.cell)), int(math.floor(y / self.cell)))

    def free(self, x, y, r, factor=0.8):
        cx, cy = self._key(x, y)
        for i in range(cx - 2, cx + 3):
            for j in range(cy - 2, cy + 3):
                for (ox, oy, orad) in self.grid.get((i, j), ()):
                    if math.hypot(x - ox, y - oy) < (r + orad) * factor:
                        return False
        return True

    def add(self, x, y, r):
        self.grid.setdefault(self._key(x, y), []).append((x, y, r))


# ============================================================
# 4. PROTOTIPOS DE VEGETACION (bmesh)
# ============================================================
def _mark(bm, n0, mat):
    bm.faces.ensure_lookup_table()
    for i in range(n0, len(bm.faces)):
        bm.faces[i].material_index = mat


def blob(bm, rng, center, radius, squash=1.0, jitter=0.12, mat=1, subdiv=2):
    n0 = len(bm.faces)
    res = bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=radius)
    vs = res["verts"]
    for v in vs:
        d = v.co.normalized() if v.co.length > 1e-9 else v.co.copy()
        v.co = v.co + d * (rng.uniform(-jitter, jitter) * radius)
        v.co.z *= squash
    bmesh.ops.translate(bm, vec=Vector(center), verts=vs)
    _mark(bm, n0, mat)


def cone(bm, r1, r2, depth, z0, mat, segments=8):
    n0 = len(bm.faces)
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                                radius1=r1, radius2=r2, depth=depth)
    bmesh.ops.translate(bm, vec=Vector((0, 0, z0 + depth / 2.0)), verts=res["verts"])
    _mark(bm, n0, mat)


def tapered_branch(bm, start, end, radius_start, radius_end, mat, segments=7):
    n0 = len(bm.faces)
    start, end = Vector(start), Vector(end)
    direction = end - start
    if direction.length < 1e-6:
        return
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                                radius1=radius_start, radius2=radius_end, depth=direction.length)
    rotation = Vector((0, 0, 1)).rotation_difference(direction.normalized())
    midpoint = (start + end) * 0.5
    for vertex in res["verts"]:
        vertex.co = rotation @ vertex.co + midpoint
    _mark(bm, n0, mat)


def perpendicular_basis(direction):
    helper = Vector((1, 0, 0)) if abs(direction.x) < 0.9 else Vector((0, 1, 0))
    first = direction.cross(helper).normalized()
    return first, direction.cross(first).normalized()


def branch_direction(tangent, angle, azimuth):
    first, second = perpendicular_basis(tangent)
    side = first * math.cos(azimuth) + second * math.sin(azimuth)
    return (tangent * math.cos(angle) + side * math.sin(angle)).normalized()


def interpolate_branch(points, radii, fraction):
    segment_count = len(points) - 1
    scaled = max(0.0, min(1.0, fraction)) * segment_count
    index = min(int(scaled), segment_count - 1)
    weight = scaled - index
    position = points[index].lerp(points[index + 1], weight)
    radius = radii[index] * (1.0 - weight) + radii[index + 1] * weight
    tangent = points[index + 1] - points[index]
    tangent = tangent.normalized() if tangent.length > 1e-9 else Vector((0, 0, 1))
    return position, radius, tangent


def make_branch_path(rng, start, direction, length, radius_start, radius_end, params, level):
    segment_count = max(3, int(length / params["segment_length"]))
    step = length / segment_count
    points = [start.copy()]
    radii = [radius_start]
    position = start.copy()
    tangent = direction.copy()
    tropism = params["tropism"][min(level, len(params["tropism"]) - 1)]

    for index in range(segment_count):
        noise = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
        tangent += noise * params["wobble"]
        tangent.z += tropism
        if tangent.length < 1e-9:
            tangent = Vector((0, 0, 1))
        tangent.normalize()
        position += tangent * step
        points.append(position.copy())
        radii.append(radius_start + (radius_end - radius_start) * (index + 1) / segment_count)

    return points, radii


def add_limb(bm, points, radii, segments):
    if len(points) < 2:
        return
    rings = []
    for index, point in enumerate(points):
        before = points[max(index - 1, 0)]
        after = points[min(index + 1, len(points) - 1)]
        tangent = after - before
        tangent = tangent.normalized() if tangent.length > 1e-9 else Vector((0, 0, 1))
        first, second = perpendicular_basis(tangent)
        ring = []
        for side in range(segments):
            angle = 2.0 * math.pi * side / segments
            offset = first * math.cos(angle) + second * math.sin(angle)
            ring.append(bm.verts.new(point + offset * radii[index]))
        rings.append(ring)

    for index in range(len(rings) - 1):
        for side in range(segments):
            bm.faces.new((rings[index][side], rings[index][(side + 1) % segments],
                          rings[index + 1][(side + 1) % segments], rings[index + 1][side]))


def grow_branch(context, start, direction, length, radius, level):
    params, rng, bm = context["params"], context["rng"], context["bm"]
    radius = max(radius, 0.02)
    end_radius = max(radius * params["taper"], 0.012)
    points, radii = make_branch_path(rng, start, direction, length, radius,
                                     end_radius, params, level)
    if level == 0 and params.get("flare"):
        points.insert(0, start - Vector((0, 0, 0.22)))
        radii.insert(0, radius * 1.55)
        radii[1] = radius * 1.12

    add_limb(bm, points, radii, max(3, TRUNK_SEGMENTS - 2 * level))
    if level in params["leaf_levels"]:
        context["leaf_sites"].append((points, radii))
    if level >= params["levels"]:
        return

    child_count = max(1, int(round(params["children"][level] * TREE_DENSITY *
                                   rng.uniform(0.85, 1.15))))
    starting_fraction = params["child_start"][level]
    azimuth_start = rng.uniform(0, 2.0 * math.pi)
    for child in range(child_count):
        fraction = rng.uniform(starting_fraction, 1.0)
        position, local_radius, tangent = interpolate_branch(points, radii, fraction)
        azimuth = azimuth_start + 2.0 * math.pi * child / child_count + rng.uniform(-0.45, 0.45)
        angle = math.radians(rng.uniform(*params["branch_angle"][level]))
        child_direction = branch_direction(tangent, angle, azimuth)
        if params.get("flatten"):
            child_direction.z *= params["flatten"]
            child_direction.normalize()
        child_length = (length * params["length_decay"][level] * rng.uniform(0.78, 1.08) *
                       (1.0 - 0.3 * (fraction - starting_fraction)))
        grow_branch(context, position, child_direction, child_length,
                    local_radius * params["child_radius"], level + 1)


def add_leaf_cards(context, tint):
    bm, rng, params = context["bm"], context["rng"], context["params"]
    cards = []
    for points, radii in context["leaf_sites"]:
        path_length = sum((points[index + 1] - points[index]).length
                          for index in range(len(points) - 1))
        card_count = max(2, int(params["cards_per_meter"] * path_length * TREE_DENSITY))
        for _ in range(card_count):
            position, _radius, tangent = interpolate_branch(
                points, radii, rng.uniform(params["leaf_start"], 1.0))
            size = params["leaf_size"] * rng.uniform(0.78, 1.22)
            if params["leaf_mode"] == "flat":
                normal = Vector((rng.uniform(-0.4, 0.4), rng.uniform(-0.4, 0.4), 1.0)).normalized()
                axis_u = tangent - normal * tangent.dot(normal)
                axis_u = axis_u.normalized() if axis_u.length > 1e-6 else perpendicular_basis(normal)[0]
                axis_v = normal.cross(axis_u).normalized()
                half_u, half_v = size * 0.8, size * 0.5
                center = position + axis_u * half_u * 0.55 + normal * rng.uniform(-0.04, 0.08)
            else:
                normal = Vector((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1) + 0.6))
                if normal.length < 1e-6:
                    normal = Vector((0, 0, 1))
                normal.normalize()
                basis_u, basis_v = perpendicular_basis(normal)
                angle = rng.uniform(0, 2.0 * math.pi)
                axis_u = basis_u * math.cos(angle) + basis_v * math.sin(angle)
                axis_v = normal.cross(axis_u).normalized()
                half_u = half_v = size * 0.5
                center = position + Vector((rng.uniform(-1, 1), rng.uniform(-1, 1),
                                             rng.uniform(-0.6, 1.0))) * (size * 0.35)
            cards.append((center, axis_u, axis_v, half_u, half_v))

    if not cards:
        return

    crown_center = sum((card[0] for card in cards), Vector((0, 0, 0))) / len(cards)
    crown_radius = max((card[0] - crown_center).length for card in cards) or 1.0
    min_height = min(card[0].z for card in cards)
    height_range = max(card[0].z for card in cards) - min_height or 1.0
    uv_layer = bm.loops.layers.uv.verify()
    if hasattr(bm.loops.layers, "float_color"):
        color_layer = bm.loops.layers.float_color.get("Col") or bm.loops.layers.float_color.new("Col")
    else:
        color_layer = bm.loops.layers.color.get("Col") or bm.loops.layers.color.new("Col")

    uv_corners = ((0, 0), (1, 0), (1, 1), (0, 1))
    for center, axis_u, axis_v, half_u, half_v in cards:
        verts = (bm.verts.new(center - axis_u * half_u - axis_v * half_v),
                 bm.verts.new(center + axis_u * half_u - axis_v * half_v),
                 bm.verts.new(center + axis_u * half_u + axis_v * half_v),
                 bm.verts.new(center - axis_u * half_u + axis_v * half_v))
        face = bm.faces.new(verts)
        face.material_index = 1
        depth = min(1.0, (center - crown_center).length / crown_radius)
        height = (center.z - min_height) / height_range
        shade = (0.42 + 0.58 * depth ** 0.8) * (0.82 + 0.35 * height)
        variation = rng.uniform(0.86, 1.14)
        color = (tint[0] * shade * variation, tint[1] * shade * variation,
                 tint[2] * shade * variation, 1.0)
        for loop, uv in zip(face.loops, uv_corners):
            loop[uv_layer].uv = uv
            loop[color_layer] = color


OAK = dict(levels=3, children=[7, 5, 4], child_start=[0.48, 0.3, 0.3],
           branch_angle=[(35, 60), (30, 55), (30, 55)], length_decay=[0.8, 0.55, 0.55],
           child_radius=0.64, taper=0.45, wobble=0.11, tropism=[0.02, 0.1, 0.12, 0.12],
           segment_length=0.7, leaf_levels=(3,), leaf_start=0.25,
           cards_per_meter=5.0, leaf_size=0.95, leaf_mode="random", flare=True)
WIDE = dict(levels=3, children=[5, 5, 4], child_start=[0.52, 0.3, 0.3],
            branch_angle=[(50, 75), (35, 60), (30, 55)], length_decay=[1.35, 0.6, 0.55],
            child_radius=0.64, taper=0.5, wobble=0.11, tropism=[0.0, 0.05, 0.07, 0.08],
            segment_length=0.7, leaf_levels=(3,), leaf_start=0.25,
            cards_per_meter=5.0, leaf_size=1.1, leaf_mode="random", flare=True)
CONIFER = dict(levels=1, children=[5], child_start=[0.3], branch_angle=[(40, 65)],
               length_decay=[0.45], child_radius=0.6, taper=0.2, wobble=0.045,
               tropism=[-0.06, -0.03], segment_length=0.6, leaf_levels=(0, 1),
               leaf_start=0.1, cards_per_meter=3.0, leaf_size=0.72,
               leaf_mode="flat", flatten=0.4, flare=False)
TREE_TINTS = [(0.2, 0.42, 0.09), (0.16, 0.38, 0.08),
              (0.26, 0.44, 0.07), (0.14, 0.34, 0.1)]
CONIFER_TINT = (0.06, 0.2, 0.09)


def build_tree(rng, params, trunk_length, trunk_radius, tint):
    context = {"bm": bmesh.new(), "rng": rng, "params": params, "leaf_sites": []}
    direction = Vector((rng.uniform(-0.1, 0.1), rng.uniform(-0.1, 0.1), 1.0)).normalized()
    grow_branch(context, Vector((0, 0, 0)), direction, trunk_length, trunk_radius, 0)
    add_leaf_cards(context, tint)
    return context["bm"], ["Veg_Corteza", "Veg_Hoja"]


def build_broad(rng, foliage, wide=False, tint=None):
    tint = tint or TREE_TINTS[0]
    if wide:
        return build_tree(rng, WIDE, rng.uniform(2.2, 2.7), rng.uniform(0.34, 0.42), tint)
    return build_tree(rng, OAK, rng.uniform(3.3, 4.0), rng.uniform(0.28, 0.34), tint)


def build_conifer(rng, tint=CONIFER_TINT):
    context = {"bm": bmesh.new(), "rng": rng, "params": CONIFER, "leaf_sites": []}
    height = rng.uniform(7.0, 8.5)
    radius = rng.uniform(0.26, 0.32)
    direction = Vector((rng.uniform(-0.025, 0.025), rng.uniform(-0.025, 0.025), 1.0)).normalized()
    grow_branch(context, Vector((0, 0, 0)), direction, height, radius, 0)
    branch_count = max(10, int(30 * TREE_DENSITY))
    golden_angle = 2.399963
    trunk_points, trunk_radii = make_branch_path(
        context["rng"], Vector((0, 0, 0)), direction, height, radius, radius * 0.12,
        dict(segment_length=1.0, wobble=0.025, tropism=[0.0]), 0)
    for index in range(branch_count):
        fraction = 0.12 + 0.86 * index / max(1, branch_count - 1)
        position, local_radius, tangent = interpolate_branch(trunk_points, trunk_radii, fraction)
        angle = math.radians(78.0 - 22.0 * fraction + rng.uniform(-5.0, 5.0))
        branch = branch_direction(tangent, angle, index * golden_angle)
        length = (2.1 * (1.0 - fraction) ** 0.85 + 0.32) * rng.uniform(0.86, 1.08)
        grow_branch(context, position, branch, length, local_radius * 0.52, 0)
    add_leaf_cards(context, tint)
    return context["bm"], ["Veg_Corteza", "Veg_Aguja"]


def build_shrub(rng, flowering=False):
    bm = bmesh.new()
    for _ in range(3):
        ang = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(0.0, 0.6)
        blob(bm, rng, (math.cos(ang) * rr, math.sin(ang) * rr, rng.uniform(0.35, 0.6)),
             rng.uniform(0.55, 0.85), squash=0.8, jitter=0.15, mat=1, subdiv=1)
    if flowering:
        for _ in range(8):
            ang = rng.uniform(0, 2 * math.pi)
            rr = rng.uniform(0.2, 0.9)
            blob(bm, rng, (math.cos(ang) * rr, math.sin(ang) * rr, rng.uniform(0.5, 1.0)),
                 0.12, jitter=0.1, mat=2, subdiv=1)
    return bm, ["Veg_Tronco", "Veg_Follaje_B", "Veg_Flor"]


def build_tuft(rng):
    bm = bmesh.new()
    for _ in range(7):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.0, 0.12)
        h = rng.uniform(0.3, 0.55)
        tilt = rng.uniform(0.1, 0.35)
        w = 0.05
        bx, by = math.cos(a) * r, math.sin(a) * r
        px, py = -math.sin(a), math.cos(a)
        v1 = bm.verts.new((bx + px * w, by + py * w, 0.0))
        v2 = bm.verts.new((bx - px * w, by - py * w, 0.0))
        v3 = bm.verts.new((bx + math.cos(a) * tilt * h, by + math.sin(a) * tilt * h, h))
        bm.faces.new((v1, v2, v3))
    return bm, ["Veg_Mechon"]


def bm_to_mesh(name, bm, mat_names, mats, mesh=None):
    mesh = mesh or bpy.data.meshes.new(name)
    mesh.clear_geometry()
    mesh.materials.clear()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()
    for m in mat_names:
        mesh.materials.append(mats[m])
    smooth_surface = mat_names[0] in {"Veg_Tronco", "Veg_Corteza"}
    for p in mesh.polygons:
        p.use_smooth = smooth_surface
    mesh.update()
    return mesh


def make_prototypes(rng, mats):
    P = {k: [] for k in ("latifolia", "copa_ancha", "conifera", "arbusto", "arbusto_flor", "mechon")}
    foliages = ["Veg_Follaje_A", "Veg_Follaje_B", "Veg_Follaje_C"]
    for v in range(PROTOTYPE_VARIANTS):
        tint = TREE_TINTS[v % len(TREE_TINTS)]
        bm, m = build_broad(rng, foliages[v % 3], tint=tint)
        P["latifolia"].append(bm_to_mesh("VEG_Latifolia_%d" % v, bm, m, mats))
        bm, m = build_broad(rng, foliages[(v + 1) % 3], wide=True,
                             tint=TREE_TINTS[(v + 1) % len(TREE_TINTS)])
        P["copa_ancha"].append(bm_to_mesh("VEG_CopaAncha_%d" % v, bm, m, mats))
        bm, m = build_conifer(rng)
        P["conifera"].append(bm_to_mesh("VEG_Conifera_%d" % v, bm, m, mats))
        bm, m = build_shrub(rng, False)
        P["arbusto"].append(bm_to_mesh("VEG_Arbusto_%d" % v, bm, m, mats))
        bm, m = build_shrub(rng, True)
        P["arbusto_flor"].append(bm_to_mesh("VEG_ArbustoFlor_%d" % v, bm, m, mats))
        bm, m = build_tuft(rng)
        P["mechon"].append(bm_to_mesh("VEG_Mechon_%d" % v, bm, m, mats))
    return P


def update_existing_tree_prototypes(mats):
    rng = random.Random(SEED + 101)
    foliages = ["Veg_Follaje_A", "Veg_Follaje_B", "Veg_Follaje_C"]
    updated_instances = 0

    for variant in range(PROTOTYPE_VARIANTS):
        tree_builders = (
            ("VEG_Latifolia_%d" % variant,
             lambda rng=rng, foliage=foliages[variant % 3], tint=TREE_TINTS[variant % len(TREE_TINTS)]:
                 build_broad(rng, foliage, tint=tint)),
            ("VEG_CopaAncha_%d" % variant,
             lambda rng=rng, foliage=foliages[(variant + 1) % 3], tint=TREE_TINTS[(variant + 1) % len(TREE_TINTS)]:
                 build_broad(rng, foliage, wide=True, tint=tint)),
            ("VEG_Conifera_%d" % variant, lambda rng=rng: build_conifer(rng)),
        )
        for mesh_name, builder in tree_builders:
            bm, material_names = builder()
            previous = bpy.data.meshes.get(mesh_name)
            users = ([obj for obj in bpy.data.objects if obj.type == 'MESH' and obj.data is previous]
                     if previous is not None else [])
            bm_to_mesh(mesh_name, bm, material_names, mats, mesh=previous)
            updated_instances += len(users)

    return updated_instances


# ============================================================
# 5. ESCENA: materiales, contorno, caminos, obstáculos
# ============================================================
def simple_material(name, color, rough):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = tuple(color) + (1.0,)
        bsdf.inputs["Roughness"].default_value = rough
    mat.diffuse_color = tuple(color) + (1.0,)
    return mat


def bark_material():
    mat = bpy.data.materials.get("Veg_Corteza") or bpy.data.materials.new("Veg_Corteza")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    links = mat.node_tree.links
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.92
    texcoord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (18.0, 18.0, 3.0)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 4.0
    noise.inputs["Detail"].default_value = 6.0
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.055, 0.035, 0.022, 1.0)
    ramp.color_ramp.elements[1].color = (0.24, 0.16, 0.095, 1.0)
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.7
    bump.inputs["Distance"].default_value = 0.025
    links.new(texcoord.outputs["Object"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], shader.inputs["Base Color"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    mat.diffuse_color = (0.14, 0.09, 0.055, 1.0)
    return mat


def leaf_material(name, needle=False):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    links = mat.node_tree.links
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Roughness"].default_value = 0.72
    texcoord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1.0, 1.65 if not needle else 2.8, 1.0)
    links.new(texcoord.outputs["UV"], mapping.inputs["Vector"])

    distance = nodes.new("ShaderNodeVectorMath")
    distance.operation = 'DISTANCE'
    distance.inputs[1].default_value = (0.5, 0.5, 0.0)
    links.new(mapping.outputs["Vector"], distance.inputs[0])
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 7.0 if not needle else 11.0
    noise.inputs["Detail"].default_value = 3.0
    links.new(texcoord.outputs["UV"], noise.inputs["Vector"])
    noise_amount = nodes.new("ShaderNodeMath")
    noise_amount.operation = 'MULTIPLY'
    noise_amount.inputs[1].default_value = 0.045
    links.new(noise.outputs["Fac"], noise_amount.inputs[0])
    edge = nodes.new("ShaderNodeMath")
    edge.operation = 'ADD'
    links.new(distance.outputs["Value"], edge.inputs[0])
    links.new(noise_amount.outputs["Value"], edge.inputs[1])
    mask = nodes.new("ShaderNodeValToRGB")
    mask.color_ramp.elements[0].position = 0.22
    mask.color_ramp.elements[0].color = (1.0, 1.0, 1.0, 1.0)
    mask.color_ramp.elements[1].position = 0.43
    mask.color_ramp.elements[1].color = (0.0, 0.0, 0.0, 1.0)
    links.new(edge.outputs["Value"], mask.inputs["Fac"])
    links.new(mask.outputs["Color"], shader.inputs["Alpha"])

    color = nodes.new("ShaderNodeAttribute")
    color.attribute_name = "Col"
    links.new(color.outputs["Color"], shader.inputs["Base Color"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    try:
        mat.surface_render_method = 'DITHERED'
    except Exception:
        pass
    mat.use_backface_culling = False
    mat.diffuse_color = (0.07, 0.23, 0.075, 1.0) if needle else (0.16, 0.36, 0.09, 1.0)
    return mat


def grass_material():
    """Pasto procedural: manchas de dos tonos + grano (bump)."""
    name = "Veg_Pasto_Base"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    L = nt.links
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (700, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (420, 0)
    bsdf.inputs["Roughness"].default_value = 0.95
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-900, 0)
    big = nt.nodes.new("ShaderNodeTexNoise")
    big.location = (-650, 150)
    big.inputs["Scale"].default_value = 0.08
    big.inputs["Detail"].default_value = 5.0
    fine = nt.nodes.new("ShaderNodeTexNoise")
    fine.location = (-650, -150)
    fine.inputs["Scale"].default_value = 25.0
    fine.inputs["Detail"].default_value = 8.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.location = (-380, 150)
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = (0.10, 0.25, 0.07, 1.0)
    ramp.color_ramp.elements[1].position = 0.65
    ramp.color_ramp.elements[1].color = (0.22, 0.40, 0.11, 1.0)
    bump = nt.nodes.new("ShaderNodeBump")
    bump.location = (180, -200)
    bump.inputs["Strength"].default_value = 0.5
    bump.inputs["Distance"].default_value = 0.05
    L.new(tc.outputs["Object"], big.inputs["Vector"])
    L.new(tc.outputs["Object"], fine.inputs["Vector"])
    L.new(big.outputs["Fac"], ramp.inputs["Fac"])
    L.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    L.new(fine.outputs["Fac"], bump.inputs["Height"])
    L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    L.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    mat.diffuse_color = (0.16, 0.32, 0.09, 1.0)
    return mat


def get_outline():
    obj = bpy.data.objects.get(BASE_OBJECT_NAME)
    if obj and obj.type == 'MESH':
        nv = len(obj.data.vertices)
        if nv >= 6 and nv % 2 == 0:
            n = nv // 2
            mw = obj.matrix_world
            pts = []
            for v in obj.data.vertices[n:]:
                w = mw @ v.co
                pts.append((w.x, w.y))
            top = max((mw @ v.co).z for v in obj.data.vertices)
            return pts, top, True
    warn("No se encontró el objeto base de 01: se usa contorno y altura de respaldo.")
    return list(FALLBACK_OUTLINE), FALLBACK_TOP_Z, False


def make_ground(top_z):
    """ground(x, y): raycast sobre la base de 01; si falla, usa top_z."""
    obj = bpy.data.objects.get(BASE_OBJECT_NAME)
    if obj is None or obj.type != 'MESH':
        return lambda x, y: top_z
    inv = obj.matrix_world.inverted()
    dloc = (inv.to_3x3() @ Vector((0, 0, -1))).normalized()

    def ground(x, y):
        hit, loc, _n, _i = obj.ray_cast(inv @ Vector((x, y, top_z + 200.0)), dloc)
        return (obj.matrix_world @ loc).z if hit else top_z

    return ground


def collect_surface_polys():
    polys = []
    col = bpy.data.collections.get(SURFACE_COLLECTION)
    if col is None:
        warn("No existe la colección '%s'." % SURFACE_COLLECTION)
        return polys
    for o in col.all_objects:
        if o.type != 'MESH':
            continue
        mw = o.matrix_world
        for f in o.data.polygons:
            if abs(f.normal.z) < 0.5:
                continue
            pts = []
            for i in f.vertices:
                w = mw @ o.data.vertices[i].co
                pts.append((w.x, w.y))
            polys.append(pts)
    return polys


def collect_roads():
    """
    Devuelve ((kdtree, semianchos, semiancho_max), lista de CAMINO_).
    El árbol indexa la LINEA CENTRAL de cada camino; así la distancia al camino
    es (distancia al eje - semiancho) y el interior de caminos anchos queda excluido.
    """
    col = bpy.data.collections.get(ROADS_COLLECTION)
    roads, pts, hws = [], [], []
    if col is not None:
        for o in col.objects:
            if o.type == 'MESH' and o.name.startswith("CAMINO_"):
                roads.append(o)
                hw = float(o.get("ancho", 4.0)) / 2.0
                st = road_stations(o)
                if st is not None:
                    for (cx, cy, _nx, _ny) in st:
                        pts.append((cx, cy))
                        hws.append(hw)
                else:   # perfil desconocido: aproxima con todos los vértices (semiancho 0)
                    mw = o.matrix_world
                    for v in o.data.vertices:
                        w = mw @ v.co
                        pts.append((w.x, w.y))
                        hws.append(0.0)
    if not pts:
        warn("No se encontraron caminos en '%s': la vegetación no esquivará caminos. "
             "Ejecuta 03 antes que 04." % ROADS_COLLECTION)
        return None, roads
    kd = kdtree.KDTree(len(pts))
    for i, (x, y) in enumerate(pts):
        kd.insert((x, y, 0.0), i)
    kd.balance()
    return (kd, hws, max(hws)), roads


def road_free(index, x, y, clear):
    """True si (x, y) está a >= clear metros del BORDE de todos los caminos."""
    if index is None:
        return True
    kd, hws, hmax = index
    for (_co, i, d) in kd.find_range((x, y, 0.0), hmax + clear + 0.1):
        if d < hws[i] + clear + 0.1:
            return False
    return True


def collect_obstacles():
    obs = [(nm, (x0, y0, x1, y1)) for (x0, y0, x1, y1, nm) in MANUAL_EXCLUSIONS]
    for col in bpy.data.collections:
        if col.name.startswith(OBSTACLE_PREFIXES):
            for o in col.all_objects:
                if o.type != 'MESH':
                    continue
                cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
                xs, ys = [c.x for c in cs], [c.y for c in cs]
                if max(max(xs) - min(xs), max(ys) - min(ys)) > MAX_OBSTACLE_SIZE:
                    continue
                obs.append((o.name, (min(xs), min(ys), max(xs), max(ys))))
    return obs


def road_stations(obj):
    """
    Línea central y dirección lateral de un CAMINO_ de 03.
    Supone el perfil de 9 vértices por sección que genera 03_caminos.py:
    vértice 4 = eje, vértices 0 y 8 = faldones derecho e izquierdo.
    """
    verts = obj.data.vertices
    n = len(verts)
    if n % 9 != 0 or n < 18:
        return None
    mw = obj.matrix_world
    out = []
    for i in range(n // 9):
        c = mw @ verts[i * 9 + 4].co
        r = mw @ verts[i * 9].co
        l = mw @ verts[i * 9 + 8].co
        dx, dy = l.x - r.x, l.y - r.y
        ln = math.hypot(dx, dy) or 1.0
        out.append((c.x, c.y, dx / ln, dy / ln))
    return out


def points_along_road(obj, spacing, offset, rng, alternate=True, prob=1.0):
    """Puntos junto al camino, a 'offset' m del borde (a ambos lados, alternando)."""
    st = road_stations(obj)
    if st is None:
        warn("%s: perfil distinto de 9 vértices por sección; se omite vegetación lateral." % obj.name)
        return []
    hw = float(obj.get("ancho", 4.0)) / 2.0
    pts = []
    cum = [0.0]
    for a, b in zip(st, st[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = cum[-1]
    d = rng.uniform(spacing * 0.4, spacing)
    side = 1 if rng.random() < 0.5 else -1
    j = 0
    while d < total - 3.0:
        while j < len(cum) - 2 and cum[j + 1] < d:
            j += 1
        seg = (cum[j + 1] - cum[j]) or 1.0
        u = (d - cum[j]) / seg
        cx = st[j][0] + (st[j + 1][0] - st[j][0]) * u
        cy = st[j][1] + (st[j + 1][1] - st[j][1]) * u
        nx = st[j][2] + (st[j + 1][2] - st[j][2]) * u
        ny = st[j][3] + (st[j + 1][3] - st[j][3]) * u
        ln = math.hypot(nx, ny) or 1.0
        nx, ny = nx / ln, ny / ln
        if rng.random() <= prob:
            s = side if alternate else (1 if rng.random() < 0.5 else -1)
            pts.append((cx + nx * s * (hw + offset), cy + ny * s * (hw + offset)))
        if alternate:
            side = -side
        d += spacing * rng.uniform(0.85, 1.15)
    return pts


# ============================================================
# 6. COLECCION
# ============================================================
def clear_collection(col):
    metas = set()
    for o in list(col.objects):
        if o.data is not None:
            metas.add(o.data)
        bpy.data.objects.remove(o, do_unlink=True)
    for d in metas:
        if d.users == 0 and isinstance(d, bpy.types.Mesh):
            bpy.data.meshes.remove(d)
    for m in list(bpy.data.meshes):          # prototipos huérfanos de ejecuciones previas
        if m.name.startswith("VEG_") and m.users == 0:
            bpy.data.meshes.remove(m)


def create_grass_overlay(col, outline, top_z):
    pts = list(outline)
    if signed_area(pts) < 0:
        pts.reverse()                          # normal hacia arriba
    verts = [(x, y, top_z + GRASS_LIFT) for x, y in pts]
    mesh = bpy.data.meshes.new("VEG_PastoBase_Mesh")
    mesh.from_pydata(verts, [], [tuple(range(len(verts)))])
    mesh.materials.append(grass_material())
    mesh.update()
    obj = col.objects.get("PASTO_BASE")
    if obj is None:
        obj = bpy.data.objects.new("PASTO_BASE", mesh)
        col.objects.link(obj)
    else:
        old_mesh = obj.data
        obj.data = mesh
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
    return obj


# ============================================================
# 7. PROGRAMA PRINCIPAL
# ============================================================
def main():
    scene = bpy.context.scene
    rng = random.Random(SEED)

    col = bpy.data.collections.get(COLLECTION_NAME)
    if col is None:
        col = bpy.data.collections.new(COLLECTION_NAME)
    linked_collections = {child.name for child in scene.collection.children_recursive}
    linked_collections.update(child.name for child in scene.collection.children)
    if col.name not in linked_collections:
        scene.collection.children.link(col)

    outline, top_z, from_scene = get_outline()
    existing_instances = [o for o in col.objects
                          if o.name.startswith(("ARBOL_", "ARBUSTO_", "PASTO_Mechon_"))]
    if existing_instances and PRESERVE_EXISTING_INSTANCES:
        tree_mats = {
            "Veg_Corteza": bark_material(),
            "Veg_Hoja": leaf_material("Veg_Hoja"),
            "Veg_Aguja": leaf_material("Veg_Aguja", needle=True),
        }
        updated_trees = update_existing_tree_prototypes(tree_mats)
        if GRASS_OVERLAY:
            create_grass_overlay(col, outline, top_z)
        print("VEGETACION PRESERVADA: %d instancias; se actualizaron las mallas de %d arboles y PASTO_BASE."
              % (len(existing_instances), updated_trees))
        return

    clear_collection(col)

    mats = {n: simple_material(n, c, r) for n, (c, r) in MATERIALES.items()}
    mats["Veg_Corteza"] = bark_material()
    mats["Veg_Hoja"] = leaf_material("Veg_Hoja")
    mats["Veg_Aguja"] = leaf_material("Veg_Aguja", needle=True)
    ground = make_ground(top_z)
    surfaces = collect_surface_polys()
    road_index, roads = collect_roads()
    obstacles = collect_obstacles()
    protos = make_prototypes(rng, mats)

    if GRASS_OVERLAY:
        create_grass_overlay(col, outline, top_z)

    placer = Placer()
    counts = {"arboles": 0, "arbustos": 0, "mechones": 0}
    total = [0]

    def valid(x, y, road_clear, edge_margin=OUTLINE_MARGIN, surf_margin=SURFACE_MARGIN,
              obst_margin=OBSTACLE_MARGIN):
        if not point_in_poly(x, y, outline) or dist_to_poly_edges((x, y), outline) < edge_margin:
            return False
        for pl in surfaces:
            if point_in_poly(x, y, pl) or dist_to_poly_edges((x, y), pl) < surf_margin:
                return False
        if not road_free(road_index, x, y, road_clear):
            return False
        for _nm, (x0, y0, x1, y1) in obstacles:
            if x0 - obst_margin <= x <= x1 + obst_margin and y0 - obst_margin <= y <= y1 + obst_margin:
                return False
        return True

    def put(kind, x, y, radius, scale_range, key, name):
        if total[0] >= MAX_OBJECTS:
            return False
        if not placer.free(x, y, radius):
            return False
        mesh = rng.choice(protos[key])
        s = rng.uniform(*scale_range)
        o = bpy.data.objects.new("%s_%03d" % (name, total[0]), mesh)
        o.location = (x, y, ground(x, y))
        o.rotation_euler = (0.0, 0.0, rng.uniform(0, 2 * math.pi))
        sx = s * rng.uniform(0.9, 1.1)
        o.scale = (sx, sx, s)
        col.objects.link(o)
        placer.add(x, y, radius * s)
        total[0] += 1
        counts[kind] += 1
        return True

    def tree(x, y, key, clear=ROAD_CLEAR_TREE):
        radius = 2.4 if key == "copa_ancha" else 2.0
        if valid(x, y, clear):
            return put("arboles", x, y, radius, SCALE_TREE, key,
                       {"latifolia": "ARBOL_Latifolia", "copa_ancha": "ARBOL_CopaAncha",
                        "conifera": "ARBOL_Conifera"}[key])
        return False

    # 1) Árboles a lo largo de caminos principales y secundarios
    for r in roads:
        if r.get("tipo") in ROADSIDE_TYPES:
            for (x, y) in points_along_road(r, ROADSIDE_SPACING, ROADSIDE_OFFSET, rng):
                tree(x, y, rng.choice(["latifolia", "latifolia", "copa_ancha"]))

    # 2) Cinturón verde perimetral
    for (x, y) in perimeter_points(outline, PERIMETER_SPACING, PERIMETER_DEPTH, rng):
        tree(x, y, rng.choice(["conifera", "latifolia", "conifera", "copa_ancha"]))

    # 3) Bosquetes en zonas abiertas
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    made, tries = 0, 0
    while made < GROVE_COUNT and tries < 600:
        tries += 1
        cx, cy = rng.uniform(min(xs), max(xs)), rng.uniform(min(ys), max(ys))
        if not valid(cx, cy, 7.0, edge_margin=6.0, surf_margin=8.0, obst_margin=8.0):
            continue
        rad = rng.uniform(*GROVE_RADIUS)
        n_try = int(rad * rad / (GROVE_TREE_SPACING * 1.2))
        for _ in range(n_try * 3):
            a, d = rng.uniform(0, 2 * math.pi), rad * math.sqrt(rng.random())
            tree(cx + math.cos(a) * d, cy + math.sin(a) * d,
                 rng.choice(["latifolia", "copa_ancha", "conifera"]))
        made += 1

    # 4) Arbustos junto a todos los caminos (con algo de flor)
    for r in roads:
        for (x, y) in points_along_road(r, SHRUB_ROAD_SPACING, SHRUB_ROAD_OFFSET, rng,
                                        alternate=False, prob=SHRUB_ROAD_PROB):
            if valid(x, y, ROAD_CLEAR_SHRUB, surf_margin=1.0, obst_margin=1.0):
                key = "arbusto_flor" if rng.random() < 0.3 else "arbusto"
                put("arbustos", x, y, 0.9, SCALE_SHRUB, key, "ARBUSTO")

    # 5) Arbustos sueltos
    placed, tries = 0, 0
    while placed < SHRUB_FREE_COUNT and tries < SHRUB_FREE_COUNT * 15:
        tries += 1
        x, y = rng.uniform(min(xs), max(xs)), rng.uniform(min(ys), max(ys))
        if valid(x, y, ROAD_CLEAR_SHRUB + 0.5, surf_margin=1.5, obst_margin=1.5):
            key = "arbusto_flor" if rng.random() < 0.25 else "arbusto"
            if put("arbustos", x, y, 0.9, SCALE_SHRUB, key, "ARBUSTO"):
                placed += 1

    # 6) Mechones de pasto
    placed, tries = 0, 0
    while placed < TUFT_COUNT and tries < TUFT_COUNT * 10:
        tries += 1
        x, y = rng.uniform(min(xs), max(xs)), rng.uniform(min(ys), max(ys))
        if valid(x, y, ROAD_CLEAR_TUFT, surf_margin=0.5, obst_margin=0.5, edge_margin=0.5):
            if put("mechones", x, y, 0.15, SCALE_TUFT, "mechon", "PASTO_Mechon"):
                placed += 1

    # ---- Informe ----
    print("=" * 60)
    print("VEGETACION CREADA: %d árboles, %d arbustos, %d mechones de pasto"
          % (counts["arboles"], counts["arbustos"], counts["mechones"]))
    print("Contorno de: %s | superficies 02: %d | caminos 03: %d | obstáculos 05-08: %d"
          % ("escena" if from_scene else "respaldo", len(surfaces), len(roads), len(obstacles)))
    if total[0] >= MAX_OBJECTS:
        print("AVISO: se alcanzó MAX_OBJECTS (%d)." % MAX_OBJECTS)
    if not obstacles:
        print("NOTA: aún no hay objetos en 05_/06_/07_/08_; vuelve a ejecutar 04 cuando existan.")
    for w in WARNINGS:
        print("AVISO: " + w)
    print("=" * 60)


main()