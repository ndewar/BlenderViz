"""
Import ESRI Multipatch OBJ files with correct positioning.
Reads JSON metadata for each OBJ to get real-world coordinates,
transforms from source CRS (EPSG:6438 Florida State Plane) to scene CRS (EPSG:3857).
"""

import bpy
import os
import json
import math

# Try to import BlenderGIS for coordinate transformation
HAS_BLENDERGIS = False
HAS_PYPROJ = False

try:
    from BlenderGIS import geoscene
    from BlenderGIS.core import proj
    HAS_BLENDERGIS = True
except ImportError:
    print("Warning: BlenderGIS not available.")

# Also try to import pyproj as fallback
try:
    from pyproj import Transformer
    HAS_PYPROJ = True
except ImportError:
    if not HAS_BLENDERGIS:
        print("Warning: Neither BlenderGIS nor pyproj available. Coordinates will not be transformed.")

# --- CONFIGURATION ---
# These can be overridden by globals from masterRunner.py
multipatch_folder = globals().get('multipatch_folder', '/path/to/your/obj/folder')
source_epsg = globals().get('source_epsg', 6438)  # Florida State Plane East (US feet)
target_epsg = globals().get('target_epsg', 3857)  # Web Mercator
source_units_per_meter = globals().get('source_units_per_meter', 1 / 0.3048006096012192)  # US feet to meters
collection_name = globals().get('multipatch_collection', 'Multipatch_Buildings')

# Position offset correction (in Blender units/meters) - adjust if buildings are offset
position_offset_x = globals().get('multipatch_offset_x', 0.0)
position_offset_y = globals().get('multipatch_offset_y', 0.0)
position_offset_z = globals().get('multipatch_offset_z', 0.0)

# Material settings
default_material_name = "MultipatchMaterial"
building_color = (0.6, 0.55, 0.5, 1.0)  # Neutral building color


def get_scene_origin():
    """Get the BlenderGIS scene origin in projected coordinates."""
    if HAS_BLENDERGIS:
        scn = bpy.context.scene
        geoscn_obj = geoscene.GeoScene(scn)
        return geoscn_obj.crsx, geoscn_obj.crsy, geoscn_obj.scale
    return 0, 0, 1


def get_dem_bounds_world():
    """
    Get the bounding box of the DEM object in world (projected) coordinates.
    Returns (min_x, max_x, min_y, max_y) in the scene's CRS (EPSG:3857).
    """
    # Find DEM object
    dem = next(
        (o for o in bpy.data.objects if o.type == 'MESH' and 'dem' in o.name.lower()),
        None
    )

    if dem is None:
        print("Warning: No DEM found in scene, cannot filter by bounds")
        return None

    # Get scene origin and scale
    scene_ox, scene_oy, scene_scale = get_scene_origin()

    # Get mesh bounds in local coordinates
    mesh = dem.data
    if not mesh.vertices:
        return None

    # Calculate bounds from vertices (in local/Blender coordinates)
    min_x_local = min(v.co.x for v in mesh.vertices)
    max_x_local = max(v.co.x for v in mesh.vertices)
    min_y_local = min(v.co.y for v in mesh.vertices)
    max_y_local = max(v.co.y for v in mesh.vertices)

    # Convert back to world/projected coordinates
    min_x_world = min_x_local * scene_scale + scene_ox
    max_x_world = max_x_local * scene_scale + scene_ox
    min_y_world = min_y_local * scene_scale + scene_oy
    max_y_world = max_y_local * scene_scale + scene_oy

    print(f"DEM bounds (EPSG:3857):")
    print(f"  X: {min_x_world:.2f} to {max_x_world:.2f}")
    print(f"  Y: {min_y_world:.2f} to {max_y_world:.2f}")

    return (min_x_world, max_x_world, min_y_world, max_y_world)


def point_in_bounds(x, y, bounds, buffer=0):
    """Check if a point is within the given bounds (with optional buffer)."""
    if bounds is None:
        return True  # No bounds = accept all

    min_x, max_x, min_y, max_y = bounds
    return (min_x - buffer <= x <= max_x + buffer and
            min_y - buffer <= y <= max_y + buffer)


# Global cache for transformation method
_transform_method = None  # Will be set to 'pyproj', 'blendergis', or 'manual'
_pyproj_transformer = None


def _test_and_cache_transform_method(source_crs, target_crs):
    """Test which transformation method works and cache it."""
    global _transform_method, _pyproj_transformer

    if _transform_method is not None:
        return _transform_method

    # Test coordinates (sample from Florida)
    test_x, test_y = 785000, 1475000

    # Try pyproj first
    if HAS_PYPROJ:
        try:
            _pyproj_transformer = Transformer.from_crs(f"EPSG:{source_crs}", f"EPSG:{target_crs}", always_xy=True)
            _pyproj_transformer.transform(test_x, test_y)
            _transform_method = 'pyproj'
            print("Using pyproj for coordinate transformation")
            return _transform_method
        except Exception as e:
            print(f"pyproj not available: {e}")

    # Try BlenderGIS
    if HAS_BLENDERGIS:
        try:
            proj.reprojPt(source_crs, target_crs, test_x, test_y)
            _transform_method = 'blendergis'
            print("Using BlenderGIS for coordinate transformation")
            return _transform_method
        except Exception as e:
            print(f"BlenderGIS transform not available: {e}")

    # Fall back to manual
    _transform_method = 'manual'
    print("Using manual coordinate transformation (EPSG:6438 -> EPSG:3857)")
    return _transform_method


def transform_coordinates(x, y, z, source_crs, target_crs):
    """
    Transform coordinates from source CRS to target CRS.

    Note: EPSG:6438 (Florida State Plane East) is defined in US feet.
    The projection library handles unit conversion automatically.
    We only need to convert Z to meters separately since it's not transformed.
    """
    global _transform_method, _pyproj_transformer

    # Convert Z from source units (US feet) to meters
    z_m = z / source_units_per_meter

    # Determine which method to use (cached after first call)
    if _transform_method is None:
        _test_and_cache_transform_method(source_crs, target_crs)

    # Use cached method
    if _transform_method == 'pyproj':
        x_out, y_out = _pyproj_transformer.transform(x, y)
        return x_out, y_out, z_m

    if _transform_method == 'blendergis':
        x_out, y_out = proj.reprojPt(source_crs, target_crs, x, y)
        return x_out, y_out, z_m

    # Manual transformation for Florida State Plane East (EPSG:6438) to Web Mercator (EPSG:3857)
    # Projection parameters for EPSG:6438 (from .prj file)
    false_easting_ft = 656166.6666666665
    false_northing_ft = 0.0
    central_meridian = -81.0
    lat_origin_deg = 24.33333333333333
    scale_factor = 0.9999411764705882
    us_ft_to_m = 0.3048006096012192

    # Convert to meters and remove false easting/northing
    x_m = (x - false_easting_ft) * us_ft_to_m
    y_m = (y - false_northing_ft) * us_ft_to_m

    # GRS80 ellipsoid parameters (used by NAD83/EPSG:6438)
    a = 6378137.0  # semi-major axis
    f = 1 / 298.257222101  # flattening
    e2 = 2 * f - f * f  # eccentricity squared
    e = math.sqrt(e2)

    # Helper function to calculate meridional arc from equator to a given latitude
    def meridional_arc(phi):
        """Calculate meridional arc distance from equator to latitude phi (radians)."""
        return a * (
            (1 - e2/4 - 3*e2*e2/64 - 5*e2*e2*e2/256) * phi
            - (3*e2/8 + 3*e2*e2/32 + 45*e2*e2*e2/1024) * math.sin(2*phi)
            + (15*e2*e2/256 + 45*e2*e2*e2/1024) * math.sin(4*phi)
            - (35*e2*e2*e2/3072) * math.sin(6*phi)
        )

    # Calculate meridional arc from equator to latitude of origin
    lat_origin_rad = math.radians(lat_origin_deg)
    M0 = meridional_arc(lat_origin_rad)

    # Total meridional arc = M0 + (y_m / scale_factor)
    # y_m is the northing from the latitude of origin
    M_total = M0 + y_m / scale_factor

    # Calculate footpoint latitude from total meridional arc using iterative method
    # Initial approximation
    mu = M_total / (a * (1 - e2/4 - 3*e2*e2/64 - 5*e2*e2*e2/256))

    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))

    # Footpoint latitude (no need to add lat_origin - it's already included in M_total)
    phi1 = mu + (3*e1/2 - 27*e1*e1*e1/32) * math.sin(2*mu)
    phi1 += (21*e1*e1/16 - 55*e1*e1*e1*e1/32) * math.sin(4*mu)
    phi1 += (151*e1*e1*e1/96) * math.sin(6*mu)
    phi1 += (1097*e1*e1*e1*e1/512) * math.sin(8*mu)

    # Calculate latitude and longitude from footpoint
    N1 = a / math.sqrt(1 - e2 * math.sin(phi1)**2)
    T1 = math.tan(phi1)**2
    C1 = e2 / (1 - e2) * math.cos(phi1)**2
    R1 = a * (1 - e2) / ((1 - e2 * math.sin(phi1)**2)**1.5)
    D = x_m / (N1 * scale_factor)

    # Final latitude (correction from footpoint)
    lat = phi1 - (N1 * math.tan(phi1) / R1) * (
        D*D/2
        - (5 + 3*T1 + 10*C1 - 4*C1*C1 - 9*e2/(1-e2)) * D*D*D*D/24
        + (61 + 90*T1 + 298*C1 + 45*T1*T1 - 252*e2/(1-e2) - 3*C1*C1) * D**6/720
    )

    # Final longitude
    lon = math.radians(central_meridian) + (
        D
        - (1 + 2*T1 + C1) * D*D*D/6
        + (5 - 2*C1 + 28*T1 - 3*C1*C1 + 8*e2/(1-e2) + 24*T1*T1) * D**5/120
    ) / math.cos(phi1)

    lat_deg = math.degrees(lat)
    lon_deg = math.degrees(lon)

    # Convert lat/lon (WGS84) to Web Mercator (EPSG:3857)
    x_3857 = lon_deg * 20037508.34 / 180.0
    lat_rad = math.radians(lat_deg)
    y_3857 = math.log(math.tan(math.pi/4 + lat_rad/2)) * 20037508.34 / math.pi

    return x_3857, y_3857, z_m


def create_default_material():
    """Create a default material for the multipatch objects."""
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


def get_or_create_collection(name):
    """Get or create a collection for the multipatch objects."""
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    return collection


def import_multipatch_obj(obj_path, json_path, collection, material):
    """Import a single OBJ file and position it using JSON metadata."""
    
    # Read JSON metadata
    try:
        with open(json_path, 'r') as f:
            metadata = json.load(f)
    except Exception as e:
        print(f"Error reading JSON {json_path}: {e}")
        return None
    
    attrs = metadata.get('attributes', {})
    
    # Get origin coordinates from JSON (in source CRS units - US feet)
    ox = attrs.get('ESRI3DO_OX', 0)
    oy = attrs.get('ESRI3DO_OY', 0)
    oz = attrs.get('ESRI3DO_OZ', 0)
    
    # Get transform parameters
    tx = attrs.get('ESRI3DO_TX', 0)
    ty = attrs.get('ESRI3DO_TY', 0)
    tz = attrs.get('ESRI3DO_TZ', 0)
    sx = attrs.get('ESRI3DO_SX', 1)
    sy = attrs.get('ESRI3DO_SY', 1)
    sz = attrs.get('ESRI3DO_SZ', 1)
    
    # Rotation (axis-angle format)
    rx = attrs.get('ESRI3DO_RX', 0)
    ry = attrs.get('ESRI3DO_RY', 1)
    rz = attrs.get('ESRI3DO_RZ', 0)
    rdeg = attrs.get('ESRI3DO_RDEG', 0)
    
    # Transform origin to target CRS
    world_x, world_y, world_z = transform_coordinates(ox + tx, oy + ty, oz + tz, source_epsg, target_epsg)
    
    # Get scene origin for relative positioning
    scene_ox, scene_oy, scene_scale = get_scene_origin()
    
    # Calculate Blender position (relative to scene origin) with offset correction
    blender_x = (world_x - scene_ox) / scene_scale + position_offset_x
    blender_y = (world_y - scene_oy) / scene_scale + position_offset_y
    blender_z = world_z / scene_scale + position_offset_z
    
    # Import OBJ
    try:
        bpy.ops.wm.obj_import(filepath=obj_path)
    except AttributeError:
        # Fallback for older Blender versions
        bpy.ops.import_scene.obj(filepath=obj_path)
    
    # Get the imported object(s)
    imported_objs = [obj for obj in bpy.context.selected_objects]
    
    for obj in imported_objs:
        # Move to collection
        for coll in obj.users_collection:
            coll.objects.unlink(obj)
        collection.objects.link(obj)
        
        # Set position
        obj.location = (blender_x, blender_y, blender_z)
        
        # Apply scale (convert from source units)
        scale_factor = 1 / source_units_per_meter / scene_scale
        obj.scale = (sx * scale_factor, sy * scale_factor, sz * scale_factor)
        
        # Apply rotation if specified
        if rdeg != 0:
            obj.rotation_mode = 'AXIS_ANGLE'
            obj.rotation_axis_angle = (math.radians(rdeg), rx, ry, rz)
        
        # Assign material
        if obj.type == 'MESH':
            if not obj.data.materials:
                obj.data.materials.append(material)
            else:
                obj.data.materials[0] = material

    return imported_objs


def find_json_for_obj(obj_path):
    """
    Find the JSON metadata file for an OBJ file.
    Handles ESRI naming convention where JSON is named differently than OBJ.
    """
    obj_dir = os.path.dirname(obj_path)
    obj_basename = os.path.basename(obj_path).replace('.obj', '')

    # Try different naming patterns
    possible_names = [
        f"{obj_basename}.json",                    # Same name as OBJ
        f"{obj_basename}_ESRI3DO.json",           # ESRI naming convention
        "esriGeometryMultiPatch_ESRI3DO.json",    # Standard ESRI multipatch name
    ]

    for name in possible_names:
        json_path = os.path.join(obj_dir, name)
        if os.path.exists(json_path):
            return json_path

    return None


def check_obj_in_bounds(json_path, bounds, buffer=0):
    """
    Check if an OBJ's center point falls within the scene bounds.
    Reads the JSON metadata without importing the OBJ.

    Returns:
    --------
    tuple: (is_in_bounds, world_x, world_y) or (False, None, None) on error
    """
    if bounds is None:
        return True, None, None

    try:
        with open(json_path, 'r') as f:
            metadata = json.load(f)
    except Exception:
        return False, None, None

    attrs = metadata.get('attributes', {})

    # Get origin coordinates (in source CRS units - US feet)
    ox = attrs.get('ESRI3DO_OX', 0)
    oy = attrs.get('ESRI3DO_OY', 0)
    oz = attrs.get('ESRI3DO_OZ', 0)
    tx = attrs.get('ESRI3DO_TX', 0)
    ty = attrs.get('ESRI3DO_TY', 0)
    tz = attrs.get('ESRI3DO_TZ', 0)

    # Transform to target CRS (EPSG:3857)
    world_x, world_y, _ = transform_coordinates(ox + tx, oy + ty, oz + tz, source_epsg, target_epsg)

    # Check if within bounds
    is_in_bounds = point_in_bounds(world_x, world_y, bounds, buffer)

    return is_in_bounds, world_x, world_y


def find_obj_files(folder_path):
    """
    Recursively find all OBJ files in folder and subfolders.
    Returns list of full paths to OBJ files.
    """
    obj_files = []
    for root, dirs, files in os.walk(folder_path):
        for f in files:
            if f.lower().endswith('.obj'):
                obj_files.append(os.path.join(root, f))
    return obj_files


def import_all_multipatch(folder_path, max_objects=None, filter_by_dem=True, buffer_meters=0):
    """
    Import all OBJ files from a folder (and subfolders) with their JSON metadata.
    Only imports objects whose center point falls within the DEM bounds.

    Parameters:
    -----------
    folder_path : str
        Path to folder containing .obj and .json files (searches recursively)
    max_objects : int, optional
        Maximum number of objects to import (for testing)
    filter_by_dem : bool
        If True, only import objects within DEM bounds (default: True)
    buffer_meters : float
        Buffer distance in meters around DEM bounds (default: 0)
    """

    if not os.path.exists(folder_path):
        print(f"Error: Folder not found: {folder_path}")
        return []

    # Get all OBJ files recursively
    obj_paths = find_obj_files(folder_path)
    print(f"Found {len(obj_paths)} OBJ files in {folder_path} (including subfolders)")

    # Get DEM bounds for filtering
    bounds = None
    if filter_by_dem:
        bounds = get_dem_bounds_world()
        if bounds is None:
            print("Warning: Could not get DEM bounds, importing all objects")

    # First pass: filter by bounds (fast - just reads JSON)
    if bounds is not None:
        print(f"\nFiltering objects by DEM bounds (buffer: {buffer_meters}m)...")
        filtered_paths = []
        skipped_count = 0
        no_json_count = 0
        debug_printed = False

        for obj_path in obj_paths:
            json_path = find_json_for_obj(obj_path)
            if json_path:
                in_bounds, world_x, world_y = check_obj_in_bounds(json_path, bounds, buffer_meters)

                # Debug: print first few coordinate transformations
                if not debug_printed and world_x is not None:
                    print(f"  Debug - Sample transformed coords: X={world_x:.2f}, Y={world_y:.2f}")
                    debug_printed = True

                if in_bounds:
                    filtered_paths.append(obj_path)
                else:
                    skipped_count += 1
            else:
                no_json_count += 1

        print(f"  {len(filtered_paths)} objects within bounds")
        print(f"  {skipped_count} objects outside bounds (skipped)")
        if no_json_count > 0:
            print(f"  {no_json_count} objects with no JSON metadata")
        obj_paths = filtered_paths

    if max_objects:
        obj_paths = obj_paths[:max_objects]
        print(f"Limiting to {max_objects} objects for testing")

    # Create collection and material
    collection = get_or_create_collection(collection_name)
    material = create_default_material()

    imported_count = 0
    failed_count = 0
    all_objects = []

    print(f"\nImporting {len(obj_paths)} objects...")

    for i, obj_path in enumerate(obj_paths):
        json_path = find_json_for_obj(obj_path)

        if not json_path:
            print(f"Warning: No JSON found for {obj_path}, skipping")
            failed_count += 1
            continue

        # Progress update every 100 objects
        if (i + 1) % 100 == 0:
            print(f"Progress: {i + 1}/{len(obj_paths)} objects imported...")

        try:
            objs = import_multipatch_obj(obj_path, json_path, collection, material)
            if objs:
                all_objects.extend(objs)
                imported_count += 1
        except Exception as e:
            print(f"Error importing {obj_path}: {e}")
            failed_count += 1

    print(f"\nImport complete:")
    print(f"  Successfully imported: {imported_count}")
    print(f"  Failed: {failed_count}")
    print(f"  Total objects in scene: {len(all_objects)}")

    return all_objects


# --- MAIN EXECUTION ---
if __name__ == "__main__" or globals().get('run_import', False):
    # Configuration options (can be set via globals before running)
    max_test = globals().get('max_test_objects', None)  # Set to a number for testing
    filter_dem = globals().get('filter_by_dem', True)   # Filter by DEM bounds
    buffer_m = globals().get('bounds_buffer_meters', 50)  # Buffer around DEM bounds

    # Run the import
    imported = import_all_multipatch(
        multipatch_folder,
        max_objects=max_test,
        filter_by_dem=filter_dem,
        buffer_meters=buffer_m
    )
    globals()['imported_multipatch'] = imported

