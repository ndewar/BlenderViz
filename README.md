# BlenderViz - Automated Flood Visualization Pipeline

An automated Blender pipeline for generating flood visualization renders from geospatial data.

## Overview

This project automates the creation of flood visualization scenes in Blender, processing multiple sites with different flood scenarios and generating high-quality renders from multiple camera angles.

## Features

- **Automated Scene Generation**: Imports DEMs, satellite imagery, and flood data
- **Multi-Site Processing**: Process multiple sites in batch with clean resets between each
- **Flood Scenario Rendering**: Generates renders for different flood levels plus no-flood baseline
- **Camera Management**: Automatically positions cameras from Google Maps URLs
- **Material System**: Applies realistic water surfaces and building materials
- **Compositing Pipeline**: Adds watermarks and post-processing effects
- **Animation Generation**: Creates GIF animations showing flood progression

## Requirements

- Blender 4.3+ with Python API
- BlenderGIS addon
- Python packages: `bpy`, `mathutils`, `bmesh`

## Project Structure

```
BlenderViz/
├── masterRunner.py          # Main pipeline orchestrator
├── scripts/
│   ├── importRasters.py     # Import DEM and flood rasters
│   ├── addSatImage.py       # Apply satellite imagery overlay
│   ├── addWorldLighting.py  # Set up HDRI lighting
│   ├── makeWaterSurface.py  # Create water materials
│   ├── setUpCompositing.py  # Configure post-processing
│   ├── addBuildings.py      # Import building shapefiles
│   └── RenderImages.py      # Generate final renders
├── facades/                 # Building material assets
└── mapbox/                  # Satellite imagery cache
```

## Usage

### Basic Usage
```bash
blender -b -P masterRunner.py -- florida brevard 1 ProjectName
```

### Batch Processing Multiple Sites
```bash
blender -b -P masterRunner.py -- florida brevard 1,2,3 ProjectName
```

### Parameters
- `state`: State name (e.g., "florida")
- `county`: County name (e.g., "brevard") 
- `site_num`: Site number(s) - single number or comma-separated list
- `project_name`: Project identifier for config lookup

## Configuration

The pipeline expects a JSON configuration file at:
```
/Users/noahdewar/Documents/HighTide/HighTideEngine/data/projects/{project_name}/blender_config.json
```

Example configuration structure:
```json
{
  "sites": {
    "brevard": {
      "site1": {
        "center_lat_long": [28.3922, -80.6077],
        "worldLightingRotationAngle": 45,
        "renderVersionNumber": 1,
        "google_url_view1": "https://maps.google.com/...",
        "google_url_view2": "https://maps.google.com/..."
      }
    }
  }
}
```

## Output

The pipeline generates:
- **Blend files**: Saved scenes for each site
- **PNG renders**: Individual flood scenario images
- **GIF animations**: Flood progression animations
- **Organized directory structure**: Renders sorted by camera and version

Output structure:
```
/data/{state}/counties/{county}/blender/
├── site1/
│   ├── brevard_site1.blend
│   └── renders/v1/site1/
│       ├── Camera1/
│       │   ├── noFlood_Camera1_v1.png
│       │   ├── floodmap_yr10_Camera1_v1.png
│       │   └── animation.gif
│       └── Camera2/
│           └── ...
```

## Pipeline Stages

1. **Scene Setup**: Clear scene and set georeference
2. **Data Import**: Load DEM, satellite imagery, and flood rasters
3. **Lighting**: Configure HDRI world lighting
4. **Materials**: Apply water surfaces and building materials
5. **Cameras**: Position cameras from Google Maps coordinates
6. **Rendering**: Generate images for all flood scenarios
7. **Post-processing**: Create animations and apply watermarks

## Development

### Adding New Scripts
Add new processing scripts to the `scripts/` directory and include them in the `scripts_to_run` list in `masterRunner.py`.

### Modifying Materials
Building materials are stored in `facades/` and can be customized for different architectural styles.

### Extending Flood Scenarios
Flood rasters are automatically detected by filename patterns containing "floodmap".

## License
This project is proprietary commercial software owned by HighTide. All rights reserved. Unauthorized use, reproduction, or distribution is prohibited.
