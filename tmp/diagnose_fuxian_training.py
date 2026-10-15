import os
from pathlib import Path

DLL_DIR = r'C:\Users\DELL\anaconda3\envs\laketopo-build\Library\bin'
dll_handle = os.add_dll_directory(DLL_DIR)
os.environ['PATH'] = DLL_DIR + os.pathsep + os.environ['PATH']
from osgeo import gdal, ogr
import numpy as np

gdal.SetConfigOption('GDAL_PAM_ENABLED', 'NO')
root = Path('E:/\u629a\u4ed9\u6e56')
print('GDAL', gdal.VersionInfo())
for p in root.glob('*.tif'):
    ds = gdal.Open(str(p))
    a = ds.ReadAsArray()
    nd = ds.GetRasterBand(1).GetNoDataValue()
    v = a[np.isfinite(a) & (a != nd)]
    print(p.name, 'shape', a.shape, 'nodata', nd, 'valid', len(v),
          'positive', np.count_nonzero(v > 0), 'negative', np.count_nonzero(v < 0),
          'range', (v.min(), v.max()) if len(v) else None,
          'gt', ds.GetGeoTransform(), 'crs', ds.GetProjection()[:100])
for p in root.glob('*.shp'):
    ds = ogr.Open(str(p), 0)
    layer = ds.GetLayer()
    print(p.name, 'count', layer.GetFeatureCount(), 'extent', layer.GetExtent(),
          'srs', layer.GetSpatialRef().GetName(),
          'fields', [(f.GetName(), f.GetTypeName()) for f in layer.schema])
    feature = layer.GetNextFeature()
    print('first', feature.items() if feature else None)
    if 'survey' in p.stem.lower():
        depth_field = 'Depth' if layer.GetLayerDefn().GetFieldIndex('Depth') >= 0 else '\u6c34\u6df1'
        depths = []
        layer.ResetReading()
        for feature in layer:
            depths.append(feature.GetField(depth_field))
        values = np.asarray([v for v in depths if v is not None], dtype=float)
        print('Depth stats', 'total', len(depths), 'null', depths.count(None),
              'positive', np.count_nonzero(values > 0), 'zero', np.count_nonzero(values == 0),
              'negative', np.count_nonzero(values < 0),
              'range', (values.min(), values.max()) if len(values) else None)
        template = gdal.Open(str(root / (root.name + '_extent.tif')))
        for field in ('Depth', depth_field):
            mem = gdal.GetDriverByName('MEM').Create('', template.RasterXSize, template.RasterYSize, 1, gdal.GDT_Float32)
            mem.SetGeoTransform(template.GetGeoTransform())
            mem.SetProjection(template.GetProjection())
            band = mem.GetRasterBand(1)
            band.SetNoDataValue(-9999)
            band.Fill(-9999)
            layer.ResetReading()
            errors = []
            gdal.PushErrorHandler(lambda level, code, message: errors.append((level, code, message)))
            try:
                status = gdal.RasterizeLayer(mem, [1], layer, options=['ATTRIBUTE=' + field, 'ALL_TOUCHED=TRUE'])
            finally:
                gdal.PopErrorHandler()
            array = band.ReadAsArray()
            print('MEM rasterization field', field, 'status', status, 'errors', errors,
                  'valid cells', np.count_nonzero(array != -9999), 'positive cells', np.count_nonzero(array > 0))
