import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from osgeo import gdal, ogr, osr
import numpy as np

import dem_builder as dem


class TerrainPolygonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.srs = osr.SpatialReference()
        self.srs.ImportFromEPSG(3857)

    def make_polygons(self, wkts):
        path = str(self.root / 'lake.shp')
        ds = ogr.GetDriverByName('ESRI Shapefile').CreateDataSource(path)
        layer = ds.CreateLayer('lake', self.srs, ogr.wkbPolygon)
        for wkt in wkts:
            feature = ogr.Feature(layer.GetLayerDefn())
            feature.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
            layer.CreateFeature(feature)
        feature = layer = ds = None
        return path

    def test_largest_multipart_member_retains_holes_and_ignores_fragments(self):
        path = self.make_polygons([
            'MULTIPOLYGON (((-2 -2,-2 -1.9,-1.9 -1.9,-1.9 -2,-2 -2)), '
            '((0 0,0 10,10 10,10 0,0 0),(4 4,6 4,6 6,4 6,4 4)))',
            'POLYGON ((12 0,12 3,15 3,15 0,12 0))',
        ])
        rings = dem.get_largest_polygon_rings(path)
        self.assertEqual(len(rings), 2)
        np.testing.assert_array_equal(rings[0].min(axis=0), [0, 0])
        np.testing.assert_array_equal(rings[0].max(axis=0), [10, 10])
        x = np.array([[-1.95, 1, 5, 13]])
        y = np.array([[-1.95, 1, 5, 1]])
        mask = dem.build_lake_mask_from_polygon(x, y, [rings])
        np.testing.assert_array_equal(mask, [[False, True, False, False]])
        np.testing.assert_array_equal(dem.get_polygon_coords(path), rings[0])

    def test_largest_is_selected_by_area_after_subtracting_holes(self):
        path = self.make_polygons([
            'POLYGON ((0 0,0 20,20 20,20 0,0 0),(0.1 0.1,19.9 0.1,19.9 19.9,0.1 19.9,0.1 0.1))',
            'POLYGON ((30 0,30 10,40 10,40 0,30 0))',
        ])
        rings = dem.get_largest_polygon_rings(path)
        np.testing.assert_array_equal(rings[0].min(axis=0), [30, 0])

    def test_all_nan_output_is_rejected_before_creating_file(self):
        x, y = np.meshgrid([0., 1.], [0., 1.])
        output = str(self.root / 'empty.tif')
        with self.assertRaisesRegex(ValueError, 'no valid depth cells'):
            dem.save_dem_to_geotiff(x, y, np.full((2, 2), np.nan), output, self.srs)
        self.assertFalse(Path(output).exists())

    def test_finite_output_and_nodata_are_written_correctly(self):
        x, y = np.meshgrid([0., 1.], [0., 1.])
        output = str(self.root / 'valid.tif')
        dem.save_dem_to_geotiff(x, y, np.array([[np.nan, 0.], [12., 25.]]), output, self.srs)
        ds = gdal.Open(output)
        a = ds.ReadAsArray()
        self.assertEqual(ds.GetRasterBand(1).GetNoDataValue(), -9999)
        self.assertEqual(np.count_nonzero(a != -9999), 3)
        self.assertEqual(a.max(), 25.)

    def make_raster(self, name, values, origin_y=11):
        path = str(self.root / name)
        ds = gdal.GetDriverByName('GTiff').Create(path, values.shape[1], values.shape[0], 1, gdal.GDT_Float32)
        ds.SetProjection(self.srs.ExportToWkt())
        ds.SetGeoTransform((0, 1, 0, origin_y, 0, -1))
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(-9999)
        band.WriteArray(values)
        band = ds = None
        return path

    def test_auto_elevation_uses_only_largest_exterior(self):
        from ui.pages.page_bathymetry import PageBathymetry
        polygon = self.make_polygons([
            'MULTIPOLYGON (((12 0,12 1,13 1,13 0,12 0)), '
            '((0 0,0 10,10 10,10 0,0 0),(4 4,6 4,6 6,4 6,4 4)))',
        ])
        values = np.full((14, 16), 100, dtype=np.float32)
        values[:, 12:] = 900  # detached fragment must not affect the mean
        values[4:8, 4:7] = 700  # internal holes must not affect the outer shore mean
        raster = self.make_raster('surround.tif', values)
        base = PageBathymetry.calculate_shore_elevation(None, polygon, raster)
        self.assertEqual(base, 100)

    def test_elevation_preserves_nodata_and_updates_statistics(self):
        from ui.pages.page_bathymetry import PageBathymetry
        depth = self.make_raster('depth.tif', np.array([[-9999, 0], [10, 20]], dtype=np.float32))
        output = str(self.root / 'height.tif')
        with patch('ui.pages.page_bathymetry.QMessageBox') as messages:
            PageBathymetry.logic_elevation(None, {
                'base_elev': '100', 'depth_raster': depth, 'out_raster': output,
            })
            messages.information.assert_called_once()
        ds = gdal.Open(output)
        np.testing.assert_array_equal(ds.ReadAsArray(), [[-9999, 100], [90, 80]])
        self.assertEqual(ds.GetRasterBand(1).GetNoDataValue(), -9999)
        self.assertEqual(ds.GetRasterBand(1).GetMinimum(), 80)
        self.assertEqual(ds.GetRasterBand(1).GetMaximum(), 100)

    def test_elevation_rejects_empty_depth_before_creating_output(self):
        from ui.pages.page_bathymetry import PageBathymetry
        depth = self.make_raster('empty_depth.tif', np.full((2, 2), -9999, dtype=np.float32))
        output = str(self.root / 'empty_height.tif')
        with self.assertRaisesRegex(ValueError, 'no valid depth cells'):
            PageBathymetry.logic_elevation(None, {
                'base_elev': '100', 'depth_raster': depth, 'out_raster': output,
            })
        self.assertFalse(Path(output).exists())


if __name__ == '__main__':
    unittest.main()
