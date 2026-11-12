# -*- coding: utf-8 -*-
"""
============================================================
ZOOLOGICO NICOLAS BRAVO - MODULO 06 - RECINTOS
============================================================
Habitats y cercados 3D procedurales:
  - "hex"       : recinto hexagonal (como los de la zona sur-oeste en la
                  vista satelital) con piso, bordillo, cerca, refugio y rocas.
  - "rect"      : recinto rectangular (cerca baja o jaula alta con techo o domo).
  - "estanque"  : estanque poligonal con agua, borde de rocas y cerca baja.
  - zonas moradas: recintos rústicos con bloque, lámina ondulada, techo
                   inclinado y cama de paja.
  - 10 recintos rústicos adicionales: se buscan junto a caminos libres.

COMO SE UBICAN (igual que el módulo 05)
  Cada recinto se ANCLA a un camino real de 03 (CAMINO_xxx):
  fracción de recorrido (t), lado, y distancia al borde. También se admite:
      pos=(x, y), yaw=grados      posición absoluta
  El FRENTE (puerta) de cada recinto mira hacia el camino. Si el sitio no es
  válido el script prueba desplazamientos y el lado opuesto; si no encuentra
  sitio, OMITE el recinto (nunca queda sobre un camino ni sobre un edificio).

REGLAS (un recinto NO se coloca...)
  - fuera del contorno de 01, ni sobre la explanada de 02,
  - sobre caminos de 03, estructuras de 05, cerca perimetral de 08 ni otro recinto.
  Los recintos rústicos adicionales prueban posiciones alternativas junto al
  camino; los de ZONAS_MORADAS siguen los polígonos dibujados en la foto aérea.

SALIDA PARA EL MODULO 07
  Cada objeto REC_xxx guarda propiedades personalizadas (puerta_x, puerta_y,
  yaw, ancho_puerta, rotulo, ...) para que 07 ponga letreros en la puerta.

IMPORTANTE
  Cantidad, tipo, tamaño y posición de RECINTOS son una PROPUESTA PRELIMINAR
  (no pude abrir el Figma). Cámbialos por los recintos reales del zoológico.

ORDEN: 01 -> 02 -> 03 -> 08 -> 05 -> 06 -> 08 -> 07 -> 04. Ejecuta 08
también después de 06 para alinear los accesos de la malla con las puertas.
Es seguro repetir este script: solo reconstruye 06_RECINTOS.
Solo API de datos (sin bpy.ops). Pensado para Blender 3.x/4.x.
============================================================
"""

import bpy
import bmesh
import math
import random
from mathutils import Vector, kdtree

# ============================================================
# 1. CONFIGURACION
# ============================================================
COLLECTION_NAME = "06_RECINTOS"
BASE_OBJECT_NAME = "BASE_ZOOLOGICO_NICOLAS_BRAVO"
TERRAIN_COLLECTIONS = ["01_BASE_TERRENO", "02_SUPERFICIES"]
SURFACE_COLLECTION = "02_SUPERFICIES"
ROADS_COLLECTION = "03_CAMINOS"
OBSTACLE_PREFIXES = ("05_", "08_")    # estructuras y barda perimetral que no se pisan

FALLBACK_OUTLINE = [
    (-35, 80), (30, 65), (22, 40), (70, 25), (70, -15), (20, -40),
    (12, -65), (-5, -90), (-75, -88), (-75, -48), (-5, -45), (-5, -5),
    (-65, 0), (-65, 30), (-45, 65),
]
FALLBACK_GROUND_Z = 1.5
RAY_START_Z = 500.0

GLOBAL_SCALE = 1.0       # multiplica las dimensiones de TODOS los recintos
ROAD_CLEAR = 1.5         # holgura mínima al borde de un camino (m)
OUTLINE_MARGIN = 1.0
SURFACE_MARGIN = 1.0
REC_GAP = 1.5            # separación mínima entre recintos
OBSTACLE_MARGIN = 1.5
MAX_OBSTACLE_SIZE = 80.0
GATE_WIDTH = 2.2         # ancho de la puerta (m)
CURB_H = 0.5             # altura del bordillo sobre el piso

TRY_EXTRA_DISTANCE = (0.0, 1.0, 2.0, 3.0, 5.0)
TRY_SHIFT_ALONG = (0, 3, -3, 6, -6, 9, -9, 12, -12, 16, -16)

# ============================================================
# 2. MATERIALES: nombre: (color, rugosidad, alfa)
# ============================================================
MATERIALES = {
    "Rec_Tierra":   ((0.45, 0.33, 0.20), 0.95, 1.0),
    "Rec_Pasto":    ((0.28, 0.42, 0.16), 0.95, 1.0),
    "Rec_Arena":    ((0.70, 0.60, 0.40), 0.95, 1.0),
    "Rec_Agua":     ((0.08, 0.26, 0.38), 0.05, 0.85),
    "Rec_Bordillo": ((0.60, 0.58, 0.54), 0.90, 1.0),
    "Rec_Cerca":    ((0.16, 0.18, 0.18), 0.55, 1.0),
    "Rec_Malla":    ((0.25, 0.27, 0.28), 0.60, 0.25),
    "Rec_Cobalto":  ((0.12, 0.20, 0.22), 0.62, 1.0),
    "Rec_Purpura":  ((0.22, 0.25, 0.18), 0.72, 1.0),
    "Rec_Malla_Domo": ((0.12, 0.15, 0.13), 0.72, 0.55),
    "Rec_Madera":   ((0.25, 0.14, 0.07), 0.80, 1.0),
    "Rec_Bloque":   ((0.48, 0.47, 0.43), 0.92, 1.0),
    "Rec_Lamina":   ((0.58, 0.62, 0.64), 0.34, 1.0),
    "Rec_Paja":     ((0.58, 0.43, 0.20), 0.95, 1.0),
    "Rec_Roca":     ((0.40, 0.38, 0.35), 0.95, 1.0),
    "Rec_Refugio":  ((0.80, 0.74, 0.60), 0.85, 1.0),
    "Rec_Techo":    ((0.48, 0.18, 0.10), 0.80, 1.0),
}

DOMO_CONFIG = dict(
    domo=True, malla=True, malla_separacion=0.45,
    domo_alzada=2.4, domo_separacion=0.30, domo_costillas=2.5,
)

# Recintos trazados sobre una imagen de 531 x 533 px (origen arriba a la izquierda).
# Ajusta la calibración si la imagen no coincide con el plano.
RECINTOS_MORADOS_ACTIVOS = True
PX_REF = (265.0, 266.0)   # centro de la imagen
WORLD_REF = (0.0, 0.0)    # coordenadas Blender del centro
METROS_POR_PIXEL = 0.22   # estimación: automóvil de ~4.5 m ocupa ~20 px
RECINTO_MURO_ALTURA = 2.45
RECINTO_TECHO_PENDIENTE = 0.075
RECINTO_PANEL_ALTURA = 1.05
RECINTOS_MORADOS_AJUSTABLES = ("RECINTO_M10", "RECINTO_M12")

ZONAS_MORADAS = {
    "RECINTO_M01": [(230, 38), (228, 41), (234, 51), (251, 62), (252, 59), (241, 38)],
    "RECINTO_M02": [(322, 36), (317, 36), (315, 48), (299, 52), (302, 70), (312, 70),
                    (319, 66), (320, 54), (317, 47), (327, 42)],
    "RECINTO_M03": [(211, 94), (224, 97), (245, 91), (247, 86), (239, 77), (219, 78), (213, 85)],
    "RECINTO_M04": [(430, 200), (408, 199), (392, 206), (380, 216), (380, 228), (389, 227),
                    (395, 221), (420, 212), (429, 205)],
    "RECINTO_M05": [(206, 184), (206, 199), (233, 244), (234, 251), (238, 253), (241, 240),
                    (227, 225), (210, 195), (210, 186)],
    "RECINTO_M06": [(415, 255), (396, 248), (387, 248), (356, 266), (353, 272), (355, 281),
                    (365, 289), (369, 303), (375, 303), (404, 279), (415, 263)],
    "RECINTO_M07": [(128, 257), (117, 255), (114, 249), (108, 251), (98, 271), (79, 297),
                    (82, 307), (90, 306), (91, 309), (95, 309), (103, 301), (129, 265)],
    "RECINTO_M08": [(200, 290), (207, 303), (218, 302), (215, 294)],
    "RECINTO_M09": [(460, 222), (452, 230), (448, 241), (437, 246), (421, 265), (432, 274),
                    (438, 274), (447, 284), (457, 359), (454, 411), (465, 414), (470, 397),
                    (471, 363), (478, 339), (479, 289), (477, 271), (468, 267), (470, 224)],
    "RECINTO_M10": [(153, 304), (145, 309), (137, 321), (136, 331), (146, 346), (158, 348),
                    (164, 353), (171, 353), (174, 349), (187, 344), (190, 327), (178, 306),
                    (170, 303)],
    "RECINTO_M11": [(267, 330), (268, 345), (262, 349), (289, 352), (290, 342), (296, 338),
                    (295, 334), (283, 335), (275, 330)],
    "RECINTO_M12": [(244, 333), (236, 335), (218, 360), (195, 383), (196, 390), (208, 399),
                    (213, 398), (213, 389), (234, 372), (239, 373), (239, 379), (243, 383),
                    (248, 383), (254, 378), (258, 368), (252, 365), (250, 357), (255, 342)],
    "RECINTO_M13": [(332, 422), (328, 427), (329, 439), (336, 440), (337, 444), (347, 444),
                    (351, 439), (348, 427)],
    "RECINTO_M14": [(294, 401), (291, 406), (291, 436), (294, 450), (300, 459), (315, 462),
                    (318, 459), (319, 446), (313, 416)],
}

# ============================================================
# 3. RECINTOS (PROPUESTA PRELIMINAR - NO CONFIRMADA)
# ============================================================
# Campos comunes:
#   name, rotulo (texto del letrero que usará 07), forma, ancla | pos
#   altura  : altura de la cerca (m)         rieles : nº de rieles horizontales
#   poste_sep: separación de postes (m)      suelo  : material del piso
#   refugio : True/False                     rocas  : cantidad de rocas
#   techo   : True = jaula con techo         bebedero: True/False
#   domo    : cubierta curva de malla sobre el recinto rectangular
# hex      : R (radio, m)
# rect     : w (ancho), d (fondo)
# estanque : R (radio), lados (por defecto 12)
# ancla = dict(camino="RAMAL_SUROESTE", t=0.2, lado=-1, distancia=3.0)
#   lado +1 = izquierda según el sentido del camino, -1 = derecha
RECINTOS = [
    # --- Zona sur-oeste: recintos hexagonales (vista satelital) ---
    dict(name="HEX_SUR_1", rotulo="Recinto 1", forma="hex", R=6.5, altura=2.2, rieles=3,
         poste_sep=2.0, suelo="Rec_Tierra", refugio=True, rocas=4,
         ancla=dict(camino="RAMAL_SUROESTE", t=0.22, lado=-1, distancia=3.0)),
    dict(name="HEX_SUR_2", rotulo="Recinto 2", forma="hex", R=6.5, altura=2.2, rieles=3,
         poste_sep=2.0, suelo="Rec_Tierra", refugio=True, rocas=4,
         ancla=dict(camino="RAMAL_SUROESTE", t=0.52, lado=-1, distancia=3.0)),
    dict(name="HEX_SUR_3", rotulo="Recinto 3", forma="hex", R=6.0, altura=2.2, rieles=3,
         poste_sep=2.0, suelo="Rec_Pasto", refugio=True, rocas=3,
         ancla=dict(camino="RAMAL_SUROESTE", t=0.80, lado=-1, distancia=3.0)),
    dict(name="HEX_SUR_4", rotulo="Recinto 4", forma="hex", R=5.5, altura=2.2, rieles=3,
         poste_sep=2.0, suelo="Rec_Tierra", refugio=True, rocas=3,
         ancla=dict(camino="RAMAL_SUROESTE", t=0.40, lado=+1, distancia=3.0)),
    dict(name="HEX_CENTRAL", rotulo="Recinto 5", forma="hex", R=8.0, altura=2.4, rieles=4,
         poste_sep=2.0, suelo="Rec_Pasto", refugio=True, rocas=6,
         ancla=dict(camino="AV_PRINCIPAL", t=0.45, lado=-1, distancia=6.0)),

    # --- Zonas marcadas en la vista aerea: recintos con domo de proteccion ---
    dict(name="JAULA_NOROESTE_1", rotulo="Aviario 1", forma="rect", w=8.0, d=6.0,
         altura=4.0, rieles=2, poste_sep=1.0, suelo="Rec_Tierra", techo=True, **DOMO_CONFIG,
         refugio=False, rocas=2, bebedero=False,
         ancla=dict(camino="SENDERO_NORTE", t=0.50, lado=+1, distancia=3.0)),
    dict(name="JAULA_NOROESTE_2", rotulo="Aviario 2", forma="rect", w=8.0, d=6.0,
         altura=4.0, rieles=2, poste_sep=1.0, suelo="Rec_Tierra", techo=True, **DOMO_CONFIG,
         refugio=False, rocas=2, bebedero=False,
         ancla=dict(camino="ANILLO_NOROESTE", t=0.20, lado=+1, distancia=3.0)),

    # --- Zona este: recintos amplios y estanques ---
    dict(name="RECINTO_ESTE", rotulo="Recinto del tigre", animal="tigre", forma="rect", w=14.0, d=10.0,
            altura=3.5, rieles=2, poste_sep=1.5, suelo="Rec_Tierra", refugio=False,
            agua=True, agua_escala=(0.68, 0.32), agua_desplazamiento=(0.0, -1.6),
            borde_rocas=False, borde_piscina=True, **dict(DOMO_CONFIG, domo_alzada=2.8),
            pasarela=True, rocas=0, bebedero=False,
         ancla=dict(camino="RAMAL_ESTE", t=0.80, lado=+1, distancia=3.0)),
    dict(name="ESTANQUE_1", rotulo="Estanque 1", forma="estanque", R=5.0, altura=1.0,
         rieles=2, poste_sep=2.5, suelo="Rec_Pasto", agua=True, refugio=False, rocas=8,
         bebedero=False,
         ancla=dict(camino="RAMAL_ESTE", t=0.35, lado=-1, distancia=3.0)),
    dict(name="ESTANQUE_2", rotulo="Estanque 2", forma="estanque", R=4.0, altura=1.0,
         rieles=2, poste_sep=2.5, suelo="Rec_Pasto", agua=True, refugio=False, rocas=6,
         bebedero=False,
         ancla=dict(camino="RAMAL_ESTE_RETORNO", t=0.50, lado=-1, distancia=3.0)),

    # --- Resto del zoológico: recintos complementarios para completar el plan general ---
    dict(name="HEX_SUR_5", rotulo="Recinto 6", forma="hex", R=5.8, altura=2.2, rieles=3,
         poste_sep=2.0, suelo="Rec_Tierra", refugio=True, rocas=3,
         ancla=dict(camino="RAMAL_SUROESTE", t=0.10, lado=+1, distancia=3.5)),
    dict(name="HEX_SUR_6", rotulo="Recinto 7", forma="hex", R=5.4, altura=2.2, rieles=3,
         poste_sep=2.0, suelo="Rec_Pasto", refugio=True, rocas=3,
         ancla=dict(camino="RAMAL_SUROESTE", t=0.68, lado=+1, distancia=3.5)),
    dict(name="JAULA_NORTE_1", rotulo="Jaula norte 1", forma="rect", w=9.0, d=6.5,
         altura=4.0, rieles=2, poste_sep=1.0, suelo="Rec_Tierra", techo=True, **DOMO_CONFIG,
         refugio=False, rocas=2, bebedero=False,
         ancla=dict(camino="SENDERO_NORTE", t=0.82, lado=-1, distancia=3.2)),
    dict(name="JAULA_NORTE_2", rotulo="Primates", forma="rect", w=9.5, d=6.0,
         altura=4.0, rieles=2, poste_sep=1.0, suelo="Rec_Tierra", techo=True, **DOMO_CONFIG,
         refugio=False, rocas=2, bebedero=False,
         ancla=dict(camino="ANILLO_NOROESTE", t=0.62, lado=-1, distancia=3.4)),
    dict(name="RECINTO_NORTE_CENTRAL", rotulo="Recinto Norte", forma="rect", w=10.5, d=7.5,
         altura=3.2, rieles=2, poste_sep=1.5, suelo="Rec_Pasto", refugio=False, **DOMO_CONFIG,
         rocas=3, bebedero=False, agua=False,
         ancla=dict(camino="AV_PRINCIPAL", t=0.70, lado=+1, distancia=5.0)),
    dict(name="RECINTO_SUR_INTERIOR", rotulo="Recinto sur interior", forma="hex", R=6.0,
         altura=2.2, rieles=3, poste_sep=2.0, suelo="Rec_Tierra", refugio=True, rocas=3,
         ancla=dict(camino="SENDERO_SUR_INTERIOR", t=0.62, lado=-1, distancia=2.8)),
    dict(name="RECINTO_ESTE_2", rotulo="Recinto este 2", forma="rect", w=11.5, d=8.5,
         altura=3.2, rieles=2, poste_sep=1.5, suelo="Rec_Tierra", refugio=False, **DOMO_CONFIG,
         rocas=2, bebedero=False, agua=False,
         ancla=dict(camino="RAMAL_ESTE", t=0.48, lado=-1, distancia=4.0)),
    dict(name="ESTANQUE_3", rotulo="Estanque 3", forma="estanque", R=4.2, altura=1.0,
         rieles=2, poste_sep=2.5, suelo="Rec_Pasto", agua=True, refugio=False, rocas=6,
         bebedero=False,
         ancla=dict(camino="RAMAL_ESTE_RETORNO", t=0.82, lado=+1, distancia=2.8)),

]

RECINTOS_RUSTICOS_ADICIONALES = [
    dict(name="RECINTO_CAMINO_01", camino="ANILLO_NOROESTE", t=0.36, lado=+1, w=6.5, d=5.0),
    dict(name="RECINTO_CAMINO_02", camino="ANILLO_NOROESTE", t=0.82, lado=-1, w=8.0, d=5.5),
    dict(name="RECINTO_CAMINO_03", camino="RAMAL_ESTE", t=0.18, lado=-1, w=6.0, d=4.5),
    dict(name="RECINTO_CAMINO_04", camino="RAMAL_ESTE", t=0.66, lado=+1, w=7.5, d=6.0),
    dict(name="RECINTO_CAMINO_05", camino="RAMAL_ESTE_RETORNO", t=0.68, lado=+1, w=8.5, d=6.0),
    dict(name="RECINTO_CAMINO_06", camino="RAMAL_SUROESTE", t=0.18, lado=+1, w=7.0, d=5.0),
    dict(name="RECINTO_CAMINO_07", camino="RAMAL_SUROESTE", t=0.92, lado=-1, w=6.5, d=5.0),
    dict(name="RECINTO_CAMINO_08", camino="SENDERO_SUR", t=0.32, lado=+1, w=6.0, d=4.5),
    dict(name="RECINTO_CAMINO_09", camino="SENDERO_SUR_INTERIOR", t=0.30, lado=-1, w=8.0, d=6.0),
    dict(name="RECINTO_CAMINO_10", camino="AV_PRINCIPAL", t=0.30, lado=+1, w=7.5, d=5.5),
]

WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)


# ============================================================
# 4. GEOMETRIA 2D
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


def polygons_overlap(a, b, gap=0.0):
    if any(point_in_poly(x, y, b) for x, y in a) or any(point_in_poly(x, y, a) for x, y in b):
        return True

    def orientation(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def segments_intersect(a0, a1, b0, b1):
        o1, o2 = orientation(a0, a1, b0), orientation(a0, a1, b1)
        o3, o4 = orientation(b0, b1, a0), orientation(b0, b1, a1)
        if ((o1 > 1e-9 and o2 < -1e-9) or (o1 < -1e-9 and o2 > 1e-9)) and \
                ((o3 > 1e-9 and o4 < -1e-9) or (o3 < -1e-9 and o4 > 1e-9)):
            return True
        return ((abs(o1) <= 1e-9 and point_seg_dist(b0, a0, a1) <= 1e-9) or
                (abs(o2) <= 1e-9 and point_seg_dist(b1, a0, a1) <= 1e-9) or
                (abs(o3) <= 1e-9 and point_seg_dist(a0, b0, b1) <= 1e-9) or
                (abs(o4) <= 1e-9 and point_seg_dist(a1, b0, b1) <= 1e-9))

    for i, a0 in enumerate(a):
        a1 = a[(i + 1) % len(a)]
        for j, b0 in enumerate(b):
            b1 = b[(j + 1) % len(b)]
            if segments_intersect(a0, a1, b0, b1):
                return True
    if gap > 0.0:
        for i, a0 in enumerate(a):
            a1 = a[(i + 1) % len(a)]
            for j, b0 in enumerate(b):
                b1 = b[(j + 1) % len(b)]
                if min(point_seg_dist(a0, b0, b1), point_seg_dist(a1, b0, b1),
                       point_seg_dist(b0, a0, a1), point_seg_dist(b1, a0, a1)) < gap:
                    return True
    return False


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


def transform_poly(poly, cx, cy, yaw):
    transformed = []
    for x, y in poly:
        rx, ry = rot(x, y, yaw)
        transformed.append((cx + rx, cy + ry))
    return transformed


def scale_poly(poly, k):
    sx, sy = k if isinstance(k, (tuple, list)) else (k, k)
    return [(x * sx, y * sy) for x, y in poly]


def regular_poly(R, n):
    """Polígono regular CCW con la arista 0 centrada hacia +Y (el frente)."""
    return [(R * math.cos(math.radians(90 - 180.0 / n + 360.0 * k / n)),
             R * math.sin(math.radians(90 - 180.0 / n + 360.0 * k / n))) for k in range(n)]


# ============================================================
# 5. CAMINOS (lectura de 03; mismo formato que usa 05)
# ============================================================
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
    def __init__(self, name, stations, hw):
        self.name, self.st, self.hw = name, stations, hw
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
                    warn("%s: perfil distinto de 9 vértices; se usa como obstáculo aproximado." % o.name)
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
        warn("No hay caminos en '%s'. Ejecuta 03 antes que 06." % ROADS_COLLECTION)
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
# 6. ESCENA
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
                if o.get("tipo") == "malla_lateral_camino":
                    continue
                cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
                xs, ys = [c.x for c in cs], [c.y for c in cs]
                if max(max(xs) - min(xs), max(ys) - min(ys)) > MAX_OBSTACLE_SIZE:
                    continue
                obs.append((o.name, (min(xs), min(ys), max(xs), max(ys))))
    return obs


def simple_material(name, color, rough, alpha=1.0, emission=0.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = tuple(color) + (1.0,)
        bsdf.inputs["Roughness"].default_value = rough
        if alpha < 1.0 and "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = alpha
        if emission > 0.0:
            emission_color = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
            if emission_color:
                emission_color.default_value = tuple(color) + (1.0,)
            emission_strength = bsdf.inputs.get("Emission Strength")
            if emission_strength:
                emission_strength.default_value = emission
    if alpha < 1.0:
        try:
            mat.blend_method = 'BLEND'
        except Exception:
            pass
    mat.diffuse_color = tuple(color) + (alpha,)
    return mat


def configure_jaula_materials(mats):
    sheet_bsdf = mats["Rec_Lamina"].node_tree.nodes.get("Principled BSDF")
    if sheet_bsdf and "Metallic" in sheet_bsdf.inputs:
        sheet_bsdf.inputs["Metallic"].default_value = 0.72

    straw = mats["Rec_Paja"]
    nodes, links = straw.node_tree.nodes, straw.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:
        return
    for node_name in ("Rec_Paja_Noise", "Rec_Paja_Ramp", "Rec_Paja_Bump"):
        old_node = nodes.get(node_name)
        if old_node is not None:
            nodes.remove(old_node)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.name = "Rec_Paja_Noise"
    noise.inputs["Scale"].default_value = 38.0
    noise.inputs["Detail"].default_value = 3.0
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.name = "Rec_Paja_Ramp"
    ramp.color_ramp.elements[0].position = 0.18
    ramp.color_ramp.elements[0].color = (0.22, 0.13, 0.045, 1.0)
    ramp.color_ramp.elements[1].position = 0.82
    ramp.color_ramp.elements[1].color = (0.84, 0.66, 0.32, 1.0)
    middle = ramp.color_ramp.elements.new(0.50)
    middle.color = (0.54, 0.36, 0.12, 1.0)
    bump = nodes.new("ShaderNodeBump")
    bump.name = "Rec_Paja_Bump"
    bump.inputs["Strength"].default_value = 0.28
    bump.inputs["Distance"].default_value = 0.035
    tex_coord = nodes.get("Texture Coordinate")
    if tex_coord is not None:
        links.new(tex_coord.outputs["Generated"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def configure_habitat_materials(mats):
    palettes = {
        "Rec_Tierra": ((0.31, 0.22, 0.13, 1.0), (0.52, 0.40, 0.25, 1.0)),
        "Rec_Pasto": ((0.12, 0.25, 0.08, 1.0), (0.30, 0.44, 0.16, 1.0)),
        "Rec_Arena": ((0.55, 0.44, 0.28, 1.0), (0.78, 0.67, 0.47, 1.0)),
    }
    for material_name, colors in palettes.items():
        material = mats[material_name]
        nodes, links = material.node_tree.nodes, material.node_tree.links
        shader = nodes.get("Principled BSDF")
        if shader is None:
            continue
        for node_name in ("Habitat_TexCoord", "Habitat_Noise", "Habitat_Ramp", "Habitat_Bump"):
            previous = nodes.get(node_name)
            if previous is not None:
                nodes.remove(previous)

        tex_coord = nodes.new("ShaderNodeTexCoord")
        tex_coord.name = "Habitat_TexCoord"
        noise = nodes.new("ShaderNodeTexNoise")
        noise.name = "Habitat_Noise"
        noise.inputs["Scale"].default_value = 9.0
        noise.inputs["Detail"].default_value = 3.0
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.name = "Habitat_Ramp"
        ramp.color_ramp.elements[0].color = colors[0]
        ramp.color_ramp.elements[1].color = colors[1]
        bump = nodes.new("ShaderNodeBump")
        bump.name = "Habitat_Bump"
        bump.inputs["Strength"].default_value = 0.16
        bump.inputs["Distance"].default_value = 0.02

        links.new(tex_coord.outputs["Generated"], noise.inputs["Vector"])
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], shader.inputs["Base Color"])
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], shader.inputs["Normal"])


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
# 7. MODELADO (bmesh). Coordenadas locales: centro en (0, 0), suelo z = 0,
#    FRENTE (puerta) hacia +Y.
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


def beam(bm, a, b, z0, z1, thick, mat):
    """Prisma horizontal entre los puntos a y b (rieles y bordillos)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L < 1e-6:
        return
    nx, ny = -dy / L * thick / 2.0, dx / L * thick / 2.0
    pts = [(a[0] - nx, a[1] - ny), (b[0] - nx, b[1] - ny), (b[0] + nx, b[1] + ny), (a[0] + nx, a[1] + ny)]
    v = [bm.verts.new((p[0], p[1], z0)) for p in pts] + [bm.verts.new((p[0], p[1], z1)) for p in pts]
    for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([v[i] for i in f]).material_index = mat


def beam3d(bm, start, end, thick, mat):
    """Prisma cuadrado entre dos puntos 3D, usado para costillas y cables."""
    a, b = Vector(start), Vector(end)
    axis = b - a
    if axis.length < 1e-6:
        return
    direction = axis.normalized()
    reference = Vector((0.0, 0.0, 1.0))
    if abs(direction.dot(reference)) > 0.95:
        reference = Vector((1.0, 0.0, 0.0))
    u = direction.cross(reference).normalized() * (thick / 2.0)
    v = direction.cross(u).normalized() * (thick / 2.0)
    corners = [a - u - v, b - u - v, b + u - v, a + u - v,
               a - u + v, b - u + v, b + u + v, a + u + v]
    verts = [bm.verts.new(p) for p in corners]
    for face in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([verts[i] for i in face]).material_index = mat


def prism(bm, poly, z0, z1, mat):
    """Losa cerrada con la forma del polígono (piso, agua, techo de jaula)."""
    n = len(poly)
    vb = [bm.verts.new((x, y, z0)) for x, y in poly]
    vt = [bm.verts.new((x, y, z1)) for x, y in poly]
    bm.faces.new(list(reversed(vb))).material_index = mat
    bm.faces.new(vt).material_index = mat
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((vb[i], vb[j], vt[j], vt[i])).material_index = mat


def sloped_prism(bm, start, end, width, z_start, z_end, thickness, mat):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    nx, ny = -dy / length * width / 2.0, dx / length * width / 2.0
    top = [bm.verts.new((start[0] + nx, start[1] + ny, z_start)),
           bm.verts.new((start[0] - nx, start[1] - ny, z_start)),
           bm.verts.new((end[0] - nx, end[1] - ny, z_end)),
           bm.verts.new((end[0] + nx, end[1] + ny, z_end))]
    bottom = [bm.verts.new((vertex.co.x, vertex.co.y, vertex.co.z - thickness)) for vertex in top]
    bm.faces.new(top).material_index = mat
    bm.faces.new(list(reversed(bottom))).material_index = mat
    for index in range(4):
        following = (index + 1) % 4
        bm.faces.new((bottom[index], bottom[following], top[following], top[index])).material_index = mat


def gable(bm, x0, x1, ya, yb, z0, z1, mat):
    ym = (ya + yb) / 2.0
    v = [bm.verts.new(p) for p in ((x0, ya, z0), (x0, yb, z0), (x0, ym, z1),
                                   (x1, ya, z0), (x1, yb, z0), (x1, ym, z1))]
    for f in ((0, 3, 4, 1), (0, 2, 5, 3), (1, 4, 5, 2)):
        bm.faces.new([v[i] for i in f]).material_index = mat
    bm.faces.new((v[0], v[1], v[2])).material_index = mat
    bm.faces.new((v[3], v[5], v[4])).material_index = mat


def cone(bm, px, py, z0, r1, r2, depth, mat, segments=8, sx=1.0, sy=1.0):
    res = bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                                radius1=r1, radius2=r2, depth=depth)
    if sx != 1.0 or sy != 1.0:
        bmesh.ops.scale(bm, vec=Vector((sx, sy, 1.0)), verts=res["verts"])
    bmesh.ops.translate(bm, vec=Vector((px, py, z0 + depth / 2.0)), verts=res["verts"])
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = mat


def lerp2(a, b, u):
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)


def build_fence(bm, poly, gate_edge, gate_w, fence_h, rails, post_sep, m_curb, m_fence, m_gate,
                m_mesh=None, mesh_spacing=0.0):
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if i == gate_edge and L > gate_w + 0.8:
            g = gate_w / L / 2.0
            segs = [(0.0, 0.5 - g), (0.5 + g, 1.0)]
            for u in (0.5 - g, 0.5 + g):           # postes de la puerta
                p = lerp2(a, b, u)
                box(bm, p[0] - 0.2, p[1] - 0.2, 0.0, p[0] + 0.2, p[1] + 0.2, fence_h + 0.5, m_gate)
        else:
            segs = [(0.0, 1.0)]
        for (u0, u1) in segs:
            pa, pb = lerp2(a, b, u0), lerp2(a, b, u1)
            sl = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
            if sl < 0.2:
                continue
            beam(bm, pa, pb, -0.6, CURB_H, 0.35, m_curb)                  # bordillo
            for r in range(rails):                                          # rieles
                z = CURB_H + (fence_h - CURB_H) * (r + 1) / rails
                beam(bm, pa, pb, z - 0.05, z + 0.05, 0.08, m_fence)
            if m_mesh is not None and mesh_spacing > 0:
                vertical_count = max(1, int(math.ceil(sl / mesh_spacing)))
                for j in range(1, vertical_count):
                    px, py = lerp2(pa, pb, j / vertical_count)
                    cone(bm, px, py, CURB_H, 0.018, 0.018,
                         fence_h - CURB_H, m_mesh, segments=4)
                z = CURB_H + mesh_spacing
                while z < fence_h:
                    beam(bm, pa, pb, z, z + 0.025, 0.025, m_mesh)
                    z += mesh_spacing
            k = max(1, int(round(sl / post_sep)))
            for j in range(k + 1):                                          # postes
                p = lerp2(pa, pb, j / k)
                box(bm, p[0] - 0.07, p[1] - 0.07, CURB_H, p[0] + 0.07, p[1] + 0.07, fence_h, m_fence)


def build_dome_canopy(bm, width, depth, fence_h, rise, spacing, rib_spacing,
                      m_frame, m_ridge, m_net):
    """Cubierta arqueada con costillas estructurales y retícula de cables."""
    arc_segments = max(16, int(math.ceil(width / 0.45)))
    depth_segments = max(2, int(math.ceil(depth / rib_spacing)))

    def roof_point(u, y):
        x = (u - 0.5) * width
        v = (y + depth / 2.0) / depth
        z = fence_h + rise * math.sin(math.pi * u) * math.sin(math.pi * v)
        return x, y, z

    for row in range(depth_segments + 1):
        y = -depth / 2.0 + depth * row / depth_segments
        for segment in range(arc_segments):
            u0, u1 = segment / arc_segments, (segment + 1) / arc_segments
            beam3d(bm, roof_point(u0, y), roof_point(u1, y), 0.10, m_frame)

    # Cables longitudinales y transversales forman una malla continua sobre el arco.
    across_count = max(12, int(math.ceil(width / spacing)))
    along_count = max(2, int(math.ceil(depth / spacing)))
    for row in range(along_count + 1):
        y = -depth / 2.0 + depth * row / along_count
        for segment in range(across_count):
            u0, u1 = segment / across_count, (segment + 1) / across_count
            beam3d(bm, roof_point(u0, y), roof_point(u1, y), 0.018, m_net)
    for column in range(across_count + 1):
        u = column / across_count
        for row in range(along_count):
            y0 = -depth / 2.0 + depth * row / along_count
            y1 = -depth / 2.0 + depth * (row + 1) / along_count
            beam3d(bm, roof_point(u, y0), roof_point(u, y1), 0.018, m_net)

    for segment in range(depth_segments):
        y0 = -depth / 2.0 + depth * segment / depth_segments
        y1 = -depth / 2.0 + depth * (segment + 1) / depth_segments
        beam3d(bm, roof_point(0.5, y0), roof_point(0.5, y1), 0.075, m_ridge)


def shape(spec):
    """(poly_local, ancho, fondo, arista_de_la_puerta)."""
    k = GLOBAL_SCALE
    f = spec["forma"]
    if f == "hex":
        R = spec["R"] * k
        return regular_poly(R, 6), 2 * R, 2 * R * math.cos(math.pi / 6), 0
    if f == "estanque":
        n = spec.get("lados", 12)
        R = spec["R"] * k
        return regular_poly(R, n), 2 * R, 2 * R * math.cos(math.pi / n), 0
    w, d = spec["w"] * k, spec["d"] * k
    return [(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)], w, d, 2


def build_recinto(spec, S):
    poly, w, d, gate = shape(spec)
    rng = random.Random(spec["name"])
    bm = bmesh.new()
    m_floor = S.idx(spec.get("suelo", "Rec_Tierra"))
    m_curb = S.idx("Rec_Bordillo")
    m_fence = S.idx("Rec_Cerca")
    m_gate = S.idx("Rec_Madera")
    m_rock = S.idx("Rec_Roca")
    m_wood = S.idx("Rec_Madera")
    fence_h = spec.get("altura", 2.2)

    prism(bm, poly, -0.6, 0.04, m_floor)                                    # piso

    water = spec.get("agua", False)
    water_radius = spec["R"] * GLOBAL_SCALE if "R" in spec else min(w, d) * 0.44
    if water:
        pool = scale_poly(poly, spec.get("agua_escala", 0.72))
        ox, oy = spec.get("agua_desplazamiento", (0.0, 0.0))
        pool = [(x + ox, y + oy) for x, y in pool]
        prism(bm, pool, 0.0, 0.10, S.idx("Rec_Agua"))
        if spec.get("borde_piscina", False):
            for index, a in enumerate(pool):
                rim_material = S.idx("Rec_Cobalto") if spec.get("domo", False) else m_curb
                beam(bm, a, pool[(index + 1) % len(pool)], 0.07, 0.24, 0.18, rim_material)
        if spec.get("borde_rocas", True):
            rock_count = int(spec.get("rocas", 6)) + 6
            for index in range(rock_count):
                angle = 2 * math.pi * index / rock_count + rng.uniform(-0.1, 0.1)
                radius = water_radius * rng.uniform(0.70, 0.78)
                rock_radius = rng.uniform(0.35, 0.7)
                cone(bm, math.cos(angle) * radius, math.sin(angle) * radius, 0.0,
                     rock_radius, rock_radius * 0.5, rock_radius * 0.9, m_rock, 6)

    m_mesh = S.idx("Rec_Malla") if spec.get("malla", False) else None
    build_fence(bm, poly, gate, GATE_WIDTH, fence_h, spec.get("rieles", 3),
                spec.get("poste_sep", 2.0), m_curb, m_fence, m_gate,
                m_mesh, spec.get("malla_separacion", 0.0))

    if spec.get("domo", False):
        build_dome_canopy(
            bm, w, d, fence_h, spec.get("domo_alzada", 2.5),
            spec.get("domo_separacion", 0.85), spec.get("domo_costillas", 2.5),
            S.idx("Rec_Cobalto"), S.idx("Rec_Neon_Purpura"), S.idx("Rec_Malla_Domo"),
        )

    if spec.get("pasarela", False):
        start = (-w * 0.30, -d * 0.40)
        end = (w * 0.28, d * 0.40)
        start_z, end_z = 0.55, 1.65
        sloped_prism(bm, start, end, 0.9, start_z, end_z, 0.12, m_wood)
        for fraction in (0.28, 0.72):
            px, py = lerp2(start, end, fraction)
            z = start_z + (end_z - start_z) * fraction
            box(bm, px - 0.09, py - 0.09, 0.0, px + 0.09, py + 0.09, z - 0.12, m_wood)

    if spec.get("techo", False) and not spec.get("domo", False):           # jaula con techo plano
        prism(bm, poly, fence_h, fence_h + 0.06, S.idx("Rec_Malla"))

    avoid = []                                                              # zonas ocupadas (x0,y0,x1,y1)
    if spec.get("refugio", False):
        hw = min(3.2, w * 0.35) / 2.0
        hd = 1.3
        cy = -d / 2.0 + 0.8 + hd
        wm, rf = S.idx("Rec_Refugio"), S.idx("Rec_Techo")
        box(bm, -hw, cy - hd, 0.0, hw, cy + hd, 2.2, wm)
        gable(bm, -hw - 0.3, hw + 0.3, cy - hd - 0.3, cy + hd + 0.3, 2.2, 2.2 + 1.0, rf)
        box(bm, -0.5, cy + hd, 0.0, 0.5, cy + hd + 0.05, 1.8, m_gate)
        avoid.append((-hw - 0.5, cy - hd - 0.5, hw + 0.5, cy + hd + 1.0))

    if spec.get("bebedero", True) and not water:
        bx = -w / 4.0
        by = d / 2.0 - 1.8
        box(bm, bx - 0.6, by - 0.25, 0.0, bx + 0.6, by + 0.25, 0.35, m_curb)
        box(bm, bx - 0.5, by - 0.17, 0.30, bx + 0.5, by + 0.17, 0.34, S.idx("Rec_Agua"))
        avoid.append((bx - 1.0, by - 0.7, bx + 1.0, by + 0.7))

    inner = scale_poly(poly, 0.78)                                          # rocas decorativas
    n_rocks = 0 if water else int(spec.get("rocas", 0))
    tries = 0
    while n_rocks > 0 and tries < 80:
        tries += 1
        x = rng.uniform(-w / 2, w / 2)
        y = rng.uniform(-d / 2, d / 2)
        if not point_in_poly(x, y, inner):
            continue
        if abs(x) < GATE_WIDTH and y > d / 2 - 3.0:                         # no tapar la puerta
            continue
        if any(a0 <= x <= a1 and b0 <= y <= b1 for (a0, b0, a1, b1) in avoid):
            continue
        r = rng.uniform(0.4, 0.9)
        cone(bm, x, y, 0.0, r, r * 0.45, r * 0.9, m_rock, 6,
             sx=rng.uniform(0.8, 1.3), sy=rng.uniform(0.8, 1.3))
        n_rocks -= 1

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm, (w, d, poly, gate)


def bm_to_object(name, bm, S, mats, col, loc, yaw, props):
    mesh = bpy.data.meshes.new("MALLA_" + name)
    bm.to_mesh(mesh)
    bm.free()
    for m in S.names:
        mesh.materials.append(mats[m])
    for p in mesh.polygons:
        p.use_smooth = False
    mesh.update()
    obj = bpy.data.objects.new("REC_" + name, mesh)
    obj.location = loc
    obj.rotation_euler = (0.0, 0.0, yaw)
    for k, v in props.items():
        obj[k] = v
    col.objects.link(obj)
    return obj


# ============================================================
# 7B. RECINTOS RUSTICOS EN LAS ZONAS MARCADAS EN MORADO
# ============================================================
def px_to_world(point):
    """Convierte las coordenadas del dibujo de la foto a coordenadas del zoo."""
    return (
        WORLD_REF[0] + (point[0] - PX_REF[0]) * METROS_POR_PIXEL,
        WORLD_REF[1] - (point[1] - PX_REF[1]) * METROS_POR_PIXEL,
    )


def build_recinto_rustico(poly, slots, seed):
    """Construye un recinto de bloques, paneles de lámina, malla y techo galvanizado."""
    bm = bmesh.new()
    m_floor = slots.idx("Rec_Paja")
    m_mesh = slots.idx("Rec_Malla_Domo")
    m_block = slots.idx("Rec_Bloque")
    m_sheet = slots.idx("Rec_Lamina")
    m_wood = slots.idx("Rec_Madera")

    floor_z = 0.08
    prism(bm, poly, 0.0, floor_z, m_floor)

    # La arista más larga representa el frente de servicio del recinto.
    edge_lengths = [
        math.hypot(poly[(i + 1) % len(poly)][0] - p[0],
                   poly[(i + 1) % len(poly)][1] - p[1])
        for i, p in enumerate(poly)
    ]
    front_edge = max(range(len(poly)), key=edge_lengths.__getitem__)
    front_a, front_b = poly[front_edge], poly[(front_edge + 1) % len(poly)]
    front_mid = ((front_a[0] + front_b[0]) * 0.5, (front_a[1] + front_b[1]) * 0.5)
    center = (sum(x for x, _y in poly) / len(poly), sum(y for _x, y in poly) / len(poly))
    depth = (center[0] - front_mid[0], center[1] - front_mid[1])
    depth_len = math.hypot(*depth) or 1.0
    depth = (depth[0] / depth_len, depth[1] / depth_len)
    tangent = ((front_b[0] - front_a[0]) / edge_lengths[front_edge],
               (front_b[1] - front_a[1]) / edge_lengths[front_edge])
    roof_poly = [(center[0] + (x - center[0]) * 1.025,
                  center[1] + (y - center[1]) * 1.025) for x, y in poly]

    def roof_height(point):
        rise = ((point[0] - front_mid[0]) * depth[0] +
                (point[1] - front_mid[1]) * depth[1]) * RECINTO_TECHO_PENDIENTE
        return RECINTO_MURO_ALTURA + rise

    # Three sides are laid in staggered concrete-block courses.
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        if i == front_edge:
            continue
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        wall_h = min(roof_height(a), roof_height(b)) - 0.08
        course_h, block_len = 0.20, 0.42
        courses = max(1, int(wall_h / course_h))
        for row in range(courses):
            z0 = row * course_h
            z1 = min(z0 + course_h - 0.018, wall_h)
            offset = 0.5 * block_len if row % 2 else 0.0
            block_count = max(1, int(math.ceil(length / block_len)))
            for block_index in range(block_count):
                u0 = max(0.0, (block_index * block_len + offset + 0.012) / length)
                u1 = min(1.0, ((block_index + 1) * block_len + offset - 0.012) / length)
                if u1 <= u0:
                    continue
                pa, pb = lerp2(a, b, u0), lerp2(a, b, u1)
                beam(bm, pa, pb, z0, z1, 0.34, m_block)

    # The long front combines a corrugated kick panel and an open wire grid.
    front_length = edge_lengths[front_edge]
    gate_width = min(1.0, front_length * 0.18)
    gate_u = gate_width / front_length
    front_height = min(roof_height(front_a), roof_height(front_b)) - 0.10
    front_parts = ((0.0, 0.5 - gate_u / 2.0), (0.5 - gate_u / 2.0, 0.5 + gate_u / 2.0),
                   (0.5 + gate_u / 2.0, 1.0))
    for part, (u0, u1) in enumerate(front_parts):
        if u1 - u0 < 0.01:
            continue
        a, b = lerp2(front_a, front_b, u0), lerp2(front_a, front_b, u1)
        beam(bm, a, b, 0.04, RECINTO_PANEL_ALTURA, 0.06, m_sheet)
        rib_count = max(1, int(math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.14)))
        for rib in range(rib_count + 1):
            x, y = lerp2(a, b, rib / rib_count)
            beam3d(bm, (x, y, 0.06), (x, y, RECINTO_PANEL_ALTURA), 0.025, m_sheet)

        # Mesh above the sheet, including a gate leaf in the middle section.
        upper_h = max(0.0, front_height - RECINTO_PANEL_ALTURA)
        vertical_count = max(1, int(math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.28)))
        for wire in range(vertical_count + 1):
            x, y = lerp2(a, b, wire / vertical_count)
            beam3d(bm, (x, y, RECINTO_PANEL_ALTURA),
                   (x, y, RECINTO_PANEL_ALTURA + upper_h), 0.014, m_mesh)
        horizontal_count = max(1, int(math.ceil(upper_h / 0.24)))
        for row in range(horizontal_count + 1):
            z = RECINTO_PANEL_ALTURA + upper_h * row / horizontal_count
            beam3d(bm, (a[0], a[1], z), (b[0], b[1], z), 0.014, m_mesh)
        if part == 1:
            for u in (0.0, 1.0):
                x, y = lerp2(a, b, u)
                beam3d(bm, (x, y, 0.0), (x, y, front_height), 0.09, m_wood)
            beam3d(bm, (a[0], a[1], front_height - 0.035),
                   (b[0], b[1], front_height - 0.035), 0.07, m_wood)

    # Lightweight rafters support the galvanized roof.
    min_t = min(x * tangent[0] + y * tangent[1] for x, y in roof_poly)
    max_t = max(x * tangent[0] + y * tangent[1] for x, y in roof_poly)
    rafter_count = max(1, int(math.ceil((max_t - min_t) / 2.0)))
    for i in range(rafter_count + 1):
        value = min_t + (max_t - min_t) * i / rafter_count
        points = []
        for a, b in zip(roof_poly, roof_poly[1:] + roof_poly[:1]):
            ta = a[0] * tangent[0] + a[1] * tangent[1]
            tb = b[0] * tangent[0] + b[1] * tangent[1]
            if (ta <= value < tb) or (tb <= value < ta):
                u = (value - ta) / (tb - ta)
                points.append(lerp2(a, b, u))
        if len(points) >= 2:
            points.sort(key=lambda p: p[0] * depth[0] + p[1] * depth[1])
            for start, end in zip(points[::2], points[1::2]):
                beam3d(bm, (start[0], start[1], roof_height(start) - 0.12),
                       (end[0], end[1], roof_height(end) - 0.12), 0.08, m_wood)

    roof_top = [bm.verts.new((x, y, roof_height((x, y)))) for x, y in roof_poly]
    roof_under = [bm.verts.new((x, y, roof_height((x, y)) - 0.06)) for x, y in roof_poly]
    bm.faces.new(roof_top).material_index = m_sheet
    bm.faces.new(list(reversed(roof_under))).material_index = m_sheet
    for i in range(len(roof_poly)):
        j = (i + 1) % len(roof_poly)
        bm.faces.new((roof_under[i], roof_under[j], roof_top[j], roof_top[i])).material_index = m_sheet

    # Raised seams read as galvanized corrugations and follow the roof pitch.
    corrugations = max(1, int(math.ceil((max_t - min_t) / 0.13)))
    for i in range(corrugations + 1):
        value = min_t + (max_t - min_t) * i / corrugations
        points = []
        for a, b in zip(roof_poly, roof_poly[1:] + roof_poly[:1]):
            ta = a[0] * tangent[0] + a[1] * tangent[1]
            tb = b[0] * tangent[0] + b[1] * tangent[1]
            if (ta <= value < tb) or (tb <= value < ta):
                u = (value - ta) / (tb - ta)
                points.append(lerp2(a, b, u))
        if len(points) >= 2:
            points.sort(key=lambda p: p[0] * depth[0] + p[1] * depth[1])
            for start, end in zip(points[::2], points[1::2]):
                beam3d(bm, (start[0], start[1], roof_height(start) + 0.018),
                       (end[0], end[1], roof_height(end) + 0.018), 0.028, m_sheet)

    # A sparse layer of straw fibers gives the bedding visible relief in renders.
    rng = random.Random("paja-" + seed)
    min_x, max_x = min(x for x, _y in poly), max(x for x, _y in poly)
    min_y, max_y = min(y for _x, y in poly), max(y for _x, y in poly)
    y = min_y
    while y <= max_y:
        x = min_x
        while x <= max_x:
            px, py = x + rng.uniform(-0.12, 0.12), y + rng.uniform(-0.12, 0.12)
            if point_in_poly(px, py, poly) and dist_to_poly_edges((px, py), poly) > 0.12:
                for _ in range(2):
                    angle = rng.uniform(0.0, math.pi)
                    length = rng.uniform(0.10, 0.22)
                    dx, dy = math.cos(angle) * length / 2.0, math.sin(angle) * length / 2.0
                    z = floor_z + rng.uniform(0.008, 0.035)
                    beam3d(bm, (px - dx, py - dy, z), (px + dx, py + dy, z), 0.009, m_floor)
            x += 0.38
        y += 0.38

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def enclosure_samples(poly, spacing=0.8):
    points = list(poly)
    for index, a in enumerate(poly):
        b = poly[(index + 1) % len(poly)]
        count = max(1, int(math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / spacing)))
        points.extend(lerp2(a, b, step / count) for step in range(1, count))
    min_x, max_x = min(x for x, _y in poly), max(x for x, _y in poly)
    min_y, max_y = min(y for _x, y in poly), max(y for _x, y in poly)
    x = min_x
    while x <= max_x:
        y = min_y
        while y <= max_y:
            if point_in_poly(x, y, poly):
                points.append((x, y))
            y += spacing
        x += spacing
    return points


def morado_placement_error(poly, outline, surfaces, road_index, obstacles,
                           occupied_polys, placed_polys):
    samples = enclosure_samples(poly)
    if any(not point_in_poly(x, y, outline) or
           dist_to_poly_edges((x, y), outline) < OUTLINE_MARGIN for x, y in samples):
        return "cerca del borde o sobre la explanada central"
    if any(polygons_overlap(poly, surface, SURFACE_MARGIN) for surface in surfaces):
        return "demasiado cerca de una superficie de 02"
    if any(not road_free(road_index, x, y, ROAD_CLEAR) for x, y in samples):
        return "demasiado cerca de un camino"
    for _name, bounds in obstacles:
        obstacle = [
            (bounds[0] - OBSTACLE_MARGIN, bounds[1] - OBSTACLE_MARGIN),
            (bounds[2] + OBSTACLE_MARGIN, bounds[1] - OBSTACLE_MARGIN),
            (bounds[2] + OBSTACLE_MARGIN, bounds[3] + OBSTACLE_MARGIN),
            (bounds[0] - OBSTACLE_MARGIN, bounds[3] + OBSTACLE_MARGIN),
        ]
        if polygons_overlap(poly, obstacle):
            return "demasiado cerca de una estructura o valla (05/08)"
    if any(polygons_overlap(poly, other, REC_GAP) for other in occupied_polys):
        return "demasiado cerca de otro recinto"
    if any(polygons_overlap(poly, other, REC_GAP) for other in placed_polys):
        return "demasiado cerca de otro recinto"
    return None


def prepare_morados(outline, surfaces, road_index, obstacles):
    worlds = {
        name: [px_to_world(point) for point in pixels]
        for name, pixels in ZONAS_MORADAS.items()
    }
    notes = []

    for name in RECINTOS_MORADOS_AJUSTABLES:
        source = worlds.get(name)
        if source is None:
            continue
        occupied = [poly for other_name, poly in worlds.items() if other_name != name]
        reason = morado_placement_error(source, outline, surfaces, road_index, obstacles,
                                        occupied, [])
        if reason is None:
            continue

        step = 0.5
        max_steps = 50
        offsets = [
            (ix * step, iy * step)
            for ix in range(-max_steps, max_steps + 1)
            for iy in range(-max_steps, max_steps + 1)
            if ix or iy
        ]
        offsets.sort(key=lambda offset: (offset[0] ** 2 + offset[1] ** 2,
                                        abs(offset[1]), offset[1], offset[0]))
        for dx, dy in offsets:
            candidate = [(x + dx, y + dy) for x, y in source]
            if morado_placement_error(candidate, outline, surfaces, road_index, obstacles,
                                      occupied, []) is None:
                worlds[name] = candidate
                notes.append("%s movido (%.1f, %.1f) m para evitar %s" %
                             (name, dx, dy, reason))
                break
        else:
            del worlds[name]
            warn("%s: no se encontró terreno libre cercano; se omite (%s)." % (name, reason))
            notes.append("OMITIDO  %-24s sin sitio libre cercano" % name)

    reserved = list(worlds.values())
    for index, (name, poly) in enumerate(worlds.items()):
        occupied = reserved[:index] + reserved[index + 1:]
        reason = morado_placement_error(poly, outline, surfaces, road_index, obstacles,
                                        occupied, [])
        if reason:
            warn("%s: conserva la ubicación trazada, pero %s." % (name, reason))
    return list(worlds.items()), notes


def prepare_roadside_morados(outline, surfaces, road_index, roads, obstacles,
                             occupied_polys, placed_polys):
    """Encuentra sitio junto a un camino para cada recinto rústico adicional."""
    placed = []
    notes = []
    for spec in RECINTOS_RUSTICOS_ADICIONALES:
        w, d = spec["w"], spec["d"]
        info = roads.get(spec["camino"])
        if info is None:
            message = "%s: no existe el camino '%s'." % (spec["name"], spec["camino"])
            warn(message)
            notes.append("OMITIDO  %-24s %s" % (spec["name"], message))
            continue

        chosen = None
        last_reason = "sin candidatos"
        for extra_distance in TRY_EXTRA_DISTANCE:
            for shift in TRY_SHIFT_ALONG:
                for side in (spec["lado"], -spec["lado"]):
                    station = max(2.0, min(
                        info.total - 2.0, spec["t"] * info.total + shift
                    ))
                    x, y, nx, ny = info.pose(station)
                    offset = info.hw + 2.0 + extra_distance + d / 2.0
                    cx, cy = x + nx * side * offset, y + ny * side * offset
                    toward_road = (-nx * side, -ny * side)
                    yaw = math.atan2(-toward_road[0], toward_road[1])
                    poly = [
                        (cx + rx, cy + ry)
                        for rx, ry in (
                            rot(-w / 2.0, d / 2.0, yaw),
                            rot(w / 2.0, d / 2.0, yaw),
                            rot(w / 2.0, -d / 2.0, yaw),
                            rot(-w / 2.0, -d / 2.0, yaw),
                        )
                    ]
                    reason = morado_placement_error(
                        poly, outline, surfaces, road_index, obstacles,
                        occupied_polys + [item[1] for item in placed], placed_polys,
                    )
                    if reason is None:
                        chosen = poly
                        break
                    last_reason = reason
                if chosen is not None:
                    break
            if chosen is not None:
                break

        if chosen is None:
            message = "%s: no se encontró espacio libre (%s)." % (spec["name"], last_reason)
            warn(message)
            notes.append("OMITIDO  %-24s sin espacio libre" % spec["name"])
            continue

        placed.append((spec["name"], chosen))
        notes.append("UBICADO  %-24s junto a %s" % (spec["name"], spec["camino"]))

    return placed, notes


def build_recintos_morados(col, mats, ground, report, morados):
    """Construye los recintos rústicos sobre los polígonos morados de la foto."""
    for name, world in morados:
        cx = sum(x for x, _y in world) / len(world)
        cy = sum(y for _x, y in world) / len(world)
        local = [(x - cx, y - cy) for x, y in world]
        z0 = max(ground(x, y) for x, y in world)

        slots = Slots()
        bm = build_recinto_rustico(local, slots, name)
        front_edge = max(
            range(len(local)),
            key=lambda i: math.hypot(
                local[(i + 1) % len(local)][0] - local[i][0],
                local[(i + 1) % len(local)][1] - local[i][1],
            ),
        )
        front_a, front_b = local[front_edge], local[(front_edge + 1) % len(local)]
        front_mid = ((front_a[0] + front_b[0]) * 0.5, (front_a[1] + front_b[1]) * 0.5)
        local_center = (sum(x for x, _y in local) / len(local),
                        sum(y for _x, y in local) / len(local))
        inward = (local_center[0] - front_mid[0], local_center[1] - front_mid[1])
        yaw = math.atan2(inward[0], -inward[1])
        width = max(x for x, _y in local) - min(x for x, _y in local)
        depth = max(y for _x, y in local) - min(y for _x, y in local)

        bm_to_object(name, bm, slots, mats, col, (cx, cy, z0), 0.0, {
            "tipo": "recinto_rustico",
            "preliminar": False,
            "rotulo": name.replace("RECINTO_", "Recinto ").replace("_", " "),
            "animal": "",
            "cubierta": "lamina galvanizada ondulada inclinada",
            "paleta": "bloque de hormigon, lamina galvanizada y madera",
            "puerta_x": cx + front_mid[0],
            "puerta_y": cy + front_mid[1],
            "puerta_z": z0,
            "yaw": yaw,
            "ancho_puerta": min(1.0, math.hypot(front_b[0] - front_a[0],
                                               front_b[1] - front_a[1]) * 0.18),
            "w": width,
            "d": depth,
            "altura": RECINTO_MURO_ALTURA,
        })
        report.append("OK       %-24s (%.1f, %.1f)  recinto rústico" % (name, cx, cy))


# ============================================================
# 8. UBICACION
# ============================================================
def candidates(spec, roads):
    if "ancla" in spec:
        a = spec["ancla"]
        info = roads.get(a["camino"])
        if info is None:
            warn("%s: no existe el camino '%s'." % (spec["name"], a["camino"]))
            return
        _poly, w, d, _g = shape(spec)
        for dd in TRY_EXTRA_DISTANCE:
            for ds in TRY_SHIFT_ALONG:
                for side in (a["lado"], -a["lado"]):
                    s = max(2.0, min(info.total - 2.0, a["t"] * info.total + ds))
                    x, y, nx, ny = info.pose(s)
                    off = info.hw + a["distancia"] + dd + d / 2.0
                    bx, by = x + nx * side * off, y + ny * side * off
                    dirx, diry = -nx * side, -ny * side            # hacia el camino
                    desc = "lado %+d, %+d m a lo largo, +%.0f m al fondo" % (side, ds, dd)
                    yield bx, by, math.atan2(-dirx, diry), desc
    elif "pos" in spec:
        yield spec["pos"][0], spec["pos"][1], math.radians(spec.get("yaw", 0.0)), "posición absoluta"
    else:
        warn("%s: sin 'ancla' ni 'pos'." % spec["name"])


def check(poly, outline, surfaces, road_index, obstacles, placed_polys,
          reserved_polys=()):
    samples = enclosure_samples(poly)
    if any(not point_in_poly(x, y, outline) or
           dist_to_poly_edges((x, y), outline) < OUTLINE_MARGIN for x, y in samples):
        return "fuera del contorno"
    if any(polygons_overlap(poly, surface, SURFACE_MARGIN) for surface in surfaces):
        return "sobre la explanada"
    if any(not road_free(road_index, x, y, ROAD_CLEAR) for x, y in samples):
        return "sobre un camino"
    for _name, bounds in obstacles:
        obstacle = [
            (bounds[0] - OBSTACLE_MARGIN, bounds[1] - OBSTACLE_MARGIN),
            (bounds[2] + OBSTACLE_MARGIN, bounds[1] - OBSTACLE_MARGIN),
            (bounds[2] + OBSTACLE_MARGIN, bounds[3] + OBSTACLE_MARGIN),
            (bounds[0] - OBSTACLE_MARGIN, bounds[3] + OBSTACLE_MARGIN),
        ]
        if polygons_overlap(poly, obstacle):
            return "choca con una estructura o valla (05/08)"
    if any(polygons_overlap(poly, other, REC_GAP)
           for other in placed_polys + list(reserved_polys)):
        return "choca con otro recinto"
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
        clear_collection(col)
    linked = {c.name for c in scene.collection.children_recursive}
    linked.update(c.name for c in scene.collection.children)
    if col.name not in linked:
        scene.collection.children.link(col)

    mats = {n: simple_material(n, c, r, a) for n, (c, r, a) in MATERIALES.items()}
    configure_habitat_materials(mats)
    configure_jaula_materials(mats)
    mats["Rec_Neon_Purpura"] = simple_material(
        "Rec_Neon_Purpura", (0.20, 0.23, 0.19), 0.62
    )
    outline = get_outline()
    ground = make_ground()
    surfaces = collect_surface_polys()
    road_index, roads = collect_roads()
    obstacles = collect_obstacles()
    placed = []
    report = []
    if RECINTOS_MORADOS_ACTIVOS:
        morados, placement_notes = prepare_morados(outline, surfaces, road_index, obstacles)
    else:
        morados, placement_notes = [], []
    report.extend(placement_notes)
    reserved_morados = [poly for _name, poly in morados]

    for spec in RECINTOS:
        name = spec["name"]
        local_poly, w, d, _g = shape(spec)
        chosen, last_reason = None, "sin candidatos"
        for (cx, cy, yaw, desc) in candidates(spec, roads):
            footprint = transform_poly(local_poly, cx, cy, yaw)
            reason = check(
                footprint, outline, surfaces, road_index, obstacles, placed, reserved_morados
            )
            if reason is None:
                chosen = (cx, cy, yaw, desc, footprint)
                break
            last_reason = reason
        if chosen is None:
            report.append("OMITIDO  %-18s motivo: %s" % (name, last_reason))
            continue

        cx, cy, yaw, desc, footprint = chosen
        S = Slots()
        bm, (w, d, _p, _gate) = build_recinto(spec, S)
        gz = [ground(x, y) for x, y in enclosure_samples(footprint, spacing=2.5)]
        z0 = max(gz)
        if max(gz) - min(gz) > 0.5:
            warn("%s: desnivel de %.2f m bajo el recinto; el bordillo baja 0.6 m para ocultarlo."
                 % (name, max(gz) - min(gz)))
        gx, gy = rot(0.0, d / 2.0, yaw)
        bm_to_object(name, bm, S, mats, col, (cx, cy, z0), yaw, {
            "tipo": spec["forma"], "preliminar": True,
            "rotulo": spec.get("rotulo", name.replace("_", " ").title()),
            "animal": spec.get("animal", ""),
            "cubierta": "domo de malla tensada" if spec.get("domo", False) else
                        ("malla" if spec.get("malla", False) else "abierta"),
            "paleta": "estructura metálica y malla oscura" if spec.get("domo", False) else "natural",
            "puerta_x": cx + gx, "puerta_y": cy + gy, "puerta_z": z0,
            "yaw": yaw, "ancho_puerta": GATE_WIDTH, "w": w, "d": d,
        })
        placed.append(footprint)
        report.append("OK       %-18s (%.1f, %.1f)  %s" % (name, cx, cy, desc))

    if RECINTOS_MORADOS_ACTIVOS:
        additional, additional_notes = prepare_roadside_morados(
            outline, surfaces, road_index, roads, obstacles, reserved_morados, placed
        )
        report.extend(additional_notes)
        morados.extend(additional)
        build_recintos_morados(col, mats, ground, report, morados)

    print("=" * 62)
    total = (len(RECINTOS) + len(ZONAS_MORADAS) + len(RECINTOS_RUSTICOS_ADICIONALES)
             if RECINTOS_MORADOS_ACTIVOS else len(RECINTOS))
    print("RECINTOS: %d de %d colocados" % (sum(r.startswith("OK") for r in report), total))
    for r in report:
        print("  " + r)
    print("Caminos leídos: %d | explanadas 02: %d | obstáculos 05/08: %d"
          % (len(roads), len(surfaces), len(obstacles)))
    for w_ in WARNINGS:
        print("AVISO: " + w_)
    print("RECORDATORIO: tipos y ubicaciones son preliminares (sin Figma ni plano).")
    print("=" * 62)


main()