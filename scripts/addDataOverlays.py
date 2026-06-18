"""
Add AR-style data overlays to Blender scene based on multipatch properties.

Features:
1. Building flood colors - Color buildings based on flood depth, per scenario
2. Asset rings - Glowing rings at base of critical assets
3. Asset labels - Floating text labels for critical assets
4. Dynamic Visibility - Smooth cinematic alpha fading for labels/lines/rings based on distance
"""

import bpy
import bpy_extras
import os
import json
import math
import mathutils
import bmesh
import re

# --- Configuration ---
state                = globals().get('state')
county               = globals().get('county')
site_num             = globals().get('siteNum')
project_name         = globals().get('project_name')
data_overlays_config = globals().get('data_overlays', {})
color_ramp_config    = globals().get('color_ramp', {})
flood_scenario       = globals().get('flood_scenario', None)

default_properties_path = f"/Users/noahdewar/Documents/HighTide/data/{state}/projects/{project_name}/blender/site{site_num}/multipatch_properties_Site{site_num}.json"
properties_path = data_overlays_config.get('properties_path', 'auto')
if properties_path == 'auto':
    properties_path = default_properties_path


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------

def robust_get_props(properties, obj):
    # 1. Try an exact name match first
    props = properties.get(obj.name, {})
    #print(obj)
    # 2. If empty, try extracting a UUID (handles Blender suffixes like .001)
    if not props:
        # Matches the standard 8-4-4-4-12 UUID format
        uuid_match = re.search(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', obj.name)
        if uuid_match:
            clean_id = uuid_match.group()
            
            # Check both uppercase and lowercase, just in case the JSON dictionary 
            # formatted the UUID letters differently than Blender did
            props = properties.get(clean_id, {})
            if not props:
                props = properties.get(clean_id.upper(), {})
            if not props:
                props = properties.get(clean_id.lower(), {})
            
    # 3. If STILL empty, fall back to basic numbers (for older legacy workflows)
    if not props:
        num_match = re.search(r'\d+', obj.name)
        if num_match:
            clean_id = num_match.group()
            props = properties.get(clean_id, {})
            
    return props

def load_properties(state: str = '', project_name: str = '', site_num: str = ''):
    if not os.path.exists(properties_path):
        print(f"  [!] Properties file not found: {properties_path}")
        fallback_properties_path = f"/Users/noahdewar/Documents/HighTide/data/{state}/projects/{project_name}/blender/site{site_num}/multipatch_properties_Site{site_num}.json"
        if not os.path.exists(fallback_properties_path):
            print(f"  [!] Properties file not found: {fallback_properties_path}")
            return {}
        else:
            with open(fallback_properties_path, 'r') as f:
                properties = json.load(f)
    else:
        with open(properties_path, 'r') as f:
            properties = json.load(f)
    print(f"  Loaded properties for {len(properties)} objects (Legacy Workflow)")
    return properties


def get_base_name(obj_name):
    if '.' in obj_name:
        parts = obj_name.rsplit('.', 1)
        if parts[1].isdigit():
            return parts[0]
    return obj_name


def interpolate_color(value, min_depth, max_depth, color_values):
    if not color_values:
        return (0.5, 0.5, 0.5, 1.0)

    if max_depth == min_depth:
        normalized = 0.0
    else:
        normalized = (value - min_depth) / (max_depth - min_depth)
    normalized = max(0.0, min(1.0, normalized))

    ramp = sorted(color_values, key=lambda x: x['position'])

    if normalized <= ramp[0]['position']:
        c = ramp[0]['color']
        return (c[0], c[1], c[2], 1.0)
    if normalized >= ramp[-1]['position']:
        c = ramp[-1]['color']
        return (c[0], c[1], c[2], 1.0)

    for i in range(len(ramp) - 1):
        if ramp[i]['position'] <= normalized <= ramp[i + 1]['position']:
            t = (normalized - ramp[i]['position']) / (ramp[i + 1]['position'] - ramp[i]['position'])
            c1, c2 = ramp[i]['color'], ramp[i + 1]['color']
            return (
                c1[0] + t * (c2[0] - c1[0]),
                c1[1] + t * (c2[1] - c1[1]),
                c1[2] + t * (c2[2] - c1[2]),
                1.0
            )

    return (0.5, 0.5, 0.5, 1.0)


# ------------------------------------------------------------------
# Building flood colors
# ------------------------------------------------------------------

def create_flood_material(name, color):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (300, 0)

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Roughness'].default_value = 0.5

    mat.node_tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    return mat

def apply_building_flood_colors(properties, passed_config, color_ramp_config, scenario='noFlood'):
    config = passed_config.get('building_flood_colors', {})
    if not config.get('enabled', False):
        print("  Building flood colors: disabled")
        return

    scenario = str(scenario).replace('floodmap_','').split('_site')[0]
    min_depth    = color_ramp_config['min_depth']
    max_depth    = color_ramp_config['max_depth']
    color_values = color_ramp_config['values']
    material_cache = {}
    colored_count  = 0

    target_objects = [
        obj for obj in bpy.data.objects 
        if obj.type == 'MESH' 
        and 'dem' not in obj.name.lower()
        and not obj.name.startswith("Ring_") 
        and not obj.name.startswith("Card_")
    ]
    total_objs = len(target_objects)

    print(f"  Coloring Buildings ({scenario})...")
    for i, obj in enumerate(target_objects):
        
        # --- Built-in Progress Tracker ---
        if i % 50 == 0 or i == total_objs - 1:
            print(f"\r    Progress: {i+1}/{total_objs} ({(i+1)/total_objs*100:.1f}%)", end="", flush=True)
            
        props = robust_get_props(properties, obj)
            
        raw_depth = obj.get(scenario)
        if raw_depth is None:
            raw_depth = props.get(scenario)
            
        if raw_depth is None or raw_depth < 0.0001:
            continue

        flood_depth = float(raw_depth or 0)
        obj['flood_depth'] = flood_depth
        obj['scenario']    = scenario

        color        = interpolate_color(flood_depth, min_depth, max_depth, color_values)
        depth_bucket = round(flood_depth * 2) / 2
        mat_name = f"FloodDepth_{scenario}_{depth_bucket:.1f}"

        if mat_name not in material_cache:
            material_cache[mat_name] = create_flood_material(mat_name, color)
        
        obj.data.materials.clear()
        obj.data.materials.append(material_cache[mat_name])
        colored_count += 1

    print(f"\n  Colored {colored_count} buildings for scenario '{scenario}'")
# ------------------------------------------------------------------
# Asset rings
# ------------------------------------------------------------------

def create_ring_material(name, color, glow_strength=10.0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)

    mat.use_nodes = True
    if hasattr(mat, "blend_method"):
        mat.blend_method = 'BLEND'
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = 'NONE'
    
    nodes = mat.node_tree.nodes
    nodes.clear()

    output      = nodes.new('ShaderNodeOutputMaterial')
    emission    = nodes.new('ShaderNodeEmission')
    transparent = nodes.new('ShaderNodeBsdfTransparent')
    mix_shader  = nodes.new('ShaderNodeMixShader')
    attr        = nodes.new('ShaderNodeAttribute')
    
    attr.attribute_type = 'OBJECT'
    attr.attribute_name = "fade_alpha"
    
    emission.inputs['Color'].default_value    = (color[0], color[1], color[2], 1.0)
    emission.inputs['Strength'].default_value = glow_strength

    links = mat.node_tree.links
    links.new(transparent.outputs['BSDF'], mix_shader.inputs[1])
    links.new(emission.outputs['Emission'], mix_shader.inputs[2])
    links.new(attr.outputs['Fac'], mix_shader.inputs[0])
    links.new(mix_shader.outputs['Shader'], output.inputs['Surface'])

    mat.diffuse_color = (color[0], color[1], color[2], 1.0)
    return mat


def get_building_footprint_radius(obj):
    bbox = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
    min_x, max_x = min(v.x for v in bbox), max(v.x for v in bbox)
    min_y, max_y = min(v.y for v in bbox), max(v.y for v in bbox)
    return max(max_x - min_x, max_y - min_y) / 2 * 1.2


def get_building_base_center(obj):
    bbox = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
    return (sum(v.x for v in bbox) / 8, sum(v.y for v in bbox) / 8, min(v.z for v in bbox))


def get_building_top_center(obj):
    bbox = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
    return (sum(v.x for v in bbox) / 8, sum(v.y for v in bbox) / 8, max(v.z for v in bbox))


def apply_asset_rings(properties):
    config = data_overlays_config.get('asset_rings', {})
    if not config.get('enabled', False):
        print("  Asset rings: disabled")
        return

    glow_strength = config.get('glow_strength', 10.0)
    ring_height   = config.get('ring_height', 1.0)
    minor_rad     = ring_height / 2.0  # This is the actual thickness of the ring
    max_distance  = data_overlays_config.get('asset_labels', {}).get('max_distance', 2000.0)
    class_colors  = config['class_colors']

    ring_collection = bpy.data.collections.get("Asset_Rings") or bpy.data.collections.new("Asset_Rings")
    if ring_collection.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(ring_collection)

    material_cache = {}
    torus_mesh_cache = {}  # Cache meshes based on rounded size to save RAM
    ring_count     = 0

    # Ensure we don't accidentally process previously generated rings/cards
    target_objects = [
        obj for obj in bpy.data.objects 
        if obj.type == 'MESH' 
        and 'dem' not in obj.name.lower()
        and not obj.name.startswith("Ring_") 
        and not obj.name.startswith("Card_")
    ]
    total_objs = len(target_objects)

    print("  Generating Asset Rings...")
    for i, obj in enumerate(target_objects):
        
        if i % 50 == 0 or i == total_objs - 1:
            print(f"\r    Progress: {i+1}/{total_objs} ({(i+1)/total_objs*100:.1f}%)", end="", flush=True)
            
        # --- NEW: Robust UUID & Legacy Property Lookup ---
        props = robust_get_props(properties, obj)
        
        # 4. Expanded fallback list for legacy column names
        ca_id = (
            obj.get('CA_ID') or props.get('CA_ID') or 
            obj.get('HighTideID') or props.get('HighTideID') or
            props.get('Asset_ID')
        )
        ca_class = obj.get('CA_Class') or props.get('CA_Class') or obj.get('AssetClass') or props.get('AssetClass')
        if ca_class == 'NCH' and project_name == 'FloridaDemo_Internal_2026':
            continue
        if not ca_id or not ca_class or f"Ring_{obj.name}" in bpy.data.objects:
            continue
        
        color = class_colors.get(ca_class, class_colors.get('default', [1.0, 1.0, 1.0]))
        mat_name = f"RingMaterial_{ca_class.replace(' ', '_')}"
        if mat_name not in material_cache:
            material_cache[mat_name] = create_ring_material(mat_name, color, glow_strength)

        base_pos = get_building_base_center(obj)
        exact_radius = get_building_footprint_radius(obj)
        hover_z  = base_pos[2] + minor_rad + 0.5

        # Round the radius to the nearest 0.5 meters (so we can reuse the same mesh data)
        rounded_radius = round(exact_radius * 2) / 2.0
        if rounded_radius < 0.5:
            rounded_radius = 0.5
            
        if rounded_radius not in torus_mesh_cache:
            torus_mesh_cache[rounded_radius] = generate_torus_mesh(
                name=f"BaseRingMesh_{rounded_radius}",
                major_radius=rounded_radius,
                minor_radius=minor_rad, # Thickness is now completely independent and protected!
                major_segments=48,
                minor_segments=12
            )

        # Create new object pointing to perfectly sized mesh
        ring_obj = bpy.data.objects.new(f"Ring_{obj.name}", torus_mesh_cache[rounded_radius])
        ring_obj.location = (base_pos[0], base_pos[1], hover_z)
        
        # WE NO LONGER SCALE THE OBJECT. The mesh is natively the exact right size!
        ring_obj.scale = (1.0, 1.0, 1.0) 
        
        ring_obj['CA_Class']        = ca_class
        ring_obj['CA_Name']         = obj.get('CA_Name') or props.get('CA_Name') or obj.get('AssetName') or props.get('AssetName') or ""
        ring_obj['parent_building'] = obj.name
        ring_obj['fade_alpha']      = 1.0
        ring_obj['max_distance']    = max_distance

        ring_collection.objects.link(ring_obj)
        ring_obj.data.materials.append(material_cache[mat_name])
        ring_count += 1

    print(f"\n  Created {ring_count} asset rings")


# ------------------------------------------------------------------
# Asset labels
# ------------------------------------------------------------------
def generate_torus_mesh(name, major_radius, minor_radius, major_segments=48, minor_segments=12):
    verts = []
    faces = []
    
    # Generate vertices
    for i in range(major_segments):
        u = i * 2 * math.pi / major_segments
        for j in range(minor_segments):
            v = j * 2 * math.pi / minor_segments
            
            x = (major_radius + minor_radius * math.cos(v)) * math.cos(u)
            y = (major_radius + minor_radius * math.cos(v)) * math.sin(u)
            z = minor_radius * math.sin(v)
            verts.append((x, y, z))
            
            # Generate faces (quads)
            next_i = (i + 1) % major_segments
            next_j = (j + 1) % minor_segments
            
            v0 = i * minor_segments + j
            v1 = next_i * minor_segments + j
            v2 = next_i * minor_segments + next_j
            v3 = i * minor_segments + next_j
            
            faces.append((v0, v1, v2, v3))
            
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    return mesh

def create_label_backing(name, text_obj, local_w, local_h, padding, material, collection):
    card_w = local_w + (padding * 2)
    
    verts = [
        (-card_w / 2, -padding,         0),
        ( card_w / 2, -padding,         0),
        ( card_w / 2, local_h + padding, 0),
        (-card_w / 2, local_h + padding, 0),
    ]
    faces = [(0, 1, 2, 3)]

    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(verts, [], faces)

    card_obj = bpy.data.objects.new(name, mesh)
    card_obj['fade_alpha']   = 1.0
    card_obj['max_distance'] = text_obj.get('max_distance', 2000.0)

    collection.objects.link(card_obj)

    bevel_mod = card_obj.modifiers.new(name="Rounded_Corners", type='BEVEL')
    bevel_mod.affect = 'VERTICES'
    bevel_mod.width = padding * 0.75
    bevel_mod.segments = 4 

    card_obj.parent   = text_obj
    card_obj.location = (0, 0, -0.1) 

    if material:
        card_obj.data.materials.append(material)

    return card_obj


def create_backing_material(name="LabelBackingMaterial"):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
    mat.use_nodes = True
    if hasattr(mat, "blend_method"):
        mat.blend_method = 'BLEND'
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = 'NONE'
    
    nodes = mat.node_tree.nodes
    nodes.clear()

    output      = nodes.new('ShaderNodeOutputMaterial')
    bsdf        = nodes.new('ShaderNodeBsdfPrincipled')
    transparent = nodes.new('ShaderNodeBsdfTransparent')
    mix_shader  = nodes.new('ShaderNodeMixShader')
    attr        = nodes.new('ShaderNodeAttribute')
    
    attr.attribute_type = 'OBJECT'
    attr.attribute_name = "fade_alpha"
    
    bsdf.inputs['Base Color'].default_value = (0.02, 0.02, 0.05, 1.0)
    bsdf.inputs['Roughness'].default_value  = 1.0
    bsdf.inputs['Alpha'].default_value      = 0.90

    links = mat.node_tree.links
    links.new(transparent.outputs['BSDF'], mix_shader.inputs[1])
    links.new(bsdf.outputs['BSDF'], mix_shader.inputs[2])
    links.new(attr.outputs['Fac'], mix_shader.inputs[0])
    links.new(mix_shader.outputs['Shader'], output.inputs['Surface'])

    mat.use_transparency_overlap = True
    try:
        mat.diffuse_color = (0.02, 0.02, 0.05, 0.90)
    except Exception:
        pass

    return mat


def create_label_material(name="LabelMaterial", color=(1.0, 1.0, 1.0)):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
    mat.use_nodes = True
    if hasattr(mat, "blend_method"): mat.blend_method = 'BLEND'
    if hasattr(mat, "shadow_method"): mat.shadow_method = 'NONE'
    
    nodes = mat.node_tree.nodes
    nodes.clear()

    output      = nodes.new('ShaderNodeOutputMaterial')
    emission    = nodes.new('ShaderNodeEmission')
    transparent = nodes.new('ShaderNodeBsdfTransparent')
    mix_shader  = nodes.new('ShaderNodeMixShader')
    
    alpha_attr  = nodes.new('ShaderNodeAttribute')
    alpha_attr.attribute_type = 'OBJECT'
    alpha_attr.attribute_name = "fade_alpha"
    
    glow_attr   = nodes.new('ShaderNodeAttribute')
    glow_attr.attribute_type  = 'OBJECT'
    glow_attr.attribute_name  = "glow_multiplier"
    
    math_node   = nodes.new('ShaderNodeMath')
    math_node.operation = 'MULTIPLY'
    math_node.inputs[1].default_value = 3.0 

    emission.inputs['Color'].default_value = (color[0], color[1], color[2], 1.0)

    links = mat.node_tree.links
    links.new(glow_attr.outputs['Fac'], math_node.inputs[0])
    links.new(math_node.outputs['Value'], emission.inputs['Strength'])
    links.new(transparent.outputs['BSDF'], mix_shader.inputs[1])
    links.new(emission.outputs['Emission'], mix_shader.inputs[2])
    links.new(alpha_attr.outputs['Fac'], mix_shader.inputs[0])
    links.new(mix_shader.outputs['Shader'], output.inputs['Surface'])
    
    return mat


def create_line_material(name="Asset_Line_Material", color=(1.0, 1.0, 1.0)):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
    mat.use_nodes = True
    if hasattr(mat, "blend_method"): mat.blend_method = 'BLEND'
    if hasattr(mat, "shadow_method"): mat.shadow_method = 'NONE'
    
    nodes = mat.node_tree.nodes
    nodes.clear()

    output      = nodes.new('ShaderNodeOutputMaterial')
    emission    = nodes.new('ShaderNodeEmission')
    transparent = nodes.new('ShaderNodeBsdfTransparent')
    mix_shader  = nodes.new('ShaderNodeMixShader')
    
    alpha_attr  = nodes.new('ShaderNodeAttribute')
    alpha_attr.attribute_type = 'OBJECT'
    alpha_attr.attribute_name = "fade_alpha"
    
    glow_attr   = nodes.new('ShaderNodeAttribute')
    glow_attr.attribute_type  = 'OBJECT'
    glow_attr.attribute_name  = "glow_multiplier"
    
    math_node   = nodes.new('ShaderNodeMath')
    math_node.operation = 'MULTIPLY'
    math_node.inputs[1].default_value = 3.0

    emission.inputs['Color'].default_value = (color[0], color[1], color[2], 1.0)

    links = mat.node_tree.links
    links.new(glow_attr.outputs['Fac'], math_node.inputs[0])
    links.new(math_node.outputs['Value'], emission.inputs['Strength'])
    links.new(transparent.outputs['BSDF'], mix_shader.inputs[1])
    links.new(emission.outputs['Emission'], mix_shader.inputs[2])
    links.new(alpha_attr.outputs['Fac'], mix_shader.inputs[0])
    links.new(mix_shader.outputs['Shader'], output.inputs['Surface'])
    
    return mat


def create_dynamic_label_driver(text_obj, camera, reference_distance, min_scale=0.1, max_scale=10.0, growth_speed=1.5):
    if text_obj.data.animation_data:
        text_obj.data.animation_data_clear()
    if text_obj.animation_data:
        text_obj.animation_data_clear()

    expression = (
        f'max({min_scale:.4f}, min({max_scale:.4f}, '
        f'1.0 + (((((cam_x-lbl_x)**2 + (cam_y-lbl_y)**2 + (cam_z-lbl_z)**2)**0.5) '
        f'/ {reference_distance:.4f}) - 1.0) * {growth_speed:.4f}))'
    )

    for scale_index in [0, 1]:
        driver_obj = text_obj.driver_add('scale', scale_index)
        drv        = driver_obj.driver
        drv.type   = 'SCRIPTED'

        for axis in ['x', 'y', 'z']:
            var                            = drv.variables.new()
            var.name                       = f'cam_{axis}'
            var.type                       = 'TRANSFORMS'
            var.targets[0].id              = camera
            var.targets[0].transform_type  = f'LOC_{axis.upper()}'
            var.targets[0].transform_space = 'WORLD_SPACE'

        for axis in ['x', 'y', 'z']:
            var                            = drv.variables.new()
            var.name                       = f'lbl_{axis}'
            var.type                       = 'TRANSFORMS'
            var.targets[0].id              = text_obj
            var.targets[0].transform_type  = f'LOC_{axis.upper()}'
            var.targets[0].transform_space = 'WORLD_SPACE'

        drv.expression = expression


def create_smooth_curve_callout(name, start_pos, end_pos, thickness, material, collection=None):
    curve_data = bpy.data.curves.new(name=name, type='CURVE')
    curve_data.dimensions = '3D'
    curve_data.fill_mode = 'FULL'
    curve_data.bevel_depth = thickness
    curve_data.bevel_resolution = 2 
    curve_data.resolution_u = 6     

    sx, sy, sz = start_pos
    ex, ey, ez = end_pos
    dx, dy, dz = ex - sx, ey - sy, ez - sz

    spline = curve_data.splines.new(type='BEZIER')
    spline.bezier_points.add(1)

    p0, p1 = spline.bezier_points[0], spline.bezier_points[1]
    p0.co = (0, 0, 0)
    p0.handle_left_type = p0.handle_right_type = 'FREE'
    p0.handle_right = (0, 0, dz * 0.5) 

    p1.co = (dx, dy, dz)
    p1.handle_left_type = p1.handle_right_type = 'FREE'
    p1.handle_left = (dx, dy, dz * 0.5) 

    line_obj = bpy.data.objects.new(name, curve_data)
    line_obj.location = mathutils.Vector(start_pos)
    
    if collection:
        collection.objects.link(line_obj)

    if material:
        line_obj.data.materials.append(material)

    return line_obj


def apply_asset_labels(properties, passed_data_overlays_config, camera=None):
    config = passed_data_overlays_config.get('asset_labels', {})

    if not config.get('enabled', False):
        print("  Asset labels: disabled")
        return

    camera = camera or bpy.context.scene.camera
    if not camera:
        print("  [!] No camera — skipping labels")
        return
    
    collections_to_clean = ["Asset_Labels", "Asset_Lines"]
    for coll_name in collections_to_clean:
        collection = bpy.data.collections.get(coll_name)
        if collection:
            for obj in list(collection.objects):
                obj_data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if obj_data:
                    if isinstance(obj_data, bpy.types.Mesh):
                        bpy.data.meshes.remove(obj_data, do_unlink=True)
                    elif isinstance(obj_data, (bpy.types.TextCurve, bpy.types.Curve)):
                        bpy.data.curves.remove(obj_data, do_unlink=True)

    dem_obj    = next((o for o in bpy.data.objects if 'dem' in o.name.lower() and o.type == 'MESH'), None)
    scene_size = max(dem_obj.dimensions) if dem_obj else 10000.0

    reference_distance = config.get('reference_distance', 500.0)
    base_size          = config.get('base_size',          5.0)
    min_size           = config.get('min_size',           5.0)
    max_size           = config.get('max_size',           100.0)
    
    min_scale          = min_size / base_size if base_size > 0 else 0.1
    max_scale          = max_size / base_size if base_size > 0 else 10.0
    growth_speed       = config.get('growth_speed',       0.25) 

    overlap_radius     = config.get('overlap_radius',     base_size * 2.5)
    stack_spacing      = config.get('stack_spacing',      base_size * 1.5)
    line_thickness     = config.get('line_thickness',     scene_size * 0.0001)
    max_distance       = config.get('max_distance',       2000.0)

    min_height_offset = config.get('min_height_offset', 20.0)
    max_height_offset = config.get('max_height_offset', 150.0)
    height_ref_low    = config.get('height_ref_low',    50.0)
    height_ref_high   = config.get('height_ref_high',   800.0)

    backing_mat = create_backing_material()

    cam_z         = camera.matrix_world.translation.z
    height_t      = max(0.0, min(1.0, (cam_z - height_ref_low) / (height_ref_high - height_ref_low)))
    height_offset = min_height_offset + height_t * (max_height_offset - min_height_offset)

    label_collection = bpy.data.collections.get("Asset_Labels") or bpy.data.collections.new("Asset_Labels")
    line_collection  = bpy.data.collections.get("Asset_Lines")  or bpy.data.collections.new("Asset_Lines")
    
    if label_collection.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(label_collection)
    if line_collection.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(line_collection)

    ring_config = passed_data_overlays_config.get('asset_rings', {})
    class_colors = ring_config['class_colors']

    label_materials = {}
    line_materials  = {}
    placed_labels   = []
    label_count     = 0

    target_objects = [
        obj for obj in bpy.data.objects 
        if obj.type == 'MESH' 
        and 'dem' not in obj.name.lower()
        and not obj.name.startswith("Ring_") 
        and not obj.name.startswith("Card_")
    ]
    text_objects_to_back = []
    total_objs = len(target_objects)

    print("  Generating Labels (Pass 1)...")
    #print(properties)
    for i, obj in enumerate(target_objects):
        
        # --- Built-in Progress Tracker ---
        if i % 50 == 0 or i == total_objs - 1:
            print(f"\r    Progress: {i+1}/{total_objs} ({(i+1)/total_objs*100:.1f}%)", end="", flush=True)
            
        # --- NEW: Robust UUID & Legacy Property Lookup ---
        props = robust_get_props(properties, obj)

        # 4. Expanded fallback list for legacy column names
        ca_id = (
            obj.get('CA_ID') or props.get('CA_ID') or 
            obj.get('HighTideID') or props.get('HighTideID') or
            props.get('ID') or props.get('OBJECTID') or
            props.get('Asset_ID')
        )
        ca_name  = obj.get('CA_Name') or props.get('CA_Name') or obj.get('AssetName') or props.get('AssetName')
        ca_class = obj.get('CA_Class') or props.get('CA_Class') or obj.get('AssetClass') or props.get('AssetClass')
        if not ca_id or not ca_class or f"Label_{obj.name}" in bpy.data.objects:
            continue

        if ca_class == 'NCH' and project_name == 'FloridaDemo_Internal_2026':
            continue
            
        top_pos   = get_building_top_center(obj)
        target_x, target_y = top_pos[0], top_pos[1]
        current_z = top_pos[2] + height_offset

        for pl in placed_labels:
            if abs(target_x - pl['x']) < overlap_radius and abs(target_y - pl['y']) < overlap_radius:
                current_z = max(current_z, pl['top_z'] + stack_spacing)

        label_pos = (target_x, target_y, current_z)
        placed_labels.append({'x': target_x, 'y': target_y, 'top_z': current_z})

        color = class_colors.get(ca_class, class_colors.get('default', [1.0, 1.0, 1.0]))
        lbl_mat_name, lin_mat_name = f"LabelMaterial_{ca_class.replace(' ', '_')}", f"LineMaterial_{ca_class.replace(' ', '_')}"

        if lbl_mat_name not in label_materials: label_materials[lbl_mat_name] = create_label_material(lbl_mat_name, color)
        if lin_mat_name not in line_materials:  line_materials[lin_mat_name]  = create_line_material(lin_mat_name, color)

        font_curve = bpy.data.curves.new(type='FONT', name=f"FontCurve_{obj.name}")
        font_curve.body    = str(ca_name)
        font_curve.size    = base_size
        font_curve.align_x = 'CENTER'
        font_curve.align_y = 'BOTTOM'
        font_curve.extrude = base_size * 0.02
        
        text_obj = bpy.data.objects.new(f"Label_{obj.name}", font_curve)
        text_obj.location = label_pos
        label_collection.objects.link(text_obj)
        text_obj.data.materials.append(label_materials[lbl_mat_name])

        track            = text_obj.constraints.new('TRACK_TO')
        track.target     = camera
        track.track_axis = 'TRACK_Z'
        track.up_axis    = 'UP_Y'

        create_dynamic_label_driver(
            text_obj, camera, reference_distance=reference_distance,
            min_scale=min_scale, max_scale=max_scale, growth_speed=growth_speed
        )
        
        line_obj = create_smooth_curve_callout(
            name=f"Line_{obj.name}", start_pos=top_pos, end_pos=label_pos,
            thickness=line_thickness, material=line_materials[lin_mat_name], collection=line_collection
        )

        text_obj['fade_alpha'] = text_obj['glow_multiplier'] = 1.0
        line_obj['fade_alpha'] = line_obj['glow_multiplier'] = 1.0
        text_obj['max_distance'] = line_obj['max_distance'] = max_distance
        text_obj['parent_building'] = line_obj['parent_building'] = obj.name
        
        text_objects_to_back.append((obj.name, text_obj))
        label_count += 1

    print(f"\n  Created {label_count} labels. Calculating exact dimensions...")
    
    # --- UPDATE VIEW LAYER EXACTLY ONCE ---
    bpy.context.view_layer.update()

    total_cards = len(text_objects_to_back)
    print("  Building Cards (Pass 2)...")
    
    # --- PASS 2: Generate Exact Backing Cards ---
    for i, (parent_name, text_obj) in enumerate(text_objects_to_back):
        
        # --- Built-in Progress Tracker ---
        if i % 10 == 0 or i == total_cards - 1:
            print(f"\r    Progress: {i+1}/{total_cards} ({(i+1)/total_cards*100:.1f}%)", end="", flush=True)

        bound_box = text_obj.bound_box
        local_w = max(v[0] for v in bound_box) - min(v[0] for v in bound_box)
        local_h = max(v[1] for v in bound_box) - min(v[1] for v in bound_box)

        create_label_backing(
            name=f"Card_{parent_name}", 
            text_obj=text_obj, 
            local_w=local_w,
            local_h=local_h,
            padding=base_size * 0.15,
            material=backing_mat, 
            collection=label_collection
        )

    print("\n  Finished generating exact backing cards.")

# ------------------------------------------------------------------
# Dynamic visibility
# ------------------------------------------------------------------

def update_label_visibility(scene, depsgraph):
    camera = scene.camera
    if not camera:
        return

    # Grab configs to dictate the fade and glow distances
    raw_fade_margin = data_overlays_config.get('fade_margin', 500.0)
    ref_distance    = data_overlays_config.get('asset_labels', {}).get('reference_distance', 500.0)

    def process_object_visibility(obj, alpha_val):
        if not obj:
            return
        obj["fade_alpha"] = max(0.0, min(1.0, alpha_val))
        visible = (alpha_val > 0.0)
        obj.hide_render   = not visible
        obj.hide_viewport = not visible

    # Handle Labels, Lines, and Cards
    label_collection = bpy.data.collections.get("Asset_Labels")
    if label_collection:
        for text_obj in label_collection.objects:
            if text_obj.type != 'FONT':
                continue

            base_name = text_obj.name.replace("Label_", "")
            line_obj  = bpy.data.objects.get(f"Line_{base_name}")
            card_obj  = bpy.data.objects.get(f"Card_{base_name}")

            max_distance = text_obj.get('max_distance', 2000.0)
            cam_dist     = (camera.matrix_world.translation - text_obj.location).length
            
            # --- FIXED MARGIN MATH ---
            actual_margin = min(raw_fade_margin, max_distance * 0.9)
            if actual_margin <= 0.0:
                actual_margin = 1.0 
            fade_start = max_distance - actual_margin

            # Distance Fade Calculation
            alpha = 1.0
            if cam_dist >= max_distance:
                alpha = 0.0
            elif cam_dist > fade_start:
                alpha = 1.0 - ((cam_dist - fade_start) / actual_margin)

            # Scale glow based on distance to fight anti-aliasing dimming
            glow_mult = max(1.0, cam_dist / ref_distance)
            text_obj["glow_multiplier"] = glow_mult
            if line_obj:
                line_obj["glow_multiplier"] = glow_mult

            if alpha > 0.0:
                # Frustum/margin check
                co2d   = bpy_extras.object_utils.world_to_camera_view(scene, camera, text_obj.location)
                screen_margin = 0.25
                if not (-screen_margin <= co2d.x <= 1.0 + screen_margin and
                        -screen_margin <= co2d.y <= 1.0 + screen_margin and
                        co2d.z > 0.0):
                    alpha = 0.0
                else:
                    # Raycast occlusion check
                    ray_origin  = camera.matrix_world.translation.copy()
                    ray_target  = mathutils.Vector(text_obj.location)
                    ray_dir     = ray_target - ray_origin
                    ray_dist    = ray_dir.length
                    ray_dir.normalize()
                    ray_origin += ray_dir * 0.1

                    hit, loc, _, _, hit_obj, _ = scene.ray_cast(depsgraph, ray_origin, ray_dir)

                    if hit:
                        hit_dist    = (loc - ray_origin).length
                        parent_name = text_obj.get('parent_building', '')
                        line_name   = line_obj.name if line_obj else ''
                        card_name   = card_obj.name if card_obj else ''
                        if (hit_dist < ray_dist - 1.0 and
                                hit_obj and
                                hit_obj.name != text_obj.name and
                                hit_obj.name != line_name and
                                hit_obj.name != card_name and
                                hit_obj.name != parent_name):
                            alpha = 0.0

            process_object_visibility(text_obj, alpha)
            process_object_visibility(line_obj, alpha)
            process_object_visibility(card_obj, alpha)

    # Handle Rings
    ring_collection = bpy.data.collections.get("Asset_Rings")
    if ring_collection:
        for ring_obj in ring_collection.objects:
            if ring_obj.type != 'MESH':
                continue

            max_distance = ring_obj.get('max_distance', 2000.0)
            cam_dist     = (camera.matrix_world.translation - ring_obj.location).length

            actual_margin = min(raw_fade_margin, max_distance * 0.9)
            if actual_margin <= 0.0:
                actual_margin = 1.0 
            fade_start = max_distance - actual_margin

            # Distance Fade Calculation
            alpha = 1.0
            if cam_dist >= max_distance:
                alpha = 0.0
            elif cam_dist > fade_start:
                alpha = 1.0 - ((cam_dist - fade_start) / actual_margin)

            process_object_visibility(ring_obj, alpha)


def frame_change_handler(scene, depsgraph):
    update_label_visibility(scene, depsgraph)


def render_pre_handler(scene, *args):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    update_label_visibility(scene, depsgraph)


def register_visibility_handlers():
    bpy.app.handlers.frame_change_post[:] = [
        h for h in bpy.app.handlers.frame_change_post
        if h.__name__ != 'frame_change_handler'
    ]
    bpy.app.handlers.render_pre[:] = [
        h for h in bpy.app.handlers.render_pre
        if h.__name__ != 'render_pre_handler'
    ]
    bpy.app.handlers.frame_change_post.append(frame_change_handler)
    bpy.app.handlers.render_pre.append(render_pre_handler)

    bpy.context.view_layer.update()
    update_label_visibility(bpy.context.scene, bpy.context.evaluated_depsgraph_get())


# ------------------------------------------------------------------
# Main execution
# ------------------------------------------------------------------

def main():
    if not data_overlays_config.get('enabled', False):
        print("  Data overlays disabled")
        return

    print("\n--- Applying Data Overlays ---")

    # Now 'properties', 'key', 'guid', and 'clean' are local to this function!
    properties = load_properties()
    for key in list(properties.keys()):
        guid = properties[key].get('GlobalID', '')
        if guid:
            clean = guid.lstrip('{').rstrip('}')
            properties[clean] = properties[key]

    apply_building_flood_colors(properties, data_overlays_config, color_ramp_config, flood_scenario)
    apply_asset_labels(properties, data_overlays_config)
    apply_asset_rings(properties)
    register_visibility_handlers()

    print("--- Data Overlays Complete ---\n")

# Run the protected scope
main()

# Optional: Clean up the main function itself from the context when done
del main