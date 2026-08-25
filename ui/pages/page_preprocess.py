import os
import shutil
import math
import tempfile
from pathlib import Path
from osgeo import gdal, ogr, osr
import Common_Function as cf

from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QFrame,
                             QApplication, QScrollArea, QMessageBox, QProgressDialog)
from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal

try:
    from ui.dialogs.preprocess_dialog import PreprocessDialog
except ImportError:
    pass


class ProjectionWorker(QObject):
    """Reproject a batch without accessing GUI objects from the worker thread."""

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, input_files, converter):
        super().__init__()
        self.input_files = list(input_files)
        self.converter = converter

    @staticmethod
    def _is_cancelled():
        return QThread.currentThread().isInterruptionRequested()

    def _make_callback(self, item_index, item_count, filename):
        def callback(completion, _message, _callback_data):
            bounded = max(0.0, min(1.0, float(completion)))
            percent = int(((item_index + bounded) / item_count) * 100)
            self.progress.emit(
                percent,
                f"Converting {item_index + 1}/{item_count}: {filename}\n"
                f"{int(bounded * 100)}%",
            )
            return 0 if self._is_cancelled() else 1

        return callback

    def run(self):
        succeeded = []
        failures = []
        cancelled = False
        total = len(self.input_files)
        try:
            for index, input_path in enumerate(self.input_files):
                if self._is_cancelled():
                    cancelled = True
                    break

                output_path = self.converter.wgs84_output_path(input_path)
                callback = self._make_callback(
                    index, total, os.path.basename(input_path)
                )
                try:
                    if not os.path.isfile(input_path):
                        raise RuntimeError("Input file does not exist.")
                    if Path(input_path).suffix.lower() == ".shp":
                        self.converter.convert_shapefile_to_wgs84(
                            input_path, output_path, callback
                        )
                    else:
                        self.converter.convert_raster_to_wgs84(
                            input_path, output_path, callback
                        )
                    succeeded.append(output_path)
                except Exception as exc:
                    if self._is_cancelled():
                        cancelled = True
                        break
                    failures.append((input_path, str(exc)))

                self.progress.emit(
                    int(((index + 1) / total) * 100),
                    f"Completed {index + 1}/{total}: {os.path.basename(input_path)}",
                )

            self.finished.emit(
                {
                    "succeeded": succeeded,
                    "failed": failures,
                    "cancelled": cancelled,
                    "total": total,
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))

class PagePreprocess(QWidget):
    def __init__(self):
        super().__init__()
        self.side_buttons = []
        self.workspace_dir = None # 存储当前工作空间路径
        self._projection_thread = None
        self._projection_worker = None
        self._projection_progress = None
        self._projection_outcome = None
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

        # --- 添加按钮 ---
        self.add_sidebar_btn(side_layout, "Open/Create Workspace", "workspace")
        self.add_sidebar_btn(side_layout, "Buffer Full Process", "buffer")
        self.add_sidebar_btn(side_layout, "Projection to WGS84", "projection_wgs84")

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
            dialog = PreprocessDialog(mode, self)
            submissions = []
            if hasattr(dialog, 'run_signal'):
                dialog.run_signal.connect(
                    lambda submitted_mode, data: submissions.append(
                        (submitted_mode, data)
                    )
                )
            dialog.exec_()
            if submissions:
                self.api_handle_result(*submissions[-1])
        except NameError:
            print("PreprocessDialog class not found.")
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
        print(f"[Preprocess Logic] Task: {mode} | Data: {data}")
        
        if mode == "workspace":
            self.logic_create_workspace(data)
        elif mode == "buffer":
            self.logic_buffer_process(data)
        elif mode == "projection_wgs84":
            self.logic_projection_wgs84(data)

    # =========================================================================
    # [业务逻辑实现]
    # =========================================================================

    @staticmethod
    def wgs84_output_path(input_path):
        """Return the requested sibling output path with a `_wgs84` suffix."""
        path = Path(input_path)
        return str(path.with_name(f"{path.stem}_wgs84{path.suffix.lower()}"))

    @staticmethod
    def _wgs84_spatial_reference():
        target_srs = osr.SpatialReference()
        target_srs.ImportFromEPSG(4326)
        target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        return target_srs

    @classmethod
    def _is_wgs84(cls, spatial_reference):
        if spatial_reference is None:
            return False
        candidate = spatial_reference.Clone()
        candidate.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        return bool(candidate.IsSame(cls._wgs84_spatial_reference()))

    @staticmethod
    def _validate_vector_projection(input_path):
        dataset = ogr.Open(input_path, 0)
        if dataset is None:
            raise RuntimeError("Cannot open shapefile.")
        layer = dataset.GetLayer(0)
        if layer is None:
            raise RuntimeError("Shapefile contains no readable layer.")
        if layer.GetSpatialRef() is None:
            raise RuntimeError("Shapefile has no source coordinate system (.prj is missing or invalid).")
        dataset = None

    @staticmethod
    def _validate_raster_projection(input_path):
        dataset = gdal.Open(input_path, gdal.GA_ReadOnly)
        if dataset is None:
            raise RuntimeError("Cannot open raster.")
        if not dataset.GetProjection():
            raise RuntimeError("Raster has no source coordinate system.")
        dataset = None

    @classmethod
    def convert_shapefile_to_wgs84(cls, input_path, output_path, callback=None):
        """Reproject a shapefile and its attributes into an EPSG:4326 sibling dataset."""
        cls._validate_vector_projection(input_path)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=".laketopo_wgs84_", dir=str(output.parent)))
        temp_output = temp_dir / output.name
        try:
            options = gdal.VectorTranslateOptions(
                format="ESRI Shapefile",
                dstSRS="EPSG:4326",
                reproject=True,
                layerName=output.stem,
                layerCreationOptions=["ENCODING=UTF-8"],
                callback=callback,
            )
            result = gdal.VectorTranslate(str(temp_output), input_path, options=options)
            if result is None:
                raise RuntimeError("Vector reprojection was cancelled or failed.")
            result = None

            temp_dataset = ogr.Open(str(temp_output), 0)
            if temp_dataset is None:
                raise RuntimeError("Converted shapefile could not be validated.")
            if not cls._is_wgs84(temp_dataset.GetLayer(0).GetSpatialRef()):
                raise RuntimeError("Converted shapefile is not WGS84 (EPSG:4326).")
            temp_dataset = None

            driver = ogr.GetDriverByName("ESRI Shapefile")
            if output.exists():
                driver.DeleteDataSource(str(output))
            moved = 0
            for component in temp_dir.iterdir():
                if component.stem.lower() == output.stem.lower():
                    os.replace(str(component), str(output.parent / component.name))
                    moved += 1
            if moved == 0 or not output.exists():
                raise RuntimeError("Converted shapefile components were not created.")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @classmethod
    def convert_raster_to_wgs84(cls, input_path, output_path, callback=None):
        """Reproject a GeoTIFF into EPSG:4326 while preserving bands and NoData."""
        cls._validate_raster_projection(input_path)
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=".laketopo_wgs84_", dir=str(output.parent)))
        temp_output = temp_dir / output.name
        try:
            options = gdal.WarpOptions(
                format="GTiff",
                dstSRS="EPSG:4326",
                resampleAlg=gdal.GRA_NearestNeighbour,
                multithread=True,
                creationOptions=["TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"],
                callback=callback,
            )
            result = gdal.Warp(str(temp_output), input_path, options=options)
            if result is None:
                raise RuntimeError("Raster reprojection was cancelled or failed.")
            result = None

            check_dataset = gdal.Open(str(temp_output), gdal.GA_ReadOnly)
            if check_dataset is None or not check_dataset.GetProjection():
                raise RuntimeError("Converted raster could not be validated.")
            check_srs = osr.SpatialReference()
            check_srs.ImportFromWkt(check_dataset.GetProjection())
            if not cls._is_wgs84(check_srs):
                raise RuntimeError("Converted raster is not WGS84 (EPSG:4326).")
            check_dataset = None
            os.replace(str(temp_output), str(output))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def logic_projection_wgs84(self, data):
        """Batch reproject selected SHP/TIF files to EPSG:4326 beside each source."""
        raw_files = data.get('input_files', [])
        if isinstance(raw_files, str):
            raw_files = [raw_files] if raw_files.strip() else []

        input_files = []
        seen = set()
        for raw_path in raw_files:
            normalized = os.path.normpath(str(raw_path).strip())
            key = os.path.normcase(os.path.abspath(normalized))
            if normalized and key not in seen:
                input_files.append(normalized)
                seen.add(key)

        if not input_files:
            QMessageBox.warning(self, "Error", "Please select at least one SHP or TIF file.")
            return

        unsupported = [
            path for path in input_files
            if Path(path).suffix.lower() not in {".shp", ".tif", ".tiff"}
        ]
        if unsupported:
            QMessageBox.warning(
                self,
                "Unsupported Files",
                "Only .shp, .tif, and .tiff files are supported:\n" + "\n".join(unsupported),
            )
            return

        self._start_projection_task(input_files)

    def _start_projection_task(self, input_files):
        if self._projection_thread is not None and self._projection_thread.isRunning():
            QMessageBox.information(
                self,
                "Processing",
                "A batch projection task is already running.",
            )
            return

        self._projection_outcome = None
        self._projection_progress = QProgressDialog(
            "Preparing projection conversion…", "Cancel", 0, 100, self.window()
        )
        self._projection_progress.setWindowTitle("Batch Projection to WGS84")
        self._projection_progress.setWindowModality(Qt.WindowModal)
        self._projection_progress.setAutoClose(False)
        self._projection_progress.setAutoReset(False)
        self._projection_progress.setMinimumDuration(0)
        self._projection_progress.setMinimumWidth(500)
        self._projection_progress.setValue(0)

        self._projection_thread = QThread(self)
        self._projection_worker = ProjectionWorker(input_files, type(self))
        self._projection_worker.moveToThread(self._projection_thread)
        self._projection_thread.started.connect(self._projection_worker.run)
        self._projection_worker.progress.connect(self._update_projection_progress)
        self._projection_worker.finished.connect(self._queue_projection_result)
        self._projection_worker.failed.connect(self._queue_projection_failure)
        self._projection_worker.finished.connect(self._projection_worker.deleteLater)
        self._projection_worker.failed.connect(self._projection_worker.deleteLater)
        self._projection_worker.finished.connect(self._projection_thread.quit)
        self._projection_worker.failed.connect(self._projection_thread.quit)
        self._projection_thread.finished.connect(self._on_projection_thread_finished)
        self._projection_progress.canceled.connect(self.cancel_projection_task)
        self._projection_thread.start()

    def _update_projection_progress(self, value, message):
        if self._projection_progress is not None:
            self._projection_progress.setLabelText(str(message))
            self._projection_progress.setValue(max(0, min(100, int(value))))

    def cancel_projection_task(self):
        if self._projection_thread is not None and self._projection_thread.isRunning():
            self._projection_thread.requestInterruption()
            if self._projection_progress is not None:
                self._projection_progress.setLabelText(
                    "Cancelling after the current GDAL operation…"
                )
                self._projection_progress.setCancelButton(None)

    def _queue_projection_result(self, result):
        self._projection_outcome = ("result", result)
        if self._projection_progress is not None:
            self._projection_progress.setLabelText("Finalizing projection results…")
            if not result.get("cancelled"):
                self._projection_progress.setValue(100)

    def _queue_projection_failure(self, message):
        self._projection_outcome = ("failure", str(message))
        if self._projection_progress is not None:
            self._projection_progress.setLabelText("Finalizing projection failure…")

    def _close_projection_progress(self):
        if self._projection_progress is not None:
            self._projection_progress.close()
            self._projection_progress.deleteLater()
            self._projection_progress = None

    @staticmethod
    def _projection_summary(result):
        succeeded = list(result.get("succeeded", []))
        failures = list(result.get("failed", []))
        cancelled = bool(result.get("cancelled", False))
        total = int(result.get("total", len(succeeded) + len(failures)))
        summary = [
            f"Converted: {len(succeeded)}/{total}",
            "Target CRS: WGS84 (EPSG:4326)",
        ]
        if succeeded:
            summary.append("\nOutputs:\n" + "\n".join(succeeded))
        if failures:
            failure_lines = [f"{path}: {message}" for path, message in failures]
            summary.append("\nFailed:\n" + "\n".join(failure_lines))
        if cancelled:
            summary.append("\nThe remaining files were cancelled.")
        return "\n".join(summary)

    def _on_projection_thread_finished(self):
        """Dispose worker/thread objects before entering a modal result dialog."""
        thread = self._projection_thread
        outcome = self._projection_outcome

        self._close_projection_progress()
        self._projection_worker = None
        self._projection_thread = None
        self._projection_outcome = None
        if thread is not None:
            thread.deleteLater()

        if outcome is None:
            return
        status, payload = outcome
        if status == "failure":
            QMessageBox.critical(
                self,
                "Projection Conversion Error",
                f"Batch projection failed: {payload}",
            )
            return

        result = payload
        self.last_projection_results = {
            "succeeded": list(result.get("succeeded", [])),
            "failed": list(result.get("failed", [])),
            "cancelled": bool(result.get("cancelled", False)),
        }
        message = self._projection_summary(result)
        if result.get("failed") or result.get("cancelled"):
            QMessageBox.warning(self, "Projection Conversion Result", message)
        else:
            QMessageBox.information(self, "Success", message)

    def shutdown(self):
        """Cancel and join a projection worker before the page is destroyed."""
        if self._projection_thread is not None and self._projection_thread.isRunning():
            self._projection_thread.requestInterruption()
            self._projection_thread.quit()
            self._projection_thread.wait()
        self._projection_outcome = None
        self._close_projection_progress()

    def logic_create_workspace(self, data):
        """
        创建或读取工作空间目录结构
        Data Keys: 'ws_path'
        """
        path = data.get('ws_path', '').strip()
        if not path:
            QMessageBox.warning(self, "Error", "Please select a workspace path.")
            return

        try:
            existed = os.path.isdir(path)
            if os.path.exists(path) and not existed:
                QMessageBox.warning(self, "Error", "Workspace path must be a directory.")
                return

            os.makedirs(path, exist_ok=True)
            for sub in ("out", "MLData", "temp_ML"):
                os.makedirs(os.path.join(path, sub), exist_ok=True)

            self.workspace_dir = os.path.normpath(path) # 保存到类变量中
            action = "loaded" if existed else "created"
            QMessageBox.information(self, "Success", f"Workspace {action} at:\n{self.workspace_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    @classmethod
    def create_wgs84_shoreline(cls, input_shp, output_shp):
        """Convert polygon boundaries, including PolygonZ, to a WGS84 shoreline."""
        cls._validate_vector_projection(input_shp)
        driver = ogr.GetDriverByName("ESRI Shapefile")
        if driver is None:
            raise RuntimeError("ESRI Shapefile driver is unavailable.")

        input_dataset = driver.Open(input_shp, 0)
        if input_dataset is None:
            raise RuntimeError("Cannot open lake polygon shapefile.")
        input_layer = input_dataset.GetLayer(0)
        if input_layer is None:
            input_dataset = None
            raise RuntimeError("Lake shapefile contains no readable layer.")

        source_srs = input_layer.GetSpatialRef()
        if source_srs is None:
            input_dataset = None
            raise RuntimeError(
                "Lake shapefile has no source coordinate system (.prj is missing or invalid)."
            )
        source_srs = source_srs.Clone()
        source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        target_srs = cls._wgs84_spatial_reference()
        coordinate_transform = None
        if not source_srs.IsSame(target_srs):
            coordinate_transform = osr.CoordinateTransformation(source_srs, target_srs)

        output = Path(output_shp)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=".laketopo_shoreline_", dir=str(output.parent)))
        temp_output = temp_dir / output.name
        output_dataset = None

        try:
            output_dataset = driver.CreateDataSource(str(temp_output))
            if output_dataset is None:
                raise RuntimeError("Cannot create the shoreline shapefile.")
            output_layer = output_dataset.CreateLayer(
                output.stem,
                srs=target_srs,
                geom_type=ogr.wkbMultiLineString,
                options=["ENCODING=UTF-8"],
            )
            if output_layer is None:
                raise RuntimeError("Cannot create the shoreline layer.")

            polygon_count = 0
            written_count = 0
            for input_feature in input_layer:
                geometry = input_feature.GetGeometryRef()
                if geometry is None or geometry.IsEmpty():
                    continue
                flat_type = ogr.GT_Flatten(geometry.GetGeometryType())
                if flat_type not in (ogr.wkbPolygon, ogr.wkbMultiPolygon):
                    continue

                polygon_count += 1
                shoreline = geometry.GetBoundary()
                if shoreline is None or shoreline.IsEmpty():
                    continue
                if coordinate_transform is not None and shoreline.Transform(coordinate_transform) != 0:
                    raise RuntimeError(
                        f"Failed to transform polygon feature {input_feature.GetFID()} to WGS84."
                    )
                shoreline.FlattenTo2D()

                shoreline_type = ogr.GT_Flatten(shoreline.GetGeometryType())
                if shoreline_type == ogr.wkbLineString:
                    multiline = ogr.Geometry(ogr.wkbMultiLineString)
                    multiline.AddGeometry(shoreline)
                    shoreline = multiline
                elif shoreline_type != ogr.wkbMultiLineString:
                    raise RuntimeError(
                        f"Unsupported polygon boundary geometry: {shoreline.GetGeometryName()}"
                    )

                min_x, max_x, min_y, max_y = shoreline.GetEnvelope()
                coordinates = (min_x, max_x, min_y, max_y)
                if not all(math.isfinite(value) for value in coordinates):
                    raise RuntimeError("WGS84 shoreline contains invalid coordinates.")
                if min_x < -180.000001 or max_x > 180.000001 or min_y < -90.000001 or max_y > 90.000001:
                    raise RuntimeError(
                        "Transformed shoreline is outside the valid WGS84 longitude/latitude range. "
                        "Check the input shapefile projection definition."
                    )

                output_feature = ogr.Feature(output_layer.GetLayerDefn())
                output_feature.SetGeometry(shoreline)
                create_result = output_layer.CreateFeature(output_feature)
                output_feature = None
                if create_result != ogr.OGRERR_NONE:
                    raise RuntimeError(
                        f"Failed to write shoreline feature {input_feature.GetFID()}."
                    )
                written_count += 1

            if polygon_count == 0:
                raise RuntimeError(
                    "The input shapefile contains no Polygon, MultiPolygon, PolygonZ, "
                    "or MultiPolygonZ features."
                )
            if written_count == 0:
                raise RuntimeError("No valid shoreline features were generated.")

            output_layer.SyncToDisk()
            output_dataset = None
            input_dataset = None

            check_dataset = ogr.Open(str(temp_output), 0)
            if check_dataset is None:
                raise RuntimeError("Generated shoreline could not be validated.")
            check_layer = check_dataset.GetLayer(0)
            if check_layer is None or check_layer.GetFeatureCount() != written_count:
                check_dataset = None
                raise RuntimeError("Generated shoreline feature count is invalid.")
            if not cls._is_wgs84(check_layer.GetSpatialRef()):
                check_dataset = None
                raise RuntimeError("Generated shoreline is not WGS84 (EPSG:4326).")
            check_dataset = None

            if output.exists():
                driver.DeleteDataSource(str(output))
            moved_count = 0
            for component in temp_dir.iterdir():
                if component.stem.lower() == output.stem.lower():
                    os.replace(str(component), str(output.parent / component.name))
                    moved_count += 1
            if moved_count == 0 or not output.exists():
                raise RuntimeError("Shoreline shapefile components were not created.")
            return written_count
        finally:
            output_dataset = None
            input_dataset = None
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def create_lake_extent_raster(reference_raster, lake_shp, output_path):
        """Rasterize the lake polygon to a 1/NoData mask aligned to a reference DEM."""
        raster_dataset = gdal.Open(reference_raster, gdal.GA_ReadOnly)
        if raster_dataset is None:
            raise RuntimeError("Cannot open the buffered DEM used for the lake extent.")
        if not raster_dataset.GetProjection():
            raster_dataset = None
            raise RuntimeError("The buffered DEM has no coordinate system.")

        vector_dataset = ogr.Open(lake_shp, 0)
        if vector_dataset is None:
            raster_dataset = None
            raise RuntimeError("Cannot open the lake polygon used for the lake extent.")
        lake_layer = vector_dataset.GetLayer(0)
        if lake_layer is None:
            vector_dataset = None
            raster_dataset = None
            raise RuntimeError("Lake shapefile contains no readable layer.")

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=".laketopo_extent_", dir=str(output.parent)))
        temp_output = temp_dir / output.name
        output_dataset = None
        try:
            output_dataset = gdal.GetDriverByName("GTiff").Create(
                str(temp_output),
                raster_dataset.RasterXSize,
                raster_dataset.RasterYSize,
                1,
                gdal.GDT_Byte,
                options=["TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"],
            )
            if output_dataset is None:
                raise RuntimeError("Cannot create the lake extent raster.")
            output_dataset.SetGeoTransform(raster_dataset.GetGeoTransform())
            output_dataset.SetProjection(raster_dataset.GetProjection())
            output_band = output_dataset.GetRasterBand(1)
            output_band.SetNoDataValue(0)
            output_band.Fill(0)

            rasterize_result = gdal.RasterizeLayer(
                output_dataset, [1], lake_layer, burn_values=[1]
            )
            if rasterize_result != gdal.CE_None:
                raise RuntimeError("Failed to rasterize the lake polygon.")
            output_band.FlushCache()

            contains_lake = False
            block_height = min(1024, output_dataset.RasterYSize)
            for y_offset in range(0, output_dataset.RasterYSize, block_height):
                rows = min(block_height, output_dataset.RasterYSize - y_offset)
                values = output_band.ReadAsArray(0, y_offset, output_dataset.RasterXSize, rows)
                if values is not None and values.max() == 1:
                    contains_lake = True
                    break
            if not contains_lake:
                raise RuntimeError(
                    "Lake extent raster contains no lake pixels. Check the input projections and overlap."
                )

            output_dataset = None
            vector_dataset = None
            raster_dataset = None
            os.replace(str(temp_output), str(output))
        finally:
            output_dataset = None
            vector_dataset = None
            raster_dataset = None
            shutil.rmtree(temp_dir, ignore_errors=True)

    def resolve_vector_buffer_distance(self, layer, buffer_distance_meters):
        srs = layer.GetSpatialRef()
        if srs is None:
            return buffer_distance_meters

        if srs.IsGeographic():
            extent = layer.GetExtent()
            center_lat = (extent[2] + extent[3]) / 2.0
            return self.meters_to_degree_distance(buffer_distance_meters, center_lat)

        linear_units = srs.GetLinearUnits() or 1.0
        return buffer_distance_meters / linear_units

    def meters_to_degree_distance(self, meters, latitude):
        lat_rad = math.radians(latitude)
        meters_per_degree_lat = (
            111132.92
            - 559.82 * math.cos(2 * lat_rad)
            + 1.175 * math.cos(4 * lat_rad)
            - 0.0023 * math.cos(6 * lat_rad)
        )
        if meters_per_degree_lat <= 0:
            meters_per_degree_lat = 111320.0
        return meters / meters_per_degree_lat

    def logic_buffer_process(self, data):
        """
        Run the complete preprocessing chain.

        Buffer -> DEM clip -> slope -> lake extent -> WGS84 shoreline.
        Data Keys: 'lake_shp', 'dem_in', 'buffer_dist'
        """
        if not self.workspace_dir:
            QMessageBox.warning(self, "Error", "Please open or create a workspace first.")
            return

        lake_shp = data.get('lake_shp', '')
        dem_in = data.get('dem_in', '')
        try:
            buffer_distance = float(data.get('buffer_dist', '1000').strip())
        except ValueError:
            QMessageBox.warning(self, "Error", "Buffer distance must be a number.")
            return
        if buffer_distance <= 0:
            QMessageBox.warning(self, "Error", "Buffer distance must be greater than zero.")
            return

        if not os.path.isfile(lake_shp) or not os.path.isfile(dem_in):
            QMessageBox.warning(self, "Error", "Input files are missing.")
            return
        ok, message = cf.check_spatial_references_match([lake_shp, dem_in])
        if not ok:
            QMessageBox.warning(self, "Projection Mismatch", message)
            return

        base = os.path.basename(os.path.normpath(self.workspace_dir))
        buffer_output = os.path.join(self.workspace_dir, f"{base}_buffer.shp")
        dem_output = os.path.join(self.workspace_dir, f"{base}_merit.tif")
        slope_output = os.path.join(self.workspace_dir, f"{base}_slope.tif")
        extent_output = os.path.join(self.workspace_dir, f"{base}_extent.tif")
        shoreline_output = os.path.join(self.workspace_dir, "shoreline.shp")

        try:
            # 1. Buffer the lake in the source CRS so it remains aligned with the DEM.
            driver = ogr.GetDriverByName('ESRI Shapefile')
            input_dataset = driver.Open(lake_shp, 0)
            if input_dataset is None:
                raise RuntimeError("Cannot open lake shapefile.")
            input_layer = input_dataset.GetLayer(0)
            if input_layer is None or input_layer.GetSpatialRef() is None:
                raise RuntimeError("Lake shapefile has no readable layer or projection.")
            buffer_distance_units = self.resolve_vector_buffer_distance(
                input_layer, buffer_distance
            )

            if os.path.exists(buffer_output):
                driver.DeleteDataSource(buffer_output)
            output_dataset = driver.CreateDataSource(buffer_output)
            if output_dataset is None:
                raise RuntimeError("Cannot create buffer shapefile.")
            output_layer = output_dataset.CreateLayer(
                'buffer', input_layer.GetSpatialRef(), ogr.wkbPolygon
            )
            if output_layer is None:
                raise RuntimeError("Cannot create buffer layer.")

            input_definition = input_layer.GetLayerDefn()
            for field_index in range(input_definition.GetFieldCount()):
                output_layer.CreateField(input_definition.GetFieldDefn(field_index))

            buffer_count = 0
            for input_feature in input_layer:
                geometry = input_feature.GetGeometryRef()
                if geometry is None or geometry.IsEmpty():
                    continue
                flat_type = ogr.GT_Flatten(geometry.GetGeometryType())
                if flat_type not in (ogr.wkbPolygon, ogr.wkbMultiPolygon):
                    continue
                buffered_geometry = geometry.Buffer(buffer_distance_units)
                if buffered_geometry is None or buffered_geometry.IsEmpty():
                    continue

                output_feature = ogr.Feature(output_layer.GetLayerDefn())
                output_feature.SetGeometry(buffered_geometry)
                for field_index in range(input_definition.GetFieldCount()):
                    output_feature.SetField(field_index, input_feature.GetField(field_index))
                create_result = output_layer.CreateFeature(output_feature)
                output_feature = None
                if create_result != ogr.OGRERR_NONE:
                    raise RuntimeError(
                        f"Failed to write buffer feature {input_feature.GetFID()}."
                    )
                buffer_count += 1

            if buffer_count == 0:
                raise RuntimeError("No polygon features were available for buffering.")
            output_layer.SyncToDisk()
            output_dataset = None
            input_dataset = None

            # 2. Clip the DEM to the buffer and keep this grid for all raster products.
            clipped_dataset = gdal.Warp(
                dem_output,
                dem_in,
                cutlineDSName=buffer_output,
                cropToCutline=True,
                dstNodata=0,
                creationOptions=["TILED=YES", "COMPRESS=DEFLATE", "BIGTIFF=IF_SAFER"],
            )
            if clipped_dataset is None:
                raise RuntimeError("DEM clipping failed.")
            clipped_dataset = None

            # 3. Calculate slope from the clipped DEM.
            slope_dataset = gdal.DEMProcessing(
                slope_output, dem_output, 'slope', computeEdges=True
            )
            if slope_dataset is None:
                raise RuntimeError("Slope generation failed.")
            slope_dataset = None

            # 4. Generate the lake mask on the exact buffered-DEM grid.
            self.create_lake_extent_raster(dem_output, lake_shp, extent_output)

            # 5. Extract Polygon/PolygonZ boundaries and explicitly reproject to WGS84.
            shoreline_count = self.create_wgs84_shoreline(
                lake_shp, shoreline_output
            )

            QMessageBox.information(
                self,
                "Success",
                "Buffer full process completed.\n"
                f"Buffer: {buffer_distance:g} m\n"
                f"Shoreline features: {shoreline_count}\n"
                "Shoreline CRS: WGS84 (EPSG:4326)\n\n"
                "Outputs:\n"
                f"{buffer_output}\n"
                f"{dem_output}\n"
                f"{slope_output}\n"
                f"{extent_output}\n"
                f"{shoreline_output}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
                
