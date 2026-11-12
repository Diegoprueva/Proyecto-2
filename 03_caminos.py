"""Genera superficies viales planas a partir de las guias guardadas en el .blend.

Las coordenadas se conservaron de las guias originales. La explanada central
se pavimenta en 02 y se mantiene libre de caminos superpuestos; el acceso norte
se acerca a su borde. Los anchos son estimaciones visuales basadas en la foto.

Orden: 01 -> 02 -> 03 -> 08 -> 05 -> 06 -> 07 -> 04.
Solo reconstruye objetos CAMINO_ y GUIA_ dentro de 03_CAMINOS.
"""

import bpy
import math

COLLECTION_NAME = "03_CAMINOS"
BASE_OBJECT_NAME = "BASE_ZOOLOGICO_NICOLAS_BRAVO"
ROAD_LIFT = 0.025
SAMPLES_PER_SEGMENT = 10
PROFILE_SEGMENTS = 8
EDGE_BAND = 0.14

# Trazados tomados de las curvas GUIA_ del .blend actual.
# No se agregan conexiones nuevas ni se usa la linea morada del perimetro.
PATHS = [
    dict(name="AV_PRINCIPAL", tipo="principal", ancho=4.0,
         puntos=[(-10.0, 68.0), (-8.0, 45.0), (0.0, 25.0), (3.0, 5.0),
                 (5.0, -20.0), (6.0, -42.0), (0.0, -62.0)]),
    dict(name="RAMAL_ESTE", tipo="secundario", ancho=3.0,
         puntos=[(1.8, 15.8), (25.0, 12.0), (45.0, 6.0), (58.0, -2.0)]),
    dict(name="RAMAL_ESTE_RETORNO", tipo="secundario", ancho=3.0,
         puntos=[(58.0, -2.0), (52.0, -12.0), (32.0, -18.0), (14.0, -20.0), (5.0, -20.0)]),
    dict(name="ANILLO_NOROESTE", tipo="secundario", ancho=3.0,
         puntos=[(-8.8, 49.8), (-28.0, 52.0), (-48.0, 40.0), (-55.0, 18.0),
                 (-35.0, 8.0), (-12.0, 10.0), (2.9, 6.2)]),
        dict(name="SENDERO_NORTE", tipo="sendero", ancho=2.0,
            puntos=[(-9.6, 60.0), (10.0, 58.0), (12.0, 48.0)]),
    dict(name="RAMAL_SUROESTE", tipo="secundario", ancho=3.0,
         puntos=[(0.0, -62.0), (-20.0, -69.0), (-45.0, -70.0), (-66.0, -68.0)]),
    dict(name="SENDERO_SUR", tipo="sendero", ancho=2.0,
         puntos=[(-30.0, -70.1), (-36.0, -81.0), (-58.0, -81.0), (-65.9, -68.0)]),
    dict(name="SENDERO_SUR_INTERIOR", tipo="sendero", ancho=2.0,
         puntos=[(-45.0, -70.0), (-50.0, -58.0), (-30.0, -56.0), (-11.6, -66.5)]),
    dict(name="ACCESO_EXPLANADA_NORTE", tipo="sendero", ancho=2.0,
         puntos=[(-29.9, 7.8), (-30.0, 1.0), (-30.0, -9.0), (-30.0, -15.2)]),
]

ROAD_COLORS = {
    "principal": (0.48, 0.47, 0.44),
    "secundario": (0.52, 0.50, 0.47),
    "sendero": (0.48, 0.45, 0.40),
}
EDGE_COLOR = (0.64, 0.61, 0.56)


def point_in_polygon(point, polygon):
    x, y = point
    inside = False
    previous = len(polygon) - 1
    for current in range(len(polygon)):
        xi, yi = polygon[current]
        xj, yj = polygon[previous]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        previous = current
    return inside


def catmull_rom(points):
    """Muestrea curvas suaves entre puntos de control existentes."""
    sampled = [points[0]]
    for index in range(len(points) - 1):
        p0 = points[max(0, index - 1)]
        p1 = points[index]
        p2 = points[index + 1]
        p3 = points[min(len(points) - 1, index + 2)]
        for step in range(1, SAMPLES_PER_SEGMENT + 1):
            t = step / SAMPLES_PER_SEGMENT
            t2, t3 = t * t, t * t * t
            sample = tuple(
                0.5 * (2 * p1[axis] + (-p0[axis] + p2[axis]) * t +
                       (2 * p0[axis] - 5 * p1[axis] + 4 * p2[axis] - p3[axis]) * t2 +
                       (-p0[axis] + 3 * p1[axis] - 3 * p2[axis] + p3[axis]) * t3)
                for axis in (0, 1)
            )
            sampled.append(sample)
    return sampled


def validate_paths(base):
    if base.type != 'MESH' or len(base.data.vertices) < 6 or len(base.data.vertices) % 2:
        raise RuntimeError("El terreno de 01 no tiene la estructura de malla esperada.")
    if "explanada" not in base.keys():
        raise RuntimeError("El terreno de 01 no contiene la referencia de la explanada.")

    coords = list(base["explanada"])
    if len(coords) < 6 or len(coords) % 2:
        raise RuntimeError("La referencia de la explanada no es valida.")
    plaza = [(float(coords[i]), float(coords[i + 1])) for i in range(0, len(coords), 2)]
    ring_size = len(base.data.vertices) // 2
    outline = [((base.matrix_world @ vertex.co).x, (base.matrix_world @ vertex.co).y)
               for vertex in base.data.vertices[ring_size:]]
    names = set()

    for path in PATHS:
        name = path["name"]
        points = path["puntos"]
        if name in names:
            raise RuntimeError("Nombre de camino duplicado: %s." % name)
        names.add(name)
        if path["tipo"] not in ROAD_COLORS or len(points) < 2 or path["ancho"] <= 0:
            raise RuntimeError("Definicion invalida para el camino %s." % name)
        if any(not math.isfinite(value) for point in points for value in point):
            raise RuntimeError("Coordenadas invalidas en el camino %s." % name)

        centerline = catmull_rom(points)
        half_width = path["ancho"] / 2.0
        for index, (x, y) in enumerate(centerline):
            previous = centerline[max(0, index - 1)]
            following = centerline[min(len(centerline) - 1, index + 1)]
            dx, dy = following[0] - previous[0], following[1] - previous[1]
            length = math.hypot(dx, dy)
            if length < 1e-8:
                continue
            nx, ny = -dy / length, dx / length
            for side in (-1.0, 0.0, 1.0):
                edge_point = (x + nx * half_width * side, y + ny * half_width * side)
                if not point_in_polygon(edge_point, outline):
                    raise RuntimeError("El camino %s sale del perimetro del terreno en (%.1f, %.1f)." %
                                       (name, edge_point[0], edge_point[1]))
                if point_in_polygon(edge_point, plaza):
                    raise RuntimeError("El camino %s invade la explanada central en (%.1f, %.1f)." %
                                       (name, edge_point[0], edge_point[1]))

    return plaza


def make_material(name, color):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = tuple(color) + (1.0,)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader:
        shader.inputs["Base Color"].default_value = tuple(color) + (1.0,)
        shader.inputs["Roughness"].default_value = 0.92
    return material


def make_road_mesh(path, centerline, height, material, edge_material, collection):
    half_width = path["ancho"] / 2.0
    vertices = []
    for index, (x, y) in enumerate(centerline):
        previous = centerline[max(0, index - 1)]
        following = centerline[min(len(centerline) - 1, index + 1)]
        dx, dy = following[0] - previous[0], following[1] - previous[1]
        length = math.hypot(dx, dy)
        if length < 1e-8:
            raise RuntimeError("Puntos consecutivos repetidos en %s." % path["name"])
        nx, ny = -dy / length, dx / length
        for section in range(PROFILE_SEGMENTS + 1):
            lateral = -half_width + path["ancho"] * section / PROFILE_SEGMENTS
            vertices.append((x + nx * lateral, y + ny * lateral, height))

    faces = []
    material_indices = []
    for station in range(len(centerline) - 1):
        for section in range(PROFILE_SEGMENTS):
            a = station * (PROFILE_SEGMENTS + 1) + section
            b = a + PROFILE_SEGMENTS + 1
            faces.append((a, b, b + 1, a + 1))
            material_indices.append(1 if section in (0, PROFILE_SEGMENTS - 1) else 0)

    mesh = bpy.data.meshes.new("MALLA_CAMINO_" + path["name"])
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(material)
    mesh.materials.append(edge_material)
    mesh.update()
    for polygon, material_index in zip(mesh.polygons, material_indices):
        polygon.material_index = material_index
        polygon.use_smooth = False

    road = bpy.data.objects.new("CAMINO_" + path["name"], mesh)
    road["tipo"] = path["tipo"]
    road["ancho"] = float(path["ancho"])
    road["ancho_estimado"] = True
    road["puntos_control"] = len(path["puntos"])
    collection.objects.link(road)

    solidify = road.modifiers.new("Espesor_Camino", "SOLIDIFY")
    solidify.thickness = 0.04
    solidify.offset = -1.0
    return road


def make_guide(path, centerline, height, collection):
    curve = bpy.data.curves.new("CURVA_GUIA_" + path["name"], 'CURVE')
    curve.dimensions = '3D'
    spline = curve.splines.new('POLY')
    spline.points.add(len(centerline) - 1)
    for control, (x, y) in zip(spline.points, centerline):
        control.co = (x, y, height, 1.0)
    guide = bpy.data.objects.new("GUIA_" + path["name"], curve)
    guide["tipo"] = path["tipo"]
    guide["ancho"] = float(path["ancho"])
    collection.objects.link(guide)
    return guide


def clear_generated_paths(collection):
    for obj in list(collection.objects):
        if not (obj.name.startswith("CAMINO_") or obj.name.startswith("GUIA_")):
            continue
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Curve):
                bpy.data.curves.remove(data)


def main():
    base = bpy.data.objects.get(BASE_OBJECT_NAME)
    if base is None:
        raise RuntimeError("Falta el terreno de 01. Ejecuta 01_base_terreno.py primero.")
    plaza = validate_paths(base)

    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)
    linked = {child.name for child in bpy.context.scene.collection.children_recursive}
    if collection.name not in linked:
        bpy.context.scene.collection.children.link(collection)

    top_z = max((base.matrix_world @ vertex.co).z for vertex in base.data.vertices)
    road_height = top_z + ROAD_LIFT
    edge_material = make_material("Material_Borde_Camino", EDGE_COLOR)
    materials = {kind: make_material("Material_Camino_" + kind.title(), color)
                 for kind, color in ROAD_COLORS.items()}

    clear_generated_paths(collection)
    report = []
    for path in PATHS:
        centerline = catmull_rom(path["puntos"])
        road = make_road_mesh(path, centerline, road_height, materials[path["tipo"]],
                              edge_material, collection)
        make_guide(path, centerline, road_height, collection)
        report.append("%-26s ancho estimado %.1f m | %d secciones" %
                      (road.name, path["ancho"], len(centerline)))

    print("=" * 64)
    print("CAMINOS RECONSTRUIDOS: %d | altura %.3f m | explanada reservada (%d vertices)" %
          (len(PATHS), road_height, len(plaza)))
    for line in report:
        print("  " + line)
    print("Anchos estimados: principal 4 m, secundario 3 m, sendero 2 m.")
    print("Se mantiene la explanada libre de caminos superpuestos.")
    print("=" * 64)


main()