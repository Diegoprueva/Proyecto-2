# -*- coding: utf-8 -*-
"""Genera la cerca perimetral y mallas laterales junto a los caminos.

Las aberturas se alinean con los extremos de caminos cercanos al perímetro.
La malla de los caminos sigue un lado y abre accesos frente a los recintos.
Ejecutar después de 03 y repetir después de 06 para alinear esos accesos.
Solo reconstruye objetos CERCA_ dentro de 08_PERIMETRO.
"""

import bpy
import math

COLLECTION_NAME = "08_PERIMETRO"
BASE_OBJECT_NAME = "BASE_ZOOLOGICO_NICOLAS_BRAVO"
ROADS_COLLECTION = "03_CAMINOS"

FENCE_HEIGHT = 3.0
POST_SPACING = 2.4
POST_WIDTH = 0.12
MESH_SPACING = 0.25
MESH_THICKNESS = 0.014
GATE_SNAP_DISTANCE = 3.25
GATE_CLEARANCE = 1.2
MIN_GATE_WIDTH = 3.2
MAX_GATE_WIDTH = 5.0
ROAD_FENCE_HEIGHT = 1.8
ROAD_FENCE_GAP = 0.3
ROAD_FENCE_POST_SPACING = 2.4
ROAD_FENCE_MESH_SPACING = 0.3
ROAD_FENCE_CHUNK_STATIONS = 16
ROAD_FENCE_MAX_DOOR_DISTANCE = 3.9


def ensure_collection():
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)
    linked = {child.name for child in bpy.context.scene.collection.children_recursive}
    linked.update(child.name for child in bpy.context.scene.collection.children)
    if collection.name not in linked:
        bpy.context.scene.collection.children.link(collection)
    return collection


def clear_generated_fence(collection):
    for obj in list(collection.objects):
        if not (obj.name.startswith("CERCA_CONTORNO_") or
                obj.name.startswith("CERCA_CAMINO_")):
            continue
        mesh = obj.data if obj.type == "MESH" else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def make_material(name, color, roughness, metallic):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is not None:
        shader.inputs["Base Color"].default_value = tuple(color) + (1.0,)
        shader.inputs["Roughness"].default_value = roughness
        metallic_socket = shader.inputs.get("Metallic")
        if metallic_socket is not None:
            metallic_socket.default_value = metallic
    material.diffuse_color = tuple(color) + (1.0,)
    return material


def lerp2(a, b, t):
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def nearest_on_segment(point, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_squared = dx * dx + dy * dy
    if length_squared < 1e-12:
        return 0.0, a, math.hypot(point[0] - a[0], point[1] - a[1])
    t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) /
                     length_squared))
    nearest = lerp2(a, b, t)
    return t, nearest, math.hypot(point[0] - nearest[0], point[1] - nearest[1])


def collect_gate_openings(outline):
    collection = bpy.data.collections.get(ROADS_COLLECTION)
    openings = {}
    if collection is None:
        return openings

    for road in collection.objects:
        if road.type != "MESH" or not road.name.startswith("CAMINO_"):
            continue
        vertices = road.data.vertices
        if len(vertices) < 18 or len(vertices) % 9:
            continue

        station_count = len(vertices) // 9
        for station_index in (0, station_count - 1):
            local = vertices[station_index * 9 + 4].co
            point = road.matrix_world @ local
            best = None
            for edge_index, a in enumerate(outline):
                b = outline[(edge_index + 1) % len(outline)]
                t, nearest, distance = nearest_on_segment((point.x, point.y), a, b)
                if best is None or distance < best[0]:
                    best = distance, edge_index, t

            distance, edge_index, t = best
            if distance > GATE_SNAP_DISTANCE:
                continue
            a, b = outline[edge_index], outline[(edge_index + 1) % len(outline)]
            edge_length = math.hypot(b[0] - a[0], b[1] - a[1])
            if edge_length < MIN_GATE_WIDTH:
                continue
            road_width = float(road.get("ancho", 2.0))
            gate_width = min(MAX_GATE_WIDTH, road_width + GATE_CLEARANCE, edge_length - 0.2)
            if gate_width < MIN_GATE_WIDTH:
                continue
            half_span = gate_width / (2.0 * edge_length)
            center = max(half_span, min(1.0 - half_span, t))
            openings.setdefault(edge_index, []).append(
                (center - half_span, center + half_span)
            )

    merged = {}
    for edge_index, spans in openings.items():
        result = []
        for start, end in sorted(spans):
            if result and start <= result[-1][1] + 0.02:
                result[-1] = (result[-1][0], max(result[-1][1], end))
            else:
                result.append((start, end))
        merged[edge_index] = result
    return merged


def add_bar(vertices, faces, material_indices, a, b, start, end,
            z0, z1, thickness, material_index):
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    if length < 1e-6 or end - start < 1e-6 or z1 - z0 < 1e-6:
        return
    p0, p1 = lerp2(a, b, start), lerp2(a, b, end)
    nx = -(b[1] - a[1]) / length * thickness / 2.0
    ny = (b[0] - a[0]) / length * thickness / 2.0
    base = len(vertices)
    vertices.extend((
        (p0[0] - nx, p0[1] - ny, z0), (p1[0] - nx, p1[1] - ny, z0),
        (p1[0] + nx, p1[1] + ny, z0), (p0[0] + nx, p0[1] + ny, z0),
        (p0[0] - nx, p0[1] - ny, z1), (p1[0] - nx, p1[1] - ny, z1),
        (p1[0] + nx, p1[1] + ny, z1), (p0[0] + nx, p0[1] + ny, z1),
    ))
    faces.extend(tuple(base + index for index in face) for face in (
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ))
    material_indices.extend((material_index,) * 6)


def add_fence_span(vertices, faces, material_indices, a, b, start, end):
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    span_length = (end - start) * length
    if span_length < 0.15:
        return

    post_count = max(1, int(math.ceil(span_length / POST_SPACING)))
    for index in range(post_count + 1):
        t = start + (end - start) * index / post_count
        half_post = POST_WIDTH / (2.0 * length)
        add_bar(vertices, faces, material_indices, a, b,
                max(start, t - half_post), min(end, t + half_post),
                0.0, FENCE_HEIGHT, POST_WIDTH, 0)

    for z0, z1 in ((0.08, 0.14), (1.35, 1.41),
                   (FENCE_HEIGHT - 0.14, FENCE_HEIGHT - 0.08)):
        add_bar(vertices, faces, material_indices, a, b, start, end,
                z0, z1, 0.06, 0)

    wire_count = max(1, int(math.ceil(span_length / MESH_SPACING)))
    half_wire = MESH_THICKNESS / (2.0 * length)
    for index in range(1, wire_count):
        t = start + (end - start) * index / wire_count
        add_bar(vertices, faces, material_indices, a, b,
                max(start, t - half_wire), min(end, t + half_wire),
                0.14, FENCE_HEIGHT - 0.14, MESH_THICKNESS, 1)

    row_count = max(1, int((FENCE_HEIGHT - 0.28) / MESH_SPACING))
    for index in range(1, row_count):
        z = 0.14 + (FENCE_HEIGHT - 0.28) * index / row_count
        add_bar(vertices, faces, material_indices, a, b, start, end,
                z - MESH_THICKNESS / 2.0, z + MESH_THICKNESS / 2.0,
                MESH_THICKNESS, 1)


def collect_road_fence_paths():
    collection = bpy.data.collections.get(ROADS_COLLECTION)
    if collection is None:
        raise RuntimeError("Falta 03_CAMINOS. Ejecuta 03_caminos.py primero.")

    paths = []
    for road in collection.objects:
        if road.type != "MESH" or not road.name.startswith("CAMINO_"):
            continue
        vertices = road.data.vertices
        if len(vertices) < 18 or len(vertices) % 9:
            raise RuntimeError("%s no tiene el perfil de camino esperado." % road.name)

        half_width = float(road.get("ancho", 0.0)) / 2.0
        if half_width <= 0.0:
            raise RuntimeError("%s no tiene un ancho de camino valido." % road.name)

        centers, points = [], []
        for station_index in range(len(vertices) // 9):
            base = station_index * 9
            center = road.matrix_world @ vertices[base + 4].co
            right_edge = road.matrix_world @ vertices[base].co
            dx, dy = right_edge.x - center.x, right_edge.y - center.y
            edge_distance = math.hypot(dx, dy)
            if edge_distance < 1e-6:
                raise RuntimeError("%s tiene una seccion de ancho cero." % road.name)
            centers.append((center.x, center.y, center.z))
            points.append((
                right_edge.x + dx / edge_distance * ROAD_FENCE_GAP,
                right_edge.y + dy / edge_distance * ROAD_FENCE_GAP,
                center.z,
            ))
        paths.append((road.name, centers, points))

    if not paths:
        raise RuntimeError("No se encontraron objetos CAMINO_ dentro de 03_CAMINOS.")
    return paths


def point_on_polyline(points, distances, distance):
    distance = max(0.0, min(distances[-1], distance))
    for index in range(len(points) - 1):
        if distance <= distances[index + 1]:
            segment = distances[index + 1] - distances[index]
            t = 0.0 if segment < 1e-9 else (distance - distances[index]) / segment
            a, b = points[index], points[index + 1]
            return tuple(a[axis] + (b[axis] - a[axis]) * t for axis in range(3))
    return points[-1]


def slice_polyline(points, distances, start, end):
    if end - start < 0.15:
        return []
    section = [point_on_polyline(points, distances, start)]
    section.extend(
        point for point, distance in zip(points, distances)
        if start + 1e-6 < distance < end - 1e-6
    )
    section.append(point_on_polyline(points, distances, end))
    return section


def collect_road_fence_openings(paths):
    enclosure_collection = bpy.data.collections.get("06_RECINTOS")
    if enclosure_collection is None:
        return {}

    road_data = {}
    for road_name, centers, fence_points in paths:
        distances = [0.0]
        for a, b in zip(fence_points, fence_points[1:]):
            distances.append(distances[-1] + math.dist(a[:2], b[:2]))
        if distances[-1] < 1e-6:
            continue
        road_data[road_name] = centers, fence_points, distances

    openings = {road_name: [] for road_name in road_data}
    for enclosure in enclosure_collection.objects:
        if enclosure.type != "MESH":
            continue
        door_x, door_y = enclosure.get("puerta_x"), enclosure.get("puerta_y")
        if door_x is None or door_y is None:
            continue
        door = (float(door_x), float(door_y))
        best_path = None
        for road_name, (centers, fence_points, distances) in road_data.items():
            best_segment = None
            for index, (fence_a, fence_b) in enumerate(zip(fence_points, fence_points[1:])):
                dx, dy = fence_b[0] - fence_a[0], fence_b[1] - fence_a[1]
                length_squared = dx * dx + dy * dy
                if length_squared < 1e-12:
                    continue
                t = max(0.0, min(1.0, (
                    (door[0] - fence_a[0]) * dx + (door[1] - fence_a[1]) * dy
                ) / length_squared))
                fence_x, fence_y = fence_a[0] + dx * t, fence_a[1] + dy * t
                center_a, center_b = centers[index], centers[index + 1]
                center_x = center_a[0] + (center_b[0] - center_a[0]) * t
                center_y = center_a[1] + (center_b[1] - center_a[1]) * t
                right_x, right_y = fence_x - center_x, fence_y - center_y
                if ((door[0] - center_x) * right_x +
                        (door[1] - center_y) * right_y) <= 0.0:
                    continue
                distance = math.hypot(door[0] - fence_x, door[1] - fence_y)
                if best_segment is None or distance < best_segment[0]:
                    along = distances[index] + math.sqrt(length_squared) * t
                    best_segment = distance, along

            if best_segment is not None and (
                    best_path is None or best_segment[0] < best_path[1][0]):
                best_path = road_name, best_segment

        if best_path is None or best_path[1][0] > ROAD_FENCE_MAX_DOOR_DISTANCE:
            continue
        road_name, (_distance, center) = best_path
        total = road_data[road_name][2][-1]
        door_width = float(enclosure.get("ancho_puerta", 1.8))
        gate_width = max(2.4, min(3.6, door_width + 0.8))
        openings[road_name].append((
            max(0.0, center - gate_width / 2.0),
            min(total, center + gate_width / 2.0),
        ))

    for road_name, road_openings in openings.items():
        merged = []
        for start, end in sorted(road_openings):
            if merged and start <= merged[-1][1] + 0.15:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        openings[road_name] = merged
    return openings


def build_road_fence_chunk(collection, road_name, chunk_index, points, materials):
    vertices, faces, material_indices = [], [], []
    next_post = 0.0
    last_post = None
    traversed = 0.0
    height = ROAD_FENCE_HEIGHT

    def add_post(px, py, tx, ty, base_z):
        post_a = (px - tx * 0.04, py - ty * 0.04)
        post_b = (px + tx * 0.04, py + ty * 0.04)
        add_bar(vertices, faces, material_indices, post_a, post_b, 0.0, 1.0,
                base_z, base_z + height, POST_WIDTH, 0)

    for a3, b3 in zip(points, points[1:]):
        a, b = a3[:2], b3[:2]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length < 1e-6:
            continue
        base_z = (a3[2] + b3[2]) * 0.5

        while next_post <= traversed + length:
            t = max(0.0, min(1.0, (next_post - traversed) / length))
            px, py = lerp2(a, b, t)
            tx, ty = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            add_post(px, py, tx, ty, base_z)
            last_post = next_post
            next_post += ROAD_FENCE_POST_SPACING

        for z0, z1 in ((0.08, 0.14), (height * 0.5, height * 0.5 + 0.06),
                       (height - 0.14, height - 0.08)):
            add_bar(vertices, faces, material_indices, a, b, 0.0, 1.0,
                    base_z + z0, base_z + z1, 0.06, 0)

        row_count = max(1, int((height - 0.28) / ROAD_FENCE_MESH_SPACING))
        for row in range(1, row_count):
            z = 0.14 + (height - 0.28) * row / row_count
            add_bar(vertices, faces, material_indices, a, b, 0.0, 1.0,
                    base_z + z - MESH_THICKNESS / 2.0,
                    base_z + z + MESH_THICKNESS / 2.0, MESH_THICKNESS, 1)

        wire_count = max(1, int(math.ceil(length / ROAD_FENCE_MESH_SPACING)))
        half_wire = MESH_THICKNESS / (2.0 * length)
        for wire in range(1, wire_count):
            t = wire / wire_count
            add_bar(vertices, faces, material_indices, a, b,
                    max(0.0, t - half_wire), min(1.0, t + half_wire),
                    base_z + 0.14, base_z + height - 0.14,
                    MESH_THICKNESS, 1)

        traversed += length

    if traversed > 0.0 and (last_post is None or traversed - last_post > 0.1):
        a3, b3 = points[-2], points[-1]
        dx, dy = b3[0] - a3[0], b3[1] - a3[1]
        length = math.hypot(dx, dy)
        if length > 1e-6:
            add_post(b3[0], b3[1], dx / length, dy / length, b3[2])

    if not faces:
        return False

    road_id = road_name[len("CAMINO_"):] if road_name.startswith("CAMINO_") else road_name
    mesh_name = "Malla_Cerca_Camino_%s_%03d" % (road_id, chunk_index)
    mesh = bpy.data.meshes.new(mesh_name)
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(materials[0])
    mesh.materials.append(materials[1])
    mesh.update()
    for polygon, material_index in zip(mesh.polygons, material_indices):
        polygon.material_index = material_index

    fence = bpy.data.objects.new(
        "CERCA_CAMINO_%s_%03d" % (road_id, chunk_index), mesh
    )
    collection.objects.link(fence)
    fence["tipo"] = "malla_lateral_camino"
    fence["altura"] = height
    fence["lado"] = "derecho_segun_sentido_del_camino"
    return True


def build_road_fences(collection, paths, materials, openings):
    built = 0
    stride = ROAD_FENCE_CHUNK_STATIONS - 1
    for road_name, _centers, points in paths:
        chunk_index = 0
        distances = [0.0]
        for a, b in zip(points, points[1:]):
            distances.append(distances[-1] + math.dist(a[:2], b[:2]))
        road_openings = openings.get(road_name, [])
        line_segments, cursor = [], 0.0
        for start, end in road_openings:
            if start > cursor:
                line_segments.append(slice_polyline(points, distances, cursor, start))
            cursor = max(cursor, end)
        if cursor < distances[-1]:
            line_segments.append(slice_polyline(points, distances, cursor, distances[-1]))

        for line in (segment for segment in line_segments if len(segment) > 1):
            for start in range(0, len(line) - 1, stride):
                chunk = line[start:start + ROAD_FENCE_CHUNK_STATIONS]
                if build_road_fence_chunk(collection, road_name, chunk_index, chunk, materials):
                    built += 1
                    chunk_index += 1
    return built


def build_edge_object(collection, edge_index, a, b, z, openings, materials):
    vertices, faces, material_indices = [], [], []
    cursor = 0.0
    for start, end in openings:
        add_fence_span(vertices, faces, material_indices, a, b, cursor, start)
        add_bar(vertices, faces, material_indices, a, b, start, end,
                FENCE_HEIGHT - 0.08, FENCE_HEIGHT,
                0.08, 0)
        cursor = end
    add_fence_span(vertices, faces, material_indices, a, b, cursor, 1.0)
    if not faces:
        return

    mesh = bpy.data.meshes.new("Malla_Cerca_Contorno_%02d" % edge_index)
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(materials[0])
    mesh.materials.append(materials[1])
    mesh.update()
    for polygon, material_index in zip(mesh.polygons, material_indices):
        polygon.material_index = material_index

    fence = bpy.data.objects.new("CERCA_CONTORNO_%02d" % edge_index, mesh)
    collection.objects.link(fence)
    fence.location.z = z
    fence["tipo"] = "malla_metalica_perimetral"
    fence["altura"] = FENCE_HEIGHT
    fence["aberturas"] = len(openings)


def main():
    road_paths = collect_road_fence_paths()
    base = bpy.data.objects.get(BASE_OBJECT_NAME)
    if base is None or base.type != "MESH":
        raise RuntimeError("Falta el terreno de 01. Ejecuta 01_base_terreno.py primero.")
    if len(base.data.vertices) < 6 or len(base.data.vertices) % 2:
        raise RuntimeError("El terreno no tiene la malla de anillos que espera 08_PERIMETRO.")

    ring_size = len(base.data.vertices) // 2
    outline = []
    top_z = float("-inf")
    for vertex in base.data.vertices[ring_size:]:
        point = base.matrix_world @ vertex.co
        outline.append((point.x, point.y))
        top_z = max(top_z, point.z)
    if len(outline) < 3:
        raise RuntimeError("El contorno necesita al menos tres vértices.")

    collection = ensure_collection()
    clear_generated_fence(collection)
    materials = (
        make_material("Material_Cerca_Metal", (0.12, 0.15, 0.14), 0.58, 0.72),
        make_material("Material_Cerca_Malla", (0.20, 0.23, 0.21), 0.72, 0.48),
    )
    openings = collect_gate_openings(outline)
    for index, a in enumerate(outline):
        build_edge_object(
            collection, index, a, outline[(index + 1) % len(outline)], top_z,
            openings.get(index, ()), materials,
        )

    road_openings = collect_road_fence_openings(road_paths)
    road_fence_count = build_road_fences(
        collection, road_paths, materials, road_openings
    )
    gate_count = sum(len(spans) for spans in openings.values())
    print("CERCA PERIMETRAL: %d tramos | %d accesos | altura %.1f m" %
          (len(outline), gate_count, FENCE_HEIGHT))
    print("MALLA DE CAMINOS: %d tramos | %d accesos | un lado | altura %.1f m" %
          (road_fence_count, sum(len(v) for v in road_openings.values()),
           ROAD_FENCE_HEIGHT))
    if gate_count == 0:
        print("AVISO: no se detectaron caminos junto al borde; la cerca queda cerrada.")


main()
