import bpy
import os

# Define your variables
county = globals().get('county', 'brevard')
siteNum = globals().get('siteNum', 1)
state = globals().get('state', 'florida')

# Define the directory path where your rasters are stored
folder_path = f'/Users/noahdewar/Documents/HighTide/data/{state}/counties/{county}/blender/site{siteNum}/'

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
