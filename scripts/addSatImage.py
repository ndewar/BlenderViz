import bpy
import os
import math
import mathutils
import bmesh

# --- SETTINGS (Handled by Master Runner) ---
material_name = "SatelliteOverlay"
county = globals().get('county', 'brevard')
siteNum = globals().get('siteNum', 1)
zoom = globals().get('sat_image_zoom', 18)

image_path = f"/Users/noahdewar/Documents/HighTide/BlenderViz/mapbox/{county}Site{siteNum}_satimage_{zoom}.png"
uv_map_name = "UVMap"

# Find the DEM object by name (better than 'active_object' in headless)
obj = next((o for o in bpy.data.objects if "dem" in o.name.lower() and o.type == 'MESH'), None)

if obj:
    # 1. Create/Setup Material
    mat = bpy.data.materials.get(material_name) or bpy.data.materials.new(name=material_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # 2. Build the Node Tree
    node_output = nodes.new(type='ShaderNodeOutputMaterial')
    node_bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    node_tex = nodes.new(type='ShaderNodeTexImage')
    node_uv = nodes.new(type='ShaderNodeUVMap')
    node_uv.uv_map = uv_map_name
    
    node_mapping = nodes.new(type='ShaderNodeMapping')
    # Use 0 rotation initially; we'll fix rotation via UVs or Mapping if needed
    node_mapping.inputs['Rotation'].default_value[2] = 0

    # 3. Load Image
    if os.path.exists(image_path):
        img = bpy.data.images.load(image_path)
        node_tex.image = img
    else:
        raise Exception(f'No image found at {image_path}')
    
    # 4. Linking
    links.new(node_uv.outputs['UV'], node_mapping.inputs['Vector'])
    links.new(node_mapping.outputs['Vector'], node_tex.inputs['Vector'])
    links.new(node_tex.outputs['Color'], node_bsdf.inputs['Base Color'])
    links.new(node_bsdf.outputs['BSDF'], node_output.inputs['Surface'])

    # 5. Assign material
    if not obj.data.materials:
        obj.data.materials.append(mat)
    else:
        obj.data.materials[0] = mat

    # 6. Headless-Safe "Project from Top" (Manual 0-1 Mapping)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Ensure UV Map exists
    if uv_map_name not in obj.data.uv_layers:
        obj.data.uv_layers.new(name=uv_map_name)
    
    uv_layer = obj.data.uv_layers[uv_map_name]
    
    # We will map the mesh's X/Y min/max to UV 0.0-1.0
    # This acts exactly like a "Scale to Bounds" top-down projection
    mesh = obj.data
    min_x = min(v.co.x for v in mesh.vertices)
    max_x = max(v.co.x for v in mesh.vertices)
    min_y = min(v.co.y for v in mesh.vertices)
    max_y = max(v.co.y for v in mesh.vertices)

    size_x = max_x - min_x
    size_y = max_y - min_y

    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            v_idx = mesh.loops[loop_index].vertex_index
            co = mesh.vertices[v_idx].co
            
            # Normalize coordinates to 0.0 - 1.0 range
            u = (co.x - min_x) / size_x
            v_coord = (co.y - min_y) / size_y
            
            # Apply to UV Layer
            uv_layer.data[loop_index].uv = (u, v_coord)

    # Force UV layer settings
    uv_layers = obj.data.uv_layers
    uv_layers.active = uv_layers[uv_map_name]

    # Final Scene Update
    bpy.context.view_layer.update()
    print(f"Manually mapped UVs for {obj.name} to full 0-1 texture space.")

else:
    print("No DEM mesh found to apply satellite overlay.")