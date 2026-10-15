import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from osgeo import gdal, ogr, osr
import numpy as np
from PyQt5.QtWidgets import QApplication

from ui.dialogs.volume_dialog import VolumeDialog
from ui.pages.page_volume import PageVolume


class VolumeReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.srs = osr.SpatialReference()
        self.srs.ImportFromEPSG(3857)
        self.dem_path = str(self.root / 'lake.tif')
        self.write_dem(np.array([[100, 100, 100], [100, 90, 100], [100, 100, 100]], dtype=np.float32))
        self.polygon_path = str(self.root / 'lake.shp')
        ds = ogr.GetDriverByName('ESRI Shapefile').CreateDataSource(self.polygon_path)
        layer = ds.CreateLayer('lake', self.srs, ogr.wkbPolygon)
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(ogr.CreateGeometryFromWkt(
            'MULTIPOLYGON (((8 8,8 8.1,8.1 8.1,8.1 8,8 8)), '
            '((0.5 0.5,0.5 2.5,2.5 2.5,2.5 0.5,0.5 0.5)))'
        ))
        layer.CreateFeature(feature)
        feature = layer = ds = None
        self.output_path = str(self.root / 'volume.csv')
        self.data = {'lake_dem': self.dem_path, 'lake_shp': self.polygon_path, 'out_csv': self.output_path}
        self.page = type('VolumeHarness', (), {
            'calculate_shore_elevation': PageVolume.calculate_shore_elevation,
            'calculate_pixel_area_m2': PageVolume.calculate_pixel_area_m2,
            'save_to_csv': PageVolume.save_to_csv,
        })()

    def write_dem(self, values):
        ds = gdal.GetDriverByName('GTiff').Create(self.dem_path, 3, 3, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((0, 1, 0, 3, 0, -1))
        ds.SetProjection(self.srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(-9999)
        band.WriteArray(values)
        band = ds = None

    def calculate(self, data):
        with patch('ui.pages.page_volume.QMessageBox') as messages:
            PageVolume.run_calculate_lake_volume(self.page, data)
            messages.warning.assert_not_called()
            messages.critical.assert_not_called()
            messages.information.assert_called_once()
        with open(self.output_path, encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        return float(rows[1][0])

    def test_blank_whitespace_or_missing_reference_samples_lake_dem(self):
        for reference in ('', '  ', None):
            with self.subTest(reference=reference):
                data = dict(self.data)
                if reference is not None:
                    data['ref_elev'] = reference
                with patch.object(self.page, 'calculate_shore_elevation', wraps=self.page.calculate_shore_elevation) as sample:
                    volume = self.calculate(data)
                    sample.assert_called_once_with(self.polygon_path, self.dem_path)
                self.assertAlmostEqual(volume, 10 / 1e8)

    def test_polygon_sampling_overrides_manual_input(self):
        for reference in ('1000', '101'):
            with self.subTest(reference=reference):
                with patch.object(self.page, 'calculate_shore_elevation', wraps=self.page.calculate_shore_elevation) as sample:
                    volume = self.calculate(dict(self.data, ref_elev=reference))
                    sample.assert_called_once_with(self.polygon_path, self.dem_path)
                self.assertAlmostEqual(volume, 10 / 1e8)

    def test_numeric_input_is_used_without_polygon_and_zero_is_valid(self):
        for reference, expected in (('101', 19 / 1e8), ('0', 0), (0, 0), ('-10', 0)):
            with self.subTest(reference=reference):
                with patch.object(self.page, 'calculate_shore_elevation', side_effect=AssertionError('Manual mode must not sample')) as sample:
                    volume = self.calculate(dict(self.data, ref_elev=reference, lake_shp=''))
                    sample.assert_not_called()
                self.assertAlmostEqual(volume, expected)

    def test_auto_mode_requires_polygon_instead_of_using_default(self):
        with patch('ui.pages.page_volume.QMessageBox') as messages:
            PageVolume.run_calculate_lake_volume(self.page, dict(self.data, ref_elev='', lake_shp=''))
            messages.warning.assert_called_once()
            messages.information.assert_not_called()
        self.assertFalse(Path(self.output_path).exists())

    def test_no_valid_shore_samples_causes_error_without_fallback(self):
        values = np.full((3, 3), -9999, dtype=np.float32)
        values[1, 1] = 90
        self.write_dem(values)
        for reference in ('', '1000'):
            with self.subTest(reference=reference):
                with patch('ui.pages.page_volume.QMessageBox') as messages:
                    PageVolume.run_calculate_lake_volume(self.page, dict(self.data, ref_elev=reference))
                    messages.critical.assert_called_once()
                    messages.information.assert_not_called()
                self.assertFalse(Path(self.output_path).exists())

    def test_invalid_or_nonfinite_manual_reference_is_rejected(self):
        for reference in ('abc', 'nan', 'inf', '-inf'):
            with self.subTest(reference=reference):
                with patch('ui.pages.page_volume.QMessageBox') as messages:
                    PageVolume.run_calculate_lake_volume(self.page, dict(self.data, ref_elev=reference, lake_shp=''))
                    messages.warning.assert_called_once()
                    messages.information.assert_not_called()
                self.assertFalse(Path(self.output_path).exists())


class VolumeDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_each_new_dialog_starts_empty_and_submits_empty_reference(self):
        for _ in range(2):
            dialog = VolumeDialog('calc_volume')
            self.assertEqual(dialog.widgets['ref_elev'].text(), '')
            received = Mock()
            dialog.run_signal.connect(received)
            dialog.on_run_clicked()
            received.assert_called_once()
            self.assertEqual(received.call_args[0][1]['ref_elev'], '')
            dialog.close()


if __name__ == '__main__':
    unittest.main()
