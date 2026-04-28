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

# --- Configuration ---
site_name = globals().get('site_name', 1)
site_num = globals().get('siteNum', 1)
font_path = globals()['font_path']
version_num = globals().get('versionNum', 1)
state = globals().get('state', 'florida')
county = globals().get('county', 'brevard')
flyover_config = globals().get('flyover_config', {})
clean_up_frames = flyover_config.get('clean_up_frames', False)

FLYOVER_FRAMES   = flyover_config.get('frames', 60) 
HOLD_FRAMES      = flyover_config.get('hold_frames', 12)
FRAMES_PER_SEC   = flyover_config.get('fps', 24)

output_directory = os.path.join(
    f"/Users/noahdewar/Documents/HighTide/data/{state}/counties/{county}/blender/renders/v{version_num}/site{site_num}/flyover/"
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

def render_flyover_frames(render_cam_obj, cameras, layer_name):
    frames_dir = os.path.join(output_directory, "frames", layer_name)
    os.makedirs(frames_dir, exist_ok=True)
    
    num_cameras = len(cameras)
    num_segments = num_cameras - 1
    total_flyover_frames = FLYOVER_FRAMES * num_segments
    total_frames = HOLD_FRAMES + total_flyover_frames + HOLD_FRAMES
    frame_paths = []

    transforms = []
    for cam in cameras:
        mat = cam.matrix_world.copy()
        transforms.append((mat.to_translation(), mat.to_quaternion()))

    for i in range(total_frames):
        frame_path = os.path.join(frames_dir, f"frame_{i:04d}.png")
        frame_paths.append(frame_path)

        if os.path.exists(frame_path):
            continue

        if i < HOLD_FRAMES: raw_t = 0.0
        elif i >= HOLD_FRAMES + total_flyover_frames: raw_t = 1.0
        else: raw_t = (i - HOLD_FRAMES) / total_flyover_frames

        t_pos_global = ease_in_out(raw_t)
        t_rot_global = ease_in_out(max(0.0, min(1.0, (raw_t - 0.04)))) 

        scaled_pos = t_pos_global * num_segments
        seg_pos = min(int(scaled_pos), num_segments - 1)
        local_t_pos = scaled_pos - seg_pos

        scaled_rot = t_rot_global * num_segments
        seg_rot = min(int(scaled_rot), num_segments - 1)
        local_t_rot = scaled_rot - seg_rot

        loc_start, _ = transforms[seg_pos]
        loc_end, _   = transforms[seg_pos + 1]
        _, rot_start = transforms[seg_rot]
        _, rot_end   = transforms[seg_rot + 1]

        render_cam_obj.location = loc_start.lerp(loc_end, local_t_pos)
        render_cam_obj.rotation_mode = 'QUATERNION'
        render_cam_obj.rotation_quaternion = rot_start.slerp(rot_end, local_t_rot)
        
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

    for layer in flyover_flood_layers:
        output_name = f"flyover_{layer}_v{version_num}"
        gif_path = os.path.join(output_directory, f"{output_name}.gif")
        mp4_path = os.path.join(output_directory, f"{output_name}.mp4")

        if os.path.exists(gif_path) and os.path.exists(mp4_path):
            continue

        # temp skip to let the studio run the USACE and LOW and HIGH scenarios while macbookair does NOAA
        if 'High' in layer or 'Low' in layer or 'USACE' in layer:
            print(f'skipping {layer} for simple multiprocessing')
            continue
        
        # render the frames
        render_utils.toggle_visibility(layer)
        frame_paths = render_flyover_frames(render_cam_obj, all_cameras, layer)

        # Stamp them all in parallel
        existing_frames = [p for p in frame_paths if os.path.exists(p)]
        render_utils.batch_apply_captions(existing_frames, layer, version_num, site_name, site_num, 'Flight Path 1', font_path)

        # assemble the outputs
        assemble_outputs(frame_paths, gif_path, mp4_path)