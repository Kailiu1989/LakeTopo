import os
import sys
from pathlib import Path

runtime = Path(r'C:\Users\DELL\anaconda3\envs\laketopo-build')
dll = os.add_dll_directory(str(runtime / 'Library/bin'))
os.environ['PATH'] = str(runtime / 'Library/bin') + os.pathsep + os.environ['PATH']
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from osgeo import gdal, ogr
import numpy as np
import dem_builder as dem

gdal.SetConfigOption('GDAL_PAM_ENABLED', 'NO')
root = Path('E:/\u629a\u4ed9\u6e56')
lake = root.name
output = Path(__file__).parent / 'terrain_largest_polygon_verified.tif'
polygon = str(root / (lake + '_wgs84.shp'))
rings = dem.get_largest_polygon_rings(polygon)
print('Selected polygon rings:', len(rings), 'extent:', rings[0].min(axis=0), rings[0].max(axis=0), flush=True)
last = [-1]
def progress(value, message):
    if value != last[0]:
        print(value, message, flush=True)
        last[0] = value
dem.runLakeDEM(
    str(root / 'temp_ML/PredictedPoints_5.shp'), 'Depth',
    str(root / 'shoreline.shp'), polygon, str(output), 100,
    progress_callback=progress,
)
ds = gdal.Open(str(output))
band = ds.GetRasterBand(1)
a = band.ReadAsArray()
valid = np.isfinite(a) & (a != band.GetNoDataValue())
assert valid.any(), 'No valid output cells'
assert a[valid].min() >= 0 and a[valid].max() < 200
print('VERIFIED:', output, 'shape:', a.shape, 'valid cells:', valid.sum(),
      'depth range:', (a[valid].min(), a[valid].max()), flush=True)
