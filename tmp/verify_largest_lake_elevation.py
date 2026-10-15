import os
import sys
from pathlib import Path
from unittest.mock import patch

runtime = Path(r'C:\Users\DELL\anaconda3\envs\laketopo-build')
dll = os.add_dll_directory(str(runtime / 'Library/bin'))
os.environ['PATH'] = str(runtime / 'Library/bin') + os.pathsep + os.environ['PATH']
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from osgeo import gdal
import numpy as np
from ui.pages.page_bathymetry import PageBathymetry

gdal.SetConfigOption('GDAL_PAM_ENABLED', 'NO')
root = Path('E:/\u629a\u4ed9\u6e56')
lake = root.name
folder = Path(__file__).parent
depth_path = folder / 'terrain_largest_polygon_verified.tif'
output = folder / 'elevation_largest_polygon_verified.tif'
polygon = str(root / (lake + '_wgs84.shp'))
surround = str(root / (lake + '_merit.tif'))
page = type('ElevationHarness', (), {
    'calculate_shore_elevation': PageBathymetry.calculate_shore_elevation,
})()
base = page.calculate_shore_elevation(polygon, surround)
with patch('ui.pages.page_bathymetry.QMessageBox') as messages:
    PageBathymetry.logic_elevation(page, {
        'lake_shp': polygon, 'surround_dem': surround,
        'depth_raster': str(depth_path), 'out_raster': str(output),
    })
    messages.information.assert_called_once()
ds = gdal.Open(str(output))
a = ds.ReadAsArray()
valid = np.isfinite(a) & (a != ds.GetRasterBand(1).GetNoDataValue())
source = gdal.Open(str(depth_path))
depths = source.ReadAsArray()
np.testing.assert_array_equal(valid, depths != source.GetRasterBand(1).GetNoDataValue())
np.testing.assert_allclose(a[valid], base - depths[valid], atol=0.001)
assert valid.any()
print('VERIFIED:', output, 'base:', base, 'valid cells:', valid.sum(),
      'elevation range:', (a[valid].min(), a[valid].max()))
