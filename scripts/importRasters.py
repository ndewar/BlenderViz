import bpy
import os

# Define your variables
county = globals().get('county', 'brevard')
siteNum = globals().get('siteNum', 1)
state = globals().get('state', 'florida')
restrict_import = globals().get('restrict_import', True)

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
            
            print(f"Importing: {file_name}")
            
            # Import the raster
            bpy.ops.importgis.georaster(
                filepath=full_path, 
                importMode='DEM_RAW'
            )
            
            # Store the object name (without .tif extension)
            object_name = file_name.replace('.tif', '')
            imported_rasters.append(object_name)
    
    # Store in globals for other scripts to use
    globals()['imported_rasters'] = imported_rasters
    print(f"Imported rasters: {imported_rasters}")
    
else:
    print(f"Error: Path not found - {folder_path}")
    globals()['imported_rasters'] = []
