import bpy
import os
import math
import re
from mathutils import Vector

# --- Configuration ---
# Get values from masterRunner's shared context
siteNum = globals().get('siteNum', 1)
versionNum = globals().get('versionNum', 1)
state = globals().get('state', 'florida')
county = globals().get('county', 'brevard')
flyover_config = globals().get('flyover_config', {})
clean_up_frames = flyover_config.get('clean_up_frames', False)

# Flyover settings (from config, with sensible defaults)
FLYOVER_FRAMES   = flyover_config.get('frames', 10) # Frames per segment
HOLD_FRAMES      = flyover_config.get('hold_frames', 12)
FRAMES_PER_SEC   = flyover_config.get('fps', 1)

output_directory = os.path.join(
    f"/Users/noahdewar/Documents/HighTide/data/{state}/counties/{county}/blender/renders/v{versionNum}/site{siteNum}/flyover/"
)

# --- End Configuration ---


def ease_in_out(t):
    # Quintic: zero velocity AND acceleration at endpoints
    return t * t * t * (t * (6 * t - 15) + 10)


def natural_sort_key(obj):
    """Helper to sort cameras naturally (e.g., Camera2 before Camera10)"""
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', obj.name)]


def setup_render_settings():
    """Sets general render settings for the flyover."""
    bpy.context.scene.render.image_settings.file_format = 'PNG'
    bpy.context.scene.render.use_stamp = False

    # Motion blur — shutter angle of 180° is the cinematic standard
    bpy.context.scene.render.use_motion_blur = True
    bpy.context.scene.render.motion_blur_shutter = 0.5

    if bpy.context.scene.render.engine == 'CYCLES':
        bpy.context.scene.cycles.motion_blur_position = 'CENTER'

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

    os.makedirs(output_directory, exist_ok=True)


def toggle_flood_layer(layer_name):
    """Shows only the specified flood layer, hiding all others."""
    flood_rasters = [n for n in bpy.data.objects.keys() if 'floodmap' in n.lower()]

    for name in flood_rasters:
        obj = bpy.data.objects.get(name)
        if obj:
            obj.hide_render = True
            obj.hide_viewport = True

    if layer_name != 'noFlood':
        target = bpy.data.objects.get(layer_name)
        if target:
            target.hide_render = False
            target.hide_viewport = False

    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            if 'dem' in obj.name.lower() or 'building' in obj.name.lower():
                obj.hide_render = False
                obj.hide_viewport = False


def get_or_create_flyover_cam(source_cam):
    """Creates (or reuses) a dedicated _FlyoverCam, copying lens settings."""
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


def render_flyover_frames(render_cam_obj, cameras, layer_name):
    """Renders frames into a scenario-specific folder, skipping existing frames."""
    frames_dir = os.path.join(output_directory, "frames", layer_name)
    os.makedirs(frames_dir, exist_ok=True)
    
    num_cameras = len(cameras)
    num_segments = num_cameras - 1
    total_flyover_frames = FLYOVER_FRAMES * num_segments
    
    # Total runtime: Initial Hold + Flight + Final Hold
    total_frames = HOLD_FRAMES + total_flyover_frames + HOLD_FRAMES
    frame_paths = []

    # Set the note text
    bpy.context.scene.render.stamp_note_text = layer_name.replace('yr_',' Year, ').replace('noFlood_','').replace('saturated','Saturated Conditions,').replace('_',' ').replace('site','Site ').replace(' C1 ',' Category 1 ').replace(' 3857','') + f', Version {versionNum}'

    # replace the short scenario names with the full ones
    bpy.context.scene.render.stamp_note_text = bpy.context.scene.render.stamp_note_text.replace(' NOAA ',' NOAA 2017 Intermediate-High Sea Level Rise Projections + HighTide Flooding and Storm Surge ')
    bpy.context.scene.render.stamp_note_text = bpy.context.scene.render.stamp_note_text.replace(' High ',' NOAA 2017 High Sea Level Rise Projections + HighTide Flooding and Storm Surge ')
    bpy.context.scene.render.stamp_note_text = bpy.context.scene.render.stamp_note_text.replace(' Low ',' NOAA 2017 Intermediate-Low Sea Level Rise Projections + HighTide Flooding and Storm Surge ')
    bpy.context.scene.render.stamp_note_text = bpy.context.scene.render.stamp_note_text.replace(' USACE ',' USACE 2013 High Sea Level Rise Projections + HighTide Flooding and Storm Surge  ')
    bpy.context.scene.render.stamp_note_text = bpy.context.scene.render.stamp_note_text.replace('noFlood,','Baseline No Flooding Scenario,')
    
    # Extract all transforms upfront
    transforms = []
    for cam in cameras:
        mat = cam.matrix_world.copy()
        transforms.append((mat.to_translation(), mat.to_quaternion()))

    for i in range(total_frames):
        frame_path = os.path.join(frames_dir, f"frame_{i:04d}.png")
        frame_paths.append(frame_path)

        # Skip logic: If the frame already exists, jump to the next frame
        if os.path.exists(frame_path):
            continue

        # Determine raw time percentage (0.0 to 1.0) across the ENTIRE flight
        if i < HOLD_FRAMES:
            raw_t = 0.0
        elif i >= HOLD_FRAMES + total_flyover_frames:
            raw_t = 1.0
        else:
            raw_t = (i - HOLD_FRAMES) / total_flyover_frames

        # Apply easing to the global progress
        t_pos_global = ease_in_out(raw_t)
        t_rot_global = ease_in_out(max(0.0, min(1.0, (raw_t - 0.04))))  # 4% lag

        # Map global 0.0-1.0 to a specific segment and local 0.0-1.0
        scaled_pos = t_pos_global * num_segments
        seg_pos = min(int(scaled_pos), num_segments - 1)
        local_t_pos = scaled_pos - seg_pos

        scaled_rot = t_rot_global * num_segments
        seg_rot = min(int(scaled_rot), num_segments - 1)
        local_t_rot = scaled_rot - seg_rot

        # Get transforms for the active segment
        loc_start, _ = transforms[seg_pos]
        loc_end, _   = transforms[seg_pos + 1]
        _, rot_start = transforms[seg_rot]
        _, rot_end   = transforms[seg_rot + 1]

        # Apply interpolations
        render_cam_obj.location = loc_start.lerp(loc_end, local_t_pos)
        render_cam_obj.rotation_mode = 'QUATERNION'
        render_cam_obj.rotation_quaternion = rot_start.slerp(rot_end, local_t_rot)
        bpy.context.view_layer.update()

        bpy.context.scene.render.filepath = frame_path
        bpy.ops.render.render(write_still=True)

    return frame_paths


def assemble_outputs(frame_paths, gif_path, mp4_path):
    """Combines rendered frames into a GIF and MP4 using ffmpeg, skipping existing files."""
    list_file = os.path.join(output_directory, "flyover_list.txt")
    frame_duration = 1.0 / FRAMES_PER_SEC

    with open(list_file, "w") as f:
        for path in frame_paths:
            f.write(f"file '{path}'\n")
            f.write(f"duration {frame_duration:.4f}\n")

    if not os.path.exists(gif_path):
        os.system(
            f'ffmpeg -y -f concat -safe 0 -i "{list_file}" '
            f'-filter_complex "[0:v]fps={FRAMES_PER_SEC},scale=1280:-1:flags=lanczos,'
            f'split[v1][v2];[v1]palettegen[p];[v2][p]paletteuse" '
            f'"{gif_path}"'
        )
        print(f"GIF saved: {gif_path}")
    else:
        print(f"Skipping GIF compilation, {gif_path} already exists.")

    if not os.path.exists(mp4_path):
        os.system(
            f'ffmpeg -y -f concat -safe 0 -i "{list_file}" '
            f'-c:v libx264 -pix_fmt yuv420p -crf 18 '
            f'"{mp4_path}"'
        )
        print(f"MP4 saved: {mp4_path}")
    else:
        print(f"Skipping MP4 compilation, {mp4_path} already exists.")

    if os.path.exists(list_file):
        os.remove(list_file)
    
    # if cleanup frames is on, clean them up
    if clean_up_frames:
        for path in frame_paths:
            os.remove(path)


# --- Main ---
print("--- Starting Multi-Camera Flyover Render ---")

# Dynamically build the list of scenarios
floodmap_meshes = [
    obj.name for obj in bpy.data.objects 
    if obj.type == 'MESH' and 'floodmap' in obj.name.lower()
]
# Ensure 'noFlood' is the first scenario, followed by the found floodmaps
flyover_flood_layers = ['noFlood'] + floodmap_meshes

# Discover and sort all cameras dynamically
all_cameras = [obj for obj in bpy.data.objects if obj.type == 'CAMERA' and obj.name != "_FlyoverCam"]
all_cameras.sort(key=natural_sort_key)

if len(all_cameras) < 2:
    print("ERROR: Need at least 2 cameras in the scene to create a flyover. Aborting.")
else:
    print(f"Found {len(all_cameras)} cameras. Render path: {' -> '.join([c.name for c in all_cameras])}")
    print(f"Found {len(flyover_flood_layers)} scenarios to render: {flyover_flood_layers}")
    
    setup_render_settings()
    render_cam_obj = get_or_create_flyover_cam(all_cameras[0])

    # Loop through all dynamically found scenarios
    for layer in flyover_flood_layers:
        output_name = f"flyover_{layer}_v{versionNum}"
        gif_path = os.path.join(output_directory, f"{output_name}.gif")
        mp4_path = os.path.join(output_directory, f"{output_name}.mp4")

        # Skip entire scenario if both final video files exist
        if os.path.exists(gif_path) and os.path.exists(mp4_path):
            print(f"--- Skipping scenario '{layer}', final outputs already exist. ---")
            continue

        print(f"\n--- Processing scenario: {layer} ---")
        toggle_flood_layer(layer)
        
        # Render frames (skips existing individual frames inside)
        frame_paths = render_flyover_frames(render_cam_obj, all_cameras, layer)
        
        # Build outputs (skips existing mp4/gif inside)
        assemble_outputs(frame_paths, gif_path, mp4_path)

print("\n--- All Flyover Renders Finished ---")