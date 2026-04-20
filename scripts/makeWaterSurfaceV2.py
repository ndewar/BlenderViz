import bpy
import math
from mathutils import Matrix

def diagnose_floodmap():
    for obj in bpy.data.objects:
        if obj.type == 'MESH' and 'floodmap' in obj.name.lower():
            print(f"\n--- {obj.name} ---")
            print(f"  Scale:      {obj.scale[:]}")
            print(f"  Dimensions: {obj.dimensions[:]}")
            print(f"  Vertex count: {len(obj.data.vertices)}")
            # Sample a few vertex Z values to check if mesh is actually flat
            zvals = [v.co.z for v in obj.data.vertices[:20]]
            print(f"  Z range (first 20 verts): {min(zvals):.4f} to {max(zvals):.4f}")
            # Check polygon count — a 2-poly plane can't show bump detail
            print(f"  Polygon count: {len(obj.data.polygons)}")

def apply_scale_direct(obj):
    if obj.type != 'MESH':
        return
    if obj.scale[:] == (1.0, 1.0, 1.0):
        return
    scale_matrix = Matrix.Diagonal(obj.scale).to_4x4()
    obj.data.transform(scale_matrix)
    obj.scale = (1.0, 1.0, 1.0)
    obj.data.update()
    print(f"  Scale baked: {obj.name}")

def create_florida_water(material_name="GeneratedComplexMaterial", render_fps=24):
    """
    Creates a modern, physically accurate water material with animated 
    multi-scale ripples, dynamic specular highlights, and volume absorption.
    """
    # --- Apply scale and measure mesh ---
    print("Applying scale to floodmap objects...")
    ref_obj = None
    for obj in bpy.data.objects:
        if obj.type == 'MESH' and 'floodmap' in obj.name.lower():
            apply_scale_direct(obj)
            if ref_obj is None:
                ref_obj = obj

    # Derive all texture/bump values from actual mesh span.
    # Your mesh is ~5196 units (metres in EPSG:3857) — hardcoded
    # scale values designed for 1-unit scenes are invisible at this size.
    if ref_obj:
        mesh_span = max(ref_obj.dimensions.x, ref_obj.dimensions.y)
        large_noise_scale = mesh_span / 20.0    # ~260m per swell — visible from altitude
        fine_noise_scale  = mesh_span / 200.0   # ~26m per ripple — fine chop
        bump_distance     = mesh_span * 0.0003  # ~1.5m height variation — realistic
        print(f"  Mesh span:     {mesh_span:.1f} m")
        print(f"  Large scale:   {large_noise_scale:.1f}")
        print(f"  Fine scale:    {fine_noise_scale:.1f}")
        print(f"  Bump distance: {bump_distance:.2f} m")
    else:
        print("  Warning: no floodmap found, using fallback values")
        large_noise_scale = 260.0
        fine_noise_scale  = 26.0
        bump_distance     = 1.5

    # --- Create a new material ---
    mat = bpy.data.materials.new(name=material_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # --- Create Nodes ---
    material_output = nodes.new(type='ShaderNodeOutputMaterial')
    material_output.location = (300, 0)

    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    bsdf.inputs['Base Color'].default_value = (0.8, 0.9, 0.9, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.03
    bsdf.inputs['IOR'].default_value = 1.333
    
    # Transmission compatibility
    try:
        bsdf.inputs['Transmission Weight'].default_value = 1.0 # Blender 4.0+
    except KeyError:
        bsdf.inputs['Transmission'].default_value = 1.0 # Older versions

    volume = nodes.new(type='ShaderNodeVolumePrincipled')
    volume.location = (0, -300)
    volume.inputs['Density'].default_value = 0.8
    volume.inputs['Color'].default_value = (0.28, 0.22, 0.14, 1.0)
    
    bump = nodes.new(type='ShaderNodeBump')
    bump.location = (-300, -100)
    bump.inputs['Distance'].default_value = bump_distance 
    bump.inputs['Strength'].default_value = 2

    noise_large = nodes.new(type='ShaderNodeTexNoise')
    noise_large.location = (-700, 150)
    noise_large.noise_dimensions = '4D'
    noise_large.inputs['Scale'].default_value = large_noise_scale
    noise_large.inputs['Detail'].default_value = 3.0
    noise_large.inputs['Roughness'].default_value = 0.5

    noise_fine = nodes.new(type='ShaderNodeTexNoise')
    noise_fine.location = (-700, -150)
    noise_fine.noise_dimensions = '4D'
    noise_fine.inputs['Scale'].default_value = fine_noise_scale
    noise_fine.inputs['Detail'].default_value = 5.0
    noise_fine.inputs['Roughness'].default_value = 0.6

    mix_noise = nodes.new(type='ShaderNodeMix')
    mix_noise.location = (-500, 0)
    mix_noise.data_type = 'FLOAT'
    mix_noise.inputs['Factor'].default_value = 0.4

    mapping = nodes.new(type='ShaderNodeMapping')
    mapping.location = (-900, 0)
    tex_coord = nodes.new(type='ShaderNodeTexCoord')
    tex_coord.location = (-1100, 0)

    # --- Highlight Control Nodes (Map Ranges) ---
    
    # 1. Map Roughness (Troughs are rougher, crests are perfect mirrors)
    rough_map = nodes.new(type='ShaderNodeMapRange')
    rough_map.location = (-250, 150)
    rough_map.inputs['From Min'].default_value = 0.4  # Mid-point of noise
    rough_map.inputs['From Max'].default_value = 0.6  # High-point of noise
    rough_map.inputs['To Min'].default_value = 0.06   # Trough roughness
    rough_map.inputs['To Max'].default_value = 0.0    # Crest roughness (Mirror)

    # 2. Map Specular (Boost reflections strictly on the high peaks)
    spec_map = nodes.new(type='ShaderNodeMapRange')
    spec_map.location = (-250, 300)
    spec_map.inputs['From Min'].default_value = 0.5   # Start boosting past the mid-point
    spec_map.inputs['From Max'].default_value = 0.7   # Peak of noise
    spec_map.inputs['To Min'].default_value = 0.5     # Base water specular
    spec_map.inputs['To Max'].default_value = 1.0     # Cranked up peak specular

    # --- Links ---
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

    links.new(bsdf.outputs['BSDF'],       material_output.inputs['Surface'])
    links.new(volume.outputs['Volume'],   material_output.inputs['Volume'])

    # --- Drivers ---
    # 1. Flow Speed (Linear drift)
    # Target speed in meters per second (e.g., 0.5 m/s is a gentle current)
    target_flow_speed_ms = 0.5 
    
    # Formula: To move 1 real meter, we move (1.0 / mesh_span) in mapping space.
    flow_div = (mesh_span * render_fps) / target_flow_speed_ms

    # 2. Phase Speed (The "boil" or evolution of the ripples)
    # The 'W' value of 4D noise changes the seed. Evolving by 1.0 completely morphs it.
    # We need to scale these divisors WAY up so it evolves slowly.
    swell_div  = 1600 * (render_fps / 24.0)  # Slow, rolling evolution
    ripple_div = 800  * (render_fps / 24.0)  # Faster, choppy surface evolution

    flow_driver = mapping.inputs['Location'].driver_add('default_value', 0) # Drive X axis
    flow_driver.driver.expression = f'frame / {flow_div:.2f}'

    w_driver1 = noise_large.inputs['W'].driver_add('default_value')
    w_driver1.driver.expression = f'frame / {swell_div:.2f}'

    w_driver2 = noise_fine.inputs['W'].driver_add('default_value')
    w_driver2.driver.expression = f'frame / {ripple_div:.2f}'

    # --- Assign Material ---
    for obj in bpy.data.objects:
        if obj.type == 'MESH' and "floodmap" in obj.name.lower():
            if not obj.data.materials:
                obj.data.materials.append(mat)
            else:
                obj.data.materials[0] = mat
            print(f"Assigned {material_name} to {obj.name}")

    # Force depsgraph to register and evaluate all drivers
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    bpy.context.view_layer.update()
    
    # Tag the node tree as updated so Blender marks drivers as active
    mat.node_tree.animation_data_create()
    
    # Explicitly tag drivers for depsgraph
    if mat.node_tree.animation_data:
        for driver in mat.node_tree.animation_data.drivers:
            driver.driver.is_valid  # accessing this property forces validation
        print(f"  Registered {len(mat.node_tree.animation_data.drivers)} drivers")
    
    return mat

# Run the function
render_fps = globals().get('render_fps', 24)
diagnose_floodmap()
create_florida_water(render_fps=render_fps)