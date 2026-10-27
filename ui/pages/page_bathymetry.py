from ui.i18n import localized, tr
import os
import numpy as np
from osgeo import gdal, ogr
from scipy.ndimage import distance_transform_edt
import Common_Function as cf

from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QFrame,
    QApplication,
    QScrollArea,
    QMessageBox,
    QProgressDialog,
)
from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal

# 引入您原有的业务逻辑模块 (请确保这些文件存在)
try:
    import A_PredictedPoints_Gen as mainFunc
    import B_Depth_Prediction as PredictFunc
    import dem_builder as DEMFunc
    import dem_mosaic as MosaicFunc
except ImportError as e:
    print(f"Warning: Failed to import backend modules: {e}")

try:
    from ui.dialogs.bathymetry_dialog import BathymetryDialog
except ImportError:
    pass


def _correct_shoreline_spikes(
    elevation,
    valid_mask,
    minimum_excess=0.5,
    maximum_distance=3.0,
):
    """Remove the constant-height shoreline artifact from an elevation DEM.

    The shoreline reference height is the dominant value 4–8 pixels inside
    the valid raster footprint. Correction is deliberately conservative: it
    is applied only when that ring is at least 80% flat and all anomalous edge
    pixels share one exact height. This avoids flattening a varied natural
    shoreline slope.
    """
    corrected = np.array(elevation, copy=True)
    valid = np.asarray(valid_mask, dtype=bool) & np.isfinite(corrected)
    result = {
        "corrected_pixels": 0,
        "shore_height": None,
        "spike_height": None,
        "reason": "",
    }

    if not valid.any():
        result["reason"] = "the raster has no valid elevation pixels"
        return corrected, result
    if valid.all():
        result["reason"] = "the raster has no invalid footprint boundary"
        return corrected, result

    distance = distance_transform_edt(valid)
    reference_ring = valid & (distance >= 4.0) & (distance <= 8.0)
    reference_count = int(reference_ring.sum())
    if reference_count == 0:
        result["reason"] = "no valid 4–8 pixel shoreline reference ring was found"
        return corrected, result

    values, counts = np.unique(corrected[reference_ring], return_counts=True)
    mode_index = int(np.argmax(counts))
    shore_height = values[mode_index]
    mode_fraction = float(counts[mode_index]) / reference_count
    result["shore_height"] = float(shore_height)
    if mode_fraction < 0.8:
        result["reason"] = (
            "the shoreline reference ring is not sufficiently flat "
            f"(dominant value share {mode_fraction:.1%})"
        )
        return corrected, result

    spikes = (
        valid
        & (distance <= float(maximum_distance))
        & (corrected > shore_height + float(minimum_excess))
    )
    spike_values = np.unique(corrected[spikes])
    if spike_values.size == 0:
        result["reason"] = "no anomalous shoreline pixels were detected"
        return corrected, result
    if spike_values.size > 1:
        result["reason"] = (
            "candidate shoreline pixels have multiple heights; correction "
            "was skipped to preserve the natural slope"
        )
        return corrected, result

    result["spike_height"] = float(spike_values[0])
    result["corrected_pixels"] = int(spikes.sum())
    corrected[spikes] = shore_height
    return corrected, result


class PredictionWorker(QObject):
    """Run long-running bathymetry tasks away from the GUI thread."""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)

    def __init__(self, mode, params):
        super().__init__()
        self.mode = mode
        self.params = params

    def _report_progress(self, value, message):
        self.progress.emit(int(value), str(message))

    def run(self):
        try:
            if self.mode == "pred_loc":
                mainFunc.runPredictedPoints(
                    self.params["work_path"],
                    self.params["lake_name"],
                    self.params["interval"],
                    self.params["win_size"],
                    progress_callback=self._report_progress,
                    lake_polygon_file=self.params["lake_polygon_path"],
                    survey_file=self.params["survey_path"],
                )
                result = None
            elif self.mode == "pred_depth":
                result = PredictFunc.runMLProcessing(
                    self.params["work_path"],
                    self.params["lake_name"],
                    self.params["interval"],
                    self.params["win_size"],
                    model_name=self.params["model"],
                    progress_callback=self._report_progress,
                    survey_file=self.params["survey_path"],
                )
            elif self.mode == "terrain":
                result = DEMFunc.runLakeDEM(
                    self.params["depth_shp"],
                    self.params["z_field"],
                    self.params["breakline"],
                    self.params["polygon"],
                    self.params["out_dem"],
                    self.params["resolution"],
                    progress_callback=self._report_progress,
                )
            elif self.mode == "mosaic":
                result = MosaicFunc.run_mosaic_dem(
                    self.params["lake_dem"],
                    self.params["mosaic_dem"],
                    self.params["out_raster"],
                    self.params["operator"],
                    progress_callback=self._report_progress,
                )
            else:
                raise ValueError(f"Unsupported prediction task: {self.mode}")
            self.finished.emit(self.mode, result)
        except Exception as exc:
            self.failed.emit(self.mode, str(exc))

class PageBathymetry(QWidget):
    def __init__(self, workspace_provider=None, preprocess_context_provider=None):
        super().__init__()
        self.side_buttons = []
        self.workspace_provider = workspace_provider
        self.preprocess_context_provider = preprocess_context_provider
        self._workspace_context_key = ""
        self.predicted_depth_points_path = ""
        self.terrain_output_path = ""
        self.elevation_output_path = ""
        self._prediction_thread = None
        self._prediction_worker = None
        self._prediction_progress = None
        self._prediction_model = None
        self._prediction_outcome = None
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 侧边栏
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

        # --- 添加功能按钮 (移除了合并点功能) ---
        
        self.add_sidebar_btn(side_layout, "Gen. Prediction Points", "pred_loc")
        self.add_sidebar_btn(side_layout, "Gen. Prediction Depth", "pred_depth")
        self.add_sidebar_btn(side_layout, "Terrain Generation", "terrain")
        self.add_sidebar_btn(side_layout, "Elevation Adjustment", "elevation")
        self.add_sidebar_btn(side_layout, "Mosaic DEM", "mosaic")

        side_layout.addStretch()
        scroll.setWidget(scroll_content)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(scroll)

        main_layout.addWidget(sidebar)

    def add_sidebar_btn(self, layout, text, mode_key):
        btn = localized(QPushButton(text))
        btn.setObjectName("sideBtnCyan")
        btn.setFixedSize(270, 60)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setProperty("modeKey", mode_key)

        btn.clicked.connect(self.on_btn_clicked)
        btn.clicked.connect(lambda: self.show_dialog(mode_key))

        self.side_buttons.append(btn)
        layout.addWidget(btn, 0, Qt.AlignHCenter)

    @staticmethod
    def _latest_shapefile(folder_path):
        """Return the most recently modified SHP directly inside a folder."""
        if not folder_path or not os.path.isdir(folder_path):
            return ""
        try:
            candidates = [
                entry.path
                for entry in os.scandir(folder_path)
                if entry.is_file() and entry.name.lower().endswith(".shp")
            ]
            if not candidates:
                return ""
            latest = max(
                candidates,
                key=lambda path: (os.path.getmtime(path), path.lower()),
            )
            return os.path.normpath(latest)
        except OSError:
            return ""

    def show_dialog(self, mode):
        QApplication.processEvents()
        try:
            workspace_path = (
                self.workspace_provider()
                if callable(self.workspace_provider)
                else ""
            )
            workspace_key = (
                os.path.normcase(os.path.abspath(workspace_path))
                if workspace_path
                else ""
            )
            if workspace_key != self._workspace_context_key:
                self._workspace_context_key = workspace_key
                self.predicted_depth_points_path = ""
                self.terrain_output_path = ""
                self.elevation_output_path = ""
            if mode == "terrain":
                self.predicted_depth_points_path = self._latest_shapefile(
                    os.path.join(workspace_path, "temp_ML")
                    if workspace_path
                    else ""
                )
            preprocess_context = (
                self.preprocess_context_provider()
                if callable(self.preprocess_context_provider)
                else {}
            ) or {}
            prefill_values = {
                "depth_shp": self.predicted_depth_points_path,
                "breakline": preprocess_context.get("shoreline_path", ""),
                "surround_dem": preprocess_context.get("merit_dem_path", ""),
                "depth_raster": self.terrain_output_path,
                "lake_dem": self.elevation_output_path,
            }
            dialog = BathymetryDialog(
                mode,
                self,
                default_workspace=workspace_path,
                prefill_values=prefill_values,
            )
            if hasattr(dialog, 'run_signal'):
                dialog.run_signal.connect(self.api_handle_result)
            dialog.exec_()
        except NameError:
            print("BathymetryDialog class not found.")
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
        print(f"[Bathymetry Logic] Task: {mode} | Data: {data}")

        if mode == "terrain":
            output_path = data.get("out_dem", "").strip()
            if output_path:
                self.terrain_output_path = os.path.normpath(output_path)
        elif mode == "elevation":
            output_path = data.get("out_raster", "").strip()
            if output_path:
                self.elevation_output_path = os.path.normpath(output_path)
        
        try:
            if mode == "pred_loc":
                self.logic_pred_loc(data)
            elif mode == "pred_depth":
                self.logic_pred_depth(data)
            elif mode == "terrain":
                self.logic_terrain(data)
            elif mode == "elevation":
                self.logic_elevation(data)
            elif mode == "mosaic":
                self.logic_mosaic(data)
        except Exception as e:
            QMessageBox.critical(self, tr("Execution Error"), tr(str(e)))

    # =========================================================================
    # [业务逻辑实现]
    # =========================================================================

    def logic_pred_loc(self, data):
        """生成预测点位置"""
        try:
            p1 = data['work_path']
            p2 = data.get('lake_name') or os.path.basename(os.path.normpath(p1))
            p3 = int(data['interval'])
            p4 = int(data['win_size'])
            p6 = data.get('lake_polygon_path', '').strip()
            p7 = data.get('survey_path', '').strip()

            if not os.path.isdir(p1):
                QMessageBox.warning(self, tr("Error"), tr("Workspace directory not found."))
                return
            if not p6 or not os.path.isfile(p6):
                QMessageBox.warning(self, tr("Error"), tr("Lake polygon SHP file not found."))
                return
            if not p7 or not os.path.isfile(p7):
                QMessageBox.warning(self, tr("Error"), tr("In-situ bath points file not found."))
                return

            resolved_workspace, resolved_lake = mainFunc._resolve_workspace(p1, p2)
            default_dem = mainFunc._resolve_dem_file(
                resolved_workspace, resolved_lake
            )
            if not os.path.isfile(default_dem):
                QMessageBox.warning(
                    self,
                    tr("Error"),
                    tr(f"Default DEM file not found: {default_dem}\n"
                    "Gen. Prediction Points expects <lake>_merit.tif in the workspace."),
                )
                return

            ok, message = cf.check_spatial_references_match(
                [default_dem, p6, p7]
            )
            if not ok:
                QMessageBox.warning(self, tr("Projection Mismatch"), tr(message))
                return

            params = {
                "work_path": p1,
                "lake_name": p2,
                "interval": p3,
                "win_size": p4,
                "lake_polygon_path": p6,
                "survey_path": p7,
            }
            self._start_prediction_task(
                "pred_loc",
                params,
                "Prediction Point Generation",
                "Preparing prediction-point generation…",
            )
        except Exception as e:
            raise Exception(f"Prediction points failed: {e}")

    def logic_pred_depth(self, data):
        """生成预测点深度"""
        try:
            p1 = data['work_path']
            p2 = data.get('lake_name') or os.path.basename(os.path.normpath(p1))
            p3 = int(data['interval'])
            p4 = int(data['win_size'])
            model_name = data.get('model', 'XGBoost')
            survey_path = data.get('survey_path', '').strip()

            if not os.path.isdir(p1):
                QMessageBox.warning(self, tr("Error"), tr("Workspace directory not found."))
                return
            if not survey_path or not os.path.isfile(survey_path):
                QMessageBox.warning(self, tr("Error"), tr("In-situ bath points file not found."))
                return

            params = {
                "work_path": p1,
                "lake_name": p2,
                "interval": p3,
                "win_size": p4,
                "model": model_name,
                "survey_path": survey_path,
            }
            self._start_prediction_task(
                "pred_depth",
                params,
                "Prediction Depth Generation",
                f"Preparing depth prediction with {model_name}…",
            )
        except Exception as e:
            raise Exception(f"Depth prediction failed: {e}")

    def _start_prediction_task(self, mode, params, title, initial_message):
        if self._prediction_thread is not None and self._prediction_thread.isRunning():
            QMessageBox.information(
                self,
                tr("Processing"),
                tr("A bathymetry prediction task is already running."),
            )
            return

        self._prediction_model = params.get("model") if mode == "pred_depth" else None
        self._prediction_progress = QProgressDialog(
            tr(initial_message), None, 0, 100, self.window()
        )
        self._prediction_progress.setWindowTitle(tr(title))
        self._prediction_progress.setWindowModality(Qt.WindowModal)
        self._prediction_progress.setAutoClose(False)
        self._prediction_progress.setAutoReset(False)
        self._prediction_progress.setMinimumDuration(0)
        self._prediction_progress.setMinimumWidth(460)
        self._prediction_progress.setValue(0)

        self._prediction_thread = QThread(self)
        self._prediction_worker = PredictionWorker(mode, params)
        self._prediction_worker.moveToThread(self._prediction_thread)
        self._prediction_thread.started.connect(self._prediction_worker.run)
        self._prediction_worker.progress.connect(self._update_prediction_progress)
        self._prediction_worker.finished.connect(self._queue_prediction_success)
        self._prediction_worker.failed.connect(self._queue_prediction_failure)
        self._prediction_worker.finished.connect(self._prediction_worker.deleteLater)
        self._prediction_worker.failed.connect(self._prediction_worker.deleteLater)
        self._prediction_worker.finished.connect(self._prediction_thread.quit)
        self._prediction_worker.failed.connect(self._prediction_thread.quit)
        self._prediction_thread.finished.connect(self._on_prediction_thread_finished)
        self._prediction_thread.start()

    def _update_prediction_progress(self, value, message):
        if self._prediction_progress is not None:
            self._prediction_progress.setLabelText(tr(message))
            self._prediction_progress.setValue(max(0, min(100, int(value))))

    def _close_prediction_progress(self):
        if self._prediction_progress is not None:
            self._prediction_progress.close()
            self._prediction_progress.deleteLater()
            self._prediction_progress = None

    def _queue_prediction_success(self, mode, result):
        """Save the result; user dialogs are shown only after QThread has stopped."""
        self._prediction_outcome = ("success", mode, result)
        if self._prediction_progress is not None:
            self._prediction_progress.setLabelText(tr("Finalizing the task…"))
            self._prediction_progress.setValue(100)

    def _queue_prediction_failure(self, mode, message):
        """Save the error; user dialogs are shown only after QThread has stopped."""
        self._prediction_outcome = ("failure", mode, message)
        if self._prediction_progress is not None:
            self._prediction_progress.setLabelText(tr("Finalizing the task…"))

    def _on_prediction_thread_finished(self):
        """Release thread-owned objects before opening a modal result dialog."""
        thread = self._prediction_thread
        outcome = self._prediction_outcome
        model_name = self._prediction_model

        self._close_prediction_progress()
        self._prediction_worker = None
        self._prediction_thread = None
        self._prediction_model = None
        self._prediction_outcome = None
        if thread is not None:
            thread.deleteLater()

        if outcome is None:
            return

        status, mode, result = outcome
        if status == "failure":
            prefix = {
                "pred_loc": "Prediction points failed",
                "pred_depth": "Depth prediction failed",
                "terrain": "Terrain generation failed",
                "mosaic": "DEM mosaic failed",
            }.get(mode, "Bathymetry task failed")
            QMessageBox.critical(self, tr("Execution Error"), tr(f"{prefix}: {result}"))
        elif mode == "pred_depth":
            QMessageBox.information(
                self,
                tr("Success"),
                tr("Task Completed!\n"
                f"Model: {model_name or 'Unknown'}\n"
                f"Holdout MAE: {float(result):.4f}"),
            )
        elif mode == "terrain":
            QMessageBox.information(
                self,
                tr("Success"),
                tr(f"Terrain DEM generated successfully!\nOutput: {result}"),
            )
        elif mode == "mosaic":
            QMessageBox.information(
                self,
                tr("Success"),
                tr("DEM mosaic completed!\n"
                f"Operator: {result['operator']}\n"
                f"Lake pixels in target grid: {result['lake_pixels']:,}\n"
                f"Changed target pixels: {result['changed_pixels']:,}\n"
                f"Output: {result['output']}"),
            )
        else:
            QMessageBox.information(self, tr("Success"), tr("Task Completed!"))

    def shutdown(self):
        """Wait for an active prediction task before destroying the page."""
        if self._prediction_thread is not None and self._prediction_thread.isRunning():
            self._prediction_thread.quit()
            self._prediction_thread.wait()
        self._prediction_outcome = None
        self._close_prediction_progress()

    def logic_terrain(self, data):
        """水下地形生成"""
        try:
            p1 = data['depth_shp'].strip()
            p2 = data['z_field'].strip()
            p3 = data['breakline'].strip()
            p4 = data['polygon'].strip()
            p5 = data['out_dem'].strip()
            p6 = float(data['resolution'])

            required_files = {
                "Depth points SHP": p1,
                "Shoreline SHP": p3,
                "Lake polygon SHP": p4,
            }
            for label, path in required_files.items():
                if not path or not os.path.isfile(path):
                    QMessageBox.warning(self, tr("Error"), tr(f"{label} file not found."))
                    return
            if not p5:
                QMessageBox.warning(self, tr("Error"), tr("Output DEM path is required."))
                return
            if p6 <= 0:
                QMessageBox.warning(self, tr("Error"), tr("Resolution must be greater than zero."))
                return

            ok, message = cf.check_spatial_references_match([p1, p3, p4])
            if not ok:
                QMessageBox.warning(self, tr("Projection Mismatch"), tr(message))
                return

            self._start_prediction_task(
                "terrain",
                {
                    "depth_shp": p1,
                    "z_field": p2,
                    "breakline": p3,
                    "polygon": p4,
                    "out_dem": p5,
                    "resolution": p6,
                },
                "Terrain Generation",
                "Preparing terrain DEM generation…",
            )
        except Exception as e:
            raise Exception(f"Terrain generation failed: {e}")

    def logic_elevation(self, data):
        """湖泊高程调整"""
        manual_elev = data.get('base_elev', '').strip()
        surround_dem = data.get('surround_dem', '')
        lake_shp = data.get('lake_shp', '')
        depth_raster = data.get('depth_raster', '')
        out_raster = data.get('out_raster', '')

        if not (depth_raster and out_raster):
            QMessageBox.warning(self, tr("Error"), tr("Depth raster and Output path are required."))
            return

        base_elev = 0.0
        if manual_elev:
            base_elev = float(manual_elev)
        elif lake_shp and surround_dem:
            ok, message = cf.check_spatial_references_match([lake_shp, surround_dem])
            if not ok:
                QMessageBox.warning(self, tr("Projection Mismatch"), tr(message))
                return
            base_elev = self.calculate_shore_elevation(lake_shp, surround_dem)
            print(f"Auto-calculated base elevation: {base_elev}")
        else:
            QMessageBox.warning(self, tr("Error"), tr("Provide Base Elevation OR Lake Polygon + Surrounding DEM."))
            return
        if not np.isfinite(base_elev):
            raise ValueError("Base elevation must be a finite number.")

        # 执行栅格运算: Elevation = Base - Depth
        ds = gdal.Open(depth_raster, gdal.GA_ReadOnly)
        if not ds: raise Exception("Cannot open depth raster.")
        
        driver = gdal.GetDriverByName('GTiff')
        out_ds = driver.CreateCopy(out_raster, ds, 0)
        if not out_ds:
            ds = None
            raise Exception("Cannot create output elevation raster.")
        band = out_ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        
        # 逐块处理或整体处理（此处假设内存够，整体处理）
        arr = band.ReadAsArray()
        if arr is None:
            out_ds = None
            ds = None
            raise Exception("Cannot read depth raster values.")

        # Use both the GDAL validity mask and finite-value check so numeric and
        # NaN NoData values are handled consistently.
        mask_band = band.GetMaskBand()
        raster_mask = mask_band.ReadAsArray() if mask_band else None
        valid_mask = np.isfinite(arr)
        if raster_mask is not None:
            valid_mask &= raster_mask > 0
        if nodata is not None and np.isfinite(nodata):
            valid_mask &= arr != nodata
        
        # 处理有效值
        arr[valid_mask] = base_elev - arr[valid_mask]

        # Remove the narrow constant-height high-value artifact sometimes
        # produced along the valid lake footprint before the DEM is saved.
        arr, shoreline_result = _correct_shoreline_spikes(arr, valid_mask)
        band.WriteArray(arr)
        band.FlushCache()
        out_ds.FlushCache()
        out_ds = None  # Save
        ds = None

        corrected_count = shoreline_result["corrected_pixels"]
        if corrected_count:
            print(
                "Shoreline correction: "
                f"shore={shoreline_result['shore_height']:.4f} m, "
                f"spike={shoreline_result['spike_height']:.4f} m, "
                f"corrected={corrected_count:,} pixels"
            )
        else:
            print(f"Shoreline correction skipped: {shoreline_result['reason']}")

        QMessageBox.information(
            self,
            tr("Success"),
            tr("Elevation adjustment done.\n"
            f"Base Level: {base_elev:.2f}m\n"
            f"Shoreline spikes corrected: {corrected_count:,}"),
        )

    def logic_mosaic(self, data):
        """DEM 镶嵌"""
        lake_dem = data.get('lake_dem', '').strip()
        mosaic_dem = data.get('mosaic_dem', '').strip()
        output = data.get('out_raster', '').strip()
        operator = data.get('operator', 'Lake DEM Priority')

        if not os.path.isfile(lake_dem) or not os.path.isfile(mosaic_dem):
            QMessageBox.warning(self, tr("Error"), tr("Input DEMs not found."))
            return
        if not output:
            QMessageBox.warning(self, tr("Error"), tr("Output Raster path is required."))
            return
        input_paths = {os.path.normcase(os.path.abspath(path)) for path in (lake_dem, mosaic_dem)}
        if os.path.normcase(os.path.abspath(output)) in input_paths:
            QMessageBox.warning(
                self,
                tr("Error"),
                tr("Output Raster must be a new file and cannot overwrite an input DEM."),
            )
            return

        self._start_prediction_task(
            "mosaic",
            {
                "lake_dem": lake_dem,
                "mosaic_dem": mosaic_dem,
                "out_raster": output,
                "operator": operator,
            },
            "Mosaic DEM",
            "Preparing grid-preserving DEM mosaic…",
        )

    # ------------------ 辅助函数 ------------------

    def calculate_shore_elevation(self, lake_shapefile, raster_path):
        """Sample the exterior shoreline of the same largest polygon used for terrain."""
        rings = DEMFunc.get_largest_polygon_rings(lake_shapefile)
        if not rings:
            raise ValueError("Lake shapefile contains no valid polygon with positive area.")
        ds_ras = gdal.Open(raster_path)
        if ds_ras is None:
            raise ValueError(f"Cannot open surrounding DEM: {raster_path}")
        try:
            gt = ds_ras.GetGeoTransform()
            inverse_gt = gdal.InvGeoTransform(gt)
            if inverse_gt is None:
                raise ValueError("Surrounding DEM has an invalid geotransform.")
            band = ds_ras.GetRasterBand(1)
            nodata = band.GetNoDataValue()
            elevs = []
            for mx, my in rings[0]:
                px_float, py_float = gdal.ApplyGeoTransform(inverse_gt, float(mx), float(my))
                px, py = int(np.floor(px_float)), int(np.floor(py_float))
                if px < 0 or py < 0 or px >= band.XSize or py >= band.YSize:
                    continue
                values = band.ReadAsArray(px, py, 1, 1)
                if values is None:
                    continue
                value = float(values[0, 0])
                if np.isfinite(value) and (nodata is None or value != nodata):
                    elevs.append(value)
            if not elevs:
                raise ValueError("No valid elevation found on the largest polygon's shoreline.")
            return float(np.mean(elevs))
        finally:
            ds_ras = None
