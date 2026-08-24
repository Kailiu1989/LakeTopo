import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import traceback

from app_paths import app_root


def run_packaging_smoke_test(raster_paths=()):
    """Verify the frozen GDAL/NumPy bridge without starting the GUI."""
    report_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    report_path = report_dir / "packaging-smoke-test.txt"
    try:
        # Import the real UI/module graph first so the test uses the same OSGeo
        # import order as an interactive raster load.
        from ui.main_window import MainWindow  # noqa: F401
        from cesiumTool.startCesium import prepare_raster_for_cesium
        import lightgbm
        import numpy as np
        import scipy
        import sklearn
        import xgboost
        from osgeo import gdal, gdal_array, osr
        from scipy.interpolate import griddata
        from scipy.ndimage import gaussian_filter
        from scipy.spatial import cKDTree

        gdal.UseExceptions()
        dataset = gdal.GetDriverByName("MEM").Create("", 3, 2, 1, gdal.GDT_Float32)
        expected = np.arange(6, dtype=np.float32).reshape(2, 3)
        band = dataset.GetRasterBand(1)
        band.WriteArray(expected)
        actual = band.ReadAsArray()
        if actual is None or not np.array_equal(actual, expected):
            raise RuntimeError("GDAL array round-trip returned invalid data")

        source_srs = osr.SpatialReference()
        source_srs.ImportFromEPSG(3857)
        dataset.SetProjection(source_srs.ExportToWkt())
        dataset.SetGeoTransform((13358338.9, 30.0, 0.0, 3632749.1, 0.0, -30.0))
        warped = gdal.Warp(
            "",
            dataset,
            options=gdal.WarpOptions(
                format="MEM",
                dstSRS="EPSG:4326",
                width=3,
                height=2,
                outputType=gdal.GDT_Float32,
                resampleAlg=gdal.GRA_Bilinear,
            ),
        )
        if warped is None or warped.ReadAsArray() is None:
            raise RuntimeError("GDAL WGS84 warp returned no raster data")

        # Exercise the SciPy functions used by prediction-point lookup and
        # terrain generation so missing native DLLs fail during packaging.
        sample_xy = np.array(
            [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
            dtype=np.float64,
        )
        tree_distance, tree_index = cKDTree(sample_xy).query([0.9, 0.9])
        if int(tree_index) != 3 or not np.isfinite(tree_distance):
            raise RuntimeError("SciPy cKDTree returned an invalid nearest point")
        interpolated = griddata(
            sample_xy,
            np.array([0.0, 1.0, 1.0, 2.0]),
            np.array([[0.5, 0.5]]),
            method="linear",
        )
        if interpolated is None or not np.all(np.isfinite(interpolated)):
            raise RuntimeError("SciPy griddata returned an invalid interpolation")
        smoothed = gaussian_filter(np.arange(9, dtype=np.float64).reshape(3, 3), 1.0)
        if smoothed.shape != (3, 3) or not np.all(np.isfinite(smoothed)):
            raise RuntimeError("SciPy gaussian_filter returned an invalid surface")

        with tempfile.TemporaryDirectory(prefix="laketopo-raster-smoke-") as temp_dir:
            raster_path = Path(temp_dir) / "projected-dem.tif"
            disk_dataset = gdal.GetDriverByName("GTiff").Create(
                str(raster_path), 3, 2, 1, gdal.GDT_Float32
            )
            disk_dataset.SetProjection(source_srs.ExportToWkt())
            disk_dataset.SetGeoTransform(dataset.GetGeoTransform())
            disk_dataset.GetRasterBand(1).WriteArray(expected)
            disk_dataset = None
            preview = prepare_raster_for_cesium(str(raster_path), max_cells=100)
            if preview["width"] != 3 or preview["height"] != 2:
                raise RuntimeError("Cesium raster preparation returned invalid dimensions")
        raster_results = []
        for raster_path in raster_paths:
            raster_preview = prepare_raster_for_cesium(raster_path)
            raster_results.append(
                f"Raster={raster_path}|{raster_preview['width']}x{raster_preview['height']}"
            )

        result = (
            "PASS\n"
            f"GDAL={gdal.VersionInfo()}\n"
            f"NumPy={np.__version__}\n"
            f"SciPy={scipy.__version__}\n"
            f"XGBoost={xgboost.__version__}\n"
            f"scikit-learn={sklearn.__version__}\n"
            f"LightGBM={lightgbm.__version__}\n"
            f"PROJ_DATA={os.environ.get('PROJ_DATA', '')}\n"
            f"Warp={warped.RasterXSize}x{warped.RasterYSize}\n"
            f"CesiumPreview={preview['width']}x{preview['height']}\n"
            f"SciPyKDTree={int(tree_index)}|{float(tree_distance):.6f}\n"
            f"SciPyGriddata={float(interpolated[0]):.6f}\n"
            f"SciPyGaussian={float(smoothed[1, 1]):.6f}\n"
            f"gdal_array={gdal_array.__file__}\n"
            + ("\n".join(raster_results) + "\n" if raster_results else "")
        )
        report_path.write_text(result, encoding="utf-8")
        return 0
    except Exception:
        report_path.write_text("FAIL\n" + traceback.format_exc(), encoding="utf-8")
        return 1


def run_gui():
    from PyQt5 import QtCore
    from PyQt5.QtWidgets import QApplication
    from ui.main_window import MainWindow

    os.chdir(app_root())
    QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    multiprocessing.freeze_support()

    if "--packaging-smoke-test" in sys.argv:
        option_index = sys.argv.index("--packaging-smoke-test")
        sys.exit(run_packaging_smoke_test(sys.argv[option_index + 1 :]))
    sys.exit(run_gui())
