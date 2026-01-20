import bpy
import os

# 1. Variables (Passed from Master Runner)
state = globals().get('state', 'florida')
county = globals().get('county', 'brevard')
siteNum = globals().get('siteNum', 1)

# 2. Path to your Shapefile
# Update this path to where your shapefiles are stored
shp_path = f"//Users/noahdewar/Documents/HighTide/data/{state}/counties/{county}/blender/site{siteNum}/finalBuildings_Site{siteNum}_3857.shp"

def import_and_extrude_shp(filepath):
    if not os.path.exists(filepath):
        print(f"Shapefile not found: {filepath}")
        return

    # 3. Import GIS Shapefile
    # fieldElevation: The column name for the base height (Z-offset)
    # fieldExtrude: The column name for the height of the extrusion
    # We removed 'force7001' and simplified the arguments
    bpy.ops.importgis.shapefile(
        filepath=filepath,
        shpCRS='EPSG:3857',
        fieldElevName='elevation', 
        fieldExtrudeName='height',
        extrusionAxis='Z',
        separateObjects=False     # Set to True if you want every building as a separate mesh
    )

    # 4. Cleanup: Name the imported object
    # BlenderGIS usually names it after the file; we can find it by looking for the active object
    obj = bpy.context.active_object
    if obj:
        obj.name = f"{county}_buildings"
        print(f"Successfully imported and extruded: {obj.name}")

# Run the function
import_and_extrude_shp(shp_path)