import bpy
import os
import math

# ==========================================
# --- CONFIGURATION ---
# ==========================================
# 1. Grab the flyover_config directly from the master runner's shared context
flyover_config = globals().get('flyover_config', {})
is_animation = flyover_config.get("enabled", False)

FOG_COLOR = (0.6, 0.7, 0.8, 1.0) 
exrFile = 'citrus_orchard_road_puresky_4k.exr'

# ==========================================
# --- WORLD SETUP ---
# ==========================================
world = bpy.data.worlds.get("World")
if not world:
    world = bpy.data.worlds.new("World")

world.use_nodes = True
nodes = world.node_tree.nodes
links = world.node_tree.links
nodes.clear() 

# Create Nodes
node_tex_coord = nodes.new(type='ShaderNodeTexCoord')
node_tex_coord.location = (-600, 300)

node_mapping = nodes.new(type='ShaderNodeMapping')
node_mapping.inputs['Rotation'].default_value[2] = math.radians(float(globals().get('worldLightingRotationAngle', 0)))
node_mapping.location = (-400, 300)

node_env = nodes.new(type='ShaderNodeTexEnvironment')
node_env.location = (-100, 300)
node_env.projection = 'EQUIRECTANGULAR'

node_background = nodes.new(type='ShaderNodeBackground')
node_background.location = (200, 300)
node_background.inputs['Strength'].default_value = float(globals().get('world_lighting_strength', 1.0))

node_world_output = nodes.new(type='ShaderNodeOutputWorld')
node_world_output.location = (400, 300)

# Load the EXR Image
img_path = f"/Users/noahdewar/Documents/HighTide/BlenderViz/{exrFile}"
if os.path.exists(img_path):
    img = bpy.data.images.load(img_path)
    node_env.image = img
    print(f"SUCCESS: Loaded HDRI from {img_path}")
else:
    print(f"CRITICAL WARNING: HDRI File not found at {img_path}!")
    node_background.inputs['Color'].default_value = (0.8, 0.9, 1.0, 1.0) 

# Link Nodes Together
links.new(node_tex_coord.outputs['Generated'], node_mapping.inputs['Vector'])
links.new(node_mapping.outputs['Vector'], node_env.inputs['Vector'])
links.new(node_env.outputs['Color'], node_background.inputs['Color'])
links.new(node_background.outputs['Background'], node_world_output.inputs['Surface'])

# ==========================================
# --- TRUE VOLUMETRIC FOG (Static Only) ---
# ==========================================
# Clear any existing World Volume links so it doesn't swallow the HDRI
for link in list(node_world_output.inputs['Volume'].links):
    links.remove(link)

if not is_animation:
    print("-> Adding True Volumetric Fog for Static render (using Fog Domain).")
    
    # 1. Clear old fog domains if re-running
    for obj in bpy.data.objects:
        if obj.name == "Volumetric_Fog_Domain":
            bpy.data.objects.remove(obj, do_unlink=True)
            
    # 2. Find the DEM to gauge scene size
    dem_obj = next((obj for obj in bpy.data.objects if 'dem' in obj.name.lower() and obj.type == 'MESH'), None)
    
    if dem_obj:
        # 3. Size the Fog Box based on the landscape
        scene_width = max(dem_obj.dimensions.x, dem_obj.dimensions.y)
        dem_center = dem_obj.location 
        
        # Create a massive Box covering the terrain
        bpy.ops.mesh.primitive_cube_add(size=1)
        fog_box = bpy.context.active_object
        fog_box.name = "Volumetric_Fog_Domain"
        
        # Scale: 1.5x width to cover edges, 2000m tall
        fog_box.scale = (scene_width * 1.5, scene_width * 1.5, 2000.0)
        fog_box.location = (dem_center.x, dem_center.y, dem_center.z + 1000.0)
        
        # 4. Create the Volume Material (WITH Z-GRADIENT)
        fog_mat = bpy.data.materials.new(name="Fog_Material")
        fog_mat.use_nodes = True
        mat_nodes = fog_mat.node_tree.nodes
        mat_links = fog_mat.node_tree.links
        mat_nodes.clear()
        
        mat_out = mat_nodes.new('ShaderNodeOutputMaterial')
        mat_out.location = (300, 0)
        
        mat_vol = mat_nodes.new('ShaderNodeVolumePrincipled')
        mat_vol.location = (0, 0)
        mat_vol.inputs['Color'].default_value = FOG_COLOR[:3] + (1.0,)
        mat_vol.inputs['Anisotropy'].default_value = 0.6 # Scatters light forward, makes it brighter
        
        # Base Density Target
        safe_width = scene_width if scene_width > 0 else 10000
        target_density = 2.0 / safe_width
        
        # Nodes for Z-Gradient
        box_coord = mat_nodes.new('ShaderNodeTexCoord')
        box_coord.location = (-800, 0)
        
        sep_xyz = mat_nodes.new('ShaderNodeSeparateXYZ')
        sep_xyz.location = (-600, 0)
        
        # A 1m primitive cube's object coordinates go from -0.5 to 0.5
        map_range = mat_nodes.new('ShaderNodeMapRange')
        map_range.location = (-400, 0)
        map_range.inputs['From Min'].default_value = -0.5  # Bottom of box
        map_range.inputs['From Max'].default_value = 0.5   # Top of box
        map_range.inputs['To Min'].default_value = 1.0     # 100% density multiplier at bottom
        map_range.inputs['To Max'].default_value = 0.0     # 0% density multiplier at top
        
        # Multiply the target density by the gradient
        mult_density = mat_nodes.new('ShaderNodeMath')
        mult_density.operation = 'MULTIPLY'
        mult_density.location = (-200, 0)
        mult_density.inputs[1].default_value = target_density
        
        # Link the gradient chain
        mat_links.new(box_coord.outputs['Object'], sep_xyz.inputs['Vector'])
        mat_links.new(sep_xyz.outputs['Z'], map_range.inputs['Value'])
        mat_links.new(map_range.outputs['Result'], mult_density.inputs[0])
        mat_links.new(mult_density.outputs['Value'], mat_vol.inputs['Density'])
        mat_links.new(mat_vol.outputs['Volume'], mat_out.inputs['Volume'])
        
        fog_box.data.materials.append(fog_mat)
        
        # Hide the solid cube from the viewport view
        fog_box.display_type = 'BOUNDS'
        
        print(f"  -> Created Fog Domain. Width: {scene_width*1.5:.0f}m, Base Density: {target_density:.6f}")
    else:
        print("  -> Could not find DEM. Skipping volumetric fog.")
else:
    print("-> Animation Mode active: Skipping True Volumetrics (Relying on Compositor Mist pass).")

print("World nodes generated and linked successfully.")