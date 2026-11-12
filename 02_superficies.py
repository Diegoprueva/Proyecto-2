
import bpy
import math
from mathutils import Vector

# ==========================================
# ZOOLOGICO NICOLAS BRAVO
# MODULO 02 - SUPERFICIES
# ==========================================

COLLECTION_NAME = "02_SUPERFICIES"
BASE_OBJECT_NAME = "BASE_ZOOLOGICO_NICOLAS_BRAVO"
SURFACE_OBJECT_NAME = "SUPERFICIE_EXPLANADA_PRINCIPAL"
SURFACE_LIFT = 0.045

# ------------------------------------------
# VALIDAR REFERENCIA DEL TERRENO
# ------------------------------------------
def validate_explanada(base):
    coords = list(base.get("explanada", []))
    if len(coords) < 6 or len(coords) % 2:
        raise RuntimeError("El terreno no contiene una propiedad 'explanada' válida. Ejecuta 01 primero.")

    points = [(float(coords[i]), float(coords[i + 1])) for i in range(0, len(coords), 2)]
    if not all(math.isfinite(value) for point in points for value in point):
        raise RuntimeError("La referencia de la explanada contiene coordenadas inválidas.")
    area = sum(points[i][0] * points[(i + 1) % len(points)][1] -
               points[(i + 1) % len(points)][0] * points[i][1]
               for i in range(len(points))) / 2.0
    if not math.isfinite(area) or abs(area) < 1e-6:
        raise RuntimeError("La explanada del terreno tiene un área inválida.")
    return points, area


def make_court_material():
    name = "Material_Cancha_Blanca"
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (520, 0)
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.location = (280, 0)
    shader.inputs["Roughness"].default_value = 0.86

    tex_coord = nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-620, 0)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-360, 80)
    noise.inputs["Scale"].default_value = 6.0
    noise.inputs["Detail"].default_value = 2.0
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-90, 80)
    ramp.color_ramp.elements[0].color = (0.67, 0.67, 0.65, 1.0)
    ramp.color_ramp.elements[1].color = (0.84, 0.84, 0.81, 1.0)

    bump = nodes.new("ShaderNodeBump")
    bump.location = (60, -150)
    bump.inputs["Strength"].default_value = 0.08
    bump.inputs["Distance"].default_value = 0.01

    links = material.node_tree.links
    links.new(tex_coord.outputs["Object"], noise.inputs["Vector"])
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], shader.inputs["Base Color"])
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    material.diffuse_color = (0.78, 0.78, 0.75, 1.0)
    return material

def ensure_collection():
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)

    linked = {child.name for child in bpy.context.scene.collection.children_recursive}
    if collection.name not in linked:
        bpy.context.scene.collection.children.link(collection)
    return collection


base = bpy.data.objects.get(BASE_OBJECT_NAME)
if base is None or base.type != 'MESH':
    raise RuntimeError("Falta el terreno de 01. Ejecuta 01_base_terreno.py antes de este módulo.")

points, area = validate_explanada(base)
collection = ensure_collection()
surface = collection.objects.get(SURFACE_OBJECT_NAME)
if surface is not None:
    mesh = surface.data if surface.type == 'MESH' else None
    bpy.data.objects.remove(surface, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)

top_z = max(vertex.co.z for vertex in base.data.vertices)
world_vertices = []
for x, y in points:
    point = base.matrix_world @ Vector((x, y, top_z))
    point.z += SURFACE_LIFT
    world_vertices.append(tuple(point))

face = tuple(range(len(world_vertices)))
if area < 0.0:
    face = tuple(reversed(face))
mesh = bpy.data.meshes.new("Malla_Cancha_Blanca")
mesh.from_pydata(world_vertices, [], [face])
mesh.materials.append(make_court_material())
mesh.update()

surface = bpy.data.objects.new(SURFACE_OBJECT_NAME, mesh)
collection.objects.link(surface)
surface["tipo"] = "cancha_blanca"
surface["area_estimada_m2"] = abs(area)
surface["fuente"] = "coordenadas obj['explanada'] de 01_BASE_TERRENO"
solidify = surface.modifiers.new("Espesor_Pavimento", "SOLIDIFY")
solidify.thickness = 0.08
solidify.offset = -1.0

print("MODULO 02 - CANCHA BLANCA: %.0f m2 | concreto claro" % abs(area))
