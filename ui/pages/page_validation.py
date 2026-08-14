import os
import numpy as np
import pandas as pd
from osgeo import gdal, ogr
import Common_Function as cf

from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QFrame, QApplication, QScrollArea, QMessageBox)
from PyQt5.QtCore import Qt

# 引入您原有的业务逻辑模块
try:
    import B_Depth_Prediction2 as PredictFunc2
except ImportError:
    print("Warning: B_Depth_Prediction2 module not found. 'Prediction Accuracy' function will not work.")

try:
    from ui.dialogs.validation_dialog import ValidationDialog
except ImportError:
    pass

class PageValidation(QWidget):
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

        # --- 添加功能按钮 ---
        self.add_sidebar_btn(side_layout, "Prediction Accuracy", "accuracy")
        self.add_sidebar_btn(side_layout, "Depth Line Check", "check")

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
            dialog = ValidationDialog(mode, self)
            if hasattr(dialog, 'run_signal'):
                dialog.run_signal.connect(self.api_handle_result)
            dialog.exec_()
        except NameError:
            print("ValidationDialog class not found.")
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
        print(f"[Validation Logic] Task: {mode} | Data: {data}")
        
        if mode == "accuracy":
            self.logic_prediction_accuracy(data)
        elif mode == "check":
            self.logic_depth_line_check(data)

    # =========================================================================
    # [业务逻辑实现]
    # =========================================================================

    def logic_prediction_accuracy(self, data):
        """
        [业务逻辑] 预测点精度验证
        调用 B_Depth_Prediction2.runMLProcessing
        Data Keys: 'work_path', 'interval'
        """
        try:
            # 1. 提取参数
            work_path = data.get('work_path', '')
            lake_name = data.get('lake_name') or os.path.basename(os.path.normpath(work_path))
            interval_str = data.get('interval', '5')
            
            if not work_path:
                QMessageBox.warning(self, "Error", "Workspace path is required.")
                return
            
            try:
                interval = int(interval_str)
            except ValueError:
                QMessageBox.warning(self, "Error", "Interval must be an integer.")
                return

            # 2. 调用外部计算模块
            # 注意：需确保 PredictFunc2 已正确导入
            QMessageBox.information(self, "Processing", "Starting accuracy validation (ML model)...")
            
            # 这里调用您原代码中的逻辑
            workspace_dir = os.path.normpath(work_path)
            acc_csv = os.path.join(workspace_dir, "acc_result.csv")
            acc_pic = os.path.join(workspace_dir, "acc_pic.jpg")

            mae, r2 = PredictFunc2.runMLProcessing(work_path, lake_name, interval, acc_pic)
            
            # 3. 显示结果
            msg = f"Validation Completed!\n\nMAE: {mae}\nR²: {r2}"
            results_df = pd.DataFrame({'MAE': [mae], 'R²': [r2]})
            results_df.to_csv(acc_csv, index=False, encoding='utf-8-sig')
            msg = f"{msg}\n\nResults saved to:\n{acc_csv}\n{acc_pic}"
            QMessageBox.information(self, "Success", msg)

            # 4. 询问是否保存结果 (原代码逻辑)
            results_df = pd.DataFrame({'MAE': [mae], 'R²': [r2]})

        except NameError:
            QMessageBox.critical(self, "System Error", "Module 'B_Depth_Prediction2' not loaded.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Processing failed: {str(e)}")

    def get_inverse_geotransform(self, geotransform):
        inv_gt = gdal.InvGeoTransform(geotransform)
        if inv_gt is None:
            raise Exception("Invalid raster geotransform.")
        if isinstance(inv_gt, tuple) and len(inv_gt) == 2 and isinstance(inv_gt[0], int):
            if not inv_gt[0]:
                raise Exception("Invalid raster geotransform.")
            return inv_gt[1]
        return inv_gt

    def sample_raster_value(self, band, inv_gt, x, y, nodata):
        px = int(inv_gt[0] + inv_gt[1] * x + inv_gt[2] * y)
        py = int(inv_gt[3] + inv_gt[4] * x + inv_gt[5] * y)
        if px < 0 or py < 0 or px >= band.XSize or py >= band.YSize:
            return None

        arr = band.ReadAsArray(px, py, 1, 1)
        if arr is None:
            return None

        value = float(arr[0, 0])
        if nodata is not None and value == nodata:
            return None
        return value

    def logic_depth_line_check(self, data):
        """
        [业务逻辑] 测深线检查 (栅格与矢量点对比)
        Data Keys: 'check_line', 'input_raster', 'output_txt'
        """
        point_shp = data.get('check_line', '')
        input_raster = data.get('input_raster', '')
        surface_dem = data.get('surface_dem', '')
        depth_field = data.get('depth_field', '').strip()
        output_txt = data.get('output_txt', '')

        # 检查文件是否存在
        if not os.path.exists(point_shp) or not os.path.exists(input_raster) or not os.path.exists(surface_dem):
            QMessageBox.warning(self, "Error", "Input files (SHP or Raster) not found.")
            return
        ok, message = cf.check_spatial_references_match([point_shp, input_raster, surface_dem])
        if not ok:
            QMessageBox.warning(self, "Projection Mismatch", message)
            return
        
        if not output_txt:
            QMessageBox.warning(self, "Error", "Output TXT path is required.")
            return
        if not depth_field:
            QMessageBox.warning(self, "Error", "Depth field is required.")
            return

        try:
            pred_ds = gdal.Open(input_raster)
            surface_ds = gdal.Open(surface_dem)
            if not pred_ds:
                raise Exception("Cannot open predicted DEM.")
            if not surface_ds:
                raise Exception("Cannot open surface DEM.")

            pred_band = pred_ds.GetRasterBand(1)
            surface_band = surface_ds.GetRasterBand(1)
            pred_inv_gt = self.get_inverse_geotransform(pred_ds.GetGeoTransform())
            surface_inv_gt = self.get_inverse_geotransform(surface_ds.GetGeoTransform())
            pred_nodata = pred_band.GetNoDataValue()
            surface_nodata = surface_band.GetNoDataValue()

            shp_ds = ogr.Open(point_shp)
            if not shp_ds:
                raise Exception("Cannot open shapefile.")
            shp_layer = shp_ds.GetLayer()
            layer_defn = shp_layer.GetLayerDefn()
            if layer_defn.GetFieldIndex(depth_field) < 0:
                raise Exception(f"Depth field not found: {depth_field}")

            diffs = []
            for feature in shp_layer:
                geom = feature.GetGeometryRef()
                if not geom:
                    continue
                geom_type = geom.GetGeometryType()
                if geom_type not in (ogr.wkbPoint, ogr.wkbPoint25D):
                    continue

                depth_value = feature.GetField(depth_field)
                if depth_value is None:
                    continue

                x, y = geom.GetX(), geom.GetY()
                pred_value = self.sample_raster_value(pred_band, pred_inv_gt, x, y, pred_nodata)
                surface_value = self.sample_raster_value(surface_band, surface_inv_gt, x, y, surface_nodata)
                if pred_value is None or surface_value is None:
                    continue

                observed_bed = float(surface_value) - float(depth_value)
                diffs.append(float(pred_value) - observed_bed)

            if not diffs:
                raise Exception("No valid point/raster overlap found.")

            diff_arr = np.array(diffs, dtype=np.float64)
            max_diff = float(np.max(diff_arr))
            min_diff = float(np.min(diff_arr))
            mean_diff = float(np.mean(diff_arr))
            mae = float(np.mean(np.abs(diff_arr)))
            rmse = float(np.sqrt(np.mean(diff_arr ** 2)))

            with open(output_txt, 'w', encoding='utf-8') as f:
                f.write(f"Valid Points: {len(diffs)}\n")
                f.write(f"Depth Field: {depth_field}\n")
                f.write("Formula: Difference = Predicted DEM - (Surface DEM - SHP Depth)\n")
                f.write(f"Max Difference: {max_diff}\n")
                f.write(f"Min Difference: {min_diff}\n")
                f.write(f"Mean Difference: {mean_diff}\n")
                f.write(f"MAE: {mae}\n")
                f.write(f"RMSE: {rmse}\n")

            QMessageBox.information(
                self,
                "Success",
                f"Check Completed!\nValid Points: {len(diffs)}\nMax: {max_diff}\nMin: {min_diff}\nMean: {mean_diff}\nMAE: {mae}\nRMSE: {rmse}\nSaved to: {output_txt}"
            )
            return

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Check failed: {str(e)}")
            return

        try:
            # 1. 读取栅格
            raster_ds = gdal.Open(input_raster)
            if not raster_ds: raise Exception("Cannot open raster file.")
            
            raster_band = raster_ds.GetRasterBand(1)
            raster_data = raster_band.ReadAsArray()
            gt = raster_ds.GetGeoTransform()
            
            # 2. 读取矢量
            shp_ds = ogr.Open(point_shp)
            if not shp_ds: raise Exception("Cannot open shapefile.")
            shp_layer = shp_ds.GetLayer()
            
            x_res = raster_band.XSize
            y_res = raster_band.YSize
            
            # 创建一个全0矩阵，用于标记 Shapefile 点的位置
            shp_raster = np.zeros((y_res, x_res), dtype=np.float32)
            
            # 3. 遍历矢量要素，映射到栅格坐标
            # 注意：原代码逻辑假设 SHP 是点要素，或者取几何体的 Vertex
            for feature in shp_layer:
                geom = feature.GetGeometryRef()
                if geom:
                    # 获取坐标 (假设是 Point 类型)
                    # 如果是 LineString，这里可能只能获取到第一个点，或者需要修改原逻辑遍历所有点
                    # 这里保持您原代码的逻辑：
                    x, y = geom.GetX(), geom.GetY()
                    
                    # 坐标转行列号
                    px = int((x - gt[0]) / gt[1])
                    py = int((y - gt[3]) / gt[5])
                    
                    # 边界检查
                    if 0 <= px < x_res and 0 <= py < y_res:
                        shp_raster[py, px] = 1
            
            # 4. 计算差异 (这里原逻辑是将 raster_data 减去 shp_raster???)
            # 原代码逻辑：diff_raster = raster_data - shp_raster
            # 这似乎是在计算：(实际水深) - (是否有测点:0或1)
            # 这通常用于检查点位是否落在特定值上，或者仅仅是测试逻辑。
            # 我将保持您提供的原代码逻辑不变。
            diff_raster = raster_data - shp_raster
            
            max_diff = np.max(diff_raster)
            min_diff = np.min(diff_raster)
            
            # 5. 输出结果
            with open(output_txt, 'w') as f:
                f.write(f"Max Difference: {max_diff}\n")
                f.write(f"Min Difference: {min_diff}\n")
            
            QMessageBox.information(self, "Success", f"Check Completed!\nMax Diff: {max_diff}\nMin Diff: {min_diff}\nSaved to: {output_txt}")


        except Exception as e:
            QMessageBox.critical(self, "Error", f"Check failed: {str(e)}")
