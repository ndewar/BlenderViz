import bpy
import addon_utils
import importlib
import sys
import time

ADDON = "BlenderGIS"

# 1. Enable addon
loaded, enabled = addon_utils.check(ADDON)
if not enabled:
    addon_utils.enable(ADDON, default_set=True, persistent=True)

BlenderGIS = importlib.import_module("BlenderGIS")
georef = BlenderGIS.core.georaster.georef 

import os
import math
import re
import json
import mathutils
from mathutils import Vector


def camera_from_google_maps_url_lookat(
    url,
    camera_name="GoogleMapsCamera",
    dem_object_name=None,
    camera_height_offset=0.0
):
    """
    Create a Blender camera from a Google Maps URL.
    The lat/lon from the URL is the camera POSITION, not the target.
    """

    # --- Parse URL ---
    coord_match = re.search(r'@([-\d.]+),([-\d.]+),', url)
    if not coord_match:
        raise ValueError(f"Could not extract coordinates from URL: {url}")
    
    lat = float(coord_match.group(1))
    lon = float(coord_match.group(2))
    
    param_match = re.search(r'([\d.]+)a,([\d.]+)y,([\d.]+)h,([\d.]+)t', url)
    if not param_match:
        raise ValueError(f"Could not extract camera parameters from URL: {url}")
    
    distance = float(param_match.group(1))  # altitude in meters
    yaw = float(param_match.group(2))       # field of view
    heading = float(param_match.group(3))   # heading degrees clockwise from north
    tilt = float(param_match.group(4))      # tilt degrees above horizontal

    # --- Convert lat/lon to Blender coordinates (CAMERA POSITION) ---
    scn = bpy.context.scene
    geoscn = BlenderGIS.geoscene.GeoScene(scn)
    
    proj_x, proj_y = BlenderGIS.core.proj.reprojPt(4326, 3857, lon, lat)
    camera_x = (proj_x - geoscn.crsx) / geoscn.scale
    camera_y = (proj_y - geoscn.crsy) / geoscn.scale
    
    # Sample terrain elevation at camera position
    camera_z = sample_dem_elevation(camera_x, camera_y, dem_object_name)
    
    # Camera position with height offset
    camera_location = Vector((camera_x, camera_y, camera_z + distance + camera_height_offset))
    
    print(f"\n\nCamera {camera_name} positioning:")
    print(f"  Camera lat/lon: {lat}, {lon}")
    print(f"  Camera location: {camera_location}")
    print(f"  Height above terrain: {distance + camera_height_offset}m")
    print(f"  Heading: {heading}°, Tilt: {tilt}°")

    # --- Create camera ---
    if camera_name in bpy.data.objects:
        cam = bpy.data.objects[camera_name]
    else:
        bpy.ops.object.camera_add()
        cam = bpy.context.object
        cam.name = camera_name

    cam.location = camera_location

    # Set field of view based on yaw parameter
    if cam.data.type == 'PERSP':
        fov_degrees = max(10, min(120, yaw))
        cam.data.lens_unit = 'FOV'
        cam.data.sensor_fit = 'VERTICAL' # Match Google's vertical FOV logic
        cam.data.angle = math.radians(fov_degrees)
        print(f"  Set camera FOV to: {fov_degrees}°")

    # --- Set camera rotation based on heading and tilt ---
    cam.rotation_mode = 'XYZ'
    
    # Convert Google Maps angles to Blender rotation
    # Google Maps: heading 0° = North, tilt 0° = straight down
    # Blender: X = pitch, Y = roll, Z = yaw
    
    # Pitch: tilt angle (0° = down, 90° = horizontal)
    pitch = math.radians(tilt)  # Convert to angle above horizontal
    
    # Yaw: heading (0° = North = +Y in Blender)
    yaw = math.radians(-heading)
    
    # Roll: keep level
    roll = 0.0
    
    cam.rotation_euler = (pitch, roll, yaw)
    
    # Set camera clipping
    cam.data.clip_end = 1000000
    
    print(f"  Camera rotation - Pitch: {math.degrees(pitch):.1f}°, Yaw: {math.degrees(yaw):.1f}°")
    print(f"  Camera clipping set to: {cam.data.clip_end}")

    return {
        "latitude": lat,
        "longitude": lon,
        "camera_location": tuple(cam.location),
        "distance_m": distance,
        "heading_deg": heading,
        "tilt_deg": tilt
    }
    

def set_georeference(epsg=3857, lat_origin=0.0, lon_origin=0.0, scale=1.0):
    """
    Set BlenderGIS georeference programmatically.

    Parameters
    ----------
    epsg : int
        EPSG code (3857 = Web Mercator, 4326 = WGS84)
    lat_origin, lon_origin : float
        Geographic origin
    scale : float
        World scale (1.0 = meters)
    """
    
    # Get current scene
    scn = bpy.context.scene
    geoscn = BlenderGIS.geoscene.GeoScene(scn)
    
    # Set CRS using SRS class
    try:
        crs = BlenderGIS.core.proj.SRS(f"EPSG:{epsg}")
        geoscn.crs = crs
    except Exception as e:
        print(f"Error setting CRS: {e}")
        return False
    
    # Convert origin lat/lon to projected coords if needed
    if epsg != 4326:
        try:
            x0, y0 = BlenderGIS.core.proj.reprojPt(
                4326, f"EPSG:{epsg}", 
                lon_origin, lat_origin
            )
        except Exception as e:
            print(f"Error reprojecting coordinates: {e}")
            return False
    else:
        x0, y0 = lon_origin, lat_origin
    
    # Set origin in projected coordinates
    geoscn.setOriginPrj(x0, y0)
    
    # Set scale
    geoscn.scale = scale
    
    print("Georeference set:")
    print(f"  EPSG:{epsg}")
    print(f"  Origin lat/lon: {lat_origin}, {lon_origin}")
    print(f"  Origin projected: {x0}, {y0}")
    print(f"  Scale: {scale}")
    
    return True


def sample_dem_elevation(x, y, dem_object_name=None, ray_height=10000.0):
    """
    Sample terrain elevation from a BlenderGIS DEM mesh using ray casting.
    Only casts against the DEM object, ignoring other meshes.
    """

    scene = bpy.context.scene

    # --- Find DEM object ---
    if dem_object_name:
        dem = bpy.data.objects.get(dem_object_name)
    else:
        dem = next(
            (o for o in bpy.data.objects
             if o.type == 'MESH' and 'dem' in o.name.lower()),
            None
        )

    if dem is None:
        raise RuntimeError("No DEM mesh found in scene")

    print(f"DEM found: {dem.name}")
    print(f"Ray casting at coordinates: ({x}, {y})")

    # --- Ray start & direction ---
    origin = Vector((x, y, ray_height))
    direction = Vector((0, 0, -1))

    # --- Ray cast only against DEM object ---
    depsgraph = bpy.context.evaluated_depsgraph_get()
    
    # Get the evaluated DEM object
    dem_eval = dem.evaluated_get(depsgraph)
    
    # Transform ray to object space
    matrix_inv = dem.matrix_world.inverted()
    origin_local = matrix_inv @ origin
    direction_local = matrix_inv.to_3x3() @ direction
    
    # Ray cast against the specific DEM object
    hit, location_local, normal, face_index = dem_eval.ray_cast(origin_local, direction_local)
    
    if hit:
        # Transform hit location back to world space
        location_world = dem.matrix_world @ location_local
        print(f"Ray cast hit DEM at: {location_world}")
        return location_world.z
    else:
        # Fallback: use DEM center Z coordinate
        bbox = [dem.matrix_world @ mathutils.Vector(corner) for corner in dem.bound_box]
        center_z = sum(corner.z for corner in bbox) / len(bbox)
        print(f"Ray miss - using DEM center Z: {center_z}")
        return center_z


def safe_clean_scene():
    """Deletes default objects without resetting Blender's system state."""
    # Ensure we are in Object Mode
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode='OBJECT')

    # Select all objects and delete
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    # Clear out leftover data blocks (meshes, materials, textures)
    # This prevents 'Cube.001', 'Material.001', etc.
    for block in [bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.textures]:
        for item in block:
            block.remove(item)


def apply_render_settings(scene):
    # 1. Set Render Engine to Cycles
    scene.render.engine = 'CYCLES'
    
    # 2. Set Samples for Render (Image)
    # In modern Blender (3.0+), this is the 'Max Samples'
    scene.cycles.samples = 124

    # this is for faster flyover creation while testing stuff
    scene.cycles.samples = 32
    
    # 3. Set Noise Threshold (Adaptive Sampling)
    # If you want exactly 124 samples without early stopping, 
    # you can toggle use_adaptive_sampling off. 
    # Otherwise, here is how to set the noise threshold:
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.01 # Adjust this value as needed
    
    # Ensure viewport samples match or are lower for performance
    scene.cycles.preview_samples = 32


def set_viewport_clipping():
    # 4. Set Viewport Max Clip Distance
    # This must be done per 3D Viewport area
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.clip_end = 1000000
                    print(f"Viewport clipping set to {space.clip_end}")


def run_pipeline():
    # 1. Capture arguments from CLI: blender -b -P run_pipeline.py -- brevard 1
    try:
        args = sys.argv[sys.argv.index("--") + 1:]
        state = args[0]
        county_val = args[1]
        site_num_val = args[2]
        project_name = args[3]
    except (IndexError, ValueError):
        print("Error: Provide state, county, site number, and project name. Example: -- florida brevard 1 CapeCav3D_ECFRPC_2025")
        return

    # 1.1 load the blender config json
    json_path = f"/Users/noahdewar/Documents/HighTide/HighTideEngine/data/projects/{project_name}/blender_config.json"

    # if given 1,2,3 run all of them, otherwise its just one site
    if ',' in site_num_val:
        sitesToRun = [int(x) for x in site_num_val.split(',')]
    else:
        sitesToRun = [int(site_num_val)]
    
    # Load JSON
    with open(json_path, 'r') as f:
        data = json.load(f)

    # print a status message and start running the sites
    print(f"Running full pipeline for state: {state}, county: {county_val}, sites: {sitesToRun}, project: {project_name}")
    for site_num_val in sitesToRun:

        # 1.1 print a status message and get the data for this site
        print(f"\n\nRunning site {site_num_val}")
        center_lat_long = data['sites'][county_val][f'site{site_num_val}']['center_lat_long']
        worldLightingRotationAngle = data['sites'][county_val][f'site{site_num_val}']['worldLightingRotationAngle']
        world_lighting_strength = data['sites'][county_val][f'site{site_num_val}'].get('world_lighting_strength', 1.0)
        renderVersionNumber = data['sites'][county_val][f'site{site_num_val}']['renderVersionNumber']
        
        # 1.2 set the georeference
        set_georeference(
            epsg=3857,
            lat_origin=center_lat_long[0],
            lon_origin=center_lat_long[1]
        )

        # 2. Define script directory and files
        script_dir = "/Users/noahdewar/Documents/HighTide/BlenderViz/scripts/"

        # Check if ESRI multipatch path is specified in config
        site_config = data['sites'][county_val][f'site{site_num_val}']
        esri_multipatch_path = site_config.get('ESRI_multi_patch_path', None)

        # Build script list - exclude addBuildings.py if using multipatch
        if esri_multipatch_path:
            print(f"Found ESRI_multi_patch_path: {esri_multipatch_path}")
            print("Will use multipatch import instead of regular building import")
            scripts_to_run = [
                "importRasters.py",
                "addSatImage.py",
                "addWorldLighting.py",
                "makeWaterSurfaceV2.py",
                "setUpCompositing.py",
                # addBuildings.py excluded - will run importMultipatch.py instead
            ]
        else:
            scripts_to_run = [
                "importRasters.py",
                "addSatImage.py",
                "addWorldLighting.py",
                "makeWaterSurfaceV2.py",
                "setUpCompositing.py",
                "addBuildings.py"
            ]


        # split based on flyover or normal rendering
        flyover_config = site_config.get('flyover', {})
        use_flyover = flyover_config.get('enabled', False)

        # 3. Create the 'Global Scope' dictionary to pass variables
        # These variables will be accessible inside the sub-scripts
        shared_context = {
            'bpy': bpy,
            'os': os,
            'state': state,
            'county': county_val,
            'siteNum': site_num_val,
            'versionNum': renderVersionNumber,
            'zoom': 18,
            'worldLightingRotationAngle': worldLightingRotationAngle,
            'world_lighting_strength': world_lighting_strength,
            'restrict_import': True,
            'sat_image_zoom': site_config.get('sat_image_zoom',18),
            'render_fps': flyover_config.get('fps',24),
        }

        # 3.1, clear the scene
        safe_clean_scene()

        # 4. Run the scripts in order
        for script_name in scripts_to_run:
            script_path = os.path.join(script_dir, script_name)

            if os.path.exists(script_path):
                print(f"\n\n--- Running: {script_name} ---")
                with open(script_path, 'r') as f:
                    # exec() runs the code using our shared_context for variables
                    exec(f.read(), shared_context)
            else:
                print(f"SKIPPING: {script_name} not found at {script_path}")

        # 4.0.1 Run multipatch import if ESRI path is specified
        if esri_multipatch_path:
            print(f"\n\n--- Running: importMultipatch.py ---")
            multipatch_script_path = os.path.join(script_dir, "importMultipatch.py")
            if os.path.exists(multipatch_script_path):
                # Add multipatch-specific variables to shared context
                shared_context['multipatch_folder'] = esri_multipatch_path
                shared_context['filter_by_dem'] = site_config.get('multipatch_filter_by_dem', True)
                shared_context['bounds_buffer_meters'] = site_config.get('multipatch_buffer_meters', 50)
                shared_context['run_import'] = True

                # Position offset correction (if buildings appear offset)
                shared_context['multipatch_offset_x'] = site_config.get('multipatch_offset_x', 0.0)
                shared_context['multipatch_offset_y'] = site_config.get('multipatch_offset_y', 0.0)
                shared_context['multipatch_offset_z'] = site_config.get('multipatch_offset_z', 0.0)

                with open(multipatch_script_path, 'r') as f:
                    exec(f.read(), shared_context)
            else:
                print(f"ERROR: importMultipatch.py not found at {multipatch_script_path}")

        # 4.1 set the render and viewport settings
        scene = bpy.context.scene
        apply_render_settings(scene)
        set_viewport_clipping()

        # 4.2 add the cameras with height offset
        cameraIDX = 1
        for key in data['sites'][county_val][f'site{site_num_val}'].keys():
            if 'google_url' in key:
                camera_from_google_maps_url_lookat(
                    data['sites'][county_val][f'site{site_num_val}'][key], 
                    f'Camera{cameraIDX}',
                    camera_height_offset=50.0  # Add 50m above calculated position
                )
                cameraIDX += 1

        # 5. Save the final result
        output_name = f"{county_val}_site{site_num_val}.blend"
        output_path = os.path.join(f"/Users/noahdewar/Documents/HighTide/data/{state}/counties/{county_val}/blender/site{site_num_val}/", output_name)
        bpy.ops.wm.save_as_mainfile(filepath=output_path)
        print(f"Done! Project saved to: {output_path}")
        if use_flyover:
            flyover_script_path = os.path.join(script_dir, "RenderFlyOver.py")
            if os.path.exists(flyover_script_path):
                print("--- Running: FlyoverRender.py ---")
                shared_context['flyover_config'] = flyover_config  # pass config in
                with open(flyover_script_path, 'r') as f:
                    exec(f.read(), shared_context)
            else:
                print(f"SKIPPING: FlyoverRender.py not found at {flyover_script_path}")
        else:
            render_script_path = os.path.join(script_dir, "RenderImages.py")
            if os.path.exists(render_script_path):
                print("--- Running: RenderImages.py ---")
                with open(render_script_path, 'r') as f:
                    exec(f.read(), shared_context)
            else:
                print(f"SKIPPING: RenderImages.py not found at {render_script_path}")


        # 5. Save the final result
        output_name = f"{county_val}_site{site_num_val}.blend"
        output_path = os.path.join(f"/Users/noahdewar/Documents/HighTide/data/{state}/counties/{county_val}/blender/site{site_num_val}/", output_name)
        bpy.ops.wm.save_as_mainfile(filepath=output_path)
        print(f"Done! Project saved to: {output_path}")

        # 6. Reset for next site (if not the last one)
        if site_num_val != sitesToRun[-1]:
            # Clear all objects
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete()
            
            # Clear all data blocks
            for collection in [
                bpy.data.meshes,        # This clears UV maps too
                bpy.data.materials, 
                bpy.data.textures,
                bpy.data.images,
                bpy.data.cameras,
                bpy.data.lights
            ]:
                for item in list(collection):
                    collection.remove(item)
            
            print(f"Cleared all objects, materials, UV maps, and cameras for next site")


def get_existing_flood_rasters(state, county, site_num, restrict_import):
    """
    Returns set of raster object names already in the scene by checking
    against the actual .tif files that would be imported, using the same
    filter logic as importRasters.py.
    """
    folder_path = f'/Users/noahdewar/Documents/HighTide/data/{state}/counties/{county}/blender/site{site_num}/'
    existing_objects = set(bpy.data.objects.keys())
    present = set()
    missing = set()

    if not os.path.exists(folder_path):
        print(f"Warning: folder not found: {folder_path}")
        return present, missing

    for file_name in os.listdir(folder_path):
        if not file_name.lower().endswith('.tif'):
            continue
        if restrict_import:
            if 'floodmap' in file_name.lower():
                if not ('_c1_' in file_name.lower() and '_high_' in file_name.lower()):
                    continue  # same filter as importRasters.py

        object_name = file_name.replace('.tif', '')
        if object_name in existing_objects:
            present.add(object_name)
        else:
            missing.add(object_name)

    return present, missing


def run_pipeline_existing(
    state, county_val, site_num_val, project_name
):
    """
    Load an existing .blend, add only missing flood rasters, render, save.
    
    Parameters
    ----------
    expected_flood_raster_names : list[str]
        The object names that importRasters.py would normally create.
        e.g. ['flood_slr_1ft', 'flood_slr_2ft', 'flood_100yr']
    """

    # 1. Load existing .blend file
    blend_path = os.path.join(
        f"/Users/noahdewar/Documents/HighTide/data/{state}/counties/{county_val}/blender/site{site_num_val}/",
        f"{county_val}_site{site_num_val}.blend"
    )

    if not os.path.exists(blend_path):
        print(f"ERROR: No existing .blend found at {blend_path}")
        return

    print(f"Loading existing .blend: {blend_path}")
    bpy.ops.wm.open_mainfile(filepath=blend_path)

    # 2. Load config
    json_path = f"/Users/noahdewar/Documents/HighTide/HighTideEngine/data/projects/{project_name}/blender_config.json"
    with open(json_path, 'r') as f:
        data = json.load(f)

    site_config = data['sites'][county_val][f'site{site_num_val}']
    center_lat_long = site_config['center_lat_long']
    worldLightingRotationAngle = site_config['worldLightingRotationAngle']
    world_lighting_strength = site_config.get('world_lighting_strength', 1.0)
    renderVersionNumber = site_config['renderVersionNumber']

    # Re-apply georeference (needed for any projection math)
    set_georeference(
        epsg=3857,
        lat_origin=center_lat_long[0],
        lon_origin=center_lat_long[1]
    )

    script_dir = "/Users/noahdewar/Documents/HighTide/BlenderViz/scripts/"
    shared_context = {
            'bpy': bpy,
            'os': os,
            'state': state,
            'county': county_val,
            'siteNum': site_num_val,
            'versionNum': renderVersionNumber,
            'zoom': 18,
            'worldLightingRotationAngle': worldLightingRotationAngle,
            'world_lighting_strength': world_lighting_strength,
            'restrict_import': False,
            'update_flag': False
        }

    # 3. Run import rasters if rasters are missing
    present, missing = get_existing_flood_rasters(state, county_val, site_num_val, shared_context['restrict_import'])
    print(f"Rasters already in scene: {present}")
    print(f"Rasters to import:        {missing}")

    if missing:
        print("--- Importing missing rasters ---")
        # importRasters.py will self-filter using existing_object_names
        raster_script = os.path.join(script_dir, "importRasters.py")
        with open(raster_script, 'r') as f:
            exec(f.read(), shared_context)
    else:
        print("All rasters present — skipping import.")

    # 3.5 After importing missing rasters, assign existing material
    assign_material_script = os.path.join(script_dir, "assignWaterSurface.py")
    if os.path.exists(assign_material_script):
        print("--- Assigning flood material to new rasters ---")
        with open(assign_material_script, 'r') as f:
            exec(f.read(), shared_context)
    else:
        print("SKIPPING: assignWaterSurface.py not found")

    # 4. Re-apply render settings and viewport clipping
    apply_render_settings(bpy.context.scene)
    set_viewport_clipping()

    # 5. Ensure cameras exist (re-create if .blend was missing them)
    for cam_name, url_key in [('Camera1', 'google_url_view1'), ('Camera2', 'google_url_view2')]:
        if cam_name not in bpy.data.objects:
            print(f"Camera {cam_name} missing — re-creating from URL")
            camera_from_google_maps_url_lookat(
                site_config[url_key],
                cam_name,
                camera_height_offset=50.0
            )
        else:
            print(f"Camera {cam_name} already exists — skipping")

    # split based on flyover or normal rendering
    flyover_config = site_config.get('flyover', {})
    use_flyover = flyover_config.get('enabled', False)
    if use_flyover:
        flyover_script_path = os.path.join(script_dir, "RenderFlyOver.py")
        if os.path.exists(flyover_script_path):
            print("--- Running: FlyoverRender.py ---")
            shared_context['flyover_config'] = flyover_config  # pass config in
            with open(flyover_script_path, 'r') as f:
                exec(f.read(), shared_context)
        else:
            print(f"SKIPPING: FlyoverRender.py not found at {flyover_script_path}")
    else:
        render_script_path = os.path.join(script_dir, "RenderImages.py")
        if os.path.exists(render_script_path):
            print("--- Running: RenderImages.py ---")
            with open(render_script_path, 'r') as f:
                exec(f.read(), shared_context)
        else:
            print(f"SKIPPING: RenderImages.py not found at {render_script_path}")

    # 7. Save
    print(f"Saving .blend to: {blend_path}")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print("Done!")


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
    except (IndexError, ValueError):
        print("Error: Provide state, county, site, project. Optionally add --existing")
        return

    if '--existing' in args:
        sites = [int(x) for x in site_num_val.split(',')] if ',' in site_num_val else [int(site_num_val)]
        for site in sites:
            run_pipeline_existing(state, county_val, site, project_name)
    else:
        run_pipeline()  # original flow
    totalTime = float(str((time.time()-startTime)*100).split('.')[0])/100
    print(f'Blender masterRunner took {totalTime} seconds to run: {args}')
if __name__ == "__main__":
    run_pipeline_dispatcher()
