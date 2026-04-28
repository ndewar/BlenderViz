import bpy
import os

# Define your variables
county = globals().get('county', 'brevard')
siteNum = globals().get('siteNum', 1)
state = globals().get('state', 'florida')
restrict_import = globals().get('restrict_import', True)

# Decimation settings (ratio = fraction of vertices to keep)
dem_decimate_ratio = globals().get('dem_decimate_ratio', 0.25)  # Keep 25% of DEM vertices
water_decimate_ratio = globals().get('water_decimate_ratio', 0.1)  # Keep 10% of water vertices


def apply_decimation(obj, ratio, mesh_type="mesh"):
    """
    Apply decimation modifier to reduce vertex count.
    Uses UN_SUBDIVIDE mode which is very fast for grid-based meshes (like imported rasters).
    The 'iterations' parameter controls how many times to halve the mesh.
    """
    if ratio >= 1.0:
        print(f"  Skipping decimation for {mesh_type} (ratio=1.0)")
        return

    original_verts = len(obj.data.vertices)
    print(f"  Decimating {mesh_type} ({original_verts:,} vertices, target ratio={ratio})...")

    # Ensure object is selected and active (required for modifier_apply)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # Make sure we're in object mode
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Use UN_SUBDIVIDE - much faster for grid meshes (imported rasters)
    # Each iteration halves the vertex count:
    # iterations=1 → ~50%, iterations=2 → ~25%, iterations=3 → ~12.5%, iterations=4 → ~6%
    if ratio <= 0.06:      # target ≤6% → 4 iterations
        iterations = 4
    elif ratio <= 0.12:    # target ≤12% → 3 iterations  (water at 0.1)
        iterations = 3
    elif ratio <= 0.25:    # target ≤25% → 2 iterations  (DEM at 0.25)
        iterations = 2
    else:                  # target >25% → 1 iteration
        iterations = 1

    decimate = obj.modifiers.new(name='Decimate', type='DECIMATE')
    decimate.decimate_type = 'UNSUBDIV'
    decimate.iterations = iterations

    # Apply the modifier
    bpy.ops.object.modifier_apply(modifier='Decimate')

    new_verts = len(obj.data.vertices)
    reduction = (1 - new_verts / original_verts) * 100 if original_verts > 0 else 0
    print(f"  Decimated {mesh_type}: {original_verts:,} → {new_verts:,} vertices ({reduction:.1f}% reduction)")

# Define the directory path where your rasters are stored
folder_path = f'/Users/noahdewar/Documents/HighTide/data/{state}/counties/{county}/blender/site{siteNum}/'

# Get list of object names already in the scene
existing_object_names = set(bpy.data.objects.keys())

# Check if the directory exists before proceeding
if os.path.exists(folder_path):
    # List all files in the directory
    files = os.listdir(folder_path)
    
    # Store imported raster names
    imported_rasters = []
    
    # Filter for .tif files and loop through them
    for file_name in files:
        if file_name.lower().endswith('.tif'):
            # Construct the full file path
            full_path = os.path.join(folder_path, file_name)

            # only import C1 High or Low floodmaps
            # for now, only import floodmap_2070_High_C1_site4_3857 as its the one we are using for the flyover
            if restrict_import:
                if 'floodmap' in file_name.lower():
                    has_c1 = '_c1_' in file_name.lower()
                    has_high = '_high_' in file_name.lower()
                    has_low = '_low_' in file_name.lower()
                    
                    #if not (has_c1 and (has_high or has_low)):
                    #    print(f"Skipping {file_name} - missing C1 or HIGH or LOW")
                    #    continue

                    #if not '2070_high_c1' in file_name.lower():
                    #    print(f"Skipping {file_name} - only import floodmap_2070_High_C1_site4_3857 for the flyover")
                    #    continue
            
            # if raster is already imported, skip import
            object_name = file_name.replace('.tif', '')
            if object_name in existing_object_names:
                print(f"Skipping {file_name} - already in scene as '{object_name}'")
                imported_rasters.append(object_name)  # still track it
                continue
            
            print(f"Importing: {file_name}...")
            import sys
            sys.stdout.flush()  # Force output to display immediately

            # Import the raster (this can be slow for large TIFs)
            bpy.ops.importgis.georaster(
                filepath=full_path,
                importMode='DEM_RAW'
            )
            print(f"  Import complete.")

            # Store the object name (without .tif extension)
            object_name = file_name.replace('.tif', '')
            imported_rasters.append(object_name)

            # Apply decimation to reduce vertex count
            imported_obj = bpy.data.objects.get(object_name)
            if imported_obj and imported_obj.type == 'MESH':
                is_water = 'floodmap' in file_name.lower()
                ratio = water_decimate_ratio if is_water else dem_decimate_ratio
                mesh_type = "water surface" if is_water else "DEM"
                apply_decimation(imported_obj, ratio, mesh_type)
            else:
                print(f"  Warning: Could not find imported object '{object_name}' for decimation")
    
    # Store in globals for other scripts to use
    globals()['imported_rasters'] = imported_rasters
    print(f"Imported rasters: {imported_rasters}")
    
else:
    print(f"Error: Path not found - {folder_path}")
    globals()['imported_rasters'] = []
