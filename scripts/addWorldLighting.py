import bpy
import os
import math

#exrFile = 'syferfontein_1d_clear_4k.exr'

# bluer one
exrFile = 'kloofendal_48d_partly_cloudy_puresky_4k.exr'

# 1. Setup World Data
# Get the world or create one if it doesn't exist
world = bpy.data.worlds.get("World")
if not world:
    world = bpy.data.worlds.new("World")

world.use_nodes = True
nodes = world.node_tree.nodes
links = world.node_tree.links

# Clear existing nodes to avoid overlaps (Optional)
nodes.clear() 

# 2. Create Nodes
# Create Texture Coordinate Node
node_tex_coord = nodes.new(type='ShaderNodeTexCoord')
node_tex_coord.location = (-600, 300)

# Create Mapping Node
node_mapping = nodes.new(type='ShaderNodeMapping')
node_mapping.inputs['Rotation'].default_value[2] = math.radians(float(globals().get('worldLightingRotationAngle', 0)))
node_mapping.location = (-400, 300)

# Create Environment Texture Node (Best for EXR/World)
# Note: Using TexEnvironment instead of TexImage because it supports .projection='SPHERE'
node_env = nodes.new(type='ShaderNodeTexEnvironment')
node_env.location = (-100, 300)
node_env.projection = 'EQUIRECTANGULAR'

# Find the Background node (usually created by default)
node_background = nodes.get("Background")
if not node_background:
    node_background = nodes.new(type='ShaderNodeBackground')
    node_background.location = (200, 300)

# Set world lighting strength from config (default 1.0)
world_lighting_strength = float(globals().get('world_lighting_strength', 1.0))
node_background.inputs['Strength'].default_value = world_lighting_strength

# Create World Output node
node_world_output = nodes.get("World Output")
if not node_world_output:
    node_world_output = nodes.new(type='ShaderNodeOutputWorld')
    node_world_output.location = (400, 300)

# 3. Load the EXR Image
img_path = f"/Users/noahdewar/Documents/HighTide/BlenderViz/{exrFile}"

if os.path.exists(img_path):
    img = bpy.data.images.load(img_path)
    node_env.image = img
else:
    print(f"Warning: File not found at {img_path}")

# 4. Link Nodes Together
# Link TexCoord (Generated) -> Mapping (Vector)
links.new(node_tex_coord.outputs['Generated'], node_mapping.inputs['Vector'])

# Link Mapping (Vector) -> Env Texture (Vector)
links.new(node_mapping.outputs['Vector'], node_env.inputs['Vector'])

# Link Env Texture (Color) -> Background (Color)
links.new(node_env.outputs['Color'], node_background.inputs['Color'])

# Link Background (Background) -> World Output (Surface)
links.new(node_background.outputs['Background'], node_world_output.inputs['Surface'])

print("World nodes generated and linked successfully.")
