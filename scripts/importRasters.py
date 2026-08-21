import bpy
import os
from mathutils import Matrix

import paths

# --- Variables ---
county = globals().get('county', 'brevard')
siteNum = globals().get('siteNum', 1)
state = globals().get('state', 'florida')
project_name = globals().get('project_name')
restrict_import = globals().get('restrict_import', True)
restrict_import = True

dem_decimate_ratio = globals().get('dem_decimate_ratio', 0.25)  
water_decimate_ratio = globals().get('water_decimate_ratio', 0.1)  

def smooth_terrain_and_water():
    """
    Applies 'Shade Smooth' to the DEM and any imported Flood Maps.
    Uses foreach_set for instant processing on high-poly meshes.
    """
    import bpy
    
    print("\n  Smoothing DEM and Flood Maps...")
    smoothed_count = 0
    
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            # Target both the DEM and the flood maps
            if 'dem' in obj.name.lower() or 'floodmap' in obj.name.lower():
                # Create an array of 'True' for every polygon in the mesh
                smooth_flags = [True] * len(obj.data.polygons)
                
                # Instantly apply it to the mesh data
                obj.data.polygons.foreach_set("use_smooth", smooth_flags)
                
                # Force Blender to update the visual geometry
                obj.data.update()
                
                smoothed_count += 1
                
    print(f"  Successfully smoothed {smoothed_count} terrain objects.")

def apply_scale_direct(obj):
    if obj.type != 'MESH' or obj.scale[:] == (1.0, 1.0, 1.0):
        return
    scale_matrix = Matrix.Diagonal(obj.scale).to_4x4()
    obj.data.transform(scale_matrix)
    obj.scale = (1.0, 1.0, 1.0)
    obj.data.update()

def apply_decimation(obj, ratio, mesh_type="mesh"):
    if ratio >= 1.0:
        return

    original_verts = len(obj.data.vertices)
    print(f"  Decimating {mesh_type} ({original_verts:,} vertices, target ratio={ratio})...")

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    if ratio <= 0.06:      iterations = 4
    elif ratio <= 0.12:    iterations = 3
    elif ratio <= 0.25:    iterations = 2
    else:                  iterations = 1

    decimate = obj.modifiers.new(name='Decimate', type='DECIMATE')
    decimate.decimate_type = 'UNSUBDIV'
    decimate.iterations = iterations

    bpy.ops.object.modifier_apply(modifier='Decimate')
    new_verts = len(obj.data.vertices)
    reduction = (1 - new_verts / original_verts) * 100 if original_verts > 0 else 0
    print(f"  Decimated {mesh_type}: {original_verts:,} → {new_verts:,} vertices ({reduction:.1f}% reduction)")

# --- Main Execution ---
folder_path = f'{paths.siteDir(state, project_name, siteNum)}/'
existing_object_names = set(bpy.data.objects.keys())

if os.path.exists(folder_path):
    files = [f for f in os.listdir(folder_path) if f.lower().endswith('.tif')]
    imported_objects = []
    
    # PHASE 1: Import everything
    newly_imported = []
    for file_name in files:
        object_name = file_name.replace('.tif', '')
        if object_name in existing_object_names:
            print(f"Skipping {file_name} - already in scene")
            imported_objects.append(bpy.data.objects[object_name])
            continue
        print(f"Importing: {file_name}...")
        import sys
        sys.stdout.flush()
        bpy.ops.importgis.georaster(filepath=os.path.join(folder_path, file_name), importMode='DEM_RAW')
        imported_obj = bpy.context.active_object
        imported_obj.name = object_name
        imported_objects.append(imported_obj)
        newly_imported.append(imported_obj)  # track fresh imports only
        print("  Import complete.")

    # shade the dem and flood rasters smooth
    smooth_terrain_and_water()

    # PHASE 2: Apply Scale (only newly imported)
    for obj in newly_imported:
        apply_scale_direct(obj)
    bpy.context.view_layer.update()

    # PHASE 3: Decimate (only newly imported)
    for obj in newly_imported:
        is_water  = 'floodmap' in obj.name.lower()
        ratio     = water_decimate_ratio if is_water else dem_decimate_ratio
        mesh_type = "water surface" if is_water else "DEM"
        apply_decimation(obj, ratio, mesh_type)
    bpy.context.view_layer.update()

    globals()['imported_rasters'] = [obj.name for obj in imported_objects]
    print(f"Imported rasters: {globals()['imported_rasters']}")
    
else:
    print(f"Error: Path not found - {folder_path}")
    globals()['imported_rasters'] = []