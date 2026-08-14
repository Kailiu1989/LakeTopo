"""PyInstaller runtime hook that pins GDAL to the DLL shipped with LakeTopo."""

import builtins
import ctypes
import os
from pathlib import Path
import sys


bundle_dir = Path(sys._MEIPASS)

if hasattr(os, "add_dll_directory"):
    # Keep the cookie alive for the lifetime of the process.
    builtins._laketopo_dll_directory = os.add_dll_directory(str(bundle_dir))

gdal_dll = bundle_dir / "gdal.dll"
if not gdal_dll.is_file():
    raise RuntimeError(f"The packaged GDAL runtime is missing: {gdal_dll}")

# Loading by absolute path before importing osgeo prevents an incompatible
# gdal.dll elsewhere on PATH from satisfying the Python extension dependency.
builtins._laketopo_gdal_dll = ctypes.WinDLL(str(gdal_dll))

gdal_data = bundle_dir / "Library" / "share" / "gdal"
proj_data = bundle_dir / "Library" / "share" / "proj"
if gdal_data.is_dir():
    os.environ["GDAL_DATA"] = str(gdal_data)
if proj_data.is_dir():
    os.environ["PROJ_LIB"] = str(proj_data)
    os.environ["PROJ_DATA"] = str(proj_data)
