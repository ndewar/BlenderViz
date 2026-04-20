import bpy
import os
import sys
import subprocess
import site
import importlib
from concurrent.futures import ThreadPoolExecutor
import functools
from datetime import date

# 1. Force Blender to recognize the Mac user's Python packages directory
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.append(user_site)

# --- Auto-Install & Import Pillow ---
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    print("Pillow not found. Installing into user environment...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "Pillow"])
        importlib.invalidate_caches()
        from PIL import Image, ImageDraw, ImageFont
        HAS_PILLOW = True
    except Exception as e:
        HAS_PILLOW = False
        print(f"CRITICAL ERROR: Failed to load Pillow: {e}")
# ------------------------------------


def get_caption_lines(layer_name, version_num, site_name, site_num, camera_name):
    """Formats the raw layer name into two clean caption lines."""
    caption_line_one = f"Site {site_num} - {site_name} - {camera_name.replace('Camera','Camera ')}"
    print(layer_name)
    caption_line_two = layer_name.replace('yr_',' Year, ').replace('noFlood_','').replace('saturated','Saturated Conditions,').replace('_',' ').split('site')[0].replace(' C1',' Category 1 Storm Surge').replace(' 3857','')
    caption_line_two = caption_line_two.replace(' Category',' Sea Level Rise Projection + High Tide Flooding and Category')
    print(caption_line_two)
    caption_line_three = f"{str(date.today())} - Version {version_num}"

    return caption_line_one, caption_line_two, caption_line_three


def apply_caption(filepath, layer_name, version_num, site_name, site_num, camera_name, font_path):
    """Draws a stacked main caption top-left, and a smaller metadata caption bottom-left."""

    line1_text, line2_text, line3_text = get_caption_lines(layer_name, version_num, site_name, site_num, camera_name)
    
    img = Image.open(filepath).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    
    # --- 1. Load Two Font Sizes ---
    main_size = 22
    small_size = 16
    
    if 'Helvetica' in font_path:
        font_main = ImageFont.truetype(font_path, size=main_size, index=1)
        font_small = ImageFont.truetype(font_path, size=small_size, index=1)
    else:
        font_main = ImageFont.truetype(font_path, size=main_size)
        font_small = ImageFont.truetype(font_path, size=small_size)
    
    padding = 8
    margin_x = 10
    margin_y = 10
    line_spacing = 6

    # --- 2. Top-Left Box (Line 1 & 2 - Stacked) ---
    bbox1 = draw.textbbox((0, 0), line1_text, font=font_main)
    w1 = bbox1[2] - bbox1[0]
    h1 = bbox1[3] - bbox1[1]
    
    bbox2 = draw.textbbox((0, 0), line2_text, font=font_main)
    w2 = bbox2[2] - bbox2[0]
    h2 = bbox2[3] - bbox2[1]
    
    # Calculate combined box dimensions for top-left
    top_box_width = max(w1, w2)
    top_box_height = h1 + line_spacing + h2
    
    x1, y1 = margin_x, margin_y
    box1_coords = [x1, y1, x1 + top_box_width + (padding * 2), y1 + top_box_height + (padding * 2)]
    
    draw.rectangle(box1_coords, fill=(0, 0, 0, 128))
    draw.text((x1 + padding, y1 + padding), line1_text, fill=(255, 255, 255, 255), font=font_main)
    # Shift line 2 down by the height of line 1 plus spacing
    draw.text((x1 + padding, y1 + padding + h1 + line_spacing), line2_text, fill=(255, 255, 255, 255), font=font_main)
    
    # --- 3. Bottom-Left Box (Line 3 - Metadata) ---
    bbox3 = draw.textbbox((0, 0), line3_text, font=font_small)
    w3 = bbox3[2] - bbox3[0]
    h3 = bbox3[3] - bbox3[1]
    
    x3 = margin_x
    # Anchor to the bottom by subtracting height and margins from total image height
    y3 = img.height - h3 - (padding * 2) - margin_y 
    
    box3_coords = [x3, y3, x3 + w3 + (padding * 2), y3 + h3 + (padding * 2)]
    
    draw.rectangle(box3_coords, fill=(0, 0, 0, 128))
    draw.text((x3 + padding, y3 + padding), line3_text, fill=(255, 255, 255, 255), font=font_small)
    
    # --- 4. Composite and overwrite ---
    combined = Image.alpha_composite(img, overlay)
    combined.save(filepath)


def batch_apply_captions(frame_paths, layer_name, version_num, site_name, site_num, camera_name, font_path):
    """Takes a list of filepaths and applies captions in parallel."""
    if not HAS_PILLOW or not frame_paths:
        return
        
    print(f"Batch stamping {len(frame_paths)} frames in parallel...")
    
    # functools.partial locks in the standard arguments so we only have to map the filepaths
    stamp_func = functools.partial(
        apply_caption,
        layer_name=layer_name,
        version_num=version_num,
        site_name=site_name,
        site_num=site_num,
        camera_name=camera_name,
        font_path=font_path
    )
    
    # ThreadPoolExecutor automatically uses the optimal number of threads for your CPU
    with ThreadPoolExecutor() as executor:
        # executor.map fires them all off simultaneously
        list(executor.map(stamp_func, frame_paths))
        
    print("Batch stamping complete.")


def toggle_visibility(layer_name):
    """Hides all flood layers except the target, ensures DEM/buildings are visible."""
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