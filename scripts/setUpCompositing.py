import bpy

def setup_compositing_nodes():
    """
    Constructs a compositing node tree in Blender based on a provided log.
    The script sets up an Alpha Over node, Image node, Scale nodes,
    and a Translate node, then connects them to a Viewer node and a Composite node.
    """

    # Enable compositing nodes
    bpy.context.scene.use_nodes = True
    tree = bpy.context.scene.node_tree

    # Clear existing nodes to start fresh
    for node in tree.nodes:
        tree.nodes.remove(node)

    # Add Render Layers node (usually present by default, but good to ensure)
    render_layers_node = tree.nodes.new(type='CompositorNodeRLayers')
    render_layers_node.location = (-1200, 400) # Set an initial position

    # Add Alpha Over node
    alpha_over_node = tree.nodes.new(type="CompositorNodeAlphaOver")
    alpha_over_node.location = (50, 230)

    # Add Image node
    image_node = tree.nodes.new(type="CompositorNodeImage")
    image_node.location = (-900, -200)
    # Open the image file
    try:
        # Construct the absolute path from the relative path provided in the log
        # This assumes the script is run from within the Blender project directory
        # Adjust this path if your script's location or image location differs
        image_path = bpy.path.abspath("/Users/noahdewar/Documents/HighTide/Powered-by-HighTide.png")
        image_node.image = bpy.data.images.load(image_path)
    except RuntimeError:
        print(f"Warning: Could not load image at {image_path}. Please ensure the path is correct.")
        print("You may need to manually set the image for the 'Image' node after running the script.")


    # Add first Scale node
    scale_node_1 = tree.nodes.new(type="CompositorNodeScale")
    scale_node_1.location = (-600, -40)
    scale_node_1.inputs[1].default_value = 0.375  # X Scale
    scale_node_1.inputs[2].default_value = 0.375  # Y Scale

    render = bpy.context.scene.render
    res_x = render.resolution_x * (render.resolution_percentage / 100)
    res_y = render.resolution_y * (render.resolution_percentage / 100)

    # Logo dimensions
    logo_source_w = 960
    logo_source_h = 384
    logo_scale = 0.375

    logo_w = logo_source_w * logo_scale  # = 360px
    logo_h = logo_source_h * logo_scale  # = 144px

    # Margin from bottom-right corner
    margin_x = 20
    margin_y = 20

    # Absolute pixel position (compositor origin = center of frame)
    translate_x = (res_x / 2) - (logo_w / 2) - margin_x
    translate_y = -(res_y / 2) + (logo_h / 2) + margin_y

    # Add Translate node
    translate_node = tree.nodes.new(type="CompositorNodeTranslate")
    translate_node.location = (-300, 60)
    translate_node.inputs[1].default_value = translate_x
    translate_node.inputs[2].default_value = translate_y
    translate_node.use_relative = False  # Absolute pixels

    # Add second Scale node
    scale_node_2 = tree.nodes.new(type="CompositorNodeScale")
    scale_node_2.location = (-100, 7) # Adjusted location for better flow


    # Add Viewer node
    viewer_node = tree.nodes.new(type="CompositorNodeViewer")
    viewer_node.location = (400, 170)
    
    # Add Composite output node
    composite_node = tree.nodes.new(type="CompositorNodeComposite")
    composite_node.location = (700, 230) # Position it after Alpha Over

    # --- Link Nodes ---
    links = tree.links

    # Link Render Layers Image to Alpha Over Image (Top)
    links.new(render_layers_node.outputs["Image"], alpha_over_node.inputs[1])

    # Link Image node Image to Scale node 1 Image
    links.new(image_node.outputs["Image"], scale_node_1.inputs["Image"])

    # Link Scale node 1 Image to Translate node Image
    links.new(scale_node_1.outputs["Image"], translate_node.inputs["Image"])

    # Link Translate node Image to Scale node 2 Image
    links.new(translate_node.outputs["Image"], scale_node_2.inputs["Image"])

    # Link Scale node 2 Image to Alpha Over Image (Bottom)
    links.new(scale_node_2.outputs["Image"], alpha_over_node.inputs[2])

    # Link Alpha Over Image to Viewer Image
    links.new(alpha_over_node.outputs["Image"], viewer_node.inputs["Image"])
    
    # Link Alpha Over Image to Composite node Image (for final render output)
    links.new(alpha_over_node.outputs["Image"], composite_node.inputs["Image"])

    print("Compositing node tree constructed successfully!")

setup_compositing_nodes()