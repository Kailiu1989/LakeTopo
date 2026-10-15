"""Regression checks for real SHP field encoding and all depth-reading paths."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from osgeo import gdal, ogr, osr
import numpy as np

import Common_Function as cf
import A_PredictedPoints_Gen as prediction
import dem_builder
import rasterProcessing


class DepthFieldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.srs = osr.SpatialReference()
        self.srs.ImportFromEPSG(4326)

    def make_shp(self, fields, point=(102.005, 24.995)):
        path = self.root / f'points_{len(list(self.root.glob("*.shp")))}.shp'
        ds = ogr.GetDriverByName('ESRI Shapefile').CreateDataSource(str(path))
        layer = ds.CreateLayer('points', self.srs, ogr.wkbPoint, options=['ENCODING=UTF-8'])
        for name, value in fields.items():
            kind = ogr.OFTString if isinstance(value, str) else ogr.OFTReal
            layer.CreateField(ogr.FieldDefn(name, kind))
        feature = ogr.Feature(layer.GetLayerDefn())
        for name, value in fields.items():
            feature.SetField(name, value)
        geom = ogr.Geometry(ogr.wkbPoint)
        geom.AddPoint_2D(*point)
        feature.SetGeometry(geom)
        layer.CreateFeature(feature)
        feature = layer = ds = None
        return str(path)

    def resolve(self, path, requested=None):
        ds = ogr.Open(path)
        return cf.resolve_depth_field(ds.GetLayer(), requested)

    def rasterize(self, path):
        template = rasterProcessing.Raster(102, 25, .01, 2, 2, -9999)
        out = str(self.root / 'survey.tif')
        prediction.rasterize_survey_to_template(path, out, template, self.srs.ExportToWkt())
        ds = gdal.Open(out)
        return ds.ReadAsArray()

    def test_chinese_depth_is_read_by_rasterization_and_terrain(self):
        path = self.make_shp({'水深': 14.31})
        self.assertEqual(self.resolve(path, 'Depth'), '水深')
        np.testing.assert_allclose(self.rasterize(path)[0, 0], 14.31, rtol=1e-6)
        for requested in (None, '', 'Depth', '水深'):
            with self.subTest(requested=requested):
                self.assertAlmostEqual(dem_builder.read_points_with_z(path, requested)[0, 2], 14.31)

    def test_english_case_and_legacy_numeric_text(self):
        path = self.make_shp({'DEPTH': '23.5'})
        self.assertEqual(self.resolve(path, '水深'), 'DEPTH')
        self.assertEqual(self.rasterize(path)[0, 0], 23.5)
        self.assertEqual(dem_builder.read_points_with_z(path, 'Depth')[0, 2], 23.5)

    def test_explicit_selection_and_default_priority(self):
        path = self.make_shp({'Depth': 10, '水深': 20, 'measured': 30})
        self.assertEqual(self.resolve(path), 'Depth')
        self.assertEqual(self.resolve(path, '水深'), '水深')
        self.assertEqual(dem_builder.read_points_with_z(path, 'measured')[0, 2], 30)
        with self.assertRaisesRegex(ValueError, 'typo'):
            self.resolve(path, 'typo')

    def test_missing_fields_fail_before_creating_raster(self):
        path = self.make_shp({'other': 10})
        with self.assertRaisesRegex(ValueError, 'Depth.*水深'):
            self.rasterize(path)
        self.assertFalse((self.root / 'survey.tif').exists())
        with self.assertRaisesRegex(ValueError, 'other'):
            dem_builder.read_points_with_z(path)

    def test_no_usable_raster_cells_fail(self):
        for value, point in ((0, (102.005, 24.995)), (10, (110, 30))):
            path = self.make_shp({'水深': value}, point)
            with self.subTest(value=value, point=point):
                with self.assertRaisesRegex(ValueError, 'no valid positive depth'):
                    self.rasterize(path)

    def test_depth_line_check_reads_chinese_with_default_or_blank_field(self):
        from ui.pages.page_validation import PageValidation
        path = self.make_shp({'水深': 14.31})
        raster = str(self.root / 'elevation.tif')
        ds = gdal.GetDriverByName('GTiff').Create(raster, 2, 2, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((102, .01, 0, 25, 0, -.01))
        ds.SetProjection(self.srs.ExportToWkt())
        ds.GetRasterBand(1).Fill(100)
        ds = None
        # Use the real page method without opening an interactive GUI.
        page = type('CheckHarness', (), {
            'get_inverse_geotransform': PageValidation.get_inverse_geotransform,
            'sample_raster_value': PageValidation.sample_raster_value,
        })()
        for requested in ('', 'Depth', '水深'):
            output = str(self.root / 'check.txt')
            with patch('ui.pages.page_validation.QMessageBox') as messages:
                PageValidation.logic_depth_line_check(page, {
                    'check_line': path, 'input_raster': raster, 'surface_dem': raster,
                    'depth_field': requested, 'output_txt': output,
                })
                messages.critical.assert_not_called()
                messages.information.assert_called_once()
            report = Path(output).read_text(encoding='utf-8')
            self.assertIn('Depth Field: 水深', report)
            self.assertIn('Valid Points: 1', report)
            self.assertIn('MAE: 14.31', report)


if __name__ == '__main__':
    unittest.main()
