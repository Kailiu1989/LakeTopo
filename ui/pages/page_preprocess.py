import os
import shutil
import math
import tempfile
from pathlib import Path
from osgeo import gdal, ogr, osr, gdalconst
import Common_Function as cf

from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QFrame,
                             QApplication, QScrollArea, QMessageBox, QProgressDialog)
from PyQt5.QtCore import Qt

try:
    from ui.dialogs.preprocess_dialog import PreprocessDialog
except ImportError:
    pass

class PagePreprocess(QWidget):
    def __init__(self):
        super().__init__()
        self.side_buttons = []
        self.workspace_dir = None # 存储当前工作空间路径
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
        self.add_sidebar_btn(side_layout, "Water Extraction", "extraction")
        self.add_sidebar_btn(side_layout, "Shoreline Generation", "shoreline")
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
            if hasattr(dialog, 'run_signal'):
                dialog.run_signal.connect(self.api_handle_result)
            dialog.exec_()
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
        elif mode == "extraction":
            self.logic_water_extraction(data)
        elif mode == "shoreline":
            self.logic_shoreline(data)
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

    def _make_reprojection_callback(self, progress, item_index, item_count, filename):
        def callback(completion, _message, _callback_data):
            percent = int(((item_index + max(0.0, min(1.0, completion))) / item_count) * 100)
            progress.setValue(percent)
            progress.setLabelText(
                f"Converting {item_index + 1}/{item_count}: {filename}\n{int(completion * 100)}%"
            )
            QApplication.processEvents()
            return 0 if progress.wasCanceled() else 1
        return callback

    def convert_shapefile_to_wgs84(self, input_path, output_path, callback=None):
        """Reproject a shapefile and its attributes into an EPSG:4326 sibling dataset."""
        self._validate_vector_projection(input_path)
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
            if not self._is_wgs84(temp_dataset.GetLayer(0).GetSpatialRef()):
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

    def convert_raster_to_wgs84(self, input_path, output_path, callback=None):
        """Reproject a GeoTIFF into EPSG:4326 while preserving bands and NoData."""
        self._validate_raster_projection(input_path)
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
            if not self._is_wgs84(check_srs):
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

        progress = QProgressDialog(
            "Preparing projection conversion…", "Cancel", 0, 100, self.window()
        )
        progress.setWindowTitle("Batch Projection to WGS84")
        progress.setWindowModality(Qt.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        succeeded = []
        failed = []
        cancelled = False
        total = len(input_files)
        for index, input_path in enumerate(input_files):
            QApplication.processEvents()
            if progress.wasCanceled():
                cancelled = True
                break

            output_path = self.wgs84_output_path(input_path)
            callback = self._make_reprojection_callback(
                progress, index, total, os.path.basename(input_path)
            )
            try:
                if not os.path.isfile(input_path):
                    raise RuntimeError("Input file does not exist.")
                if Path(input_path).suffix.lower() == ".shp":
                    self.convert_shapefile_to_wgs84(input_path, output_path, callback)
                else:
                    self.convert_raster_to_wgs84(input_path, output_path, callback)
                succeeded.append(output_path)
            except Exception as exc:
                if progress.wasCanceled():
                    cancelled = True
                    break
                failed.append((input_path, str(exc)))
            progress.setValue(int(((index + 1) / total) * 100))

        progress.close()
        progress.deleteLater()

        summary = [
            f"Converted: {len(succeeded)}/{total}",
            "Target CRS: WGS84 (EPSG:4326)",
        ]
        if succeeded:
            summary.append("\nOutputs:\n" + "\n".join(succeeded))
        if failed:
            failure_lines = [f"{path}: {message}" for path, message in failed]
            summary.append("\nFailed:\n" + "\n".join(failure_lines))
        if cancelled:
            summary.append("\nThe remaining files were cancelled.")

        self.last_projection_results = {
            "succeeded": list(succeeded),
            "failed": list(failed),
            "cancelled": cancelled,
        }

        message = "\n".join(summary)
        if failed or cancelled:
            QMessageBox.warning(self, "Projection Conversion Result", message)
        else:
            QMessageBox.information(self, "Success", message)

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

    def logic_water_extraction(self, data):
        """
        水域栅格提取 (掩膜提取)
        Data Keys: 'raster_in', 'mask_in'
        """
        if not self.workspace_dir:
            QMessageBox.warning(self, "Error", "Please open or create a workspace first.")
            return

        input_raster = data.get('raster_in', '')
        input_mask = data.get('mask_in', '')

        if not os.path.exists(input_raster) or not os.path.exists(input_mask):
            QMessageBox.warning(self, "Error", "Input files do not exist.")
            return
        ok, message = cf.check_spatial_references_match([input_raster, input_mask])
        if not ok:
            QMessageBox.warning(self, "Projection Mismatch", message)
            return

        ws_base = os.path.basename(os.path.normpath(self.workspace_dir))
        output_path = os.path.join(self.workspace_dir, f"{ws_base}_extent.tif")

        try:
            # 1. 打开栅格
            raster_ds = gdal.Open(input_raster, gdal.GA_ReadOnly)
            if not raster_ds: raise Exception("Cannot open raster.")
            
            geo_transform = raster_ds.GetGeoTransform()
            proj = raster_ds.GetProjection()
            band = raster_ds.GetRasterBand(1)
            nodata = band.GetNoDataValue()

            # 2. 打开掩膜
            mask_ds = ogr.Open(input_mask)
            if not mask_ds: raise Exception("Cannot open mask shapefile.")
            mask_layer = mask_ds.GetLayer()

            # 3. 创建输出文件
            driver = gdal.GetDriverByName('GTiff')
            out_ds = driver.Create(output_path, raster_ds.RasterXSize, raster_ds.RasterYSize, 1, band.DataType)
            out_ds.SetGeoTransform(geo_transform)
            out_ds.SetProjection(proj)

            # 4. 栅格化掩膜 (内存中)
            mem_driver = gdal.GetDriverByName('MEM')
            mask_raster = mem_driver.Create('', raster_ds.RasterXSize, raster_ds.RasterYSize, 1, gdal.GDT_Byte)
            mask_raster.SetGeoTransform(geo_transform)
            mask_raster.SetProjection(proj)
            gdal.RasterizeLayer(mask_raster, [1], mask_layer, burn_values=[1])

            # 5. 应用掩膜逻辑
            raster_arr = band.ReadAsArray()
            mask_arr = mask_raster.GetRasterBand(1).ReadAsArray()

            nodata_out = nodata if nodata is not None else -9999
            # 掩膜区域设为1，非掩膜设为 NoData
            raster_arr[mask_arr == 1] = 1
            raster_arr[mask_arr == 0] = nodata_out

            out_band = out_ds.GetRasterBand(1)
            out_band.WriteArray(raster_arr)
            out_band.SetNoDataValue(nodata_out)

            out_ds = None # Save & Close
            QMessageBox.information(self, "Success", f"Extraction completed:\n{output_path}")

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def logic_shoreline(self, data):
        """
        湖岸线生成 (Polygon To Line)
        Data Keys: 'feat_in'
        """
        if not self.workspace_dir:
            QMessageBox.warning(self, "Error", "Please open or create a workspace first.")
            return

        input_shp = data.get('feat_in', '')
        if not os.path.exists(input_shp):
            QMessageBox.warning(self, "Error", "Input file not found.")
            return

        out_dir = os.path.join(self.workspace_dir)
        os.makedirs(out_dir, exist_ok=True)
        output_shp = os.path.join(out_dir, "lakeshoreline.shp")

        try:
            driver = ogr.GetDriverByName("ESRI Shapefile")
            in_ds = driver.Open(input_shp, 0)
            if not in_ds: raise Exception("Cannot open shapefile.")
            in_layer = in_ds.GetLayer()

            output_srs = osr.SpatialReference()
            output_srs.ImportFromEPSG(4326)
            output_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            
            if os.path.exists(output_shp):
                driver.DeleteDataSource(output_shp)
            
            out_ds = driver.CreateDataSource(output_shp)
            out_layer = out_ds.CreateLayer("shoreline", srs=output_srs, geom_type=ogr.wkbMultiLineString)

            # 简单转换：将 Polygon 边界转为 Line
            # (为简化代码，这里使用 OGR 内置方法或简化逻辑)
            for feat in in_layer:
                geom = feat.GetGeometryRef()
                if geom and geom.GetGeometryType() in [ogr.wkbPolygon, ogr.wkbMultiPolygon]:
                    # 将面转为线 (OGR 默认 Boundary)
                    line_geom = geom.GetBoundary()
                    out_feat = ogr.Feature(out_layer.GetLayerDefn())
                    out_feat.SetGeometry(line_geom)
                    out_layer.CreateFeature(out_feat)
            
            out_ds = None
            QMessageBox.information(self, "Success", f"Shoreline created:\n{output_shp}")

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

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
            缓冲区一键处理 (Buffer -> Clip -> Slope)
            Data Keys: 'lake_shp', 'dem_in', 'buffer_dist'
            """
            if not self.workspace_dir:
                QMessageBox.warning(self, "Error", "Please open or create a workspace first.")
                return

            lake_shp = data.get('lake_shp', '')
            dem_in = data.get('dem_in', '')
            
            # 【修复】获取用户输入的距离，如果无效则默认为 1000
            try:
                val_str = data.get('buffer_dist', '1000').strip()
                buffer_distance = float(val_str)
            except ValueError:
                QMessageBox.warning(self, "Error", "Buffer distance must be a number.")
                return

            if not os.path.exists(lake_shp) or not os.path.exists(dem_in):
                QMessageBox.warning(self, "Error", "Input files missing.")
                return
            ok, message = cf.check_spatial_references_match([lake_shp, dem_in])
            if not ok:
                QMessageBox.warning(self, "Projection Mismatch", message)
                return

            base = os.path.basename(os.path.normpath(self.workspace_dir))
            buf_out = os.path.join(self.workspace_dir, f"{base}_buffer.shp")
            dem_out = os.path.join(self.workspace_dir, f"{base}_Merit.tif")
            slope_out = os.path.join(self.workspace_dir, f"{base}_slope.tif")

            try:
                # 1. 创建缓冲区
                driver = ogr.GetDriverByName('ESRI Shapefile')
                in_ds = driver.Open(lake_shp, 0)
                if not in_ds: raise Exception("Cannot open lake shapefile")
                in_lyr = in_ds.GetLayer()
                buffer_distance_units = self.resolve_vector_buffer_distance(in_lyr, buffer_distance)
                
                if os.path.exists(buf_out): driver.DeleteDataSource(buf_out)
                out_ds = driver.CreateDataSource(buf_out)
                out_lyr = out_ds.CreateLayer('buffer', in_lyr.GetSpatialRef(), ogr.wkbPolygon)

                # 复制字段定义
                in_defn = in_lyr.GetLayerDefn()
                for i in range(in_defn.GetFieldCount()):
                    out_lyr.CreateField(in_defn.GetFieldDefn(i))

                for feat in in_lyr:
                    geom = feat.GetGeometryRef()
                    if geom:
                        # 使用与输入矢量坐标单位一致的距离
                        buf_geom = geom.Buffer(buffer_distance_units)
                        
                        out_feat = ogr.Feature(out_lyr.GetLayerDefn())
                        out_feat.SetGeometry(buf_geom)
                        # 复制属性
                        for i in range(in_defn.GetFieldCount()):
                            out_feat.SetField(i, feat.GetField(i))
                        
                        out_lyr.CreateFeature(out_feat)
                
                out_ds = None # Flush Buffer SHP

                # 2. 裁剪 DEM
                gdal.Warp(dem_out, dem_in, cutlineDSName=buf_out, cropToCutline=True, dstNodata=0)

                # 3. 计算坡度
                gdal.DEMProcessing(slope_out, dem_out, 'slope', computeEdges=True)

                QMessageBox.information(self, "Success", f"Buffer process completed.\nBuffer: {buffer_distance}m\nOutput:\n{buf_out}\n{dem_out}\n{slope_out}")

            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
                
