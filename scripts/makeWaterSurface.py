import bpy

def create_complex_material(material_name="GeneratedComplexMaterial"):
    """
    Creates a new material with a complex node setup for a realistic glass
    or liquid effect with volume and surface imperfections.

    This script programmatically builds the shader tree, connects all the
    nodes, and sets their values, resulting in a ready-to-use material.

    Args:
        material_name (str): The name for the new material.
    """
    # --- Create a new material ---
    mat = bpy.data.materials.new(name=material_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    # --- Clear existing nodes ---
    # We start with a clean slate by removing all default nodes.
    for node in nodes:
        nodes.remove(node)

    # --- Create all necessary nodes ---
    # We create every node we'll need and store them in variables
    # for easy access later.

    # Output node
    material_output = nodes.new(type='ShaderNodeOutputMaterial')
    material_output.location = (400, 0)

    # --- Surface Shaders ---
    mix_shader = nodes.new(type='ShaderNodeMixShader')
    mix_shader.location = (200, 0)
    mix_shader.inputs[0].default_value = 0.5 # Factor from log

    mix_shader_2 = nodes.new(type='ShaderNodeMixShader')
    mix_shader_2.location = (0, 100)

    transparent_bsdf = nodes.new(type='ShaderNodeBsdfTransparent')
    transparent_bsdf.location = (0, -150)

    glass_bsdf = nodes.new(type='ShaderNodeBsdfGlass')
    glass_bsdf.location = (-200, 200)
    glass_bsdf.inputs['Roughness'].default_value = 0.1

    glossy_bsdf = nodes.new(type='ShaderNodeBsdfGlossy')
    glossy_bsdf.location = (-200, 0)
    glossy_bsdf.inputs['Roughness'].default_value = 0.1

    # --- Volume Shaders ---
    add_volume_shader = nodes.new(type='ShaderNodeAddShader')
    add_volume_shader.location = (200, -300)

    volume_scatter = nodes.new(type='ShaderNodeVolumeScatter')
    volume_scatter.location = (0, -300)
    volume_scatter.inputs['Density'].default_value = 1.0
    #volume_scatter.inputs['Backscatter'].default_value = -0.2
    volume_scatter.inputs['Color'].default_value = (0.294, 0.345, 0.259, 1.0)  # Murky green #4B5842FF
    volume_scatter.phase = 'FOURNIER_FORAND'
    # The log specifies 'FOURNIER_FORAND', which is not a valid phase function in recent Blender versions.
    # 'henyey_greenstein' is the standard. We will set anisotropy instead.
    # volume_scatter.phase_function = 'henyey_greenstein' # Example
    #volume_scatter.inputs['Anisotropy'].default_value = 0.0 # Default value

    volume_absorption = nodes.new(type='ShaderNodeVolumeAbsorption')
    volume_absorption.location = (0, -500)
    volume_absorption.inputs['Density'].default_value = 2.0
    volume_absorption.inputs['Color'].default_value = (0.275, 0.557, 0.631, 1.0)  # Light blue #468EA1FF

    # --- Control & Texture Nodes ---
    fresnel = nodes.new(type='ShaderNodeFresnel')
    fresnel.location = (-200, 350)

    value_node = nodes.new(type='ShaderNodeValue')
    value_node.location = (-400, 350)
    value_node.outputs[0].default_value = 1.333 # IOR for water

    bump_node = nodes.new(type='ShaderNodeBump')
    bump_node.location = (-400, 100)
    bump_node.inputs['Strength'].default_value = 2  # Increase bump strength

    gabor_texture = nodes.new(type='ShaderNodeTexGabor')
    gabor_texture.location = (-600, 100)
    gabor_texture.inputs['Scale'].default_value = 5.0         # Larger scale for water waves
    gabor_texture.inputs['Frequency'].default_value = 3.0     # Wave frequency
    gabor_texture.inputs['Anisotropy'].default_value = 0.1    # Directional variation
    gabor_texture.inputs['Orientation'].default_value = 0   # Wave direction

    mapping_node = nodes.new(type='ShaderNodeMapping')
    mapping_node.location = (-800, 100)
    mapping_node.inputs['Scale'].default_value = (10.0, 10.0, 1.0)  # Scale up the texture

    tex_coord_node = nodes.new(type='ShaderNodeTexCoord')
    tex_coord_node.location = (-1000, 100)


    # --- Link all the nodes together ---
    # This is where we build the shader tree by connecting the sockets.

    # Texture Coordinate setup
    links.new(tex_coord_node.outputs['Generated'], mapping_node.inputs['Vector'])
    links.new(mapping_node.outputs['Vector'], gabor_texture.inputs['Vector'])

    # Bump setup
    links.new(gabor_texture.outputs['Value'], bump_node.inputs['Height'])
    links.new(bump_node.outputs['Normal'], glass_bsdf.inputs['Normal'])
    links.new(bump_node.outputs['Normal'], glossy_bsdf.inputs['Normal'])

    # Surface shader mixing
    links.new(fresnel.outputs['Fac'], mix_shader_2.inputs[0])
    links.new(glass_bsdf.outputs['BSDF'], mix_shader_2.inputs[1])
    links.new(glossy_bsdf.outputs['BSDF'], mix_shader_2.inputs[2])

    # Fresnel setup for mixing transparent and glass/glossy
    links.new(value_node.outputs['Value'], fresnel.inputs['IOR'])
    links.new(transparent_bsdf.outputs['BSDF'], mix_shader.inputs[1])
    links.new(mix_shader_2.outputs['Shader'], mix_shader.inputs[2])

    # Volume shader mixing
    links.new(fresnel.outputs['Fac'], volume_scatter.inputs['IOR'])
    links.new(volume_scatter.outputs['Volume'], add_volume_shader.inputs[0])
    links.new(volume_absorption.outputs['Volume'], add_volume_shader.inputs[1])

    # --- Final connections to the output node ---
    links.new(mix_shader.outputs['Shader'], material_output.inputs['Surface'])
    links.new(add_volume_shader.outputs['Shader'], material_output.inputs['Volume'])

    # --- Assign material to all meshes except DEMs ---
    # We iterate through every object in the data
    for obj in bpy.data.objects:
        # Check if it's a mesh and the name has floodmap in it
        if obj.type == 'MESH' and "floodmap" in obj.name.lower():
            
            # If the object has no material slots, add one
            if not obj.data.materials:
                obj.data.materials.append(mat)
            else:
                # If it already has slots, replace the first one
                obj.data.materials[0] = mat
                
            print(f"Assigned {material_name} to {obj.name}")

    return mat

# now run it
create_complex_material()
