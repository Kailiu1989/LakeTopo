import os
import sys
from pathlib import Path

runtime = Path(r'C:\Users\DELL\anaconda3\envs\laketopo-build')
dll = os.add_dll_directory(str(runtime / 'Library/bin'))
os.environ['PATH'] = str(runtime / 'Library/bin') + os.pathsep + os.environ['PATH']
from osgeo import gdal, ogr
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dem_builder as dem

gdal.SetConfigOption('GDAL_PAM_ENABLED', 'NO')
root = Path('E:/\u629a\u4ed9\u6e56')
lake = root.name
for suffix in ('_depth.tif', '_height.tif'):
    path = root / (lake + suffix)
    ds = gdal.Open(str(path))
    band = ds.GetRasterBand(1)
    a = band.ReadAsArray()
    nodata = band.GetNoDataValue()
    valid = np.isfinite(a) & (a != nodata)
    print(path.name, 'shape', a.shape, 'nodata', nodata, 'finite', np.isfinite(a).sum(),
          'valid', valid.sum(), 'nan', np.isnan(a).sum(), 'inf', np.isinf(a).sum(),
          'valid range', (a[valid].min(), a[valid].max()) if valid.any() else None,
          'gt', ds.GetGeoTransform(), 'stats metadata', band.GetMetadata(), flush=True)
    print('common values', sorted(zip(*np.unique(a, return_counts=True)), key=lambda pair: -pair[1])[:8], flush=True)
points_path = root / 'temp_ML/PredictedPoints_5.shp'
pts = dem.read_points_with_z(str(points_path), 'Depth')
print('Predicted points', pts.shape, 'range', np.min(pts, axis=0), np.max(pts, axis=0), flush=True)
for path in (root / 'shoreline.shp', root / (lake + '_wgs84.shp')):
    ds = ogr.Open(str(path))
    layer = ds.GetLayer()
    print(path.name, 'extent', layer.GetExtent(), 'srs', layer.GetSpatialRef().GetName(), flush=True)
    if 'wgs84' in path.stem:
        import Common_Function as cf
        parts = []
        for feature in layer:
            for part in cf.iter_polygon_parts(feature.GetGeometryRef()):
                parts.append((part.GetArea(), part.GetEnvelope(), part.GetGeometryCount()))
        print('Polygon parts', len(parts), 'first', parts[:2], 'largest', sorted(parts, reverse=True)[:2], flush=True)
polygon = dem.get_polygon_coords(str(root / (lake + '_wgs84.shp')))
print('Polygon coords', polygon.shape, 'range', polygon.min(axis=0), polygon.max(axis=0), 'first', polygon[:5], flush=True)
ds = gdal.Open(str(root / (lake + '_depth.tif')))
gt = ds.GetGeoTransform()
xx = gt[0] + np.arange(ds.RasterXSize) * gt[1]
yy = gt[3] + np.arange(ds.RasterYSize) * gt[5]
xi, yi = np.meshgrid(xx, yy)
mask = dem.build_lake_mask_from_polygon(xi, yi, polygon)
print('Polygon mask cells on output grid:', mask.sum(), flush=True)
