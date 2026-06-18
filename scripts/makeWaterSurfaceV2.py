import bpy
from mathutils import Matrix
import os

# Generate a UV map from the mesh's XY world extent
def project_uv_from_bounds(obj, uv_map_name="depth_uv", flip_v=False):
    import numpy as np

    mesh = obj.data

    if uv_map_name not in mesh.uv_layers:
        mesh.uv_layers.new(name=uv_map_name)
    uv_layer = mesh.uv_layers[uv_map_name]
    mesh.uv_layers.active = mesh.uv_layers[uv_map_name]

    # Get bounds from local coords (same as sat image script — no world matrix needed
    # since scale is already baked by apply_scale_direct)
    vert_cos = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", vert_cos)
    vert_cos = vert_cos.reshape(-1, 3)

    min_x, max_x = vert_cos[:, 0].min(), vert_cos[:, 0].max()
    min_y, max_y = vert_cos[:, 1].min(), vert_cos[:, 1].max()
    span_x = max_x - min_x
    span_y = max_y - min_y

    us = (vert_cos[:, 0] - min_x) / span_x
    vs = (vert_cos[:, 1] - min_y) / span_y
    if flip_v:
        vs = 1.0 - vs

    # Write per-loop UVs via foreach_set
    loop_verts = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_verts)

    uv_data = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    uv_data[0::2] = us[loop_verts]
    uv_data[1::2] = vs[loop_verts]
    uv_layer.data.foreach_set("uv", uv_data)

    print(f"  UV projected for {obj.name} | X: {min_x:.1f}-{max_x:.1f}, Y: {min_y:.1f}-{max_y:.1f}")

def diagnose_floodmap():
    for obj in bpy.data.objects:
        if obj.type == 'MESH' and 'floodmap' in obj.name.lower():
            print(f"\n--- {obj.name} ---")
            print(f"  Scale:      {obj.scale[:]}")
            print(f"  Dimensions: {obj.dimensions[:]}")
            print(f"  Vertex count: {len(obj.data.vertices)}")
            zvals = [v.co.z for v in obj.data.vertices[:20]]
            print(f"  Z range (first 20 verts): {min(zvals):.4f} to {max(zvals):.4f}")
            print(f"  Polygon count: {len(obj.data.polygons)}")

def apply_scale_direct(obj):
    if obj.type != 'MESH' or obj.scale[:] == (1.0, 1.0, 1.0):
        return
    scale_matrix = Matrix.Diagonal(obj.scale).to_4x4()
    obj.data.transform(scale_matrix)
    obj.scale = (1.0, 1.0, 1.0)
    obj.data.update()
    print(f"  Scale baked: {obj.name}")

# ---> CHANGED: Function now requires a specific 'flood_obj' <---
def create_florida_water(flood_obj, render_fps=24, animate_water=True, depth_texture_name=None):
    
    print(f"  Building custom water material for: {flood_obj.name}")
    
    # Calculate noise scales based on THIS specific object's dimensions
    mesh_span = max(flood_obj.dimensions.x, flood_obj.dimensions.y)
    large_noise_scale = mesh_span / 20.0    
    fine_noise_scale  = mesh_span / 200.0   
    bump_distance     = mesh_span * 0.0003  

    # Create a uniquely named material for this mesh
    mat_name = f"WaterMat_{flood_obj.name}"
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # --- Create Standard Nodes ---
    material_output = nodes.new(type='ShaderNodeOutputMaterial')
    material_output.location = (600, 0)

    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (300, 0)
    
    default_base_color = (0.8, 0.9, 0.9, 1.0)
    bsdf.inputs['Base Color'].default_value = default_base_color
    bsdf.inputs['Roughness'].default_value = 0.03
    bsdf.inputs['IOR'].default_value = 1.333
    
    try:
        bsdf.inputs['Transmission Weight'].default_value = 1.0 
    except KeyError:
        bsdf.inputs['Transmission'].default_value = 1.0 

    volume = nodes.new(type='ShaderNodeVolumePrincipled')
    volume.location = (300, -300)
    volume.inputs['Density'].default_value = 0.8
    volume.inputs['Color'].default_value = (0.28, 0.22, 0.14, 1.0)
    
    bump = nodes.new(type='ShaderNodeBump')
    bump.location = (0, -100)
    bump.inputs['Distance'].default_value = bump_distance 
    bump.inputs['Strength'].default_value = 2

    noise_large = nodes.new(type='ShaderNodeTexNoise')
    noise_large.location = (-400, 150)
    noise_large.noise_dimensions = '4D'
    noise_large.inputs['Scale'].default_value = large_noise_scale

    noise_fine = nodes.new(type='ShaderNodeTexNoise')
    noise_fine.location = (-400, -150)
    noise_fine.noise_dimensions = '4D'
    noise_fine.inputs['Scale'].default_value = fine_noise_scale

    mix_noise = nodes.new(type='ShaderNodeMix')
    mix_noise.location = (-200, 0)
    mix_noise.data_type = 'FLOAT'
    mix_noise.inputs['Factor'].default_value = 0.4

    mapping = nodes.new(type='ShaderNodeMapping')
    mapping.location = (-600, 0)
    tex_coord = nodes.new(type='ShaderNodeTexCoord')
    tex_coord.location = (-800, 0)

    rough_map = nodes.new(type='ShaderNodeMapRange')
    rough_map.location = (50, 150)
    rough_map.inputs['From Min'].default_value = 0.4  
    rough_map.inputs['From Max'].default_value = 0.6  
    rough_map.inputs['To Min'].default_value = 0.06   
    rough_map.inputs['To Max'].default_value = 0.0    

    spec_map = nodes.new(type='ShaderNodeMapRange')
    spec_map.location = (50, 300)
    spec_map.inputs['From Min'].default_value = 0.5   
    spec_map.inputs['From Max'].default_value = 0.7   
    spec_map.inputs['To Min'].default_value = 0.5     
    spec_map.inputs['To Max'].default_value = 1.0     

    # ==========================================
    # --- TEXTURE INTEGRATION ---
    # ==========================================
    
    if depth_texture_name:
        # Emission node shows the depth color on top of whatever the water shader does
        depth_emission = nodes.new(type='ShaderNodeEmission')
        depth_emission.location = (300, -500)

        mix_shader = nodes.new(type='ShaderNodeMixShader')
        mix_shader.location = (500, 0)

        uv_map_node = nodes.new(type='ShaderNodeUVMap')
        uv_map_node.location = (-500, -500)
        uv_map_node.uv_map = "depth_uv"

        depth_tex = nodes.new(type='ShaderNodeTexImage')
        depth_tex.location = (-300, -500)
        if depth_texture_name in bpy.data.images:
            depth_tex.image = bpy.data.images[depth_texture_name]

        links.new(uv_map_node.outputs['UV'],      depth_tex.inputs['Vector'])
        links.new(depth_tex.outputs['Color'],     depth_emission.inputs['Color'])
        depth_emission.inputs['Strength'].default_value = 0.25

        # Alpha from texture controls blend between water and depth color
        links.new(bsdf.outputs['BSDF'],           mix_shader.inputs[1])
        links.new(depth_emission.outputs['Emission'], mix_shader.inputs[2])
        links.new(depth_tex.outputs['Alpha'],     mix_shader.inputs['Fac'])
        links.new(mix_shader.outputs['Shader'],   material_output.inputs['Surface'])

    # ==========================================

    # --- Standard Links ---
    links.new(tex_coord.outputs['Generated'], mapping.inputs['Vector'])
    links.new(mapping.outputs['Vector'],      noise_large.inputs['Vector'])
    links.new(mapping.outputs['Vector'],      noise_fine.inputs['Vector'])

    links.new(noise_large.outputs['Fac'], mix_noise.inputs['A'])
    links.new(noise_fine.outputs['Fac'],  mix_noise.inputs['B'])

    links.new(mix_noise.outputs['Result'], bump.inputs['Height'])
    links.new(bump.outputs['Normal'],      bsdf.inputs['Normal'])

    links.new(mix_noise.outputs['Result'], rough_map.inputs['Value'])
    links.new(mix_noise.outputs['Result'], spec_map.inputs['Value'])

    links.new(rough_map.outputs['Result'], bsdf.inputs['Roughness'])
    try:
        links.new(spec_map.outputs['Result'], bsdf.inputs['Specular IOR Level'])
    except KeyError:
        links.new(spec_map.outputs['Result'], bsdf.inputs['Specular'])

    if not depth_texture_name:
        links.new(bsdf.outputs['BSDF'],       material_output.inputs['Surface'])
    links.new(volume.outputs['Volume'],   material_output.inputs['Volume'])

    # --- Drivers ---
    if animate_water:
        target_flow_speed_ms = 0.5
        flow_div = (mesh_span * render_fps) / target_flow_speed_ms
        swell_div  = 1600 * (render_fps / 24.0)  
        ripple_div = 800  * (render_fps / 24.0)  

        flow_driver = mapping.inputs['Location'].driver_add('default_value', 0) 
        flow_driver.driver.expression = f'frame / {flow_div:.2f}'

        w_driver1 = noise_large.inputs['W'].driver_add('default_value')
        w_driver1.driver.expression = f'frame / {swell_div:.2f}'

        w_driver2 = noise_fine.inputs['W'].driver_add('default_value')
        w_driver2.driver.expression = f'frame / {ripple_div:.2f}'

    # ---> CHANGED: Assign only to this specific object <---
    if not flood_obj.data.materials:
        flood_obj.data.materials.append(mat)
    else:
        flood_obj.data.materials[0] = mat

    # Finalize animation data for the material
    mat.node_tree.animation_data_create()
    if mat.node_tree.animation_data:
        for driver in mat.node_tree.animation_data.drivers:
            driver.driver.is_valid  
    
    return mat

# ==========================================
# --- Main Run Loop ---
# ==========================================
render_fps = globals().get('render_fps', 24)
animate_water = globals().get('animate_water', True)
data_overlays = globals().get('data_overlays', {})
color_ramp = globals().get('color_ramp', {})
state = globals().get('state', 'florida')
county = globals().get('county', 'brevard')
project_name = globals().get('project_name')
siteNum = globals().get('siteNum', 1)

# Check if flood raster depth coloring is enabled
flood_raster_depth_enabled = data_overlays.get('flood_raster_depth_coloring', {}).get('enabled', False)

# Build folder path for depth textures
folder_path = f"/Users/noahdewar/Documents/HighTide/data/{state}/projects/{project_name}/blender/site{siteNum}/"

print("\n--- Starting Water Material Setup ---")
print(f"  Flood raster depth coloring: {'enabled' if flood_raster_depth_enabled else 'disabled'}")
diagnose_floodmap()

# 1. Find all floodmap meshes in the scene
water_objs = [obj for obj in bpy.data.objects if obj.type == 'MESH' and 'floodmap' in obj.name.lower()]

# 2. Loop through each object individually
for water_obj in water_objs:
    # Scale the specific mesh
    apply_scale_direct(water_obj)

    # Only set up depth textures if flood raster depth coloring is enabled
    depth_texture_name = None
    if flood_raster_depth_enabled:
        project_uv_from_bounds(water_obj)

        # Determine the expected texture name
        expected_texture_name = f"{water_obj.name.replace('_3857','')}_depth_texture.png"
        texture_filepath = os.path.join(folder_path, expected_texture_name)

        # Load the image from the hard drive if it isn't in Blender yet
        if expected_texture_name not in bpy.data.images:
            if os.path.exists(texture_filepath):
                print(f"  Loading image from disk: {expected_texture_name}")
                bpy.data.images.load(texture_filepath)
            else:
                print(f"  [!] Depth texture not found: {texture_filepath}")

        if expected_texture_name in bpy.data.images:
            depth_texture_name = expected_texture_name
        
        
        img = bpy.data.images[expected_texture_name]
        print(f"  Image size: {img.size[0]}x{img.size[1]}")
        print(f"  Color space: {img.colorspace_settings.name}")
        print(f"  Alpha mode: {img.alpha_mode}")
        # Sample center pixel to verify alpha isn't zero
        px = img.pixels[:]
        center = len(px) // 2
        center = (center // 4) * 4  # align to RGBA boundary
        print(f"  Center pixel RGBA: {[round(px[center+i],3) for i in range(4)]}")

    # Generate the material for this specific mesh
    create_florida_water(
        flood_obj=water_obj,
        render_fps=render_fps,
        animate_water=animate_water,
        depth_texture_name=depth_texture_name
    )

# Force Blender to update the viewport to show the changes
bpy.context.scene.frame_set(bpy.context.scene.frame_current)
bpy.context.view_layer.update()
print("--- Water Material Setup Complete ---")