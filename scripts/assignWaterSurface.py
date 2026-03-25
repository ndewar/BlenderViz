import bpy

def assign_flood_material_to_new_rasters(material_name="GeneratedComplexMaterial"):
    """
    Finds the existing flood water material and assigns it to any
    floodmap mesh objects that don't already have a material assigned.
    """

    # --- Find the existing material ---
    mat = bpy.data.materials.get(material_name)
    if mat is None:
        print(f"ERROR: Material '{material_name}' not found in scene.")
        print(f"Available materials: {[m.name for m in bpy.data.materials]}")
        return None

    print(f"Found material: {mat.name}")
    assigned = []
    skipped = []

    for obj in bpy.data.objects:
        if obj.type == 'MESH' and 'floodmap' in obj.name.lower():
            
            # Check if it already has this material assigned
            if mat.name in [m.name for m in obj.data.materials if m]:
                skipped.append(obj.name)
                continue

            if not obj.data.materials:
                obj.data.materials.append(mat)
            else:
                obj.data.materials[0] = mat

            assigned.append(obj.name)
            print(f"Assigned '{mat.name}' to {obj.name}")

    print(f"\nAssigned to {len(assigned)} objects: {assigned}")
    print(f"Skipped {len(skipped)} objects (already had material): {skipped}")
    return mat

assign_flood_material_to_new_rasters()