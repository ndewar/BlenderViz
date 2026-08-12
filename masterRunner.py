import bpy
import addon_utils
import importlib
import sys
import time
import os
import math
import re
import json
import mathutils
from mathutils import Vector

# 1. Define the possible folder names
candidate_names = ["BlenderGIS", "BlenderGIS-master", "blendergis", "blendergis-master"]
ADDON = None

# 2. Scan Blender's installed addons to find the correct local name
for mod in addon_utils.modules():
    if mod.__name__ in candidate_names:
        ADDON = mod.__name__
        break

if ADDON is None:
    raise ImportError("[!] BlenderGIS addon not found on this system. Please ensure it is installed.")

# 3. Enable the found addon
loaded, enabled = addon_utils.check(ADDON)
if not enabled:
    addon_utils.enable(ADDON, default_set=True, persistent=True)

# 4. Import the module using the localized name
BlenderGIS = importlib.import_module(ADDON)
print(f"Successfully loaded addon: {ADDON}")
georef = BlenderGIS.core.georaster.georef 

# --- Shared Helper Functions ---

def camera_from_google_maps_url_lookat(url, camera_name="GoogleMapsCamera", dem_object_name=None, camera_height_offset=0.0):
    # [Unchanged: Keep your exact implementation here]
    coord_match = re.search(r'@([-\d.]+),([-\d.]+),', url)
    if not coord_match:
        raise ValueError(f"Could not extract coordinates from URL: {url}")
    
    lat = float(coord_match.group(1))
    lon = float(coord_match.group(2))
    
    param_match = re.search(r'([\d.]+)a,([\d.]+)y,([\d.]+)h,([\d.]+)t', url)
    if not param_match:
        raise ValueError(f"Could not extract camera parameters from URL: {url}")
    
    distance = float(param_match.group(1))  
    yaw = float(param_match.group(2))       
    heading = float(param_match.group(3))   
    tilt = float(param_match.group(4))      

    scn = bpy.context.scene
    geoscn = BlenderGIS.geoscene.GeoScene(scn)
    
    proj_x, proj_y = BlenderGIS.core.proj.reprojPt(4326, 3857, lon, lat)
    camera_x = (proj_x - geoscn.crsx) / geoscn.scale
    camera_y = (proj_y - geoscn.crsy) / geoscn.scale
    
    camera_z = sample_dem_elevation(camera_x, camera_y, dem_object_name)
    camera_location = Vector((camera_x, camera_y, camera_z + distance + camera_height_offset))
    
    print(f"\n\nCamera {camera_name} positioning:")
    print(f"  Camera location: {camera_location}")

    if camera_name in bpy.data.objects:
        cam = bpy.data.objects[camera_name]
    else:
        bpy.ops.object.camera_add()
        cam = bpy.context.object
        cam.name = camera_name

    cam.location = camera_location

    if cam.data.type == 'PERSP':
        fov_degrees = max(10, min(120, yaw))
        cam.data.lens_unit = 'FOV'
        cam.data.sensor_fit = 'VERTICAL' 
        cam.data.angle = math.radians(fov_degrees)

    cam.rotation_mode = 'XYZ'
    pitch = math.radians(tilt)  
    yaw = math.radians(-heading)
    roll = 0.0
    
    cam.rotation_euler = (pitch, roll, yaw)
    cam.data.clip_end = 1000000
    bpy.context.scene.camera = cam

    return { "latitude": lat, "longitude": lon, "camera_location": tuple(cam.location) }

def set_georeference(epsg=3857, lat_origin=0.0, lon_origin=0.0, scale=1.0):
    # [Unchanged: Keep your exact implementation here]
    scn = bpy.context.scene
    geoscn = BlenderGIS.geoscene.GeoScene(scn)
    try:
        crs = BlenderGIS.core.proj.SRS(f"EPSG:{epsg}")
        geoscn.crs = crs
    except Exception as e:
        print(f"Error setting CRS: {e}")
        return False
    
    if epsg != 4326:
        try:
            x0, y0 = BlenderGIS.core.proj.reprojPt(4326, f"EPSG:{epsg}", lon_origin, lat_origin)
        except Exception as e:
            print(f"Error reprojecting coordinates: {e}")
            return False
    else:
        x0, y0 = lon_origin, lat_origin
    
    geoscn.setOriginPrj(x0, y0)
    geoscn.scale = scale
    return True

def sample_dem_elevation(x, y, dem_object_name=None, ray_height=10000.0):
    # [Unchanged: Keep your exact implementation here]
    scene = bpy.context.scene
    if dem_object_name:
        dem = bpy.data.objects.get(dem_object_name)
    else:
        dem = next((o for o in bpy.data.objects if o.type == 'MESH' and 'dem' in o.name.lower()), None)

    if dem is None:
        raise RuntimeError("No DEM mesh found in scene")

    origin = Vector((x, y, ray_height))
    direction = Vector((0, 0, -1))

    depsgraph = bpy.context.evaluated_depsgraph_get()
    dem_eval = dem.evaluated_get(depsgraph)
    
    matrix_inv = dem.matrix_world.inverted()
    origin_local = matrix_inv @ origin
    direction_local = matrix_inv.to_3x3() @ direction
    
    hit, location_local, normal, face_index = dem_eval.ray_cast(origin_local, direction_local)
    
    if hit:
        return (dem.matrix_world @ location_local).z
    else:
        bbox = [dem.matrix_world @ mathutils.Vector(corner) for corner in dem.bound_box]
        return sum(corner.z for corner in bbox) / len(bbox)

def safe_clean_scene():
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for block in [bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.textures]:
        for item in block:
            block.remove(item)

def apply_render_settings(scene):
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 124
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.01 
    scene.cycles.preview_samples = 32

def set_viewport_clipping():
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.clip_end = 1000000

def get_existing_flood_rasters(state, project_name, site_num, restrict_import):
    folder_path = f'/Users/noahdewar/Documents/HighTide/data/{state}/projects/{project_name}/blender/site{site_num}/'
    existing_objects = set(bpy.data.objects.keys())
    present, missing = set(), set()

    if not os.path.exists(folder_path):
        return present, missing

    for file_name in os.listdir(folder_path):
        if not file_name.lower().endswith('.tif'):
            continue
        if restrict_import and 'floodmap' in file_name.lower():
            if not ('_c1_' in file_name.lower() and '_high_' in file_name.lower()):
                continue

        object_name = file_name.replace('.tif', '')
        if object_name in existing_objects:
            present.add(object_name)
        else:
            missing.add(object_name)
    return present, missing

def run_external_script(script_dir, script_name, shared_context):
    """Helper to safely execute external scripts."""
    script_path = os.path.join(script_dir, script_name)
    if os.path.exists(script_path):
        print(f"\n--- Running: {script_name} ---")
        with open(script_path, 'r') as f:
            exec(f.read(), shared_context)
    else:
        print(f"SKIPPING: {script_name} not found at {script_path}")


# --- Refactored Core Pipeline ---

def build_shared_context(state, county, site_num, site_config, is_existing):
    """Constructs the unified dictionary passed to external scripts."""
    flyover_config = site_config.get('flyover', {})
    return {
        #'font_path': '/Users/noahdewar/Documents/HighTide/platform/src/assets/fonts/newOrder/NewOrder-Bold.ttf',
        'font_path': '/System/Library/Fonts/Helvetica.ttc',
        'site_name': site_config.get('site_name', f'Site {site_num}'),
        'project_name': site_config['project_name'],
        'bpy': bpy,
        'os': os,
        'state': state,
        'county': county,
        'siteNum': site_num,
        'versionNum': site_config.get('renderVersionNumber', 1),
        'zoom': 18,
        'worldLightingRotationAngle': site_config.get('worldLightingRotationAngle', 0),
        'world_lighting_strength': site_config.get('world_lighting_strength', 1.0),
        'restrict_import': not is_existing,
        'dem_decimate_ratio': site_config.get('dem_decimate_ratio', 0.25),
        'water_decimate_ratio': site_config.get('water_decimate_ratio', 0.1),
        'sat_image_zoom': site_config.get('sat_image_zoom', 18),
        'render_fps': flyover_config.get('fps', 24),
        'animate_water': site_config.get('animate_water', True),  # Set to False for static water
        'color_ramp': site_config.get('color_ramp', {}),  # Shared color ramp for depth visualization
        'data_overlays': site_config.get('data_overlays', {}),  # Data overlay settings
        'flood_maps_to_run': site_config.get('flood_maps_to_run', {}),
        'update_flag': not is_existing,
        "building_obj_path": site_config.get('building_obj_path', ''),
        'flyover_config': flyover_config
    }

def process_single_site(state, county, site_num, project_name, site_config, is_existing):
    """The unified core logic for building or updating a site."""
    script_dir = "/Users/noahdewar/Documents/HighTide/BlenderViz/scripts/"
    blend_dir = f"/Users/noahdewar/Documents/HighTide/data/{state}/projects/{project_name}/blender/site{site_num}/"
    blend_path = os.path.join(blend_dir, f"{county}_site{site_num}.blend")

    # 1. Setup Scene (Load or Clean)
    if is_existing:
        if not os.path.exists(blend_path):
            print(f"ERROR: No existing .blend found at {blend_path}")
            return
        print(f"Loading existing .blend: {blend_path}")
        bpy.ops.wm.open_mainfile(filepath=blend_path)
    else:
        safe_clean_scene()

    # 2. Georeference
    center_lat_long = site_config['center_lat_long']
    set_georeference(epsg=3857, lat_origin=center_lat_long[0], lon_origin=center_lat_long[1])

    # 3. Create Context
    shared_context = build_shared_context(state, county, site_num, site_config, is_existing)

    # 4. Import Geometry & Materials (The Divergent Step)
    if is_existing:
        present, missing = get_existing_flood_rasters(state, project_name, site_num, shared_context['restrict_import'])
        print(f"Rasters already in scene: {present}\nRasters to import: {missing}")
        if missing:
            run_external_script(script_dir, "importRasters.py", shared_context)
            run_external_script(script_dir, "makeWaterSurfaceV2.py", shared_context)
        else:
            print("All rasters present — skipping import.")
    else:
        esri_multipatch = site_config.get('ESRI_multi_patch_path', None)
        buildings_obj = site_config.get('building_obj_path', None)
        scripts_to_run = ["importRasters.py", "addSatImage.py", "addWorldLighting.py", "makeWaterSurfaceV2.py", "setUpCompositing.py"]
        if not esri_multipatch and not buildings_obj:
            scripts_to_run.append("addBuildings.py")

        for script in scripts_to_run:
            run_external_script(script_dir, script, shared_context)

        if buildings_obj:
            run_external_script(script_dir, "importMasterBuildings.py", shared_context)

        if esri_multipatch:
            shared_context.update({
                'multipatch_folder': esri_multipatch,
                'filter_by_dem': site_config.get('multipatch_filter_by_dem', True),
                'bounds_buffer_meters': site_config.get('multipatch_buffer_meters', 50),
                'run_import': True,
                'multipatch_offset_x': site_config.get('multipatch_offset_x', 0.0),
                'multipatch_offset_y': site_config.get('multipatch_offset_y', 0.0),
                'multipatch_offset_z': site_config.get('multipatch_offset_z', 0.0)
            })
            run_external_script(script_dir, "importMultipatch.py", shared_context)

    # 5. Global Render Settings
    scene = bpy.context.scene
    apply_render_settings(scene)

    flyover_config = site_config.get('flyover', {})
    if flyover_config.get('enabled', False):
        scene.cycles.samples = 32  # Faster test renders for flyovers

    set_viewport_clipping()

    # 6. Setup Cameras (must happen before data overlays for label tracking)
    cameraIDX = 1
    for key, url in site_config.items():
        if 'google_url' in key:
            cam_name = f'Camera{cameraIDX}'
            if is_existing and cam_name in bpy.data.objects:
                print(f"Camera {cam_name} already exists — skipping")
            else:
                camera_from_google_maps_url_lookat(url, cam_name, camera_height_offset=50.0)
            cameraIDX += 1

    # 7. Apply data overlays (flood colors, asset rings, labels) - after cameras are set up
    data_overlays_config = site_config.get('data_overlays', {})
    if data_overlays_config.get('enabled', False):
        run_external_script(script_dir, "addDataOverlays.py", shared_context)

    # 8. Checkpoint Save
    os.makedirs(blend_dir, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)

    # 9. Render
    if flyover_config.get('enabled', False):
        run_external_script(script_dir, "RenderFlyOver.py", shared_context)
    else:
        run_external_script(script_dir, "RenderImages.py", shared_context)

    # 10. Final Save
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"Done! Project saved to: {blend_path}")


def run_pipeline_dispatcher():
    """
    CLI usage:
      New pipeline:      blender -b -P run_pipeline.py -- florida brevard 1 MyProject
      Existing pipeline: blender -b -P run_pipeline.py -- florida brevard 1 MyProject --existing
    """
    startTime = time.time()
    try:
        args = sys.argv[sys.argv.index("--") + 1:]
        state = args[0]
        county_val = args[1]
        site_num_val = args[2]
        project_name = args[3]
        is_existing = '--existing' in args
    except (IndexError, ValueError):
        print("Error: Provide state, county, site, project. Optionally add --existing")
        return

    # Load JSON Config once for all sites
    json_path = f"/Users/noahdewar/Documents/HighTide/HighTideEngine/data/projects/{project_name}/blender_config.json"
    with open(json_path, 'r') as f:
        data = json.load(f)

    # Handle multiple sites
    sitesToRun = [int(x) for x in site_num_val.split(',')] if ',' in site_num_val else [int(site_num_val)]
    
    # if theres a comma in counties, then different sites are in different counties
    if ',' in county_val:
        counties = county_val.split(',')
    else:
        counties = [county_val]*len(sitesToRun)
    if len(counties) != len(sitesToRun):
        raise Exception(f'Number of counties and sites must match, countes: {len(counties)}, sites: {len(sitesToRun)}')

    print(f"Running pipeline (Existing={is_existing}) for state: {state}, county: {county_val}, sites: {sitesToRun}, project: {project_name}")

    # Get top-level config options
    top_level_data_overlays = data.get('data_overlays', {})
    top_level_color_ramp = data.get('color_ramp', {})

    for site_num, county in zip(sitesToRun,counties):
        print(f"\n\n{'='*40}\nProcessing Site {site_num}\n{'='*40}")
        site_config = data['sites'][county][f'site{site_num}']

        # Merge top-level configs into site_config
        site_config['data_overlays'] = top_level_data_overlays
        site_config['color_ramp'] = top_level_color_ramp
        site_config['project_name'] = project_name

        process_single_site(state, county, site_num, project_name, site_config, is_existing)

        # Reset memory blocks if generating new scenes in a sequence
        if not is_existing and site_num != sitesToRun[-1]:
            safe_clean_scene()
            for collection in [bpy.data.cameras, bpy.data.lights]:
                for item in list(collection):
                    collection.remove(item)
            print(f"Cleared memory blocks for next site")

    totalTime = float(str((time.time() - startTime) * 100).split('.')[0]) / 100
    print(f'Blender masterRunner took {totalTime} seconds to run.')

if __name__ == "__main__":
    run_pipeline_dispatcher()