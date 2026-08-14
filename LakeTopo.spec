# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs, collect_submodules


datas = [
    ("assets", "assets"),
    ("cesiumTool", "cesiumTool"),
    ("ui/style.qss", "ui"),
    ("User_guide.pdf", "."),
]
proj_data_dir = Path(sys.prefix) / "Library" / "share" / "proj"
if proj_data_dir.is_dir():
    datas += [(str(proj_data_dir), "Library/share/proj")]
binaries = []
hiddenimports = [
    "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtWebChannel",
    "pandas",
    "openpyxl",
    "pyqtgraph",
    "xgboost",
    "matplotlib",
]
hiddenimports += collect_submodules("ui")
hiddenimports += collect_submodules("cesiumTool")

osgeo_datas, osgeo_binaries, osgeo_hiddenimports = collect_all("osgeo")
datas += osgeo_datas
binaries += osgeo_binaries
hiddenimports += osgeo_hiddenimports

datas += collect_data_files("xgboost", excludes=["**/tests/**", "**/testing/**"])
binaries += collect_dynamic_libs("xgboost")
xgboost_dll = Path(sys.prefix) / "Library" / "bin" / "xgboost.dll"
if xgboost_dll.exists():
    binaries += [(str(xgboost_dll), "xgboost/lib")]


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["packaging_runtime_gdal.py"],
    excludes=[
        "notebook",
        "IPython",
        "pytest",
        "PySide6",
        "qtpy",
        "pandas.tests",
        "pyqtgraph.examples",
        "pyqtgraph.opengl",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LakeTopo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="cesiumTool/favicon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LakeTopo",
)
