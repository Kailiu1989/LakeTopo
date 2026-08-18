import os
import shutil
import math
import numpy as np
from osgeo import gdal, ogr, osr, gdalconst
import Common_Function as cf

from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QFrame, QApplication, QScrollArea, QMessageBox)
from PyQt5.QtCore import Qt

# 引入您原有的业务逻辑模块 (请确保这些文件存在)
try:
    import A_PredictedPoints_Gen as mainFunc
    import B_Depth_Prediction as PredictFunc
    import dem_builder as DEMFunc
except ImportError as e:
    print(f"Warning: Failed to import backend modules: {e}")

try:
    from ui.dialogs.bathymetry_dialog import BathymetryDialog
except ImportError:
    pass

class PageBathymetry(QWidget):
    def __init__(self):
        super().__init__()
        self.side_buttons = []
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
            dialog = BathymetryDialog(mode, self)
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
            QMessageBox.critical(self, "Execution Error", str(e))

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
            p5 = int(data['cell_size'])
            p6 = data.get('dem_path', '').strip()
            p7 = data.get('survey_path', '').strip()

            if p6 and not os.path.exists(p6):
                QMessageBox.warning(self, "Error", "Input DEM file not found.")
                return
            if p7 and not os.path.exists(p7):
                QMessageBox.warning(self, "Error", "In-situ bath points file not found.")
                return
            ok, message = cf.check_spatial_references_match([p for p in (p6, p7) if p])
            if not ok:
                QMessageBox.warning(self, "Projection Mismatch", message)
                return
            
            QMessageBox.information(self, "Processing", "Starting prediction points generation...")
            mainFunc.runPredictedPoints(p1, p2, p3, p4, p5, p6 or None, p7 or None)
            QMessageBox.information(self, "Success", "Task Completed!")
        except Exception as e:
            raise Exception(f"Prediction points failed: {e}")

    def logic_pred_depth(self, data):
        """生成预测点深度"""
        try:
            p1 = data['work_path']
            p2 = data.get('lake_name') or os.path.basename(os.path.normpath(p1))
            p3 = int(data['interval'])
            p4 = int(data['win_size'])
            p5 = int(data['cell_size'])
            model_name = data.get('model', 'XGBoost')
            
            QMessageBox.information(
                self, "Processing", f"Starting depth prediction with {model_name}..."
            )
            mae = PredictFunc.runMLProcessing(p1, p2, p3, p4, p5, model_name)
            QMessageBox.information(
                self,
                "Success",
                f"Task Completed!\nModel: {model_name}\nHoldout MAE: {mae:.4f}",
            )
        except Exception as e:
            raise Exception(f"Depth prediction failed: {e}")

    def logic_terrain(self, data):
        """水下地形生成"""
        try:
            p1 = data['depth_shp']
            p2 = data['z_field']
            p3 = data['breakline']
            p4 = data['polygon']
            p5 = data['out_dem']
            p6 = data['resolution']
            ok, message = cf.check_spatial_references_match([p1, p3, p4])
            if not ok:
                QMessageBox.warning(self, "Projection Mismatch", message)
                return
            
            QMessageBox.information(self, "Processing", "Starting DEM construction...")
            DEMFunc.runLakeDEM(p1, p2, p3, p4, p5, p6)
            QMessageBox.information(self, "Success", "DEM Generated successfully!")
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
            QMessageBox.warning(self, "Error", "Depth raster and Output path are required.")
            return

        base_elev = 0.0
        if manual_elev:
            base_elev = float(manual_elev)
        elif lake_shp and surround_dem:
            ok, message = cf.check_spatial_references_match([lake_shp, surround_dem])
            if not ok:
                QMessageBox.warning(self, "Projection Mismatch", message)
                return
            base_elev = self.calculate_shore_elevation(lake_shp, surround_dem)
            print(f"Auto-calculated base elevation: {base_elev}")
        else:
            QMessageBox.warning(self, "Error", "Provide Base Elevation OR Lake Polygon + Surrounding DEM.")
            return

        # 执行栅格运算: Elevation = Base - Depth
        ds = gdal.Open(depth_raster, gdal.GA_ReadOnly)
        if not ds: raise Exception("Cannot open depth raster.")
        
        driver = gdal.GetDriverByName('GTiff')
        out_ds = driver.CreateCopy(out_raster, ds, 0)
        band = out_ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        
        # 逐块处理或整体处理（此处假设内存够，整体处理）
        arr = band.ReadAsArray()
        
        # 处理有效值
        if nodata is not None:
            mask = (arr != nodata)
            arr[mask] = base_elev - arr[mask]
        else:
            arr = base_elev - arr
            
        band.WriteArray(arr)
        out_ds = None # Save
        QMessageBox.information(self, "Success", f"Elevation adjustment done.\nBase Level: {base_elev:.2f}m")

    def logic_mosaic(self, data):
        """DEM 镶嵌"""
        lake_dem = data.get('lake_dem')
        mosaic_dem = data.get('mosaic_dem')
        pixel_size = float(data.get('cell_size', 10))
        output = data.get('out_raster')
        operator = data.get('operator', 'First')

        if not os.path.exists(lake_dem) or not os.path.exists(mosaic_dem):
            QMessageBox.warning(self, "Error", "Input DEMs not found.")
            return

        # 映射 Operator
        # "First", "Maximum", "Minimum", "Mean"
        ok, message = cf.check_spatial_references_match([lake_dem, mosaic_dem])
        if not ok:
            QMessageBox.warning(self, "Projection Mismatch", message)
            return

        alg_map = {
            "First": None, # Default
            "Maximum": "MAX",
            "Minimum": "MIN",
            "Mean": "AVERAGE"
        }
        alg = alg_map.get(operator)

        warp_options = ["NUM_THREADS=ALL_CPUS"]
        if alg:
            warp_options.append(f"MERGE_ALG={alg}")

        # 获取 NodData
        ds = gdal.Open(lake_dem)
        nodata = ds.GetRasterBand(1).GetNoDataValue()
        dtype = ds.GetRasterBand(1).DataType
        x_res, y_res = self.resolve_raster_resolution(ds, pixel_size)
        ds = None

        options = gdal.WarpOptions(
            format="GTiff",
            xRes=x_res, yRes=y_res,
            srcNodata=nodata, dstNodata=nodata,
            outputType=dtype,
            warpOptions=warp_options,
            resampleAlg=gdalconst.GRA_NearestNeighbour
        )

        gdal.Warp(output, [lake_dem, mosaic_dem], options=options)
        QMessageBox.information(self, "Success", "Mosaic completed.")

    # ------------------ 辅助函数 ------------------
    def resolve_raster_resolution(self, raster_ds, resolution_meters):
        srs = osr.SpatialReference()
        projection = raster_ds.GetProjection()
        if projection:
            srs.ImportFromWkt(projection)
        else:
            return resolution_meters, resolution_meters

        if srs.IsGeographic():
            latitude = self.get_raster_center_y(raster_ds)
            return self.meters_to_degree_resolution_xy(resolution_meters, latitude)

        linear_units = srs.GetLinearUnits() or 1.0
        resolution_units = resolution_meters / linear_units
        return resolution_units, resolution_units

    def get_raster_center_y(self, raster_ds):
        gt = raster_ds.GetGeoTransform()
        return gt[3] + gt[4] * (raster_ds.RasterXSize / 2.0) + gt[5] * (raster_ds.RasterYSize / 2.0)

    def meters_to_degree_resolution_xy(self, meters, latitude):
        lat_rad = math.radians(latitude)
        meters_per_degree_lat = (
            111132.92
            - 559.82 * math.cos(2 * lat_rad)
            + 1.175 * math.cos(4 * lat_rad)
            - 0.0023 * math.cos(6 * lat_rad)
        )
        meters_per_degree_lon = (
            111412.84 * math.cos(lat_rad)
            - 93.5 * math.cos(3 * lat_rad)
            + 0.118 * math.cos(5 * lat_rad)
        )
        if meters_per_degree_lat <= 0:
            meters_per_degree_lat = 111320.0
        if abs(meters_per_degree_lon) <= 0.000001:
            meters_per_degree_lon = meters_per_degree_lat
        return meters / abs(meters_per_degree_lon), meters / meters_per_degree_lat

    def calculate_shore_elevation(self, lake_shapefile, raster_path):
        """计算湖岸线平均高程"""
        temp_dir = os.path.join(os.path.dirname(raster_path), "lake_temp_elev")
        try:
            os.makedirs(temp_dir, exist_ok=True)
            ds_shp = ogr.Open(lake_shapefile)
            ds_ras = gdal.Open(raster_path)
            if not ds_shp or not ds_ras: raise Exception("Invalid input files")

            gt = ds_ras.GetGeoTransform()
            band = ds_ras.GetRasterBand(1)
            layer = ds_shp.GetLayer()
            
            elevs = []
            for feat in layer:
                geom = feat.GetGeometryRef()
                if geom:
                    # 简化：取外边界点
                    ring = geom.GetGeometryRef(0) 
                    for i in range(ring.GetPointCount()):
                        mx, my = ring.GetX(i), ring.GetY(i)
                        px = int((mx - gt[0]) / gt[1])
                        py = int((my - gt[3]) / gt[5])
                        try:
                            val = band.ReadAsArray(px, py, 1, 1)[0, 0]
                            if val != band.GetNoDataValue():
                                elevs.append(val)
                        except: pass
            
            if elevs: return np.mean(elevs)
            else: raise Exception("No valid elevation found on shoreline.")

        except Exception as e:
            raise e
        finally:
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
