import bpy
import os
from mathutils import Matrix

# --- Variables ---
county = globals().get('county', 'brevard')
siteNum = globals().get('siteNum', 1)
state = globals().get('state', 'florida')
restrict_import = globals().get('restrict_import', True)
restrict_import = True

dem_decimate_ratio = globals().get('dem_decimate_ratio', 0.25)  
water_decimate_ratio = globals().get('water_decimate_ratio', 0.1)  

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
folder_path = f'/Users/noahdewar/Documents/HighTide/data/{state}/counties/{county}/blender/site{siteNum}/'
existing_object_names = set(bpy.data.objects.keys())

if os.path.exists(folder_path):
    files = [f for f in os.listdir(folder_path) if f.lower().endswith('.tif')]
    imported_objects = []
    
    # PHASE 1: Import everything
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
        print("  Import complete.")

    # PHASE 2: Identify targets and Apply Scale
    dem_obj = next((obj for obj in imported_objects if 'dem' in obj.name.lower()), None)
    water_objs = [obj for obj in imported_objects if 'floodmap' in obj.name.lower()]
    
    for obj in imported_objects:
        apply_scale_direct(obj)
    bpy.context.view_layer.update()

    # PHASE 3: Decimate FIRST
    for obj in imported_objects:
        is_water   = 'floodmap' in obj.name.lower()
        ratio      = water_decimate_ratio if is_water else dem_decimate_ratio
        mesh_type  = "water surface" if is_water else "DEM"
        apply_decimation(obj, ratio, mesh_type)

    bpy.context.view_layer.update()

    globals()['imported_rasters'] = [obj.name for obj in imported_objects]
    print(f"Imported rasters: {globals()['imported_rasters']}")
    
else:
    print(f"Error: Path not found - {folder_path}")
    globals()['imported_rasters'] = []