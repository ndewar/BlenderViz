import bpy
import os

# --- Configuration ---

# Get values from masterRunner's shared context
siteNum = globals().get('siteNum', 1)
versionNum = globals().get('versionNum', 1)
state = globals().get('state', 'florida')
county = globals().get('county', 'brevard')
update_flag = globals().get('update_flag', True)

# 1. Get the existing object names from the scene
existing_object_names = set(bpy.data.objects.keys())

# Filter for flood maps only (exclude DEM)
flood_rasters = [name for name in existing_object_names if 'floodmap' in name.lower()]

# Add noFlood at the beginning for a render with no flood layers visible
collection_names = ['noFlood'] + flood_rasters

print(f"Found flood rasters to render: {collection_names}")

# 2. List the names of the cameras you want to render from.
camera_names = ["Camera1", "Camera2"]  # Changed from ["view1","view2"]

# 3. Set the output directory for your renders.
#    This will create a folder on your desktop.
#    For Windows, it might look like: "C:/Users/YourUsername/Desktop/renders"
#    For macOS/Linux, it will be: "/Users/YourUsername/Desktop/renders"
output_directory = f"/Users/noahdewar/Documents/HighTide/data/{state}/counties/{county}/blender/renders/v{versionNum}/site{siteNum}/"
#os.path.join(os.path.expanduser("~"), "Desktop", "renders")

# 4. Define your desired image format.
#    Options include 'PNG', 'JPEG', 'OPEN_EXR', etc.
image_format = 'PNG'

# --- End of Configuration ---


# --- Script Logic (No need to edit below this line unless you are experienced) ---

def setup_render_settings():
    """Sets the general render settings."""
    bpy.context.scene.render.image_settings.file_format = image_format
    bpy.context.scene.render.use_stamp_frame = False
    bpy.context.scene.render.use_stamp_render_time = False
    bpy.context.scene.render.use_stamp_time = False
    bpy.context.scene.render.use_stamp_camera = False
    bpy.context.scene.render.use_stamp_scene = False
    bpy.context.scene.render.use_stamp_filename = False
    bpy.context.scene.render.use_stamp_note = True
    bpy.context.scene.render.use_stamp = True
    bpy.context.scene.render.stamp_background = (0, 0, 0, 0.75)
    bpy.context.scene.render.stamp_font_size = 16

    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

def toggle_object_visibility(target_object_name):
    """Hides all specified flood objects and makes only the target one visible."""
    
    # Hide all flood rasters first
    for name in collection_names:
        if name != 'noFlood':  # Skip the noFlood placeholder
            obj = bpy.data.objects.get(name)
            if obj:
                obj.hide_render = True
                obj.hide_viewport = True

    # Show the target flood object if it's not noFlood
    if target_object_name != 'noFlood':
        target_obj = bpy.data.objects.get(target_object_name)
        if target_obj:
            target_obj.hide_render = False
            target_obj.hide_viewport = False

    # Always ensure DEM and buildings are visible
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            if "dem" in obj.name.lower():
                obj.hide_render = False
                obj.hide_viewport = False
            elif "building" in obj.name.lower():
                obj.hide_render = False
                obj.hide_viewport = False

def render_and_save(collection_name, camera_name, update_flag = True):
    """Sets the active camera, renders, and saves the image."""
    # Set the active camera
    camera = bpy.data.objects.get(camera_name)
    if not camera or camera.type != 'CAMERA':
        print(f"Warning: Camera '{camera_name}' not found or is not a camera.")
        return None

    bpy.context.scene.camera = camera

    # Construct the output filename
    filename = f"{collection_name}_{camera_name}_v{versionNum}.{image_format.lower()}"
    filepath = os.path.join(output_directory + f'/{camera_name}', filename)
    if os.path.exists(filepath) and not update_flag:
        print(f"Skipping render: {filepath} already exists")
        return filename
    
    bpy.context.scene.render.filepath = filepath
    os.makedirs(output_directory + f'/{camera_name}',exist_ok = True)
    
    # Set the note text
    bpy.context.scene.render.stamp_note_text = collection_name.replace('yr_',' Year, ').replace('noFlood_','').replace('saturated','Saturated Conditions,').replace('_',' ').replace('site','Site ').replace(' C1 ',' Category 1 ').replace(' 3857','') + f', Version {versionNum}'

    # replace the short scenario names with the full ones
    bpy.context.scene.render.stamp_note_text = bpy.context.scene.render.stamp_note_text.replace(' NOAA ',' NOAA 2017 Intermediate-High Sea Level Rise Projections + HighTide Flooding and Storm Surge ')
    bpy.context.scene.render.stamp_note_text = bpy.context.scene.render.stamp_note_text.replace(' High ',' NOAA 2017 High Sea Level Rise Projections + HighTide Flooding and Storm Surge ')
    bpy.context.scene.render.stamp_note_text = bpy.context.scene.render.stamp_note_text.replace(' Low ',' NOAA 2017 Intermediate-Low Sea Level Rise Projections + HighTide Flooding and Storm Surge ')
    bpy.context.scene.render.stamp_note_text = bpy.context.scene.render.stamp_note_text.replace(' USACE ',' USACE 2013 High Sea Level Rise Projections + HighTide Flooding and Storm Surge  ')
    bpy.context.scene.render.stamp_note_text = bpy.context.scene.render.stamp_note_text.replace('noFlood,','Baseline No Flooding Scenario,')
    
    # Render the image
    print(f"Rendering: Collection '{collection_name}', Camera '{camera_name}'")
    bpy.ops.render.render(write_still=True)
    print(f"Saved to: {filepath}")
    
    return filename
    
def set_active_camera(camera_name):
    camera = bpy.data.objects.get(camera_name)
    bpy.context.scene.camera = camera
    
# Ranking functions
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

def view_rank(name):
    if "view1" in name: return 1
    if "view2" in name: return 2
    if "Camera1" in name: return 1
    if "Camera2" in name: return 2
    return 999
    

"""Main function to run the rendering automation."""
setup_render_settings()

print("--- Starting Automated Render ---")
filenames = []

# Loop through each collection
for collection_name in collection_names:
    print(f"\nProcessing Collection: {collection_name}")
    toggle_object_visibility(collection_name)

    # Loop through each camera for the current collection
    for camera_name in camera_names:
        currFilename = render_and_save(collection_name, camera_name, update_flag)
        if currFilename:  # Only append successful renders
            filenames.append(currFilename)

# list all potential scenario tags
# TODO: get this from the project config
potentialScenarios = ['High','Low','USACE','NOAA']

# sort and filter the files
for camera_name in camera_names:
    currFiles = [x for x in filenames if camera_name in x]
    no_flood_file = [x for x in currFiles if 'noFlood' in x][0]

    scenarios = {}
    for filename in currFiles:
        for tag in potentialScenarios:
            if tag in filename:
                if tag not in scenarios:
                    scenarios[tag] = []
                scenarios[tag].append(filename)

    # now make an animation for each scenario
    for curr_scenario in scenarios.keys():

        # Sort by year first, then flood severity
        sorted_files = sorted(scenarios[curr_scenario], key=lambda x: (x.split('_')[1], flood_rank(x)))
        newList = [no_flood_file]
        newList.extend(sorted_files)

        # save the files with camera-specific list file
        list_file_path = f"{output_directory}/{camera_name}/list.txt"
        with open(list_file_path, "w") as f:
            for file in newList:
                f.write(f"file '{output_directory}/{camera_name}/{file}'\n")
                f.write('duration 2.0\n')
        
        # run ffmpeg with camera-specific list file
        commandStr = f'ffmpeg -y -f concat -safe 0 -i {list_file_path} -filter_complex "[0:v]fps=3,split[v1][v2];[v1]palettegen[p];[v2][p]paletteuse" {output_directory}/{camera_name}/{curr_scenario}_animation.gif'
        os.system(commandStr)    

        # remove the list.txt file
        os.remove(list_file_path)

print("\n--- Automated Render Finished ---")

