"""
Import Master 3D Building OBJ and spatially join it with Enriched GeoJSON.

Features:
1. Parses OBJ header for true Lat/Lon origin.
2. Imports and correctly projects the master mesh into EPSG:3857 space.
3. Splits the master mesh into individual building objects.
4. Performs a Point-in-Polygon spatial join against the enriched GeoJSON.
5. Assigns all GeoJSON properties (Asset Classes, Flood Depths) to Blender custom properties.
6. Clips out buildings outside the defined shapefile domain.
"""

import bpy
import os
import json
import math
import mathutils
import addon_utils
import importlib

# --- Try to dynamically find and load BlenderGIS ---
HAS_BLENDERGIS = False
candidate_names = ["BlenderGIS", "BlenderGIS-master", "blendergis", "blendergis-master"]
ADDON = None

for mod in addon_utils.modules():
    if mod.__name__ in candidate_names:
        ADDON = mod.__name__
        break

if ADDON:
    try:
        loaded, enabled = addon_utils.check(ADDON)
        if not enabled:
            addon_utils.enable(ADDON, default_set=True, persistent=True)
        
        # Dynamically load the modules we need using the localized name
        geoscene = importlib.import_module(f"{ADDON}.geoscene")
        proj = importlib.import_module(f"{ADDON}.core.proj")
        HAS_BLENDERGIS = True
    except Exception as e:
        print(f"Warning: Found {ADDON} but failed to load submodules: {e}")
else:
    print("Warning: BlenderGIS not found on this system.")

# --- CONFIGURATION ---
state = globals().get('state', 'florida')
county = globals().get('county', 'brevard')
site_num = globals().get('siteNum', 1)
project_name = globals().get('project_name')

# Paths
base_path = f"/Users/noahdewar/Documents/HighTide/data/{state}/projects/{project_name}/blender/site{site_num}"
obj_path = globals().get('building_obj_path', f"{base_path}/buildings_3d_blender.obj")
geojson_path = globals().get('enriched_geojson_path', f"{base_path}/buildings_enriched_Site{site_num}.geojson")
clip_shapefile_path = f"{base_path}/clipGeom.shp"

print(obj_path)
print(geojson_path)
collection_name = globals().get('building_collection', 'Master_Buildings')
default_material_name = "MasterBuildingMaterial"
building_color = (0.6, 0.55, 0.5, 1.0) 


def get_scene_origin():
    """Get the BlenderGIS scene origin in projected coordinates."""
    if HAS_BLENDERGIS:
        scn = bpy.context.scene
        geoscn_obj = geoscene.GeoScene(scn)
        return geoscn_obj.crsx, geoscn_obj.crsy, geoscn_obj.scale
    
    # Bulletproof Fallback: check if the scene has the properties natively attached
    if hasattr(bpy.context.scene, 'geoscene'):
        gs = bpy.context.scene.geoscene
        return gs.crsx, gs.crsy, gs.scale
        
    print("  [!] Could not determine geoscene origin. Buildings will be placed at 0,0.")
    return 0, 0, 1


def parse_obj_header_for_origin(filepath):
    """Reads the top lines of the OBJ to extract the centre lat/lon."""
    print(f"  Parsing OBJ header: {filepath}")
    lat, lon = None, None
    with open(filepath, 'r') as f:
        for _ in range(20):  # Check first 20 lines
            line = f.readline()
            if not line: break
            if "Centre: lon=" in line and "lat=" in line:
                parts = line.split()
                for p in parts:
                    if p.startswith("lon="): lon = float(p.split("=")[1])
                    if p.startswith("lat="): lat = float(p.split("=")[1])
                break
    
    if lat is None or lon is None:
        raise ValueError("Could not find 'centre lon=... lat=...' in OBJ header.")
    
    print(f"    Found Origin: Lat {lat}, Lon {lon}")
    return lat, lon


def create_default_material():
    """Create a neutral default material for the buildings."""
    mat = bpy.data.materials.get(default_material_name)
    if mat is None:
        mat = bpy.data.materials.new(name=default_material_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        bsdf = nodes.get('Principled BSDF')
        if bsdf:
            bsdf.inputs['Base Color'].default_value = building_color
            bsdf.inputs['Roughness'].default_value = 0.8
    return mat


def point_in_polygon(x, y, polygon):
    """
    Ray-casting algorithm to determine if a 2D point is inside a 2D polygon.
    Polygon is a list of [x, y] coordinate pairs.
    """
    n = len(polygon)
    inside = False
    p1x, p1y = polygon[0]
    for i in range(n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xints = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xints:
                        inside = not inside
        p1x, p1y = p2x, p2y
    return inside


def ground_buildings_to_dem(buildings):
    """
    Raycasts down from the sky to the DEM at the corners of each building 
    to find the average ground elevation, then shifts the building vertically.
    """
    print("\n  Grounding buildings to DEM...")
    
    # 1. Find the DEM object in the scene
    dem_obj = next((o for o in bpy.data.objects if 'dem' in o.name.lower() and o.type == 'MESH'), None)
    if not dem_obj:
        print("  [!] Could not find DEM object to ground buildings.")
        return

    # Pre-calculate matrix inversions for fast local-space raycasting
    dem_mat_inv = dem_obj.matrix_world.inverted()
    down_vec_local = (dem_mat_inv.to_3x3() @ mathutils.Vector((0, 0, -1))).normalized()

    grounded_count = 0
    
    for obj in buildings:
        if obj.type != 'MESH':
            continue

        # 2. Get the bottom 4 corners and bottom center of the building's bounding box
        bbox_world = [obj.matrix_world @ mathutils.Vector(v) for v in obj.bound_box]
        bottom_corners = sorted(bbox_world, key=lambda v: v.z)[:4]
        
        bottom_center = mathutils.Vector((
            sum(v.x for v in bottom_corners) / 4,
            sum(v.y for v in bottom_corners) / 4,
            sum(v.z for v in bottom_corners) / 4
        ))
        
        sample_points = bottom_corners + [bottom_center]
        hit_z_values = []

        # 3. Raycast straight down from the sky (Z + 10000) for each point
        for pt in sample_points:
            ray_origin_world = mathutils.Vector((pt.x, pt.y, pt.z + 10000.0))
            ray_origin_local = dem_mat_inv @ ray_origin_world
            
            # Use the DEM's native ray_cast (much faster and ignores other buildings)
            success, loc, normal, face_index = dem_obj.ray_cast(ray_origin_local, down_vec_local)
            
            if success:
                hit_world = dem_obj.matrix_world @ loc
                hit_z_values.append(hit_world.z)

        # 4. Calculate the offset and apply it
        if hit_z_values:
            avg_dem_z = sum(hit_z_values) / len(hit_z_values)
            bldg_bottom_z = bottom_center.z
            
            # The difference between the DEM and the building's current bottom
            z_offset = avg_dem_z - bldg_bottom_z
            
            # Optional: subtract an extra 0.2 meters to "plant" the foundation 
            # slightly underground so it doesn't float on slopes!
            z_offset -= 0.2 
            
            obj.location.z += z_offset
            grounded_count += 1
            
    print(f"  Successfully grounded {grounded_count} buildings.")


def spatial_join_properties(buildings, geojson_path):
    """
    Mathematically match each Blender building to its GeoJSON footprint 
    and copy the properties over. Deletes any building not found in the GeoJSON.
    """
    print(f"\n  Starting Spatial Join with: {geojson_path}")
    if not os.path.exists(geojson_path):
        print("  [!] GeoJSON not found, skipping spatial join.")
        return

    with open(geojson_path, 'r') as f:
        data = json.load(f)
    
    features = data.get("features", [])
    print(f"    Loaded {len(features)} polygons from GeoJSON.")

    scene_ox, scene_oy, scene_scale = get_scene_origin()
    match_count = 0
    removed_count = 0

    # Ensure all objects have updated transforms before measuring locations
    bpy.context.view_layer.update()

    # Wrap in list() so we don't break the loop when we delete objects
    for obj in list(buildings):
        if obj.type != 'MESH':
            continue

        # 1. Get building center in world (EPSG:3857) coordinates
        world_x = (obj.location.x * scene_scale) + scene_ox
        world_y = (obj.location.y * scene_scale) + scene_oy

        found_match = False

        # 2. Loop through GeoJSON to find which polygon encloses this point
        for feature in features:
            geom = feature.get("geometry", {})
            geom_type = geom.get("type", "")
            coords = geom.get("coordinates", [])

            is_inside = False

            if geom_type == "Polygon":
                exterior_ring = coords[0]
                is_inside = point_in_polygon(world_x, world_y, exterior_ring)
            
            elif geom_type == "MultiPolygon":
                for poly in coords:
                    exterior_ring = poly[0]
                    if point_in_polygon(world_x, world_y, exterior_ring):
                        is_inside = True
                        break
            
            # 3. If matched, copy all properties and break the loop
            if is_inside:
                props = feature.get("properties", {})
                
                # Assign to Blender Custom Properties
                for key, value in props.items():
                    if value is not None:
                        obj[key] = value
                
                # Optionally rename the object if it has a CA_Name or ID
                if "CA_Name" in props and props["CA_Name"]:
                    obj.name = str(props["CA_Name"]).replace(" ", "_")
                
                match_count += 1
                found_match = True
                break
        
        # --- NEW: Delete the building if it wasn't in the clipped GeoJSON ---
        if not found_match:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed_count += 1

    print(f"  Spatial Join Complete: Matched {match_count} buildings. Deleted {removed_count} out-of-bounds buildings.")
    

def import_master_mesh():
    """Imports, projects, splits, and formats the Master OBJ."""
    print(f"\n--- Importing Master Building Mesh ---")
    
    if not os.path.exists(obj_path):
        print(f"  [!] Master OBJ not found at {obj_path}")
        return

    # 1. Parse Header & Project
    lat, lon = parse_obj_header_for_origin(obj_path)
    if HAS_BLENDERGIS:
        world_x, world_y = proj.reprojPt(4326, 3857, lon, lat)
    else:
        # Fallback pseudo-mercator math if BlenderGIS is missing
        world_x = lon * 20037508.34 / 180.0
        world_y = math.log(math.tan((90 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
        world_y = world_y * 20037508.34 / 180.0

    scene_ox, scene_oy, scene_scale = get_scene_origin()
    
    blender_x = (world_x - scene_ox) / scene_scale
    blender_y = (world_y - scene_oy) / scene_scale
    blender_z = 0.0  # Align to ground

    # 2. Import the OBJ
    print("  Importing OBJ (this may take a moment)...")
    bpy.ops.object.select_all(action='DESELECT')
    
    try:
        # Blender 4.x new importer
        bpy.ops.wm.obj_import(filepath=obj_path, forward_axis='Y', up_axis='Z')
    except AttributeError:
        # Legacy importer
        bpy.ops.import_scene.obj(filepath=obj_path, axis_forward='Y', axis_up='Z')
        
    imported_objs = bpy.context.selected_objects
    if not imported_objs:
        print("  [!] Failed to import any objects.")
        return
    
    master_obj = imported_objs[0]
    
    # 3. Position and Scale the Master Mesh(es)
    # Calculate the Web Mercator stretch factor based on the site's latitude
    mercator_stretch = 1.0 / math.cos(math.radians(lat))
    print(f"  Applying Web Mercator stretch factor: {mercator_stretch:.5f}")

    bpy.ops.object.select_all(action='DESELECT')

    for obj in imported_objs:
        # Set the origin location
        obj.location = (blender_x, blender_y, blender_z)
        
        # Scale X and Y by the Mercator stretch. 
        # Z remains 1.0 (True Meters) so the buildings don't become artificially tall.
        # Everything is additionally divided by the scene_scale for BlenderGIS compliance.
        obj.scale = (
            mercator_stretch / scene_scale, 
            mercator_stretch / scene_scale, 
            1.0 / scene_scale
        )
        obj.select_set(True)
    
    bpy.context.view_layer.objects.active = imported_objs[0]
    bpy.context.view_layer.update()

    # CRITICAL: We must "Apply" the scale permanently to the vertices before splitting.
    # Otherwise, the bounding-box math for the spatial join will fail!
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    # 4. Split by Loose Parts
    print("  Splitting mesh into individual buildings...")
    bpy.ops.mesh.separate(type='LOOSE')

    # Force selection to a standard list to avoid context issues during deletion
    buildings = list(bpy.context.selected_objects)
    print(f"    Split into {len(buildings)} individual buildings.")

    # 5. Set Origin to Geometry Bounds for every building
    print("  Centering origins for all buildings...")
    bpy.ops.object.select_all(action='DESELECT')
    for obj in buildings:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = buildings[0] if buildings else None
    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')

    # --- NEW: Ground the buildings to the DEM ---
    ground_buildings_to_dem(buildings)
    bpy.context.view_layer.update()

    # 6. Organize in Collection and Assign Material
    collection = bpy.data.collections.get(collection_name)
    if not collection:
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)
        
    material = create_default_material()

    for obj in buildings:
        # Move to correct collection
        for coll in obj.users_collection:
            coll.objects.unlink(obj)
        collection.objects.link(obj)
        
        # Apply Material
        if obj.type == 'MESH':
            if not obj.data.materials:
                obj.data.materials.append(material)
            else:
                obj.data.materials[0] = material

    # 7. Perform the Spatial Join
    spatial_join_properties(buildings, geojson_path)

    print("--- Master Building Import Complete ---\n")

# Main Execution Trigger
if globals().get('run_import', True):
    print("\n[DEBUG] Pipeline trigger detected. Starting import process...")
    import_master_mesh()
else:
    print("\n[DEBUG] 'run_import' was False. Skipping building import.")