# -*- coding: utf-8 -*-
"""
============================================================
ZOOLOGICO NICOLAS BRAVO - MODULO 07 - DETALLES
============================================================
Mobiliario y señalización, como mallas 3D procedurales:
  - Bancas, lámparas y botes de basura repartidos a lo largo de los caminos
    de 03, según el TIPO de camino (principal / secundario / sendero).
  - Letreros con el nombre de cada recinto de 06, junto a su puerta.
  - Señales manuales (mapa de entrada, información, etc.) ancladas a un camino.

COMO SE UBICAN
  Todo se reparte por distancia a lo largo de cada CAMINO_xxx de 03 y se
  coloca a un lado, mirando al camino. Cada pieza se valida: dentro del
  contorno de 01, no sobre otro camino, estructuras (05), recintos (06) ni
  cerca perimetral (08), y a distancia mínima de piezas del mismo tipo. Si un sitio
  no es válido se prueba el lado opuesto; si tampoco, se omite esa pieza.

IMPORTANTE
  Las separaciones (REGLAS) y las señales (SENALES) son una PROPUESTA
  PRELIMINAR. Ajusta cantidades y textos a lo que exista en el zoológico.

ORDEN: 01 -> 02 -> 03 -> 08 -> 05 -> 06 -> 07 -> 04. Es seguro repetir este
script: solo reconstruye 07_DETALLES. Si vuelves a correr 03, corre
después 05, 06 y 07 (03 puede avisar de "cruces" con estas piezas; para
evitarlo agrega "07_" a IGNORE_COLLECTION_PREFIXES en 03).
Solo API de datos (sin bpy.ops). Pensado para Blender 3.x/4.x.
============================================================
"""

import bpy
import bmesh
import math
from mathutils import Vector, kdtree

# ============================================================
# 1. CONFIGURACION
# ============================================================
COLLECTION_NAME = "07_DETALLES"
BASE_OBJECT_NAME = "BASE_ZOOLOGICO_NICOLAS_BRAVO"
TERRAIN_COLLECTIONS = ["01_BASE_TERRENO", "02_SUPERFICIES"]
ROADS_COLLECTION = "03_CAMINOS"
RECINTOS_COLLECTION = "06_RECINTOS"
OBSTACLE_PREFIXES = ("05_", "06_", "08_")

FALLBACK_OUTLINE = [
    (-35, 80), (30, 65), (22, 40), (70, 25), (70, -15), (20, -40),
    (12, -65), (-5, -90), (-75, -88), (-75, -48), (-5, -45), (-5, -5),
    (-65, 0), (-65, 30), (-45, 65),
]
FALLBACK_GROUND_Z = 1.5
RAY_START_Z = 500.0

OUTLINE_MARGIN = 0.6
ROAD_CLEAR = 0.3          # holgura al borde de cualquier camino (m)
OBSTACLE_MARGIN = 0.5
MAX_OBSTACLE_SIZE = 80.0
END_MARGIN = 6.0          # no poner piezas a menos de X m de los extremos del camino
SHOW_SIGN_TEXT = True     # texto 3D en los letreros

# Cada cuántos metros va cada pieza, por tipo de camino (0 = ninguna)
REGLAS = {
    "principal":  dict(bancas=20.0, lamparas=16.0, botes=40.0),
    "secundario": dict(bancas=28.0, lamparas=22.0, botes=56.0),
    "sendero":    dict(bancas=35.0, lamparas=0.0,  botes=0.0),
}
# Ajustes por camino concreto (sobrescriben a REGLAS). Ejemplo:
# "ACCESO_EXPLANADA_NORTE": dict(lamparas=10.0)
OVERRIDES = {}
EXCLUIR_CAMINOS = ()      # nombres de caminos sin mobiliario

OFFSET_BANCA = 0.95       # distancia del borde del camino al centro de la pieza
OFFSET_LAMPARA = 0.70
OFFSET_BOTE = 0.80
MIN_SEP = dict(banca=6.0, lampara=6.0, bote=6.0, senal=3.0)

# Señales manuales ancladas a un camino: t = fracción del recorrido (0..1).
SENALES = [
    dict(name="MAPA_ENTRADA", texto="MAPA DEL ZOOLOGICO", w=2.4, h=1.4,
         camino="AV_PRINCIPAL", t=0.07, lado=-1, distancia=1.5),
    dict(name="INFO_EXPLANADA", texto="EXPLANADA", w=1.6, h=0.6,
         camino="ACCESO_EXPLANADA_NORTE", t=0.90, lado=+1, distancia=1.0),
    dict(name="INFO_SUR", texto="ZONA SUR", w=1.6, h=0.6,
         camino="RAMAL_SUROESTE", t=0.10, lado=+1, distancia=1.0),
    dict(name="INFO_ESTE", texto="ZONA ESTE", w=1.6, h=0.6,
         camino="RAMAL_ESTE", t=0.10, lado=+1, distancia=1.0),
]

# ============================================================
# 2. MATERIALES: nombre: (color, rugosidad, emision)
# ============================================================
MATERIALES = {
    "Det_Madera":  ((0.30, 0.17, 0.08), 0.80, 0.0),
    "Det_Concreto": ((0.60, 0.58, 0.54), 0.90, 0.0),
    "Det_Metal":   ((0.10, 0.11, 0.12), 0.45, 0.0),
    "Det_Luz":     ((1.00, 0.90, 0.60), 0.30, 3.0),
    "Det_Bote":    ((0.12, 0.35, 0.18), 0.60, 0.0),
    "Det_Panel":   ((0.08, 0.30, 0.18), 0.70, 0.0),
    "Det_Texto":   ((0.95, 0.95, 0.92), 0.60, 0.0),
}

WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)


# ============================================================
# 3. GEOMETRIA / LECTURA DE LA ESCENA
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


def rot(x, y, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return x * c - y * s, x * s + y * c


def road_stations(obj):
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


class RoadInfo:
    def __init__(self, name, stations, hw, tipo):
        self.name, self.st, self.hw, self.tipo = name, stations, hw, tipo
        self.cum = [0.0]
        for a, b in zip(stations, stations[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.total = self.cum[-1]

    def pose(self, s):
        s = max(0.0, min(self.total, s))
        j = 0
        while j < len(self.cum) - 2 and self.cum[j + 1] < s:
            j += 1
        seg = (self.cum[j + 1] - self.cum[j]) or 1.0
        u = (s - self.cum[j]) / seg
        a, b = self.st[j], self.st[j + 1]
        x = a[0] + (b[0] - a[0]) * u
        y = a[1] + (b[1] - a[1]) * u
        nx = a[2] + (b[2] - a[2]) * u
        ny = a[3] + (b[3] - a[3]) * u
        ln = math.hypot(nx, ny) or 1.0
        return x, y, nx / ln, ny / ln


def collect_roads():
    col = bpy.data.collections.get(ROADS_COLLECTION)
    infos, pts, hws = {}, [], []
    if col is not None:
        for o in col.objects:
            if o.type == 'MESH' and o.name.startswith("CAMINO_"):
                hw = float(o.get("ancho", 4.0)) / 2.0
                st = road_stations(o)
                if st is None:
                    warn("%s: perfil distinto de 9 vértices; se ignora para el mobiliario." % o.name)
                    continue
                infos[o.name[len("CAMINO_"):]] = RoadInfo(o.name, st, hw, o.get("tipo", "secundario"))
                for (cx, cy, _a, _b) in st:
                    pts.append((cx, cy))
                    hws.append(hw)
    if not pts:
        warn("No hay caminos en '%s'. Ejecuta 03 antes que 07." % ROADS_COLLECTION)
        return None, infos
    kd = kdtree.KDTree(len(pts))
    for i, (x, y) in enumerate(pts):
        kd.insert((x, y, 0.0), i)
    kd.balance()
    return (kd, hws, max(hws)), infos


def road_free(index, x, y, clear):
    if index is None:
        return True
    kd, hws, hmax = index
    for (_co, i, d) in kd.find_range((x, y, 0.0), hmax + clear + 0.1):
        if d < hws[i] + clear + 0.1:
            return False
    return True


def get_outline():
    obj = bpy.data.objects.get(BASE_OBJECT_NAME)
    if obj and obj.type == 'MESH':
        nv = len(obj.data.vertices)
        if nv >= 6 and nv % 2 == 0:
            mw = obj.matrix_world
            return [((mw @ v.co).x, (mw @ v.co).y) for v in obj.data.vertices[nv // 2:]]
    warn("No se encontró el objeto base de 01: se usa el contorno de respaldo.")
    return list(FALLBACK_OUTLINE)


def make_ground():
    objs = []
    for cname in TERRAIN_COLLECTIONS:
        col = bpy.data.collections.get(cname)
        if col is None:
            warn("Colección de suelo no encontrada: '%s'." % cname)
            continue
        objs.extend(o for o in col.all_objects if o.type == 'MESH')
    data = []
    for o in objs:
        inv = o.matrix_world.inverted()
        data.append((o, inv, (inv.to_3x3() @ Vector((0, 0, -1))).normalized()))

    def ground(x, y):
        best = None
        for o, inv, dloc in data:
            hit, loc, _n, _i = o.ray_cast(inv @ Vector((x, y, RAY_START_Z)), dloc)
            if hit:
                z = (o.matrix_world @ loc).z
                if best is None or z > best:
                    best = z
        return best if best is not None else FALLBACK_GROUND_Z

    return ground


def collect_obstacles():
    obs = []
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


def collect_gates():
    """Puertas de recintos (propiedades que guarda el módulo 06)."""
    out = []
    col = bpy.data.collections.get(RECINTOS_COLLECTION)
    if col is None:
        warn("No hay colección '%s': no se crean letreros de recintos." % RECINTOS_COLLECTION)
        return out
    for o in col.objects:
        if "puerta_x" in o.keys():
            out.append(dict(name=o.name[len("REC_"):], rotulo=str(o.get("rotulo", o.name)),
                            x=float(o["puerta_x"]), y=float(o["puerta_y"]),
                            yaw=float(o["yaw"]), gate_w=float(o.get("ancho_puerta", 2.2))))
    return out


def simple_material(name, color, rough, emit):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = tuple(color) + (1.0,)
        bsdf.inputs["Roughness"].default_value = rough
        if emit > 0:
            for key, val in (("Emission Color", tuple(color) + (1.0,)), ("Emission", tuple(color) + (1.0,))):
                if key in bsdf.inputs:
                    bsdf.inputs[key].default_value = val
                    break
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = emit
    mat.diffuse_color = tuple(color) + (1.0,)
    return mat


def clear_collection(col):
    metas = set()
    for o in list(col.objects):
        if o.data is not None:
            metas.add(o.data)
        bpy.data.objects.remove(o, do_unlink=True)
    for d in metas:
        if d.users == 0:
            if isinstance(d, bpy.types.Mesh):
                bpy.data.meshes.remove(d)
            elif isinstance(d, bpy.types.Curve):
                bpy.data.curves.remove(d)


# ============================================================
# 4. MODELADO (bmesh). Local: centro (0, 0), suelo z = 0, FRENTE hacia +Y.
# ============================================================
class Slots:
    def __init__(self):
        self.names = []

    def idx(self, name):
        if name not in self.names:
            self.names.append(name)
        return self.names.index(name)


def box(bm, x0, y0, z0, x1, y1, z1, mat):
    v = [bm.verts.new(p) for p in ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))]
    for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([v[i] for i in f]).material_index = mat


def cone(bm, px, py, z0, r1, r2, depth, mat, segments=8):
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                                radius1=r1, radius2=r2, depth=depth)
    bmesh.ops.translate(bm, vec=Vector((px, py, z0 + depth / 2.0)), verts=res["verts"])
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = mat


def build_banca(S):
    bm = bmesh.new()
    wood, conc = S.idx("Det_Madera"), S.idx("Det_Concreto")
    L = 1.7
    for sx in (-1, 1):                                              # patas de concreto
        box(bm, sx * (L / 2 - 0.15) - 0.07, -0.25, -0.1, sx * (L / 2 - 0.15) + 0.07, 0.25, 0.45, conc)
    box(bm, -L / 2, -0.25, 0.45, L / 2, 0.25, 0.52, wood)           # asiento
    box(bm, -L / 2, -0.27, 0.60, L / 2, -0.22, 0.95, wood)          # respaldo (atrás = -Y)
    for sx in (-1, 1):
        box(bm, sx * (L / 2 - 0.15) - 0.04, -0.27, 0.52, sx * (L / 2 - 0.15) + 0.04, -0.22, 0.95, conc)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def build_lampara(S):
    bm = bmesh.new()
    metal, luz, conc = S.idx("Det_Metal"), S.idx("Det_Luz"), S.idx("Det_Concreto")
    cone(bm, 0, 0, -0.2, 0.28, 0.22, 0.5, conc, 8)                  # base
    cone(bm, 0, 0, 0.3, 0.07, 0.05, 3.7, metal, 8)                  # poste
    box(bm, -0.05, 0.0, 3.85, 0.05, 0.7, 3.93, metal)               # brazo hacia el camino (+Y)
    box(bm, -0.2, 0.5, 3.70, 0.2, 0.9, 3.85, luz)                   # luminaria
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def build_bote(S):
    bm = bmesh.new()
    body, metal = S.idx("Det_Bote"), S.idx("Det_Metal")
    cone(bm, 0, 0, 0.0, 0.26, 0.30, 0.85, body, 10)
    cone(bm, 0, 0, 0.85, 0.32, 0.30, 0.08, metal, 10)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def build_senal(S, w, h):
    bm = bmesh.new()
    metal, panel = S.idx("Det_Metal"), S.idx("Det_Panel")
    top = 0.9 + h + 0.15
    for sx in (-1, 1):
        box(bm, sx * (w / 2 - 0.1) - 0.04, -0.04, -0.2, sx * (w / 2 - 0.1) + 0.04, 0.04, top, metal)
    box(bm, -w / 2, -0.03, 0.9, w / 2, 0.03, 0.9 + h, panel)        # panel (frente +Y)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def bm_to_object(name, bm, S, mats, col, loc, yaw, props):
    mesh = bpy.data.meshes.new("MALLA_" + name)
    bm.to_mesh(mesh)
    bm.free()
    for m in S.names:
        mesh.materials.append(mats[m])
    for p in mesh.polygons:
        p.use_smooth = False
    mesh.update()
    obj = bpy.data.objects.new("DET_" + name, mesh)
    obj.location = loc
    obj.rotation_euler = (0.0, 0.0, yaw)
    for k, v in props.items():
        obj[k] = v
    col.objects.link(obj)
    return obj


def add_text(name, texto, x, y, z, yaw, w, h, mat, col):
    """Texto 3D de frente al +Y local del panel."""
    cu = bpy.data.curves.new("TXT_" + name, 'FONT')
    cu.body = texto
    cu.align_x = 'CENTER'
    cu.align_y = 'CENTER'
    cu.extrude = 0.004
    # tamaño: que quepa en el ancho y en el alto del panel
    cu.size = max(0.08, min(h * 0.55, (w - 0.2) / max(4.0, len(texto) * 0.62)))
    cu.materials.append(mat)
    obj = bpy.data.objects.new("TXT_" + name, cu)
    dx, dy = rot(0.0, 0.05, yaw)
    obj.location = (x + dx, y + dy, z)
    obj.rotation_euler = (math.pi / 2.0, 0.0, yaw + math.pi)
    col.objects.link(obj)


# ============================================================
# 5. COLOCACION
# ============================================================
class Placer:
    def __init__(self, outline, road_index, obstacles, ground, col, mats):
        self.outline, self.road_index, self.obstacles = outline, road_index, obstacles
        self.ground, self.col, self.mats = ground, col, mats
        self.pts = {k: [] for k in MIN_SEP}
        self.count = {k: 0 for k in MIN_SEP}

    def valid(self, kind, x, y):
        if not point_in_poly(x, y, self.outline) or dist_to_poly_edges((x, y), self.outline) < OUTLINE_MARGIN:
            return False
        if not road_free(self.road_index, x, y, ROAD_CLEAR):
            return False
        for _nm, (x0, y0, x1, y1) in self.obstacles:
            if x0 - OBSTACLE_MARGIN <= x <= x1 + OBSTACLE_MARGIN and \
                    y0 - OBSTACLE_MARGIN <= y <= y1 + OBSTACLE_MARGIN:
                return False
        for (px, py) in self.pts[kind]:
            if math.hypot(px - x, py - y) < MIN_SEP[kind]:
                return False
        return True

    def put(self, kind, builder, label, x, y, yaw, props=None):
        S = Slots()
        bm = builder(S)
        z = self.ground(x, y)
        self.count[kind] += 1
        nm = "%s_%03d" % (label, self.count[kind])
        bm_to_object(nm, bm, S, self.mats, self.col, (x, y, z), yaw, dict(props or {}, tipo=kind))
        self.pts[kind].append((x, y))
        return nm, z


def scatter_along(road, kind, builder, label, spacing, offset, placer, start_shift=0.0):
    """Reparte piezas cada 'spacing' m a lo largo del camino, alternando lados."""
    if spacing <= 0:
        return 0
    placed = 0
    s = END_MARGIN + start_shift
    side = 1
    while s < road.total - END_MARGIN:
        x, y, nx, ny = road.pose(s)
        for sd in (side, -side):
            off = road.hw + offset
            px, py = x + nx * sd * off, y + ny * sd * off
            if placer.valid(kind, px, py):
                dirx, diry = -nx * sd, -ny * sd                       # hacia el camino
                placer.put(kind, builder, label, px, py, math.atan2(-dirx, diry),
                           {"camino": road.name})
                placed += 1
                break
        side = -side
        s += spacing
    return placed


# ============================================================
# 6. PROGRAMA PRINCIPAL
# ============================================================
def main():
    scene = bpy.context.scene
    col = bpy.data.collections.get(COLLECTION_NAME)
    if col is None:
        col = bpy.data.collections.new(COLLECTION_NAME)
    else:
        clear_collection(col)
    linked = {c.name for c in scene.collection.children_recursive}
    linked.update(c.name for c in scene.collection.children)
    if col.name not in linked:
        scene.collection.children.link(col)

    mats = {n: simple_material(n, c, r, e) for n, (c, r, e) in MATERIALES.items()}
    outline = get_outline()
    ground = make_ground()
    road_index, roads = collect_roads()
    obstacles = collect_obstacles()
    gates = collect_gates()
    placer = Placer(outline, road_index, obstacles, ground, col, mats)
    report = []

    # --- Bancas, lámparas y botes a lo largo de los caminos ---
    for rname, road in roads.items():
        if rname in EXCLUIR_CAMINOS:
            continue
        rules = dict(REGLAS.get(road.tipo, REGLAS["secundario"]))
        rules.update(OVERRIDES.get(rname, {}))
        nb = scatter_along(road, "banca", build_banca, "BANCA", rules.get("bancas", 0),
                           OFFSET_BANCA, placer, start_shift=3.0)
        nl = scatter_along(road, "lampara", build_lampara, "LAMPARA", rules.get("lamparas", 0),
                           OFFSET_LAMPARA, placer, start_shift=0.0)
        nt = scatter_along(road, "bote", build_bote, "BOTE", rules.get("botes", 0),
                           OFFSET_BOTE, placer, start_shift=6.0)
        report.append("%-24s %-10s bancas %2d | lámparas %2d | botes %2d" % (rname, road.tipo, nb, nl, nt))

    # --- Letreros de recintos (junto a la puerta) ---
    ns = 0
    mat_text = mats["Det_Texto"]
    for g in gates:
        w, h = 1.4, 0.55
        yaw = g["yaw"]
        lat = g["gate_w"] / 2.0 + 0.9
        placed_ok = False
        for sd in (1, -1):
            ox, oy = rot(sd * lat, 1.2, yaw)                          # al lado de la puerta, hacia afuera
            x, y = g["x"] + ox, g["y"] + oy
            # el letrero va pegado al recinto: solo se exige estar dentro del contorno y fuera de caminos
            if point_in_poly(x, y, outline) and road_free(road_index, x, y, ROAD_CLEAR):
                nm, z = placer.put("senal", lambda S, w=w, h=h: build_senal(S, w, h),
                                   "LETRERO_" + g["name"], x, y, yaw, {"recinto": g["name"]})
                if SHOW_SIGN_TEXT:
                    add_text(nm, g["rotulo"], x, y, z + 0.9 + h / 2.0, yaw, w, h, mat_text, col)
                ns += 1
                placed_ok = True
                break
        if not placed_ok:
            warn("Letrero de %s omitido: no hay sitio libre junto a la puerta." % g["name"])
    report.append("Letreros de recintos: %d de %d" % (ns, len(gates)))

    # --- Señales manuales ---
    nm_ok = 0
    for sp in SENALES:
        road = roads.get(sp["camino"])
        if road is None:
            warn("%s: no existe el camino '%s'." % (sp["name"], sp["camino"]))
            continue
        done = False
        for ds in (0, 2, -2, 4, -4, 6, -6):
            for sd in (sp["lado"], -sp["lado"]):
                s = max(1.0, min(road.total - 1.0, sp["t"] * road.total + ds))
                x, y, nx, ny = road.pose(s)
                off = road.hw + sp["distancia"] + sp["h"] * 0.0
                px, py = x + nx * sd * off, y + ny * sd * off
                if placer.valid("senal", px, py):
                    yaw = math.atan2(nx * sd, -ny * sd)               # frente hacia el camino
                    w, h = sp["w"], sp["h"]
                    nm, z = placer.put("senal", lambda S, w=w, h=h: build_senal(S, w, h),
                                       sp["name"], px, py, yaw, {"camino": road.name})
                    if SHOW_SIGN_TEXT:
                        add_text(nm, sp["texto"], px, py, z + 0.9 + h / 2.0, yaw, w, h, mat_text, col)
                    nm_ok += 1
                    done = True
                    break
            if done:
                break
        if not done:
            warn("%s: omitida, no hay sitio válido cerca de t=%.2f en %s." % (sp["name"], sp["t"], sp["camino"]))
    report.append("Señales manuales: %d de %d" % (nm_ok, len(SENALES)))

    print("=" * 62)
    print("DETALLES: bancas %d | lámparas %d | botes %d | señales/letreros %d"
          % (placer.count["banca"], placer.count["lampara"], placer.count["bote"], placer.count["senal"]))
    for r in report:
        print("  " + r)
    print("Caminos leídos: %d | recintos con puerta: %d | obstáculos 05/06/08: %d"
          % (len(roads), len(gates), len(obstacles)))
    for w_ in WARNINGS:
        print("AVISO: " + w_)
    print("RECORDATORIO: separaciones y señales son preliminares.")
    print("=" * 62)


main()