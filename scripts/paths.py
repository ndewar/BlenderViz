"""Filesystem roots for the BlenderViz pipeline.

Roots are derived from this file's own location, so a fresh checkout works
anywhere with no configuration. The expected layout is:

    <HIGHTIDE_ROOT>/
        BlenderViz/scripts/paths.py
        HighTideEngine/
        data/

Every value can be overridden with the matching environment variable, which is
how the worker points a job at a different tree.

Blender runs its own Python interpreter, so this module must stay dependency
free -- stdlib only.
"""

import os
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent

BLENDERVIZ_ROOT = Path(os.environ.get('BLENDERVIZ_ROOT', _SCRIPTS.parent))
HIGHTIDE_ROOT = Path(os.environ.get('HIGHTIDE_ROOT', BLENDERVIZ_ROOT.parent))
DATA_ROOT = Path(os.environ.get('HIGHTIDE_DATA_ROOT', HIGHTIDE_ROOT / 'data'))
ENGINE_ROOT = Path(os.environ.get('HIGHTIDE_ENGINE_ROOT', HIGHTIDE_ROOT / 'HighTideEngine'))
DEBUG_RENDERS = Path(os.environ.get('HIGHTIDE_DEBUG_RENDERS', HIGHTIDE_ROOT / 'debug_renders'))

SCRIPTS_DIR = _SCRIPTS
WATERMARK = HIGHTIDE_ROOT / 'Powered-by-HighTide.png'
FONT_PATH = os.environ.get('HIGHTIDE_FONT_PATH', '/System/Library/Fonts/Helvetica.ttc')

# Interpreter used for GDAL/pyproj work that Blender's bundled Python cannot do.
# The worker sets this to its own sys.executable; when unset the caller falls
# back to picking a conda env by hostname.
GEO_PYTHON = os.environ.get('HIGHTIDE_GEO_PYTHON')


def geoToolchain():
    """Return (python, ogr2ogr, env) for GDAL/pyproj work Blender cannot do itself.

    The worker sets HIGHTIDE_GEO_PYTHON to its own sys.executable, which is
    definitionally the right interpreter. Standalone runs fall back to picking a
    conda env by hostname, which is what this used to do everywhere.
    """
    if GEO_PYTHON:
        pythonBin = Path(GEO_PYTHON)
        prefix = pythonBin.resolve().parent.parent
    else:
        import platform
        envName = 'surf_v2' if 'studio' in platform.node().lower() else 'surf_v1'
        prefix = Path.home() / 'miniconda3' / 'envs' / envName
        pythonBin = prefix / 'bin' / 'python'

    env = os.environ.copy()
    env['PROJ_LIB'] = str(prefix / 'share' / 'proj')
    env['GDAL_DATA'] = str(prefix / 'share' / 'gdal')
    return str(pythonBin), str(prefix / 'bin' / 'ogr2ogr'), env


def projectDir(state: str, projectName: str) -> Path:
    return DATA_ROOT / state / 'projects' / projectName


def blenderDir(state: str, projectName: str) -> Path:
    return projectDir(state, projectName) / 'blender'


def siteDir(state: str, projectName: str, siteNum) -> Path:
    return blenderDir(state, projectName) / f'site{siteNum}'


def renderDir(state: str, projectName: str, siteNum, versionNum) -> Path:
    return blenderDir(state, projectName) / 'renders' / f'v{versionNum}' / f'site{siteNum}'


# The three paths below used to live inside the BlenderViz checkout under keys
# that carried no project, so two jobs in the same county overwrote each other's
# data. They are keyed by project and written into the project's data directory.

def legendPath(state: str, projectName: str) -> Path:
    return blenderDir(state, projectName) / 'flood_depth_legend.png'


def satImage(state: str, projectName: str, county: str, siteNum, zoom) -> Path:
    return blenderDir(state, projectName) / f'{county}Site{siteNum}_satimage_{zoom}.png'


def tileCache(state: str, projectName: str, county: str, siteNum, zoom) -> Path:
    return blenderDir(state, projectName) / 'mapboxTiles' / f'{county}_{zoom}_site{siteNum}'
