import bpy
import os

import paths

# ==========================================
# --- CONFIGURATION ---
# ==========================================
# Grab configurations from globals
state = globals().get('state', 'florida')
project_name = globals().get('project_name')
flyover_config = globals().get('flyover_config', {})
is_animation = flyover_config.get("enabled", False)

# Determine if the legend should be shown based on coloring variables
data_overlays = globals().get('data_overlays', {})
flood_raster_coloring = data_overlays.get('flood_raster_depth_coloring', {}).get('enabled', False)
building_coloring = data_overlays.get('building_flood_colors', {}).get('enabled', False)
SHOW_LEGEND = flood_raster_coloring or building_coloring

FOG_COLOR = (0.6, 0.7, 0.8, 1.0)

# --- DEBUG SETTINGS ---
DEBUG_ENABLED = False
DEBUG_DIR = f"{paths.DEBUG_RENDERS}/"

# --- FILE PATHS ---
LOGO_PATH = bpy.path.abspath(str(paths.WATERMARK))
# written by prepDataForBlender.runPrep -- keep the two in sync
LEGEND_PATH = bpy.path.abspath(str(paths.legendPath(state, project_name)))

def setup_compositing_nodes(is_animation_enabled, show_legend):
    bpy.context.scene.use_nodes = True
    tree = bpy.context.scene.node_tree

    bpy.context.view_layer.use_pass_mist = is_animation_enabled
    
    if is_animation_enabled:
        dem_obj = next((obj for obj in bpy.data.objects if 'dem' in obj.name.lower() and obj.type == 'MESH'), None)
        if dem_obj:
            scene_size = max(dem_obj.dimensions)
            fog_start = scene_size * 0.05
            fog_depth = scene_size * 1.5
            for cam in bpy.data.cameras:
                cam.clip_end = scene_size * 2.0
                cam.clip_start = 10.0 
        else:
            fog_start = 500.0
            fog_depth = 25000.0 
            for cam in bpy.data.cameras:
                cam.clip_end = 50000.0
                cam.clip_start = 10.0

        bpy.context.scene.world.mist_settings.start = fog_start
        bpy.context.scene.world.mist_settings.depth = fog_depth

    # Clear existing nodes
    for node in tree.nodes:
        tree.nodes.remove(node)

    # --- 1. RENDER & POST-PROCESSING BASE ---
    render_layers_node = tree.nodes.new(type='CompositorNodeRLayers')
    render_layers_node.location = (-1500, 400) 

    glare_node = tree.nodes.new(type="CompositorNodeGlare")
    glare_node.location = (-1200, 400)
    glare_node.glare_type = 'FOG_GLOW'
    glare_node.quality = 'HIGH'
    glare_node.size = 8                 
    glare_node.threshold = 1.0          

    current_image_output = glare_node.outputs["Image"]
    mist_mix_node = None
    
    if is_animation_enabled:
        mist_mix_node = tree.nodes.new(type="CompositorNodeMixRGB")
        mist_mix_node.location = (-900, 400)
        mist_mix_node.inputs[2].default_value = FOG_COLOR
        
        tree.links.new(current_image_output, mist_mix_node.inputs[1])
        tree.links.new(render_layers_node.outputs["Mist"], mist_mix_node.inputs[0])
        current_image_output = mist_mix_node.outputs["Image"]

    # Grab render resolution for mathematical placement. masterRunner applies the
    # render settings BEFORE this script runs, so these are the final numbers.
    render = bpy.context.scene.render
    res_x = int(render.resolution_x * (render.resolution_percentage / 100))
    res_y = int(render.resolution_y * (render.resolution_percentage / 100))

    # Everything below is sized as a fraction of the frame rather than in fixed
    # pixels, so the overlays keep their proportions at any resolution. The
    # fractions are the values that were hardcoded for 1920x1080.
    margin_x = margin_y = round(30 * res_x / 1920)
    LOGO_WIDTH_FRAC = 0.1875   # 360px in a 1920 frame == the old 0.375 of a 960px logo

    # --- 2. ADD LEGEND (BOTTOM-LEFT) ---
    if show_legend:
        print("  Legend enabled. Adding to compositor...")
        try:
            legend_img = bpy.data.images.load(LEGEND_PATH)
            
            legend_node = tree.nodes.new(type="CompositorNodeImage")
            legend_node.location = (-900, 0)
            legend_node.image = legend_img

            alpha_over_leg = tree.nodes.new(type="CompositorNodeAlphaOver")
            alpha_over_leg.location = (0, 400)
            tree.links.new(current_image_output, alpha_over_leg.inputs[1])

            if tuple(legend_img.size) == (res_x, res_y):
                # prepDataForBlender wrote a full frame legend: it is already the
                # right size and already in the corner, so it goes straight in.
                # No Scale node means nothing resamples it -- the Scale node
                # minifies with a two-tap bilinear filter, which shreds the text.
                print(f"  Legend is full frame ({res_x}x{res_y}), compositing 1:1")
                tree.links.new(legend_node.outputs["Image"], alpha_over_leg.inputs[2])
            else:
                # A legend from an older prep run, or a resolution that changed
                # after prep. Scale it so the frame is still correct, and say so:
                # the placement is right but the text will be soft.
                print(f"  [!] Legend is {tuple(legend_img.size)} but the render is "
                      f"{res_x}x{res_y} - scaling it to fit. Re-run prep for a sharp "
                      f"legend.")
                leg_scale = (0.275 * res_x) / legend_img.size[0]
                scale_leg = tree.nodes.new(type="CompositorNodeScale")
                scale_leg.location = (-600, 0)
                scale_leg.space = 'RELATIVE'
                scale_leg.inputs['X'].default_value = leg_scale
                scale_leg.inputs['Y'].default_value = leg_scale

                leg_w, leg_h = legend_img.size[0] * leg_scale, legend_img.size[1] * leg_scale
                trans_leg = tree.nodes.new(type="CompositorNodeTranslate")
                trans_leg.location = (-300, 0)
                trans_leg.inputs['X'].default_value = round(-(res_x / 2) + (leg_w / 2) + margin_x)
                trans_leg.inputs['Y'].default_value = round(-(res_y / 2) + (leg_h / 2) + margin_y)

                tree.links.new(legend_node.outputs["Image"], scale_leg.inputs["Image"])
                tree.links.new(scale_leg.outputs["Image"], trans_leg.inputs["Image"])
                tree.links.new(trans_leg.outputs["Image"], alpha_over_leg.inputs[2])
            
            # Update the chain to pass through the legend
            current_image_output = alpha_over_leg.outputs["Image"]
            
        except RuntimeError:
            print(f"  [!] Error: Could not load Legend image at {LEGEND_PATH}")

    # --- 3. ADD LOGO WATERMARK (BOTTOM-RIGHT) ---
    try:
        logo_img = bpy.data.images.load(LOGO_PATH)
        
        logo_node = tree.nodes.new(type="CompositorNodeImage")
        logo_node.location = (-900, -300)
        logo_node.image = logo_img

        # Scale off the FRAME, not off the logo's own size. RELATIVE is relative to
        # the source image, so the old fixed 0.375 pinned the watermark to 360px
        # and it would have rendered half-size at 4K.
        logo_scale = (LOGO_WIDTH_FRAC * res_x) / logo_img.size[0]
        scale_logo = tree.nodes.new(type="CompositorNodeScale")
        scale_logo.location = (-600, -300)
        scale_logo.space = 'RELATIVE'
        scale_logo.inputs['X'].default_value = logo_scale
        scale_logo.inputs['Y'].default_value = logo_scale

        # Calculate bottom-right coordinates. Rounded because a half pixel offset
        # is snapped by the Translate node's NEAREST interpolation, which moves the
        # watermark by an unpredictable whole pixel instead of half of one.
        logo_w, logo_h = logo_img.size[0] * logo_scale, logo_img.size[1] * logo_scale
        trans_logo_x = round((res_x / 2) - (logo_w / 2) - margin_x)
        trans_logo_y = round(-(res_y / 2) + (logo_h / 2) + margin_y)

        trans_logo = tree.nodes.new(type="CompositorNodeTranslate")
        trans_logo.location = (-300, -300)
        trans_logo.inputs['X'].default_value = trans_logo_x
        trans_logo.inputs['Y'].default_value = trans_logo_y

        alpha_over_logo = tree.nodes.new(type="CompositorNodeAlphaOver")
        alpha_over_logo.location = (300, 400)

        # Link Logo into the chain
        tree.links.new(logo_node.outputs["Image"], scale_logo.inputs["Image"])
        tree.links.new(scale_logo.outputs["Image"], trans_logo.inputs["Image"])
        tree.links.new(current_image_output, alpha_over_logo.inputs[1])
        tree.links.new(trans_logo.outputs["Image"], alpha_over_logo.inputs[2])

        # Finalize chain
        current_image_output = alpha_over_logo.outputs["Image"]

    except RuntimeError:
        print(f"  [!] Error: Could not load Logo image at {LOGO_PATH}")

    # --- 4. OUTPUT ---
    viewer_node = tree.nodes.new(type="CompositorNodeViewer")
    viewer_node.location = (600, 500)
    
    composite_node = tree.nodes.new(type="CompositorNodeComposite")
    composite_node.location = (600, 300) 

    tree.links.new(render_layers_node.outputs["Image"], glare_node.inputs["Image"])
    tree.links.new(current_image_output, viewer_node.inputs["Image"])
    tree.links.new(current_image_output, composite_node.inputs["Image"])

    # ==========================================
    # --- DEBUGGING FILE OUTPUT NODE ---
    # ==========================================
    if DEBUG_ENABLED:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        debug_out = tree.nodes.new(type="CompositorNodeOutputFile")
        debug_out.location = (100, 700)
        debug_out.label = "DEBUG OUTPUT"
        debug_out.base_path = DEBUG_DIR
        debug_out.format.file_format = 'PNG'
        debug_out.file_slots.clear()

        debug_out.file_slots.new("01_Raw_Render_")
        tree.links.new(render_layers_node.outputs["Image"], debug_out.inputs["01_Raw_Render_"])

        if "Mist" in render_layers_node.outputs:
            debug_out.file_slots.new("02_Raw_Mist_")
            tree.links.new(render_layers_node.outputs["Mist"], debug_out.inputs["02_Raw_Mist_"])

        debug_out.file_slots.new("03_After_Glare_")
        tree.links.new(glare_node.outputs["Image"], debug_out.inputs["03_After_Glare_"])

        if mist_mix_node:
            debug_out.file_slots.new("04_After_Fog_")
            tree.links.new(mist_mix_node.outputs["Image"], debug_out.inputs["04_After_Fog_"])

        print(f"Debug nodes added! Check {DEBUG_DIR} after rendering.")

# Execute Script
setup_compositing_nodes(is_animation, SHOW_LEGEND)