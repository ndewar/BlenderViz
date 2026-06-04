import bpy
import os
import sys

# --- Import Shared Logic ---
script_dir = "/Users/noahdewar/Documents/HighTide/BlenderViz/scripts/"
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
update_flag = globals().get('update_flag', True)
data_overlays_config = globals().get('data_overlays', {})
color_ramp_config = globals().get('color_ramp', {})
existing_object_names = set(bpy.data.objects.keys())
flood_rasters = [name for name in existing_object_names if 'floodmap' in name.lower()]
collection_names = ['noFlood'] + flood_rasters

camera_names = ["Camera1", "Camera2"] 
output_directory = f"/Users/noahdewar/Documents/HighTide/data/{state}/counties/{county}/blender/renders/v{version_num}/site{site_num}/"
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
    collection_name, collection_name_only_scenario = render_utils.process_scenario_name(collection_name)
    print(collection_name)
    bpy.context.scene.camera = camera
    filename = f"{collection_name}_{camera_name}_v{version_num}.{image_format.lower()}"
    filepath = os.path.join(output_directory + f"/{camera_name}/{collection_name_only_scenario}", filename)
    
    if os.path.exists(filepath) and not update_flag:
        print(f"Skipping render: {filepath} already exists")
        return filename
    
    bpy.context.scene.render.filepath = filepath
    os.makedirs(output_directory + f"/{camera_name}/{collection_name.replace('_C1','').replace('2040_','').replace('2070_','').replace('2100_','')}", exist_ok=True)
    
    print(f"Rendering: Collection '{collection_name}', Camera '{camera_name}'")
    bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(output_directory, "DEBUG_PRE_RENDER.blend"))
    bpy.ops.render.render(write_still=True)

    # 2. Force a full Depsgraph rebuild by "scrubbing" the timeline
    current_frame = bpy.context.scene.frame_current
    bpy.context.scene.frame_set(current_frame)
    
    # --- Shared Caption Logic ---
    print(filepath, collection_name, version_num, site_name, site_num, camera_name)
    render_utils.apply_caption(filepath, collection_name, version_num, site_name, site_num, camera_name, font_path)
    
    return filename
    
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
        currFilename = render_and_save(collection_name, camera_name, update_flag)
        if currFilename:
            filenames.append(currFilename)

potentialScenarios = ['NOAA_2017_High','NOAA_2017_Intermediate-Low','USACE_2013_High','NOAA_2017_Intermediate-High']

for camera_name in camera_names:
    currFiles = [x for x in filenames if camera_name in x]
    no_flood_file = [x for x in currFiles if 'Baseline_No_Flooding' in x][0]
    scenarios = {tag: [] for tag in potentialScenarios}
    
    for filename in currFiles:
        for tag in potentialScenarios:
            if tag in filename:
                scenarios[tag].append(filename)

    for curr_scenario, files in scenarios.items():
        if not files: continue
        sorted_files = sorted(files, key=lambda x: (x.split('_')[1], flood_rank(x)))
        camera_and_version = 'Camera' + sorted_files[0].split('Camera')[1]

        list_file_path = f"{output_directory}/{camera_name}/list.txt"
        with open(list_file_path, "w") as f:
            f.write(f"file '{output_directory}/{camera_name}/Baseline_No_Flooding/{no_flood_file}'\nduration 2.0\n")
            for file in sorted_files:
                f.write(f"file '{output_directory}/{camera_name}/{curr_scenario}/{file}'\nduration 2.0\n")
        
        commandStr = f'ffmpeg -y -f concat -safe 0 -i {list_file_path} -filter_complex "[0:v]fps=3,split[v1][v2];[v1]palettegen[p];[v2][p]paletteuse" {output_directory}/{camera_name}/{curr_scenario}/animation_{curr_scenario}_{camera_and_version}.gif'
        os.system(commandStr)    
        os.remove(list_file_path)