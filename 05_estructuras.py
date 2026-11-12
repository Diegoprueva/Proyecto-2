# -*- coding: utf-8 -*-
"""
============================================================
ZOOLOGICO NICOLAS BRAVO - MODULO 05 - ESTRUCTURAS
============================================================
Edificios y construcciones de apoyo, como mallas 3D procedurales:
  - "casa": edificio con zócalo, techo (dos aguas / cuatro aguas / plano),
            puerta y ventanas.
  - "kiosco": pabellón abierto con columnas y techo cónico.
  - "portico": entrada con losa sobre columnas y letrero (cruza un camino).

COMO SE UBICAN
  Cada estructura se ANCLA a un camino real de 03 (CAMINO_xxx):
  fracción de recorrido (t), lado, y distancia al borde. Así se adapta si
  cambias los caminos. También se admite:
      pos=(x, y)            posición absoluta
      explanada=(dx, dy)    desplazamiento desde el centro de la explanada de 02
  Si el sitio pedido no es válido, el script PRUEBA desplazamientos y el lado
  opuesto (solo para estructuras ancladas) y avisa. Si no encuentra un sitio
  válido, OMITE la estructura (nunca la deja sobre un camino).

REGLAS (una estructura NO se coloca...)
  - fuera del contorno de 01 (salvo las marcadas en explanada),
  - sobre la explanada de 02 (salvo las marcadas en explanada),
  - sobre caminos de 03,
  - sobre otra estructura (separación STRUCT_GAP) ni sobre objetos de 06_/07_/08_.

IMPORTANTE
  Posiciones, tipos y tamaños de ESTRUCTURAS son una PROPUESTA PRELIMINAR:
  no hay fotos aéreas ni plano con el que confirmarlos. Cámbialos por los
  edificios reales (nombre, tamaño, ubicación).

ORDEN: 01 -> 02 -> 03 -> 08 -> 05 -> 06 -> 07 -> 04. Es seguro repetir este
script: solo reconstruye 05_ESTRUCTURAS.
Usa solo la API de datos (sin bpy.ops). Pensado para Blender 3.x/4.x.
============================================================
"""

import bpy
import bmesh
import math
from mathutils import Vector

# ============================================================
# 1. CONFIGURACION
# ============================================================
COLLECTION_NAME = "05_ESTRUCTURAS"
BASE_OBJECT_NAME = "BASE_ZOOLOGICO_NICOLAS_BRAVO"
TERRAIN_COLLECTIONS = ["01_BASE_TERRENO", "02_SUPERFICIES"]
SURFACE_COLLECTION = "02_SUPERFICIES"
ROADS_COLLECTION = "03_CAMINOS"
OBSTACLE_PREFIXES = ("06_", "07_", "08_")  # recintos, detalles y barda perimetral

FALLBACK_OUTLINE = [
    (-35, 80), (30, 65), (22, 40), (70, 25), (70, -15), (20, -40),
    (12, -65), (-5, -90), (-75, -88), (-75, -48), (-5, -45), (-5, -5),
    (-65, 0), (-65, 30), (-45, 65),
]
FALLBACK_GROUND_Z = 1.5
RAY_START_Z = 500.0

GLOBAL_SCALE = 1.0       # multiplica las dimensiones de TODAS las estructuras
PRESERVE_EXISTING_STRUCTURES = True
ROAD_CLEAR = 1.0         # holgura mínima al borde de un camino (m)
OUTLINE_MARGIN = 1.0     # holgura al contorno de 01
SURFACE_MARGIN = 1.0     # holgura a explanadas de 02
STRUCT_GAP = 1.0         # separación mínima entre estructuras
OBSTACLE_MARGIN = 2.0
MAX_OBSTACLE_SIZE = 80.0

# Variaciones que se prueban si el sitio ideal no es válido (solo estructuras ancladas)
TRY_EXTRA_DISTANCE = (0.0, 1.0, 2.0, 3.0, 4.0, 6.0)             # m más lejos del camino
TRY_SHIFT_ALONG = (0, 2, -2, 4, -4, 6, -6, 8, -8, 12, -12)      # m a lo largo del camino

# ============================================================
# 2. MATERIALES (nombre: (color, rugosidad))
# ============================================================
MATERIALES = {
    "Estr_Muro_Crema":   ((0.80, 0.74, 0.60), 0.85),
    "Estr_Muro_Blanco":  ((0.86, 0.85, 0.82), 0.85),
    "Estr_Muro_Ocre":    ((0.72, 0.55, 0.30), 0.85),
    "Estr_Zocalo":       ((0.35, 0.33, 0.30), 0.90),
    "Estr_Techo_Teja":   ((0.48, 0.18, 0.10), 0.80),
    "Estr_Techo_Lamina": ((0.40, 0.42, 0.44), 0.55),
    "Estr_Losa":         ((0.55, 0.54, 0.52), 0.90),
    "Estr_Vidrio":       ((0.05, 0.12, 0.18), 0.10),
    "Estr_Madera":       ((0.25, 0.14, 0.07), 0.80),
    "Estr_Columna":      ((0.62, 0.60, 0.56), 0.85),
    "Estr_Marco":        ((0.68, 0.64, 0.56), 0.82),
}

# ============================================================
# 3. ESTRUCTURAS (PROPUESTA PRELIMINAR - NO CONFIRMADA)
# ============================================================
# Campos comunes: name, tipo ("casa" | "kiosco" | "portico")
# casa   : w (ancho a lo largo del camino), d (fondo), h (altura de muros),
#          techo ("dos_aguas" | "cuatro_aguas" | "plano"), muro, cubierta,
#          ventanas (n en fachada), puerta (True/False)
# kiosco : r (radio), h (altura de columnas), cubierta
# portico: d (fondo), h (altura libre), libre (m de cada lado del camino
#          donde van las columnas)
# Ubicación (una de):
#   ancla=dict(camino="AV_PRINCIPAL", t=0.2, lado=+1, distancia=6.0)
#       lado +1 = izquierda según el sentido del camino, -1 = derecha
#   cruza=dict(camino="AV_PRINCIPAL", t=0.05)       (solo portico)
#   explanada=(dx, dy)  [con en_explanada=True]
#   pos=(x, y), yaw=grados
ESTRUCTURAS = [
    dict(name="ENTRADA_PORTICO", tipo="portico", d=3.0, h=4.6, libre=5.6,
         cruza=dict(camino="AV_PRINCIPAL", t=0.05)),     # acceso por CONFIRMAR

    dict(name="TAQUILLA_A", tipo="casa", w=2.6, d=2.6, h=2.8, techo="plano",
         servicio="TAQUILLA",
         muro="Estr_Muro_Blanco", ventanas=1,
         ancla=dict(camino="AV_PRINCIPAL", t=0.05, lado=+1, distancia=1.5)),
    dict(name="TAQUILLA_B", tipo="casa", w=2.6, d=2.6, h=2.8, techo="plano",
         servicio="TAQUILLA",
         muro="Estr_Muro_Blanco", ventanas=1,
         ancla=dict(camino="AV_PRINCIPAL", t=0.05, lado=-1, distancia=1.5)),

    dict(name="TIENDA", tipo="casa", w=7.0, d=5.0, h=3.0, techo="dos_aguas",
         servicio="TIENDA",
         muro="Estr_Muro_Ocre", cubierta="Estr_Techo_Teja", ventanas=2,
         ancla=dict(camino="AV_PRINCIPAL", t=0.09, lado=-1, distancia=4.0)),

    dict(name="ADMINISTRACION", tipo="casa", w=12.0, d=7.0, h=3.4, techo="dos_aguas",
         servicio="ADMINISTRACION",
         muro="Estr_Muro_Crema", cubierta="Estr_Techo_Teja", ventanas=3,
         ancla=dict(camino="AV_PRINCIPAL", t=0.20, lado=+1, distancia=6.0)),

    dict(name="SANITARIOS_NORTE", tipo="casa", w=8.0, d=4.0, h=3.0, techo="plano",
         servicio="SANITARIOS",
         muro="Estr_Muro_Blanco", ventanas=2,
         ancla=dict(camino="ANILLO_NOROESTE", t=0.45, lado=+1, distancia=4.0)),

    dict(name="CAFETERIA", tipo="casa", w=10.0, d=8.0, h=3.5, techo="cuatro_aguas",
         servicio="CAFETERIA",
         muro="Estr_Muro_Crema", cubierta="Estr_Techo_Teja", ventanas=3,
         ancla=dict(camino="AV_PRINCIPAL", t=0.60, lado=+1, distancia=8.0)),

    dict(name="KIOSCO_ESTE", tipo="kiosco", r=3.0, h=2.8,
         cubierta="Estr_Techo_Teja",
         ancla=dict(camino="RAMAL_ESTE", t=0.55, lado=+1, distancia=5.0)),

    dict(name="MIRADOR_ESTE", tipo="kiosco", r=3.5, h=2.8,
         cubierta="Estr_Techo_Lamina",
         ancla=dict(camino="RAMAL_ESTE_RETORNO", t=0.40, lado=+1, distancia=5.0)),

    dict(name="PERGOLA_EXPLANADA", tipo="kiosco", r=4.0, h=3.0,
         cubierta="Estr_Techo_Lamina", en_explanada=True, explanada=(0.0, 0.0)),

    dict(name="VETERINARIA", tipo="casa", w=10.0, d=6.0, h=3.2, techo="plano",
         servicio="VETERINARIA",
         muro="Estr_Muro_Blanco", ventanas=3,
         ancla=dict(camino="RAMAL_SUROESTE", t=0.85, lado=-1, distancia=4.0)),

    dict(name="SANITARIOS_SUR", tipo="casa", w=7.0, d=4.0, h=3.0, techo="plano",
         servicio="SANITARIOS",
         muro="Estr_Muro_Blanco", ventanas=2,
         ancla=dict(camino="SENDERO_SUR", t=0.50, lado=+1, distancia=3.0)),
]

WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)


# ============================================================
# 4. GEOMETRIA 2D (funciones puras)
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


def poly_area(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def rot(x, y, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return x * c - y * s, x * s + y * c


def rect_poly(cx, cy, w, d, yaw, grow=0.0):
    hw, hd = w / 2.0 + grow, d / 2.0 + grow
    out = []
    for lx, ly in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
        rx, ry = rot(lx, ly, yaw)
        out.append((cx + rx, cy + ry))
    return out


def rect_samples(cx, cy, w, d, yaw, step=1.2):
    nx = max(2, int(w / step) + 1)
    ny = max(2, int(d / step) + 1)
    pts = []
    for i in range(nx):
        for j in range(ny):
            lx = -w / 2.0 + w * i / (nx - 1)
            ly = -d / 2.0 + d * j / (ny - 1)
            rx, ry = rot(lx, ly, yaw)
            pts.append((cx + rx, cy + ry))
    return pts


def rects_overlap(a, b, gap):
    """a, b = (cx, cy, w, d, yaw). Comprobación por muestreo (con separación 'gap')."""
    pb = rect_poly(b[0], b[1], b[2], b[3], b[4], gap)
    for (x, y) in rect_samples(*a):
        if point_in_poly(x, y, pb):
            return True
    pa = rect_poly(a[0], a[1], a[2], a[3], a[4], gap)
    for (x, y) in rect_samples(*b):
        if point_in_poly(x, y, pa):
            return True
    return False


# ============================================================
# 5. CAMINOS (lectura de 03)
# ============================================================
def road_stations(obj):
    """
    Línea central y dirección lateral de un CAMINO_ de 03 (perfil de 9 vértices
    por sección: 4 = eje, 0 y 8 = faldones derecho e izquierdo).
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


class RoadInfo:
    def __init__(self, name, stations, hw):
        self.name, self.st, self.hw = name, stations, hw
        self.cum = [0.0]
        for a, b in zip(stations, stations[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.total = self.cum[-1]

    def pose(self, s):
        """(x, y, nx, ny) a distancia s del inicio; (nx, ny) = normal izquierda."""
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
    """Devuelve (índice para consultas, dict nombre -> RoadInfo)."""
    from mathutils import kdtree
    col = bpy.data.collections.get(ROADS_COLLECTION)
    infos, pts, hws = {}, [], []
    if col is not None:
        for o in col.objects:
            if o.type == 'MESH' and o.name.startswith("CAMINO_"):
                hw = float(o.get("ancho", 4.0)) / 2.0
                st = road_stations(o)
                if st is None:
                    warn("%s: perfil distinto de 9 vértices; se usa solo como obstáculo aproximado." % o.name)
                    mw = o.matrix_world
                    for v in o.data.vertices:
                        w = mw @ v.co
                        pts.append((w.x, w.y))
                        hws.append(0.0)
                    continue
                infos[o.name[len("CAMINO_"):]] = RoadInfo(o.name, st, hw)
                for (cx, cy, _a, _b) in st:
                    pts.append((cx, cy))
                    hws.append(hw)
    if not pts:
        warn("No hay caminos en '%s'. Ejecuta 03 antes que 05." % ROADS_COLLECTION)
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


# ============================================================
# 6. ESCENA: contorno, suelo, superficies, obstáculos, materiales
# ============================================================
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
    """ground(x, y): altura más alta bajo (x, y) en las colecciones de suelo."""
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


def collect_surface_polys():
    polys = []
    col = bpy.data.collections.get(SURFACE_COLLECTION)
    if col is None:
        return polys
    for o in col.all_objects:
        if o.type != 'MESH':
            continue
        mw = o.matrix_world
        for f in o.data.polygons:
            if abs(f.normal.z) < 0.5:
                continue
            polys.append([((mw @ o.data.vertices[i].co).x, (mw @ o.data.vertices[i].co).y)
                          for i in f.vertices])
    return polys


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


def simple_material(name, color, rough):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = tuple(color) + (1.0,)
        bsdf.inputs["Roughness"].default_value = rough
    mat.diffuse_color = tuple(color) + (1.0,)
    return mat


def clear_collection(col):
    metas = set()
    for o in list(col.objects):
        if o.data is not None:
            metas.add(o.data)
        bpy.data.objects.remove(o, do_unlink=True)
    for d in metas:
        if d.users == 0 and isinstance(d, bpy.types.Mesh):
            bpy.data.meshes.remove(d)


# ============================================================
# 7. MODELADO (bmesh). Coordenadas locales: centro de la huella en (0, 0),
#    suelo en z = 0, FRENTE (puerta) hacia +Y.
# ============================================================
class Slots:
    """Asigna un índice de material a cada nombre usado en una malla."""

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


def facade_window(bm, center_x, face_y, side, z0, z1, width, m_glass, m_frame):
    frame = 0.08
    depth = 0.08
    inner = width - frame * 2.0
    outer_y0, outer_y1 = sorted((face_y, face_y + side * depth))
    pane_y0, pane_y1 = sorted((face_y, face_y + side * 0.04))
    box(bm, center_x - inner / 2.0, pane_y0, z0, center_x + inner / 2.0, pane_y1, z1, m_glass)
    box(bm, center_x - width / 2.0, outer_y0, z0 - 0.05,
        center_x - inner / 2.0, outer_y1, z1 + 0.05, m_frame)
    box(bm, center_x + inner / 2.0, outer_y0, z0 - 0.05,
        center_x + width / 2.0, outer_y1, z1 + 0.05, m_frame)
    box(bm, center_x - inner / 2.0, outer_y0, z1 - frame,
        center_x + inner / 2.0, outer_y1, z1 + 0.05, m_frame)
    box(bm, center_x - inner / 2.0, outer_y0, z0 - 0.10,
        center_x + inner / 2.0, outer_y1, z0 - 0.02, m_frame)


def side_window(bm, face_x, center_y, side, z0, z1, width, m_glass, m_frame):
    frame = 0.08
    depth = 0.08
    inner = width - frame * 2.0
    outer_x0, outer_x1 = sorted((face_x, face_x + side * depth))
    pane_x0, pane_x1 = sorted((face_x, face_x + side * 0.04))
    box(bm, pane_x0, center_y - inner / 2.0, z0, pane_x1, center_y + inner / 2.0, z1, m_glass)
    box(bm, outer_x0, center_y - width / 2.0, z0 - 0.05,
        outer_x1, center_y - inner / 2.0, z1 + 0.05, m_frame)
    box(bm, outer_x0, center_y + inner / 2.0, z0 - 0.05,
        outer_x1, center_y + width / 2.0, z1 + 0.05, m_frame)
    box(bm, outer_x0, center_y - inner / 2.0, z1 - frame,
        outer_x1, center_y + inner / 2.0, z1 + 0.05, m_frame)
    box(bm, outer_x0, center_y - inner / 2.0, z0 - 0.10,
        outer_x1, center_y + inner / 2.0, z0 - 0.02, m_frame)


def circular_ring(bm, cx, cy, z0, z1, outer_radius, inner_radius, mat, segments=32):
    outer_bottom, outer_top, inner_bottom, inner_top = [], [], [], []
    for index in range(segments):
        angle = 2.0 * math.pi * index / segments
        cosine, sine = math.cos(angle), math.sin(angle)
        outer_bottom.append(bm.verts.new((cx + outer_radius * cosine, cy + outer_radius * sine, z0)))
        outer_top.append(bm.verts.new((cx + outer_radius * cosine, cy + outer_radius * sine, z1)))
        inner_bottom.append(bm.verts.new((cx + inner_radius * cosine, cy + inner_radius * sine, z0)))
        inner_top.append(bm.verts.new((cx + inner_radius * cosine, cy + inner_radius * sine, z1)))

    for index in range(segments):
        following = (index + 1) % segments
        for face in ((outer_bottom[index], outer_bottom[following], outer_top[following], outer_top[index]),
                     (inner_bottom[following], inner_bottom[index], inner_top[index], inner_top[following]),
                     (outer_top[index], outer_top[following], inner_top[following], inner_top[index]),
                     (outer_bottom[following], outer_bottom[index], inner_bottom[index], inner_bottom[following])):
            bm.faces.new(face).material_index = mat


def frustum(bm, bx, by, tx, ty, z0, z1, mat):
    """Tronco de pirámide (techo a cuatro aguas)."""
    v = [bm.verts.new(p) for p in ((-bx, -by, z0), (bx, -by, z0), (bx, by, z0), (-bx, by, z0),
                                   (-tx, -ty, z1), (tx, -ty, z1), (tx, ty, z1), (-tx, ty, z1))]
    for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([v[i] for i in f]).material_index = mat


def gable(bm, x0, x1, ya, yb, z0, z1, mat):
    """Prisma triangular (techo a dos aguas, cumbrera a lo largo de X)."""
    ym = (ya + yb) / 2.0
    v = [bm.verts.new(p) for p in ((x0, ya, z0), (x0, yb, z0), (x0, ym, z1),
                                   (x1, ya, z0), (x1, yb, z0), (x1, ym, z1))]
    for f in ((0, 3, 4, 1), (0, 2, 5, 3), (1, 4, 5, 2)):
        bm.faces.new([v[i] for i in f]).material_index = mat
    bm.faces.new((v[0], v[1], v[2])).material_index = mat
    bm.faces.new((v[3], v[5], v[4])).material_index = mat


def cylinder(bm, px, py, z0, r1, r2, depth, mat, segments=8):
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                                radius1=r1, radius2=r2, depth=depth)
    bmesh.ops.translate(bm, vec=Vector((px, py, z0 + depth / 2.0)), verts=res["verts"])
    bm.faces.ensure_lookup_table()
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = mat


def build_casa(spec, S):
    k = GLOBAL_SCALE
    w, d, h = spec["w"] * k, spec["d"] * k, spec["h"] * k
    bm = bmesh.new()
    m_wall = S.idx(spec.get("muro", "Estr_Muro_Crema"))
    m_base = S.idx("Estr_Zocalo")
    m_roof = S.idx(spec.get("cubierta", "Estr_Techo_Lamina"))
    m_slab = S.idx("Estr_Losa")
    m_glass = S.idx("Estr_Vidrio")
    m_door = S.idx("Estr_Madera")
    m_frame = S.idx("Estr_Marco")

    # Muros y zócalo (bajan 0.4 m bajo el piso para ocultar desniveles)
    box(bm, -w / 2, -d / 2, 0.15, w / 2, d / 2, h, m_wall)
    box(bm, -w / 2 - 0.04, -d / 2 - 0.04, -0.4, w / 2 + 0.04, d / 2 + 0.04, 0.6, m_base)

    # Techo
    tipo = spec.get("techo", "plano")
    o = 0.5
    if tipo == "dos_aguas":
        gable(bm, -w / 2 - o, w / 2 + o, -d / 2 - o, d / 2 + o, h, h + d * 0.30, m_roof)
    elif tipo == "cuatro_aguas":
        rh = 1.6
        frustum(bm, w / 2 + o, d / 2 + o, max(0.4, w / 2 + o - rh * 1.4),
                max(0.4, d / 2 + o - rh * 1.4), h, h + rh, m_roof)
    else:
        box(bm, -w / 2 - 0.3, -d / 2 - 0.3, h, w / 2 + 0.3, d / 2 + 0.3, h + 0.25, m_slab)

    # Puerta (frente +Y) y ventanas
    door = spec.get("puerta", True)
    wz0 = max(1.0, h * 0.35)
    wz1 = min(h - 0.4, wz0 + 1.2)
    if door:
        door_top = min(2.2, h - 0.3)
        face_y = d / 2
        box(bm, -0.55, face_y, 0.15, 0.55, face_y + 0.05, door_top, m_door)
        box(bm, -0.68, face_y, 0.12, -0.55, face_y + 0.09, door_top + 0.08, m_frame)
        box(bm, 0.55, face_y, 0.12, 0.68, face_y + 0.09, door_top + 0.08, m_frame)
        box(bm, -0.68, face_y, door_top, 0.68, face_y + 0.09, door_top + 0.13, m_frame)
    n = int(spec.get("ventanas", max(1, int((w - 2) / 3))))
    if wz1 > wz0 + 0.3:
        for i in range(n):
            x = -w / 2 + (i + 0.5) * w / n
            if not (door and abs(x) < 1.2):
                facade_window(bm, x, d / 2, 1, wz0, wz1, 1.2, m_glass, m_frame)
            facade_window(bm, x, -d / 2, -1, wz0, wz1, 1.2, m_glass, m_frame)
        if d >= 4.0:
            side_window(bm, w / 2, 0.0, 1, wz0, wz1, 1.2, m_glass, m_frame)
            side_window(bm, -w / 2, 0.0, -1, wz0, wz1, 1.2, m_glass, m_frame)

    if tipo == "dos_aguas":
        for side in (-1, 1):
            y0, y1 = sorted((side * (d / 2 + o), side * (d / 2 + o - 0.12)))
            box(bm, -w / 2 - o, y0, h - 0.14, w / 2 + o, y1, h + 0.02, m_roof)
    return bm, (w, d)


def build_kiosco(spec, S):
    k = GLOBAL_SCALE
    R, h = spec["r"] * k, spec.get("h", 2.8) * k
    bm = bmesh.new()
    m_base = S.idx("Estr_Zocalo")
    m_col = S.idx("Estr_Columna")
    m_roof = S.idx(spec.get("cubierta", "Estr_Techo_Lamina"))
    m_trim = S.idx("Estr_Marco")
    cylinder(bm, 0, 0, -0.4, R, R, 0.55, m_base, segments=16)            # piso
    n = 8
    for i in range(n):
        a = 2 * math.pi * i / n
        px, py = math.cos(a) * (R - 0.35), math.sin(a) * (R - 0.35)
        cylinder(bm, px, py, 0.15, 0.21, 0.16, 0.22, m_base, segments=12)
        cylinder(bm, px, py, 0.28, 0.14, 0.12, h - 0.28, m_col)
        cylinder(bm, px, py, h - 0.28, 0.17, 0.2, 0.20, m_trim, segments=12)
    circular_ring(bm, 0, 0, h - 0.12, h, R + 0.6, R + 0.38, m_roof)
    cylinder(bm, 0, 0, h, R + 0.6, 0.12, 1.5, m_roof, segments=16)       # techo cónico
    return bm, (2 * R + 1.2, 2 * R + 1.2)


def build_portico(spec, S, W):
    d, h = spec.get("d", 3.0) * GLOBAL_SCALE, spec.get("h", 4.6) * GLOBAL_SCALE
    bm = bmesh.new()
    m_col = S.idx("Estr_Columna")
    m_slab = S.idx("Estr_Losa")
    m_sign = S.idx("Estr_Muro_Blanco")
    m_trim = S.idx("Estr_Marco")
    for sx in (-1, 1):
        for sy in (-1, 1):
            cx, cy = sx * (W / 2 - 0.4), sy * (d / 2 - 0.25)
            box(bm, cx - 0.3, cy - 0.3, -0.4, cx + 0.3, cy + 0.3, h, m_col)
            box(bm, cx - 0.4, cy - 0.4, -0.4, cx + 0.4, cy + 0.4, 0.05, m_slab)
            box(bm, cx - 0.36, cy - 0.36, h - 0.24, cx + 0.36, cy + 0.36, h, m_trim)
    box(bm, -W / 2, -d / 2, h, W / 2, d / 2, h + 0.4, m_slab)
    box(bm, -W / 2 + 0.5, d / 2 - 0.2, h + 0.4, W / 2 - 0.5, d / 2, h + 1.5, m_sign)   # letrero
    box(bm, -W / 2 + 0.38, d / 2 - 0.24, h + 0.35, -W / 2 + 0.5, d / 2 + 0.04, h + 1.55, m_trim)
    box(bm, W / 2 - 0.5, d / 2 - 0.24, h + 0.35, W / 2 - 0.38, d / 2 + 0.04, h + 1.55, m_trim)
    box(bm, -W / 2 + 0.38, d / 2 - 0.24, h + 0.35, W / 2 - 0.38, d / 2 + 0.04, h + 0.48, m_trim)
    box(bm, -W / 2 + 0.38, d / 2 - 0.24, h + 1.42, W / 2 - 0.38, d / 2 + 0.04, h + 1.55, m_trim)
    return bm, (W, d)


def bm_to_object(name, bm, S, mats, col, loc, yaw, props):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    mesh = bpy.data.meshes.new("MALLA_" + name)
    bm.to_mesh(mesh)
    bm.free()
    for m in S.names:
        mesh.materials.append(mats[m])
    for p in mesh.polygons:
        p.use_smooth = False
    mesh.update()
    obj = bpy.data.objects.new("EST_" + name, mesh)
    obj.location = loc
    obj.rotation_euler = (0.0, 0.0, yaw)
    for k, v in props.items():
        obj[k] = v
    col.objects.link(obj)
    return obj


def replace_object_geometry(obj, bm, S, mats):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    mesh = bpy.data.meshes.new("MALLA_" + obj.name + "_Actualizada")
    bm.to_mesh(mesh)
    bm.free()
    for material_name in S.names:
        mesh.materials.append(mats[material_name])
    for polygon in mesh.polygons:
        polygon.use_smooth = False
    mesh.update()

    previous = obj.data
    obj.data = mesh
    if previous is not None and previous.users == 0:
        bpy.data.meshes.remove(previous)


def update_existing_geometry(col, mats):
    updated = 0
    for spec in ESTRUCTURAS:
        obj = col.objects.get("EST_" + spec["name"])
        if obj is None or obj.type != 'MESH':
            continue

        slots = Slots()
        if spec["tipo"] == "casa":
            bm, _size = build_casa(spec, slots)
        elif spec["tipo"] == "kiosco":
            bm, _size = build_kiosco(spec, slots)
        elif spec["tipo"] == "portico":
            local_x = [vertex.co.x for vertex in obj.data.vertices]
            if not local_x:
                continue
            width = max(local_x) - min(local_x)
            bm, _size = build_portico(spec, slots, width)
        else:
            continue

        replace_object_geometry(obj, bm, slots, mats)
        obj["tipo"] = spec["tipo"]
        obj["preliminar"] = True
        if spec.get("servicio"):
            service_metadata = structure_service_metadata(spec)
            for key, value in service_metadata.items():
                obj[key] = value
        elif "servicio" in obj:
            del obj["servicio"]
            for key in ("servicio_ancho", "servicio_fondo", "servicio_altura"):
                if key in obj:
                    del obj[key]
        updated += 1
    return updated


def structure_service_metadata(spec):
    """Guarda la fachada y dimensiones para que 07 coloque placas en servicios."""
    scale = GLOBAL_SCALE
    return {
        "servicio": spec["servicio"],
        "servicio_ancho": float(spec["w"]) * scale,
        "servicio_fondo": float(spec["d"]) * scale,
        "servicio_altura": float(spec["h"]) * scale,
    }


# ============================================================
# 8. UBICACION
# ============================================================
def spec_size(spec):
    """(w, d) de la huella principal, en metros ya escalados."""
    k = GLOBAL_SCALE
    if spec["tipo"] == "kiosco":
        return (2 * spec["r"] * k + 1.2, 2 * spec["r"] * k + 1.2)
    if spec["tipo"] == "portico":
        return (0.0, spec.get("d", 3.0) * k)
    return (spec["w"] * k, spec["d"] * k)


def footprints(spec, cx, cy, yaw, portico_w=0.0):
    """Lista de rectángulos (cx, cy, w, d, yaw) que ocupa la estructura en el suelo."""
    if spec["tipo"] != "portico":
        w, d = spec_size(spec)
        return [(cx, cy, w, d, yaw)]
    d = spec.get("d", 3.0) * GLOBAL_SCALE
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            lx, ly = sx * (portico_w / 2 - 0.4), sy * (d / 2 - 0.25)
            rx, ry = rot(lx, ly, yaw)
            out.append((cx + rx, cy + ry, 0.6, 0.6, yaw))
    return out


def candidates(spec, roads, surfaces):
    """Genera (cx, cy, yaw, portico_w, descripcion) en orden de preferencia."""
    if "cruza" in spec:
        c = spec["cruza"]
        info = roads.get(c["camino"])
        if info is None:
            warn("%s: no existe el camino '%s'." % (spec["name"], c["camino"]))
            return
        W = 2 * (info.hw + spec.get("libre", 5.6)) + 0.8
        for ds in (0, 3, -3, 6, -6):
            x, y, nx, ny = info.pose(c["t"] * info.total + ds)
            yield x, y, math.atan2(ny, nx), W, "desplazado %+d m" % ds
    elif "ancla" in spec:
        a = spec["ancla"]
        info = roads.get(a["camino"])
        if info is None:
            warn("%s: no existe el camino '%s'." % (spec["name"], a["camino"]))
            return
        w, d = spec_size(spec)
        for dd in TRY_EXTRA_DISTANCE:
            for ds in TRY_SHIFT_ALONG:
                for side in (a["lado"], -a["lado"]):
                    s = max(2.0, min(info.total - 2.0, a["t"] * info.total + ds))
                    x, y, nx, ny = info.pose(s)
                    off = info.hw + a["distancia"] + dd + d / 2.0
                    bx, by = x + nx * side * off, y + ny * side * off
                    dirx, diry = -nx * side, -ny * side       # hacia el camino
                    desc = "lado %+d, %+d m a lo largo, +%.0f m al fondo" % (side, ds, dd)
                    yield bx, by, math.atan2(-dirx, diry), 0.0, desc
    elif "explanada" in spec:
        if not surfaces:
            warn("%s: no hay explanadas en 02." % spec["name"])
            return
        poly = max(surfaces, key=poly_area)
        gx = sum(p[0] for p in poly) / len(poly)
        gy = sum(p[1] for p in poly) / len(poly)
        dx, dy = spec["explanada"]
        yield gx + dx, gy + dy, math.radians(spec.get("yaw", 0.0)), 0.0, "centro de explanada"
    elif "pos" in spec:
        yield spec["pos"][0], spec["pos"][1], math.radians(spec.get("yaw", 0.0)), 0.0, "posición absoluta"
    else:
        warn("%s: sin 'ancla', 'cruza', 'explanada' ni 'pos'." % spec["name"])


def check(spec, foots, outline, surfaces, road_index, obstacles, placed):
    """Devuelve None si es válido, o el motivo del rechazo."""
    on_plaza = spec.get("en_explanada", False)
    for r in foots:
        for (x, y) in rect_samples(*r):
            if on_plaza:
                if not any(point_in_poly(x, y, pl) and dist_to_poly_edges((x, y), pl) >= 0.5
                           for pl in surfaces):
                    return "sale de la explanada"
            else:
                if not point_in_poly(x, y, outline) or dist_to_poly_edges((x, y), outline) < OUTLINE_MARGIN:
                    return "fuera del contorno"
                for pl in surfaces:
                    if point_in_poly(x, y, pl) or dist_to_poly_edges((x, y), pl) < SURFACE_MARGIN:
                        return "sobre la explanada"
            if not road_free(road_index, x, y, ROAD_CLEAR):
                return "sobre un camino"
            for _nm, (x0, y0, x1, y1) in obstacles:
                if x0 - OBSTACLE_MARGIN <= x <= x1 + OBSTACLE_MARGIN and \
                        y0 - OBSTACLE_MARGIN <= y <= y1 + OBSTACLE_MARGIN:
                    return "choca con un recinto/detalle (06/07)"
        for p in placed:
            if rects_overlap(r, p, STRUCT_GAP):
                return "choca con otra estructura"
    return None


# ============================================================
# 9. PROGRAMA PRINCIPAL
# ============================================================
def main():
    scene = bpy.context.scene
    col = bpy.data.collections.get(COLLECTION_NAME)
    if col is None:
        col = bpy.data.collections.new(COLLECTION_NAME)
    else:
        existing = [obj for obj in col.objects if obj.name.startswith("EST_")]
        if existing and PRESERVE_EXISTING_STRUCTURES:
            mats = {name: simple_material(name, color, roughness)
                    for name, (color, roughness) in MATERIALES.items()}
            updated = update_existing_geometry(col, mats)
            print("ESTRUCTURAS PRESERVADAS: %d objetos; se actualizaron sus mallas sin moverlos." % updated)
            return
        clear_collection(col)

    linked_collections = {child.name for child in scene.collection.children_recursive}
    linked_collections.update(child.name for child in scene.collection.children)
    if col.name not in linked_collections:
        scene.collection.children.link(col)

    mats = {n: simple_material(n, c, r) for n, (c, r) in MATERIALES.items()}
    outline = get_outline()
    ground = make_ground()
    surfaces = collect_surface_polys()
    road_index, roads = collect_roads()
    obstacles = collect_obstacles()
    placed = []
    report = []

    for spec in ESTRUCTURAS:
        name = spec["name"]
        chosen, last_reason = None, "sin candidatos"
        for (cx, cy, yaw, pw, desc) in candidates(spec, roads, surfaces):
            foots = footprints(spec, cx, cy, yaw, pw)
            reason = check(spec, foots, outline, surfaces, road_index, obstacles, placed)
            if reason is None:
                chosen = (cx, cy, yaw, pw, desc, foots)
                break
            last_reason = reason
        if chosen is None:
            report.append("OMITIDA  %-20s motivo: %s" % (name, last_reason))
            continue

        cx, cy, yaw, pw, desc, foots = chosen
        S = Slots()
        if spec["tipo"] == "casa":
            bm, _sz = build_casa(spec, S)
        elif spec["tipo"] == "kiosco":
            bm, _sz = build_kiosco(spec, S)
        elif spec["tipo"] == "portico":
            bm, _sz = build_portico(spec, S, pw)
        else:
            report.append("OMITIDA  %-20s tipo desconocido '%s'" % (name, spec["tipo"]))
            bm = None
        if bm is None:
            continue

        gz = [ground(x, y) for r in foots for (x, y) in rect_samples(*r, step=2.0)]
        z0 = max(gz)
        if max(gz) - min(gz) > 0.35:
            warn("%s: desnivel de %.2f m bajo la huella; revisa el zócalo." % (name, max(gz) - min(gz)))
        properties = {"tipo": spec["tipo"], "preliminar": True}
        if spec.get("servicio"):
            properties.update(structure_service_metadata(spec))
        bm_to_object(name, bm, S, mats, col, (cx, cy, z0), yaw, properties)
        placed.extend(foots)
        report.append("OK       %-20s (%.1f, %.1f)  %s" % (name, cx, cy, desc))

    print("=" * 62)
    print("ESTRUCTURAS: %d de %d colocadas" % (sum(r.startswith("OK") for r in report), len(ESTRUCTURAS)))
    for r in report:
        print("  " + r)
    print("Caminos leídos: %d | explanadas 02: %d | obstáculos 06/07/08: %d"
          % (len(roads), len(surfaces), len(obstacles)))
    for w in WARNINGS:
        print("AVISO: " + w)
    print("RECORDATORIO: tipos y ubicaciones son preliminares (sin fotos ni plano).")
    print("=" * 62)


main()