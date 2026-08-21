import bpy
import os
import re
import subprocess
import sys

# --- Import Shared Logic ---
# masterRunner puts scripts/ on sys.path before exec'ing this
import paths
script_dir = f"{paths.SCRIPTS_DIR}/"
if script_dir not in sys.path:
    sys.path.append(script_dir)
import render_utils
import addDataOverlays

# --- Configuration ---
site_name = globals()['site_name']
site_num = globals().get('siteNum', 1)
font_path = globals()['font_path']
version_num = globals().get('versionNum', 1)
state = globals().get('state', 'florida')
county = globals().get('county', 'brevard')
project_name = globals().get('project_name')
update_flag = globals().get('update_flag', True)
data_overlays_config = globals().get('data_overlays', {})
color_ramp_config = globals().get('color_ramp', {})
depth_to_year = globals().get('flood_maps_to_run', {}).get('depth_to_year',{})
existing_object_names = set(bpy.data.objects.keys())
flood_rasters = [name for name in existing_object_names if 'floodmap' in name.lower()]
collection_names = ['noFlood'] + flood_rasters

# masterRunner names one camera per google_url* key, so the count varies by site
camera_names = sorted(
    (o.name for o in bpy.data.objects if o.type == 'CAMERA' and re.fullmatch(r'Camera\d+', o.name)),
    key=lambda n: int(n[len('Camera'):]),
)
output_directory = f"{paths.renderDir(state, project_name, site_num, version_num)}/"
image_format = 'PNG'

def setup_render_settings():
    bpy.context.scene.render.image_settings.file_format = image_format
    bpy.context.scene.render.use_stamp = False # Disabled so Pillow can handle it
    os.makedirs(output_directory, exist_ok=True)

def render_and_save(collection_name, camera_name, update_flag=True):
    camera = bpy.data.objects.get(camera_name)
    if not camera or camera.type != 'CAMERA':
        return None

    # Update label visibility based on camera distance
    render_utils.update_labels_for_camera(camera)

    print(collection_name)
    collection_name, collection_name_only_scenario = render_utils.process_scenario_name(collection_name, depth_to_year)
    print(collection_name)
    bpy.context.scene.camera = camera
    filename = f"{collection_name}_{camera_name}_v{version_num}.{image_format.lower()}"
    filepath = os.path.join(output_directory + f"/{camera_name}/{collection_name_only_scenario}", filename)
    
    if os.path.exists(filepath) and not update_flag:
        print(f"Skipping render: {filepath} already exists")
        return filepath
    
    bpy.context.scene.render.filepath = filepath
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    print(f"Rendering: Collection '{collection_name}', Camera '{camera_name}'")
    bpy.context.view_layer.update()
    #bpy.ops.wm.save_as_mainfile(filepath=os.path.join(output_directory, "DEBUG_PRE_RENDER.blend"))
    bpy.ops.render.render(write_still=True)

    # 2. Force a full Depsgraph rebuild by "scrubbing" the timeline
    current_frame = bpy.context.scene.frame_current
    bpy.context.scene.frame_set(current_frame)
    
    # --- Shared Caption Logic ---
    print(filepath, collection_name, version_num, site_name, site_num, camera_name)
    render_utils.apply_caption(filepath, collection_name, version_num, site_name, site_num, camera_name, font_path)

    return filepath

def flood_rank(name):
    if "noFlood" in name: return 0
    if "2040" in name: return 1
    if "2070" in name: return 2
    if "2100" in name: return 3
    if "200yr_saturated" in name: return 2
    if "200yr" in name: return 1
    if "500yr_saturated" in name: return 4
    if "500yr" in name: return 3
    return 999

# --- Main Run ---
setup_render_settings()
filenames = []

# --- NEW: Load properties once before the loop ---
mp_properties = {}
if globals().get('data_overlays', {}).get('enabled', False):
    import addDataOverlays
    mp_properties = addDataOverlays.load_properties()
    # Map GlobalIDs for flexible lookup (same as main execution)
    for key in list(mp_properties.keys()):
        guid = mp_properties[key].get('GlobalID', '')
        if guid:
            mp_properties[guid.lstrip('{').rstrip('}')] = mp_properties[key]
# -------------------------------------------------

for collection_name in collection_names:
    render_utils.toggle_visibility(collection_name)
    # --- NEW: Update building colors for the current scenario ---
    if globals().get('data_overlays', {}).get('enabled', False):
        # Format the layer name (e.g. 'floodmap_2100_High_C1_site1_3857') to match SCENARIO_FIELD_MAP ('2100_high_c1')
        cleaned_scenario = 'no_flood' if collection_name == 'noFlood' else collection_name.lower().replace('floodmap_', '').split('_site')[0]
        globals()['flood_scenario'] = cleaned_scenario
        addDataOverlays.apply_building_flood_colors(mp_properties, data_overlays_config, color_ramp_config, scenario=collection_name)
    # ------------------------------------------------------------

    for camera_name in camera_names:
        if globals().get('data_overlays', {}).get('enabled', False):
            # Format the layer name (e.g. 'floodmap_2100_High_C1_site1_3857') to match SCENARIO_FIELD_MAP ('2100_high_c1')
            cam_obj = bpy.data.objects.get(camera_name)  # or whatever your camera name is
            addDataOverlays.apply_asset_labels(mp_properties, data_overlays_config, camera=cam_obj)
        currFilepath = render_and_save(collection_name, camera_name, update_flag)
        if currFilepath:
            filenames.append(currFilepath)

# Trailing depth/year on a scenario folder, e.g. '..._Storm_Surge_8.23_feet_2030' or 'Storm_surge_11.25'.
# Stripping it groups every depth of one scenario into a single animation.
SCENARIO_DEPTH_SUFFIX = re.compile(r'_\d+(?:\.\d+)?(?:_feet)?(?:_\d{4})?$')

def scenario_dir_of(filepath):
    return os.path.basename(os.path.dirname(filepath))

def scenario_family(filepath):
    """Group key for a rendered frame: the scenario minus its depth/year suffix."""
    scenario = scenario_dir_of(filepath)
    return SCENARIO_DEPTH_SUFFIX.sub('', scenario) or scenario

def scenario_stem(filepath):
    """The scenario name as process_scenario_name built it, i.e. the frame filename
    without its '_Camera1_v3.png' tail."""
    return re.sub(r'_Camera\d+_v\d+\.\w+$', '', os.path.basename(filepath))

def frame_sort_key(filepath):
    """Order frames by year, then flood depth. Year leads the scenario name
    ('2040_NOAA_2017_High') or ends it ('..._Storm_Surge_8.23_feet_2030'); the scenario
    folder is a fallback for renders made before depths shared one folder."""
    stem = scenario_stem(filepath)
    scenario = scenario_dir_of(filepath)
    year_match = re.match(r'(\d{4})_', stem) or re.search(r'_(\d{4})$', stem) or re.search(r'_(\d{4})$', scenario)
    depth_match = re.search(r'(\d+(?:\.\d+)?)_feet', stem) or re.search(r'(\d+\.\d+)', scenario)
    return (
        int(year_match.group(1)) if year_match else 0,
        float(depth_match.group(1)) if depth_match else 0.0,
        flood_rank(stem),
    )

for camera_name in camera_names:
    currFiles = [x for x in filenames if camera_name in os.path.basename(x)]
    no_flood_files = [x for x in currFiles if 'Baseline_No_Flooding' in x]
    no_flood_file = no_flood_files[0] if no_flood_files else None

    scenarios = {}
    for filepath in currFiles:
        if filepath in no_flood_files:
            continue
        scenarios.setdefault(scenario_family(filepath), []).append(filepath)

    for curr_scenario, files in scenarios.items():
        sorted_files = sorted(files, key=frame_sort_key)
        frames = ([no_flood_file] if no_flood_file else []) + sorted_files
        if len(frames) < 2:
            print(f"Skipping animation for '{curr_scenario}' ({camera_name}): only {len(frames)} frame")
            continue

        # Scenarios split across per-depth folders have no folder of their own, so the
        # animation lands beside them in the camera folder.
        gif_dir = os.path.join(output_directory, camera_name, curr_scenario)
        if not os.path.isdir(gif_dir):
            gif_dir = os.path.join(output_directory, camera_name)
        gif_path = os.path.join(gif_dir, f"animation_{curr_scenario}_{camera_name}_v{version_num}.gif")

        list_file_path = os.path.join(output_directory, camera_name, "list.txt")
        with open(list_file_path, "w") as f:
            for frame in frames:
                f.write(f"file '{frame}'\nduration 2.0\n")

        command = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_file_path,
            '-filter_complex', '[0:v]fps=3,split[v1][v2];[v1]palettegen[p];[v2][p]paletteuse',
            gif_path,
        ]
        result = subprocess.run(command)
        if result.returncode != 0:
            print(f"ffmpeg failed ({result.returncode}) for '{curr_scenario}' ({camera_name}) - no gif written")
        else:
            print(f"Wrote animation: {gif_path} ({len(frames)} frames)")
        os.remove(list_file_path)