import bpy
import os
import math
import re
import sys
from mathutils import Vector

# --- Import Shared Logic ---
script_dir = "/Users/noahdewar/Documents/HighTide/BlenderViz/scripts/"
if script_dir not in sys.path:
    sys.path.append(script_dir)
import render_utils
import addDataOverlays

# --- Configuration ---
site_name = globals().get('site_name', 1)
site_num = globals().get('siteNum', 1)
font_path = globals()['font_path']
version_num = globals().get('versionNum', 1)
state = globals().get('state', 'florida')
county = globals().get('county', 'brevard')
project_name = globals().get('project_name')
data_overlays_config = globals().get('data_overlays', {})
color_ramp_config = globals().get('color_ramp', {})
flyover_config = globals().get('flyover_config', {})
clean_up_frames = flyover_config.get('clean_up_frames', False)

addDataOverlays.state                = globals().get('state', 'florida')
addDataOverlays.county               = globals().get('county', 'brevard')
addDataOverlays.site_num             = globals().get('siteNum', 1)
addDataOverlays.project_name         = globals().get('project_name')
addDataOverlays.data_overlays_config = globals().get('data_overlays', {})
addDataOverlays.color_ramp_config    = globals().get('color_ramp', {})

# Try to get speed; if not present, fall back to frames
FLYOVER_SPEED    = flyover_config.get('speed', None) 
FLYOVER_FRAMES   = flyover_config.get('frames', 60) 
HOLD_FRAMES      = flyover_config.get('hold_frames', 12)
FRAMES_PER_SEC   = flyover_config.get('fps', 24)
print(globals())
output_directory = os.path.join(
    f"/Users/noahdewar/Documents/HighTide/data/{state}/projects/{project_name}/blender/renders/v{version_num}/site{site_num}/flyover/"
)

def ease_in_out(t):
    # Gentle quadratic ease-in-out (smoothstep)
    return t * t * (3 - 2 * t)

def natural_sort_key(obj):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', obj.name)]

def setup_render_settings():
    bpy.context.scene.render.image_settings.file_format = 'PNG'
    bpy.context.scene.render.use_stamp = False # Let Pillow handle it
    bpy.context.scene.render.use_motion_blur = True
    bpy.context.scene.render.motion_blur_shutter = 0.5

    if bpy.context.scene.render.engine == 'CYCLES':
        bpy.context.scene.cycles.motion_blur_position = 'CENTER'

    os.makedirs(output_directory, exist_ok=True)

def get_or_create_flyover_cam(source_cam):
    render_cam_name = "_FlyoverCam"
    if render_cam_name in bpy.data.objects:
        render_cam_obj = bpy.data.objects[render_cam_name]
    else:
        cam_data = bpy.data.cameras.new(name=render_cam_name)
        render_cam_obj = bpy.data.objects.new(render_cam_name, cam_data)
        bpy.context.scene.collection.objects.link(render_cam_obj)

    if source_cam:
        render_cam_obj.data.lens        = source_cam.data.lens
        render_cam_obj.data.sensor_width = source_cam.data.sensor_width
        render_cam_obj.data.clip_end    = source_cam.data.clip_end
        render_cam_obj.data.lens_unit   = source_cam.data.lens_unit
        render_cam_obj.data.sensor_fit  = source_cam.data.sensor_fit
        render_cam_obj.data.angle       = source_cam.data.angle

    bpy.context.scene.camera = render_cam_obj
    return render_cam_obj

def render_flyover_frames(render_cam_obj, cameras, layer_name, properties):
    frames_dir = os.path.join(output_directory, "frames", layer_name)
    os.makedirs(frames_dir, exist_ok=True)
    
    num_cameras = len(cameras)
    num_segments = num_cameras - 1
    frame_paths = []

    # Extract transforms
    transforms = []
    for cam in cameras:
        mat = cam.matrix_world.copy()
        transforms.append((mat.to_translation(), mat.to_quaternion()))

    # --- Conditional Logic: Speed vs. Frames ---
    if FLYOVER_SPEED is not None:
        # Distance-Based Calculation (Constant Speed)
        segment_distances = []
        for i in range(num_segments):
            dist = (transforms[i+1][0] - transforms[i][0]).length
            segment_distances.append(dist)
            
        total_distance = sum(segment_distances)
        if total_distance == 0: total_distance = 0.0001
        
        total_duration_sec = total_distance / FLYOVER_SPEED
        total_flyover_frames = int(total_duration_sec * FRAMES_PER_SEC)
        input(f'With a speed of {FLYOVER_SPEED} and {FRAMES_PER_SEC} frames per second we will be rendering {total_flyover_frames}, ok?')
        
        dist_breakpoints = [0.0]
        current_dist = 0.0
        for d in segment_distances:
            current_dist += d
            dist_breakpoints.append(current_dist / total_distance)
            
    else:
        # Time-Based Calculation (Constant Frames per Segment)
        total_flyover_frames = FLYOVER_FRAMES * num_segments
        
        # Breakpoints are evenly spaced fractions (e.g., 0.0, 0.5, 1.0 for 2 segments)
        dist_breakpoints = [i / num_segments for i in range(num_segments + 1)]

    # Calculate total frames including holds
    total_frames = HOLD_FRAMES + total_flyover_frames + HOLD_FRAMES
    
    # Position camera at frame 0 first
    loc_start, rot_start = transforms[0], transforms[0] 
    render_cam_obj.location = transforms[0][0]
    render_cam_obj.rotation_mode = 'QUATERNION'
    render_cam_obj.rotation_quaternion = transforms[0][1]
    bpy.context.view_layer.update()

    # NOW create labels with correct cam_z
    if globals().get('data_overlays', {}).get('enabled', False):
        addDataOverlays.apply_asset_labels(properties, data_overlays_config, camera=render_cam_obj)
        addDataOverlays.register_visibility_handlers()

    for i in range(total_frames):
        frame_path = os.path.join(frames_dir, f"frame_{i:04d}.png")
        frame_paths.append(frame_path)

        if os.path.exists(frame_path):
            continue

        if i < HOLD_FRAMES: raw_t = 0.0
        elif i >= HOLD_FRAMES + total_flyover_frames: raw_t = 1.0
        else: raw_t = (i - HOLD_FRAMES) / total_flyover_frames

        # Global easing applied to the overall timeline
        t_pos_global = ease_in_out(raw_t)
        t_rot_global = ease_in_out(max(0.0, min(1.0, (raw_t - 0.04)))) 

        # --- Universal Segment Mapping for Position ---
        seg_pos = 0
        local_t_pos = 0.0
        for s in range(num_segments):
            if t_pos_global <= dist_breakpoints[s+1]:
                seg_pos = s
                segment_t_start = dist_breakpoints[s]
                segment_t_length = dist_breakpoints[s+1] - segment_t_start
                if segment_t_length > 0:
                    local_t_pos = (t_pos_global - segment_t_start) / segment_t_length
                break
        else:
            seg_pos = num_segments - 1
            local_t_pos = 1.0

        # --- Universal Segment Mapping for Rotation ---
        seg_rot = 0
        local_t_rot = 0.0
        for s in range(num_segments):
            if t_rot_global <= dist_breakpoints[s+1]:
                seg_rot = s
                segment_t_start = dist_breakpoints[s]
                segment_t_length = dist_breakpoints[s+1] - segment_t_start
                if segment_t_length > 0:
                    local_t_rot = (t_rot_global - segment_t_start) / segment_t_length
                break
        else:
            seg_rot = num_segments - 1
            local_t_rot = 1.0

        # Apply transforms
        loc_start, _ = transforms[seg_pos]
        loc_end, _   = transforms[seg_pos + 1]
        _, rot_start = transforms[seg_rot]
        _, rot_end   = transforms[seg_rot + 1]

        render_cam_obj.location = loc_start.lerp(loc_end, local_t_pos)
        render_cam_obj.rotation_mode = 'QUATERNION'
        render_cam_obj.rotation_quaternion = rot_start.slerp(rot_end, local_t_rot)

        # Update label visibility based on camera distance
        render_utils.update_labels_for_camera(render_cam_obj)

        bpy.context.scene.frame_set(i + 1)
        bpy.context.view_layer.update()
        bpy.context.scene.render.filepath = frame_path

        # Render the frame
        bpy.ops.render.render(write_still=True)
        
    return frame_paths

def assemble_outputs(frame_paths, gif_path, mp4_path):
    list_file = os.path.join(output_directory, "flyover_list.txt")
    frame_duration = 1.0 / FRAMES_PER_SEC

    with open(list_file, "w") as f:
        for path in frame_paths:
            f.write(f"file '{path}'\nduration {frame_duration:.4f}\n")

    if not os.path.exists(gif_path):
        os.system(f'ffmpeg -y -f concat -safe 0 -i "{list_file}" -filter_complex "[0:v]fps={FRAMES_PER_SEC},scale=1280:-1:flags=lanczos,split[v1][v2];[v1]palettegen[p];[v2][p]paletteuse" "{gif_path}"')
    
    if not os.path.exists(mp4_path):
        os.system(f'ffmpeg -y -f concat -safe 0 -i "{list_file}" -c:v libx264 -pix_fmt yuv420p -crf 18 "{mp4_path}"')

    if os.path.exists(list_file): os.remove(list_file)
    if clean_up_frames:
        for path in frame_paths: os.remove(path)

# --- Main ---
print("--- Starting Multi-Camera Flyover Render ---")

floodmap_meshes = [obj.name for obj in bpy.data.objects if obj.type == 'MESH' and 'floodmap' in obj.name.lower()]
flyover_flood_layers = ['noFlood'] + floodmap_meshes

all_cameras = [obj for obj in bpy.data.objects if obj.type == 'CAMERA' and obj.name != "_FlyoverCam"]
all_cameras.sort(key=natural_sort_key)

if len(all_cameras) < 2:
    print("ERROR: Need at least 2 cameras in the scene to create a flyover. Aborting.")
else:
    setup_render_settings()
    render_cam_obj = get_or_create_flyover_cam(all_cameras[0])

    # --- NEW: Load properties once before the loop ---
    mp_properties = {}
    if globals().get('data_overlays', {}).get('enabled', False):
        import addDataOverlays
        mp_properties = addDataOverlays.load_properties(state=state,project_name=project_name,site_num=site_num)
        for key in list(mp_properties.keys()):
            guid = mp_properties[key].get('GlobalID', '')
            if guid:
                mp_properties[guid.lstrip('{').rstrip('}')] = mp_properties[key]
    # -------------------------------------------------

    for layer in flyover_flood_layers:
        # fix layer names and make output filename
        fixed_layer_name, fixed_layer_name_only_scenario = render_utils.process_scenario_name(layer)
        output_name = f"flyover_{fixed_layer_name}_v{version_num}"

        # make output paths and folders
        gif_path = os.path.join(output_directory, fixed_layer_name_only_scenario, f"{output_name}.gif")
        mp4_path = os.path.join(output_directory, fixed_layer_name_only_scenario, f"{output_name}.mp4")
        os.makedirs(os.path.join(output_directory, fixed_layer_name_only_scenario),exist_ok=True)
        if os.path.exists(gif_path) and os.path.exists(mp4_path):
            continue

        # temp skip to let the studio run the USACE and LOW and HIGH scenarios while macbookair does NOAA
        if 'High' in layer or 'Low' in layer or 'USACE' in layer or 'noFlood' in layer:
            print(f'skipping {layer} for simple multiprocessing')
            continue

        # render the frames
        render_utils.toggle_visibility(layer)
        # --- NEW: Update building colors for the current scenario ---
        if globals().get('data_overlays', {}).get('enabled', False):
            cleaned_scenario = 'no_flood' if layer == 'noFlood' else layer.lower().replace('floodmap_', '').split('_site')[0]
            globals()['flood_scenario'] = cleaned_scenario
            addDataOverlays.apply_building_flood_colors(mp_properties, data_overlays_config, color_ramp_config, scenario=layer)
        # ------------------------------------------------------------
        frame_paths = render_flyover_frames(render_cam_obj, all_cameras, layer, mp_properties)
        
        # Stamp them all in parallel
        existing_frames = [p for p in frame_paths if os.path.exists(p)]
        render_utils.batch_apply_captions(existing_frames, fixed_layer_name, version_num, site_name, site_num, 'Flight Path 1', font_path)

        # assemble the outputs
        assemble_outputs(frame_paths, gif_path, mp4_path)