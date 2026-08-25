import os
import csv
import shutil
import numpy as np
from matplotlib.figure import Figure
from osgeo import gdal, ogr, osr
import Common_Function as cf

from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QFrame,
                             QApplication, QScrollArea, QMessageBox, QProgressDialog)
from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal

# 设置 Matplotlib 中文支持

try:
    from ui.dialogs.volume_dialog import VolumeDialog
except ImportError:
    pass


def _capacity_pixel_areas(raster_ds):
    """Return either a scalar or one area per raster row, always in m²."""
    gt = raster_ds.GetGeoTransform()
    rows = raster_ds.RasterYSize
    cols = raster_ds.RasterXSize
    pixel_area_units = abs(gt[1] * gt[5] - gt[2] * gt[4])

    srs = osr.SpatialReference()
    projection = raster_ds.GetProjection()
    if not projection:
        return pixel_area_units
    srs.ImportFromWkt(projection)

    if not srs.IsGeographic():
        linear_units = srs.GetLinearUnits() or 1.0
        return pixel_area_units * (linear_units ** 2)

    row_indices = np.arange(rows, dtype=np.float64)
    center_lats = gt[3] + gt[4] * (cols / 2.0) + gt[5] * (row_indices + 0.5)
    lat_rad = np.radians(center_lats)
    meters_per_degree_lat = (
        111132.92
        - 559.82 * np.cos(2 * lat_rad)
        + 1.175 * np.cos(4 * lat_rad)
        - 0.0023 * np.cos(6 * lat_rad)
    )
    meters_per_degree_lon = (
        111412.84 * np.cos(lat_rad)
        - 93.5 * np.cos(3 * lat_rad)
        + 0.118 * np.cos(5 * lat_rad)
    )
    return pixel_area_units * np.abs(meters_per_degree_lon) * meters_per_degree_lat


def _sample_terrain(dem_data, geo_transform, max_samples=120):
    """Downsample a DEM for responsive embedded 3-D rendering."""
    rows, cols = dem_data.shape
    row_indices = np.unique(np.linspace(0, rows - 1, min(rows, max_samples)).astype(int))
    col_indices = np.unique(np.linspace(0, cols - 1, min(cols, max_samples)).astype(int))
    sampled = dem_data[np.ix_(row_indices, col_indices)].astype(np.float64, copy=True)

    column_grid, row_grid = np.meshgrid(col_indices + 0.5, row_indices + 0.5)
    gt = geo_transform
    x_grid = gt[0] + gt[1] * column_grid + gt[2] * row_grid
    y_grid = gt[3] + gt[4] * column_grid + gt[5] * row_grid
    return x_grid, y_grid, sampled


class CapacityCurveWorker(QObject):
    """Read and analyse the DEM away from the GUI thread."""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, dem_path, level_count=24):
        super().__init__()
        self.dem_path = dem_path
        self.level_count = max(3, int(level_count))

    def _is_cancelled(self):
        return QThread.currentThread().isInterruptionRequested()

    def run(self):
        raster_ds = None
        try:
            self.progress.emit(4, "Opening lake DEM…")
            raster_ds = gdal.Open(self.dem_path)
            if raster_ds is None:
                raise RuntimeError("Cannot open DEM file.")

            band = raster_ds.GetRasterBand(1)
            nodata = band.GetNoDataValue()
            dem_data = band.ReadAsArray().astype(np.float64, copy=False)
            valid_mask = np.isfinite(dem_data)
            if nodata is not None and np.isfinite(nodata):
                valid_mask &= dem_data != nodata
            dem_data = np.where(valid_mask, dem_data, np.nan)
            if not valid_mask.any():
                raise RuntimeError("The selected DEM contains no valid elevation pixels.")

            min_elevation = float(np.nanmin(dem_data))
            max_elevation = float(np.nanmax(dem_data))
            if np.isclose(min_elevation, max_elevation):
                raise RuntimeError("The selected DEM has no elevation range.")

            self.progress.emit(12, "Preparing pixel areas and water levels…")
            levels = np.linspace(min_elevation, max_elevation, self.level_count)
            pixel_areas = _capacity_pixel_areas(raster_ds)
            volumes = []

            for index, level in enumerate(levels):
                if self._is_cancelled():
                    self.cancelled.emit()
                    return
                flooded = valid_mask & (dem_data <= level)
                depth = np.where(flooded, level - dem_data, 0.0)
                if np.isscalar(pixel_areas):
                    volume_m3 = float(np.sum(depth, dtype=np.float64) * pixel_areas)
                else:
                    volume_m3 = float(np.sum(depth * pixel_areas[:, np.newaxis], dtype=np.float64))
                volumes.append(volume_m3 / 1e8)
                percent = 12 + int(73 * (index + 1) / len(levels))
                self.progress.emit(percent, f"Calculating water level {index + 1}/{len(levels)}…")

            if self._is_cancelled():
                self.cancelled.emit()
                return

            self.progress.emit(90, "Building the 3-D terrain preview…")
            terrain_x, terrain_y, terrain_z = _sample_terrain(
                dem_data, raster_ds.GetGeoTransform()
            )
            srs = osr.SpatialReference()
            if raster_ds.GetProjection():
                srs.ImportFromWkt(raster_ds.GetProjection())
            is_geographic = bool(raster_ds.GetProjection() and srs.IsGeographic())
            result = {
                "dem_path": self.dem_path,
                "levels": levels,
                "volumes": np.asarray(volumes, dtype=np.float64),
                "terrain_x": terrain_x,
                "terrain_y": terrain_y,
                "terrain_z": terrain_z,
                "x_label": "Longitude" if is_geographic else "Easting / X",
                "y_label": "Latitude" if is_geographic else "Northing / Y",
            }
            self.progress.emit(100, "E-V curve completed.")
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            raster_ds = None


class PageVolume(QWidget):
    curve_calculation_started = pyqtSignal()
    curve_ready = pyqtSignal(object)
    curve_calculation_failed = pyqtSignal(str)
    curve_calculation_cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.side_buttons = []
        self._curve_thread = None
        self._curve_worker = None
        self._curve_progress = None
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(320)
        sidebar.setStyleSheet("background-color: rgba(11, 18, 21, 0.4); border: none;")

        scroll = QScrollArea(sidebar)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        
        scroll_content = QWidget()
        side_layout = QVBoxLayout(scroll_content)
        side_layout.setContentsMargins(0, 30, 0, 20)
        side_layout.setSpacing(15)

        self.add_sidebar_btn(side_layout, "Lake Volume Calculation", "calc_volume")
        self.add_sidebar_btn(side_layout, "E-V Curve", "ev_curve")

        side_layout.addStretch()
        scroll.setWidget(scroll_content)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(scroll)

        main_layout.addWidget(sidebar)

    def add_sidebar_btn(self, layout, text, mode_key):
        btn = QPushButton(text)
        btn.setObjectName("sideBtnCyan")
        btn.setFixedSize(270, 60)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setProperty("modeKey", mode_key)

        btn.clicked.connect(self.on_btn_clicked)
        btn.clicked.connect(lambda: self.show_dialog(mode_key))

        self.side_buttons.append(btn)
        layout.addWidget(btn, 0, Qt.AlignHCenter)

    def show_dialog(self, mode):
        QApplication.processEvents()
        try:
            dialog = VolumeDialog(mode, self)
            if hasattr(dialog, 'run_signal'):
                dialog.run_signal.connect(self.api_handle_result)
            dialog.exec_()
        except NameError:
            print("VolumeDialog class not found.")
        self.reset_buttons()

    def reset_buttons(self):
        for btn in self.side_buttons:
            btn.setObjectName("sideBtnCyan")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def on_btn_clicked(self):
        sender = self.sender()
        if not sender: return
        self.reset_buttons()
        sender.setObjectName("sideBtnGold")
        sender.style().unpolish(sender)
        sender.style().polish(sender)

    # =========================================================================
    # [API 接口] 业务逻辑分发
    # =========================================================================
    def api_handle_result(self, mode, data):
        print(f"[Volume Logic] Received Task: {mode} | Data: {data}")
        
        if mode == "calc_volume":
            self.run_calculate_lake_volume(data)
        elif mode == "ev_curve":
            self.run_capacity_curve(data)

    # =========================================================================
    # [核心功能] 湖泊水量计算
    # =========================================================================
    def run_calculate_lake_volume(self, data):
        """
        湖泊水量计算逻辑
        Keys: 'ref_elev', 'lake_dem', 'lake_shp', 'out_csv'
        """
        try:
            base_elevation = float(data.get('ref_elev', 0))
        except ValueError:
            QMessageBox.warning(self, "Error", "Reference elevation must be a number.")
            return

        dem_raster_path = data.get('lake_dem', '')
        output_csv_path = data.get('out_csv', '')
        lake_shapefile_path = data.get('lake_shp', '')

        if not os.path.exists(dem_raster_path):
            QMessageBox.warning(self, "Error", "Lake DEM file not found.")
            return

        try:
            # 如果提供了湖泊面SHP，尝试自动计算基准高程
            if lake_shapefile_path and os.path.exists(lake_shapefile_path):
                ok, message = cf.check_spatial_references_match([dem_raster_path, lake_shapefile_path])
                if not ok:
                    QMessageBox.warning(self, "Projection Mismatch", message)
                    return
                print("Calculating shore elevation from Shapefile...")
                try:
                    calculated_elev = self.calculate_shore_elevation(lake_shapefile_path, dem_raster_path)
                    print(f"Auto-calculated Elevation: {calculated_elev}")
                    base_elevation = calculated_elev
                except Exception as e:
                    print(f"Auto-calculation failed, using manual input: {e}")

            # GDAL 处理
            dem_raster_ds = gdal.Open(dem_raster_path)
            if dem_raster_ds is None:
                raise Exception("Cannot open DEM file.")
            
            dem_band = dem_raster_ds.GetRasterBand(1)
            dem_transform = dem_raster_ds.GetGeoTransform()
            dem_nodata = dem_band.GetNoDataValue()
            dem_data = dem_band.ReadAsArray()
            
            if dem_nodata is not None:
                dem_data = np.where(dem_data == dem_nodata, np.nan, dem_data)
            
            # 像元面积
            pixel_area = self.calculate_pixel_area_m2(dem_raster_ds)
            
            total_volume = 0
            # 向量化计算：只计算有效且低于基准面的点
            valid_mask = (~np.isnan(dem_data)) & (dem_data < base_elevation)
            depths = base_elevation - dem_data
            total_volume = np.nansum(depths[valid_mask] * pixel_area[valid_mask])

            # 转换为 10^8
            total_volume /= 1e8
            
            # 保存 CSV
            self.save_to_csv(output_csv_path, total_volume)
            
            QMessageBox.information(self, "Success", f"Volume Calculation Completed.\nTotal Volume: {total_volume:.4f} (10^8 m³)\nSaved to: {output_csv_path}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Calculation failed: {str(e)}")

    # =========================================================================
    # [辅助函数]
    # =========================================================================
    def run_capacity_curve(self, data):
        """Start asynchronous E-V calculation for the selected lake DEM."""
        dem_raster_path = data.get('lake_dem', '')
        if not os.path.exists(dem_raster_path):
            QMessageBox.warning(self, "Error", "Lake DEM file not found.")
            return
        if self._curve_thread is not None and self._curve_thread.isRunning():
            QMessageBox.information(self, "E-V Curve", "An E-V calculation is already running.")
            return

        self.curve_calculation_started.emit()
        self._curve_progress = QProgressDialog(
            "Opening lake DEM…", "Cancel", 0, 100, self.window()
        )
        self._curve_progress.setWindowTitle("E-V Curve Generation")
        self._curve_progress.setWindowModality(Qt.WindowModal)
        self._curve_progress.setAutoClose(False)
        self._curve_progress.setAutoReset(False)
        self._curve_progress.setMinimumDuration(0)
        self._curve_progress.setValue(0)

        self._curve_thread = QThread(self)
        self._curve_worker = CapacityCurveWorker(dem_raster_path)
        self._curve_worker.moveToThread(self._curve_thread)
        self._curve_thread.started.connect(self._curve_worker.run)
        self._curve_worker.progress.connect(self._update_curve_progress)
        self._curve_worker.finished.connect(self._on_curve_finished)
        self._curve_worker.failed.connect(self._on_curve_failed)
        self._curve_worker.cancelled.connect(self._on_curve_cancelled)
        self._curve_worker.finished.connect(self._curve_worker.deleteLater)
        self._curve_worker.failed.connect(self._curve_worker.deleteLater)
        self._curve_worker.cancelled.connect(self._curve_worker.deleteLater)
        self._curve_worker.finished.connect(self._curve_thread.quit)
        self._curve_worker.failed.connect(self._curve_thread.quit)
        self._curve_worker.cancelled.connect(self._curve_thread.quit)
        self._curve_thread.finished.connect(self._cleanup_curve_thread)
        self._curve_progress.canceled.connect(self.cancel_capacity_curve)
        self._curve_thread.start()

    def _update_curve_progress(self, value, message):
        if self._curve_progress is not None:
            self._curve_progress.setLabelText(message)
            self._curve_progress.setValue(value)

    def cancel_capacity_curve(self):
        if self._curve_thread is not None and self._curve_thread.isRunning():
            self._curve_thread.requestInterruption()
            if self._curve_progress is not None:
                self._curve_progress.setLabelText("Cancelling E-V calculation…")
                self._curve_progress.setCancelButton(None)

    def _close_curve_progress(self):
        if self._curve_progress is not None:
            self._curve_progress.close()
            self._curve_progress.deleteLater()
            self._curve_progress = None

    def _on_curve_finished(self, result):
        self._close_curve_progress()
        curve_path = os.path.join(
            os.path.dirname(os.path.normpath(result["dem_path"])), "E-V_Curve.jpg"
        )
        try:
            self.plot_capacity_curve(result["levels"], result["volumes"], curve_path)
            result["curve_path"] = curve_path
            saved_message = f"\nCurve image saved to: {curve_path}"
        except Exception as exc:
            result["curve_save_error"] = str(exc)
            saved_message = (
                "\nThe embedded result is available, but the JPG could not be saved: "
                f"{exc}"
            )

        self.curve_ready.emit(result)
        QMessageBox.information(
            self,
            "Success",
            "E-V Curve Generation Completed.\n"
            "Use the bottom curve to select a water level and update the 3-D simulation."
            + saved_message,
        )

    def _on_curve_failed(self, message):
        self._close_curve_progress()
        self.curve_calculation_failed.emit(message)
        QMessageBox.critical(self, "Error", f"Curve generation failed: {message}")

    def _on_curve_cancelled(self):
        self._close_curve_progress()
        self.curve_calculation_cancelled.emit()

    def _cleanup_curve_thread(self):
        thread = self._curve_thread
        self._curve_worker = None
        self._curve_thread = None
        if thread is not None:
            thread.deleteLater()

    def shutdown(self):
        """Stop a running analysis before the application is destroyed."""
        if self._curve_thread is not None and self._curve_thread.isRunning():
            self._curve_thread.requestInterruption()
            self._curve_thread.quit()
            self._curve_thread.wait()
        self._close_curve_progress()

    def calculate_pixel_area_m2(self, raster_ds):
        gt = raster_ds.GetGeoTransform()
        rows = raster_ds.RasterYSize
        cols = raster_ds.RasterXSize
        x_size = abs(gt[1])
        y_size = abs(gt[5])

        srs = osr.SpatialReference()
        projection = raster_ds.GetProjection()
        if projection:
            srs.ImportFromWkt(projection)
        else:
            return np.full((rows, cols), x_size * y_size, dtype=np.float64)

        if srs.IsGeographic():
            row_indices = np.arange(rows, dtype=np.float64)
            center_lats = gt[3] + gt[4] * (cols / 2.0) + gt[5] * (row_indices + 0.5)
            lat_rad = np.radians(center_lats)
            meters_per_degree_lat = (
                111132.92
                - 559.82 * np.cos(2 * lat_rad)
                + 1.175 * np.cos(4 * lat_rad)
                - 0.0023 * np.cos(6 * lat_rad)
            )
            meters_per_degree_lon = (
                111412.84 * np.cos(lat_rad)
                - 93.5 * np.cos(3 * lat_rad)
                + 0.118 * np.cos(5 * lat_rad)
            )
            row_area = x_size * np.abs(meters_per_degree_lon) * y_size * meters_per_degree_lat
            return np.repeat(row_area[:, np.newaxis], cols, axis=1)

        linear_units = srs.GetLinearUnits() or 1.0
        area = x_size * y_size * (linear_units ** 2)
        return np.full((rows, cols), area, dtype=np.float64)

    def save_to_csv(self, csv_path, volume):
        try:
            # utf-8-sig 兼容 Excel 中文显示
            with open(csv_path, mode='w', newline='', encoding='utf-8-sig') as file:
                writer = csv.writer(file)
                writer.writerow(["Lake Volume (10^8 m³)"])
                writer.writerow([volume])
        except Exception as e:
            raise Exception(f"Failed to save CSV: {str(e)}")

    def calculate_shore_elevation(self, lake_shapefile, raster_path):
        """
        通过取湖泊面边界上的栅格高程平均值来估算水位
        """
        temp_dir = os.path.join(os.path.dirname(raster_path), "lake_temp_vol")
        try:
            os.makedirs(temp_dir, exist_ok=True)
            
            driver = ogr.GetDriverByName("ESRI Shapefile")
            shapefile_ds = driver.Open(lake_shapefile, 0)
            if shapefile_ds is None:
                raise Exception(f"Cannot open SHP: {lake_shapefile}")
            
            layer = shapefile_ds.GetLayer()
            raster_ds = gdal.Open(raster_path)
            if raster_ds is None:
                raise Exception(f"Cannot open Raster: {raster_path}")
                
            geo_transform = raster_ds.GetGeoTransform()
            band = raster_ds.GetRasterBand(1)
            nodata = band.GetNoDataValue()
            
            elevations = []
            polygon_count = 0
            for feature in layer:
                geom = feature.GetGeometryRef()
                for boundary in cf.iter_polygon_exterior_rings(geom):
                    polygon_count += 1
                    for i in range(boundary.GetPointCount()):
                        x_coord, y_coord = boundary.GetX(i), boundary.GetY(i)
                        px = int((x_coord - geo_transform[0]) / geo_transform[1])
                        py = int((y_coord - geo_transform[3]) / geo_transform[5])
                        if px < 0 or py < 0 or px >= band.XSize or py >= band.YSize:
                            continue

                        values = band.ReadAsArray(px, py, 1, 1)
                        if values is None:
                            continue
                        elevation = float(values[0, 0])
                        if np.isfinite(elevation) and (
                            nodata is None or elevation != nodata
                        ):
                            elevations.append(elevation)
                            
            if polygon_count == 0:
                raise Exception(
                    "Lake shapefile contains no valid Polygon, MultiPolygon, "
                    "PolygonZ, or MultiPolygonZ geometry."
                )
            if elevations:
                return np.mean(elevations)
            raise Exception("No valid elevation data found on shoreline.")
        
        except Exception as e:
            raise RuntimeError(f"Shore elevation calc failed: {str(e)}")
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    def plot_capacity_curve(self, x_data, y_data, output_path=None):
        """Save a standalone E-V curve image without opening another window."""
        x = np.asarray(x_data, dtype=float)
        y = np.asarray(y_data, dtype=float)
        if x.size == 0 or x.size != y.size:
            raise ValueError("E-V curve data is empty or inconsistent.")

        figure = Figure(figsize=(10, 7), dpi=100, facecolor="white")
        ax = figure.add_subplot(111)
        ax.set_facecolor("#f8f9fa")
        ax.grid(True, linestyle="--", alpha=0.45)
        ax.plot(x, y, color="#008fa6", linewidth=2.5, label="Capacity Curve")
        ax.fill_between(x, y, color="#00bcd4", alpha=0.18)
        ax.scatter(x, y, color="#e74c3c", s=38, edgecolor="white", linewidth=1.0)
        ax.set_title("Lake Elevation-Volume Curve", fontsize=16, fontweight="bold", pad=20)
        ax.set_xlabel("Water level (m)", fontsize=12, fontweight="bold")
        ax.set_ylabel("Volume (10⁸ m³)", fontsize=12, fontweight="bold")
        ax.legend(loc="upper left")
        figure.tight_layout()
        if output_path:
            figure.savefig(output_path, dpi=300, bbox_inches="tight")
