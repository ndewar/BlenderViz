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
import struct
import mathutils
import addon_utils
import importlib
import subprocess
import platform
import ast
from pathlib import Path

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
clip_shapefile_path = f"{base_path}/clipGeom_3857.shp"

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


def batch_project_survivors(survivors, source_epsg=3857):
    """
    Passes a list of coordinates to your external Conda Python to get Web
    Mercator (EPSG:3857) and Lat/Lon (EPSG:4326) coordinates back in a single
    batch call.

    NOTE: The extraction pipeline (extract_tile) already reprojects all point
    cloud data, footprints, and JSON metadata (building_min_x_absolute,
    tile_offset_x/y, etc.) into EPSG:3857 before writing them to disk. So by
    default, source_epsg is 3857 -- the "projection" for wm_x/wm_y is a
    passthrough, and we only need pyproj to derive accurate lat/lon (via the
    inverse Web Mercator transform) for the Mercator-stretch scale factor.
    Only override source_epsg if you are feeding this function coordinates
    that are NOT already in 3857 (e.g. raw State Plane values from some other
    source).
    """
    print(f"  [CRS] Batch projecting {len(survivors)} buildings via Conda Python (source EPSG:{source_epsg})...")

    hostname = platform.node().lower()
    env_name = "surf_v2" if "studio" in hostname else "surf_v1"
    python_bin = f"/Users/noahdewar/miniconda3/envs/{env_name}/bin/python"

    script = f"""
from pyproj import Transformer

source_epsg = {source_epsg}

if source_epsg == 3857:
    def to_3857(x, y):
        return x, y
else:
    _t3857 = Transformer.from_crs(f'EPSG:{{source_epsg}}', 'EPSG:3857', always_xy=True)
    def to_3857(x, y):
        return _t3857.transform(x, y)

transformer_4326 = Transformer.from_crs(f'EPSG:{{source_epsg}}', 'EPSG:4326', always_xy=True)

results = {{}}
for bid, x, y in {[(b['id'], b['x'], b['y']) for b in survivors]}:
    wm_x, wm_y = to_3857(x, y)
    lon, lat = transformer_4326.transform(x, y)
    results[bid] = (wm_x, wm_y, lat, lon)
print(results)
"""
    try:
        custom_env = os.environ.copy()
        custom_env["PROJ_LIB"] = f"/Users/noahdewar/miniconda3/envs/{env_name}/share/proj"

        # THE FIX: Run python without '-c', and pipe the script directly into standard input
        result = subprocess.run(
            [python_bin], 
            input=script, 
            env=custom_env, 
            capture_output=True, 
            text=True
        )
        
        # Check for stderr in case the python script itself crashed
        if result.returncode != 0:
            print(f"  [!] Conda Python Error: {result.stderr.strip()}")
            return None
            
        return ast.literal_eval(result.stdout.strip())
        
    except Exception as e:
        print(f"  [!] Batch projection failed: {e}")
        return None

    
def reproject_shapefile_ogr(shp_path, target_epsg=3857):
    """
    Uses GDAL's ogr2ogr via absolute path to reproject a shapefile.
    Automatically detects if running on Mac Studio (surf_v2) or MacBook (surf_v1)
    and injects the correct Conda environment variables so GDAL can find its projection data.
    """
    out_shp = shp_path.replace('.shp', f'_{target_epsg}.shp')
    
    if os.path.exists(out_shp):
        print(f"    [OGR] Found existing projected shapefile: {os.path.basename(out_shp)}")
        return out_shp
        
    print(f"    [OGR] Reprojecting shapefile to EPSG:{target_epsg}...")
    
    # 1. Detect the machine and set the environment name
    hostname = platform.node().lower()
    if "studio" in hostname:
        env_name = "surf_v2"
        print("    [OGR] Detected Mac Studio. Using env: surf_v2")
    else:
        env_name = "surf_v1"
        print(f"    [OGR] Detected {platform.node()}. Using env: surf_v1")
    
    # 2. Build the dynamic paths
    ogr_path = f"/Users/noahdewar/miniconda3/envs/{env_name}/bin/ogr2ogr"
    
    custom_env = os.environ.copy()
    custom_env["PROJ_LIB"] = f"/Users/noahdewar/miniconda3/envs/{env_name}/share/proj"
    custom_env["GDAL_DATA"] = f"/Users/noahdewar/miniconda3/envs/{env_name}/share/gdal"

    # 3. Execute ogr2ogr
    try:
        cmd = [ogr_path, "-t_srs", f"EPSG:{target_epsg}", out_shp, shp_path]
        
        result = subprocess.run(cmd, env=custom_env, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"    [!] ogr2ogr failed:\n{result.stderr}")
            if not os.path.exists(out_shp):
                return None
                
        return out_shp
        
    except FileNotFoundError:
        print(f"    [!] ogr2ogr binary not found at {ogr_path}")
        return None
    

def point_in_any_polygon(x, y, rings):
    """True if (x, y) falls inside any ring in a list of polygon rings."""
    for ring in rings:
        if point_in_polygon(x, y, ring):
            return True
    return False


def load_clip_polygon_rings(shp_path):
    """
    Minimal dependency-free .shp reader for Polygon-type (shape type 5) shapefiles.
    Reads coordinates exactly as they exist in the file.
    """
    if not os.path.exists(shp_path):
        print(f"  [!] Clip shapefile not found at {shp_path}")
        return None

    with open(shp_path, 'rb') as f:
        f.seek(32)
        shape_type = struct.unpack('<i', f.read(4))[0]
        if shape_type != 5:
            print(f"  [!] Clip shapefile shape type {shape_type} is not Polygon (5); skipping clip.")
            return None

        f.seek(100)
        rings = []
        while True:
            header = f.read(8)
            if len(header) < 8:
                break
            _rec_num, _content_len = struct.unpack('>ii', header)
            rec_shape_type = struct.unpack('<i', f.read(4))[0]

            if rec_shape_type == 0:
                continue

            f.read(32)
            num_parts, num_points = struct.unpack('<ii', f.read(8))
            parts = struct.unpack(f'<{num_parts}i', f.read(4 * num_parts))
            points = [list(struct.unpack('<dd', f.read(16))) for _ in range(num_points)]

            for i in range(num_parts):
                start = parts[i]
                end = parts[i + 1] if i + 1 < num_parts else num_points
                rings.append(points[start:end])

    return rings


def clip_buildings_to_shapefile(buildings, shp_path):
    """
    Removes buildings whose center falls outside every ring of the clip
    shapefile. 
    """
    print(f"\n  Clipping buildings to shapefile domain: {shp_path}")
    
    # 1. Reproject the shapefile externally so it matches Blender's EPSG:3857 space
    projected_shp = reproject_shapefile_ogr(shp_path, target_epsg=3857)
    
    # Fallback in case ogr2ogr fails
    if not projected_shp:
        print("  [!] Projection failed. Falling back to unprojected shapefile (Clip will likely fail).")
        projected_shp = shp_path
        
    # 2. Load rings from the (now correctly projected) shapefile
    rings = load_clip_polygon_rings(projected_shp)
    
    if not rings:
        print("  [!] Skipping shapefile clip (no usable rings).")
        return buildings

    scene_ox, scene_oy, scene_scale = get_scene_origin()
    bpy.context.view_layer.update()

    kept = []
    removed_count = 0
    
    # Wrap in list() to safely remove items while iterating
    for obj in list(buildings): 
        world_x = (obj.location.x * scene_scale) + scene_ox
        world_y = (obj.location.y * scene_scale) + scene_oy

        if point_in_any_polygon(world_x, world_y, rings):
            kept.append(obj)
        else:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed_count += 1

    print(f"  Clip complete: kept {len(kept)} buildings, removed {removed_count} outside the domain.")
    
    if len(kept) == 0:
        print("  [!] No buildings remain after shapefile clip. Aborting.")
        
    return kept


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


def parse_wkt_polygon(wkt_text):
    """Extracts the exterior ring coordinates from a WKT POLYGON string."""
    inner = wkt_text.split("((", 1)[1]
    inner = inner.rsplit("))", 1)[0]
    exterior_text = inner.split("),(")[0]
    coords = []
    for pair in exterior_text.split(","):
        parts = pair.strip().split()
        coords.append((float(parts[0]), float(parts[1])))
    return coords


def polygon_centroid(ring):
    """Area-weighted centroid of a ring. Falls back to vertex average if degenerate."""
    n = len(ring)
    if n < 3:
        return ring[0] if ring else (0.0, 0.0)
    area = cx = cy = 0.0
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area *= 0.5
    if abs(area) < 1e-9:
        return (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n)
    return (cx / (6 * area), cy / (6 * area))


def nearest_feature_distance(x, y, features):
    """Debug only: brute-force nearest polygon centroid distance, in meters."""
    best_dist = None
    for feature in features:
        geom = feature.get("geometry", {})
        gtype = geom.get("type", "")
        coords = geom.get("coordinates", [])
        if gtype == "Polygon" and coords:
            ring = coords[0]
        elif gtype == "MultiPolygon" and coords:
            ring = coords[0][0]
        else:
            continue
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        if best_dist is None or d < best_dist:
            best_dist = d
    return best_dist

def spatial_join_properties(buildings, geojson_path, footprint_rings=None):
    """
    Mathematically match each Blender building to its GeoJSON footprint 
    and copy the properties over. Deletes any building not found in the GeoJSON.

    When footprint_rings is supplied (building name -> list of absolute
    EPSG:3857 (x, y) ring vertices), the match is tested against multiple
    points sampled from the building's real extraction footprint -- the
    ring's own vertices plus its centroid -- instead of a single point
    derived from the Blender object's mesh origin. This is far more
    reliable for concave / L-shaped / courtyard buildings, where a single
    bounding-box or median-surface point can fall outside the footprint
    entirely even when the building is correctly placed.
    """
    print(f"\n  Starting Spatial Join with: {geojson_path}")
    if not os.path.exists(geojson_path):
        print("  [!] GeoJSON not found, skipping spatial join.")
        return

    footprint_rings = footprint_rings or {}

    with open(geojson_path, 'r') as f:
        data = json.load(f)

    features = data.get("features", [])
    print(f"    Loaded {len(features)} polygons from GeoJSON.")

    # Precompute a bbox per feature so we can cheaply skip features that
    # can't possibly contain a given sample point before running the
    # (more expensive) ray-casting point_in_polygon test.
    feature_bboxes = []
    for feature in features:
        geom = feature.get("geometry", {})
        geom_type = geom.get("type", "")
        coords = geom.get("coordinates", [])
        rings = []
        if geom_type == "Polygon" and coords:
            rings = [coords[0]]
        elif geom_type == "MultiPolygon" and coords:
            rings = [poly[0] for poly in coords]
        if not rings:
            feature_bboxes.append(None)
            continue
        xs = [p[0] for ring in rings for p in ring]
        ys = [p[1] for ring in rings for p in ring]
        feature_bboxes.append((min(xs), min(ys), max(xs), max(ys)))

    scene_ox, scene_oy, scene_scale = get_scene_origin()
    match_count = 0
    removed_count = 0

    bpy.context.view_layer.update()

    for obj in list(buildings):
        if obj.type != 'MESH':
            continue

        ring = footprint_rings.get(obj.name)
        if ring:
            sample_points = ring + [polygon_centroid(ring)]
        else:
            world_x = (obj.location.x * scene_scale) + scene_ox
            world_y = (obj.location.y * scene_scale) + scene_oy
            sample_points = [(world_x, world_y)]

        found_match = False

        for feature, bbox in zip(features, feature_bboxes):
            if bbox is None:
                continue
            bminx, bminy, bmaxx, bmaxy = bbox

            geom = feature.get("geometry", {})
            geom_type = geom.get("type", "")
            coords = geom.get("coordinates", [])

            is_inside = False
            for (px, py) in sample_points:
                if px < bminx or px > bmaxx or py < bminy or py > bmaxy:
                    continue
                if geom_type == "Polygon":
                    if point_in_polygon(px, py, coords[0]):
                        is_inside = True
                        break
                elif geom_type == "MultiPolygon":
                    for poly in coords:
                        if point_in_polygon(px, py, poly[0]):
                            is_inside = True
                            break
                if is_inside:
                    break

            if is_inside:
                props = feature.get("properties", {})
                for key, value in props.items():
                    if value is not None:
                        obj[key] = value
                if "CA_Name" in props and props["CA_Name"]:
                    obj.name = str(props["CA_Name"]).replace(" ", "_")
                match_count += 1
                found_match = True
                break

        if not found_match:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed_count += 1

    print(f"  Spatial Join Complete: Matched {match_count} buildings. Deleted {removed_count} out-of-bounds buildings.")
    
def import_master_mesh():
    """Imports, projects, splits, and formats either a Master OBJ or a directory of JIT OBJs."""
    print("\n--- Importing Master Building Mesh(es) ---")
    
    if not os.path.exists(obj_path):
        print(f"  [!] Path not found at {obj_path}")
        return

    scene_ox, scene_oy, scene_scale = get_scene_origin()
    buildings = []
    footprint_rings = {}

    # ==========================================
    # BRANCH A: JIT DIRECTORY IMPORT
    # ==========================================
    if 1 == 1: #if os.path.isdir(obj_path):
        print("  [!] Directory detected. Switching to Just-In-Time (JIT) batch import...")
        
        rings = load_clip_polygon_rings(clip_shapefile_path)
        if not rings:
            print("  [!] No valid clip rings found. Aborting JIT import.")
            return
            
        all_obj_files = list(Path(obj_path).rglob("*_optimized.obj"))
        print(f"  Found {len(all_obj_files)} total buildings in directory.")
        
        candidates = []

        # 1. Parse JSON for all buildings and gather coordinates
        for single_obj_path in all_obj_files:
            json_files = list(single_obj_path.parent.glob("*.json"))
            if not json_files:
                continue
                
            with open(json_files[0], 'r') as f:
                meta = json.load(f)
            
            # already EPSG:3857 -- reprojected by the extraction pipeline
            sp_x = meta.get("building_min_x_absolute", 0.0)
            sp_y = meta.get("building_min_y_absolute", 0.0)
            
            footprint_files = list(single_obj_path.parent.glob("*_footprint.txt"))

            candidates.append({
                'id': str(single_obj_path), 
                'x': sp_x, 
                'y': sp_y, 
                'tile_x': meta.get("tile_offset_x", 0.0),
                'tile_y': meta.get("tile_offset_y", 0.0),
                'obj_path': single_obj_path,
                'footprint_path': footprint_files[0] if footprint_files else None,
            })

        # not doing this    
        # 2. Project the absolute building locations to EPSG:3857 for the clip check
        print("  Projecting absolute coordinates to EPSG:3857 for spatial clip check...")
        projected_absolute_coords = batch_project_survivors(candidates, source_epsg=3857)
        
        if not projected_absolute_coords:
            print("  [!] Initial projection failed. Aborting.")
            return

        survivors = []
        skipped_count = 0
        
        # 3. Perform shapefile clip check against the 3857 rings
        for b in candidates:
            b_path_str = str(b['obj_path'])
            wm_x, wm_y, lat, lon = projected_absolute_coords[b_path_str]
            
            if not point_in_any_polygon(wm_x, wm_y, rings):
                skipped_count += 1
                continue
                
            # Building survived! Swap the 'x' and 'y' to the tile offsets
            # so the next projection accurately places the origin anchor for Blender.
            b['x'] = b['tile_x']
            b['y'] = b['tile_y']
            survivors.append(b)
            
        print(f"  Clip complete. {len(survivors)} buildings survived (Skipped {skipped_count}).")
        if not survivors:
            return
            
        # 4. Project the Tile Origins to EPSG:3857 for Blender Placement
        print("  Projecting tile origins for Blender scene placement...")
        projected_tiles = batch_project_survivors(survivors, source_epsg=3857)
        if not projected_tiles:
            return
            
        # Import and Scale
        bpy.ops.object.select_all(action='DESELECT')
        for b in survivors:
            b_path = b['obj_path']
            wm_x, wm_y, lat, lon = projected_tiles[str(b_path)]
            
            try:
                bpy.ops.wm.obj_import(filepath=str(b_path), forward_axis='NEGATIVE_Z', up_axis='Y')
            except AttributeError:
                bpy.ops.import_scene.obj(filepath=str(b_path), axis_forward='-Z', axis_up='Y')
                
            new_obj = bpy.context.selected_objects[0]
            bpy.context.view_layer.objects.active = new_obj
            
            # --- THE FIX: Apply the 90-degree import rotation to the mesh ---
            # This resets Rotation to 0,0,0 so Local X/Y/Z matches World X/Y/Z.
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)

            # data in 3587 doesnt need projection
            #mercator_stretch = 1.0 / math.cos(math.radians(lat))
            new_obj.location = ((wm_x - scene_ox) / scene_scale, (wm_y - scene_oy) / scene_scale, 0.0)
            new_obj.scale = (1 / scene_scale, 1 / scene_scale, 1.0 / scene_scale)
            
            buildings.append(new_obj)
            if b.get('footprint_path') and b['footprint_path'].exists():
                try:
                    with open(b['footprint_path'], 'r') as f:
                        local_ring = parse_wkt_polygon(f.read().strip())
                    # local_ring is relative to this building's tile origin
                    # (tile_offset_x/y), already in EPSG:3857 -- shift to absolute.
                    footprint_rings[new_obj.name] = [
                        (px + b['tile_x'], py + b['tile_y']) for px, py in local_ring
                    ]
                except Exception as e:
                    print(f"  [!] Could not parse footprint for {b['obj_path'].name}: {e}")
            bpy.ops.object.select_all(action='DESELECT') 
            
        # Apply transform scale globally to all imported buildings
        for obj in buildings:
            obj.select_set(True)
        if buildings:
            bpy.context.view_layer.objects.active = buildings[0]
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    # ==========================================
    # BRANCH B: SINGLE FILE MASTER MESH IMPORT
    # ==========================================
    else:
        # 1. Parse Header & Project
        lat, lon = parse_obj_header_for_origin(obj_path)
        world_x, world_y = None, None
        
        if 'master_city_assembly' in obj_path:
            try:
                with open(obj_path, 'r') as f:
                    line = f.readline()
                    if 'wmx=' in line and 'wmy=' in line:
                        for p in line.split():
                            if p.startswith('wmx='): world_x = float(p.split('=')[1])
                            if p.startswith('wmy='): world_y = float(p.split('=')[1])
                        print(f"  Found exact Web Mercator origin: X={world_x:.2f}, Y={world_y:.2f}")
            except Exception as e:
                print(f"  [!] Could not parse wmx/wmy: {e}")

        if world_x is None or world_y is None:
            if HAS_BLENDERGIS:
                world_x, world_y = proj.reprojPt(4326, 3857, lon, lat)
            else:
                world_x = lon * 20037508.34 / 180.0
                world_y = math.log(math.tan((90 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
                world_y = world_y * 20037508.34 / 180.0

        blender_x = (world_x - scene_ox) / scene_scale
        blender_y = (world_y - scene_oy) / scene_scale
        blender_z = 0.0  

        # 2. Import the OBJ
        print("  Importing OBJ (this may take a moment)...")
        bpy.ops.object.select_all(action='DESELECT')
        try:
            if 'master_city_assembly' in obj_path:
                bpy.ops.wm.obj_import(filepath=obj_path, forward_axis='NEGATIVE_Z', up_axis='Y')
            else:
                bpy.ops.wm.obj_import(filepath=obj_path, forward_axis='Y', up_axis='Z')
        except AttributeError:
            if 'master_city_assembly' in obj_path:
                bpy.ops.import_scene.obj(filepath=obj_path, axis_forward='-Z', axis_up='Y')
            else:
                bpy.ops.import_scene.obj(filepath=obj_path, axis_forward='Y', axis_up='Z')
            
        imported_objs = bpy.context.selected_objects
        if not imported_objs:
            print("  [!] Failed to import any objects.")
            return
        
        # 3. Position and Scale
        bpy.ops.object.select_all(action='DESELECT')
        if 'master_city_assembly' not in obj_path:
            mercator_stretch = 1.0 / math.cos(math.radians(lat))
            print(f"  Applying Web Mercator stretch factor: {mercator_stretch:.5f}")
        else:
            mercator_stretch = 1.0 
            print("  Master City detected. Skipping Web Mercator stretch.")

        for obj in imported_objs:
            obj.location = (blender_x, blender_y, blender_z)
            obj.scale = (mercator_stretch / scene_scale, mercator_stretch / scene_scale, 1.0 / scene_scale)
            obj.select_set(True)
        
        bpy.context.view_layer.objects.active = imported_objs[0]
        bpy.context.view_layer.update()
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        # 4. Split by Loose Parts
        if 'master_city_assembly' not in obj_path:
            print("  Splitting mesh into individual buildings...")
            bpy.ops.mesh.separate(type='LOOSE')

        buildings = list(bpy.context.selected_objects)
        print(f"    Imported {len(buildings)} individual buildings.")

    # ==========================================
    # SHARED PIPELINE: GROUND, ORGANIZE, JOIN
    # ==========================================
    if not buildings:
        print("  [!] No buildings to process. Aborting.")
        return

    print("  Centering origins for all buildings...")
    bpy.ops.object.select_all(action='DESELECT')
    for obj in buildings:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = buildings[0]
    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')

    ground_buildings_to_dem(buildings)
    bpy.context.view_layer.update()

    collection = bpy.data.collections.get(collection_name)
    if not collection:
        collection = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(collection)
        
    material = create_default_material()

    for obj in buildings:
        for coll in obj.users_collection:
            coll.objects.unlink(obj)
        collection.objects.link(obj)
        
        if obj.type == 'MESH':
            if not obj.data.materials:
                obj.data.materials.append(material)
            else:
                obj.data.materials[0] = material

    spatial_join_properties(buildings, geojson_path) #, footprint_rings=footprint_rings)

    print("--- Master Building Import Complete ---\n")

# Main Execution Trigger
if globals().get('run_import', True):
    print("\n[DEBUG] Pipeline trigger detected. Starting import process...")
    import_master_mesh()
else:
    print("\n[DEBUG] 'run_import' was False. Skipping building import.")