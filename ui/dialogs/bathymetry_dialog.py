from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QFrame, QComboBox,
                             QGraphicsDropShadowEffect, QWidget, QSizePolicy, QFileDialog)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QPoint
from PyQt5.QtGui import QIcon, QColor, QPixmap, QPainter, QBrush


class BackgroundFrame(QFrame):
    def __init__(self, opacity=240, parent=None):
        super().__init__(parent)
        self.setObjectName("DialogBg")
        self.opacity = opacity

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        brush_color = QColor(11, 18, 21, self.opacity)
        painter.setBrush(QBrush(brush_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 12, 12)


class BathymetryDialog(QDialog):
    # 信号：传回 (功能模式, 参数字典)
    run_signal = pyqtSignal(str, dict)

    def __init__(self, mode="pred_loc", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.setObjectName("BathymetryDialog")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # Depth prediction has one additional model selector.
        self.setFixedSize(660, 500 if self.mode == "pred_depth" else 430)

        self.dragPos = QPoint()
        self.widgets = {} 
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.bg_frame = BackgroundFrame(opacity=240)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 5)
        self.bg_frame.setGraphicsEffect(shadow)
        main_layout.addWidget(self.bg_frame)

        # --- 内部垂直布局 ---
        bg_layout = QVBoxLayout(self.bg_frame)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        bg_layout.setSpacing(0)

        # 1. 标题栏
        self.create_title_bar(bg_layout)

        # 2. 装饰线
        line_lbl = QLabel()
        line_lbl.setFixedHeight(10)
        line_pix = QPixmap("assets/icons/line_green_bottom.png")
        if not line_pix.isNull():
            line_lbl.setPixmap(line_pix)
            line_lbl.setScaledContents(True)
            line_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        else:
            line_lbl.setStyleSheet("background: #00ffcc;")
        bg_layout.addWidget(line_lbl)

        # 3. 动态内容容器
        self.form_container = QWidget()
        self.form_layout = QVBoxLayout(self.form_container)
        self.form_layout.setContentsMargins(30, 20, 30, 10)
        self.form_layout.setSpacing(10) 

        self.setup_dynamic_content()
        bg_layout.addWidget(self.form_container)

        # 4. 弹簧 (将 Run 按钮顶到底部)
        bg_layout.addStretch()

        # 5. Run 按钮固定位置
        btn_layout = QHBoxLayout()
        self.btn_run = QPushButton("  Run") 
        self.btn_run.setFixedSize(251, 60)
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 147, 119, 0.43); border-radius: 16px; color: #ffffff;
                font-size: 18px; font-weight: bold; border: none;
            }
            QPushButton:hover { background-color: rgba(0, 147, 119, 0.7); }
            QPushButton:pressed { background-color: rgba(0, 147, 119, 0.9); }
        """)
        icon_run = QIcon("assets/icons/icon_run.png")
        if not icon_run.isNull():
            self.btn_run.setIcon(icon_run)
            self.btn_run.setIconSize(QSize(24, 24))
        
        self.btn_run.clicked.connect(self.on_run_clicked)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_run)
        btn_layout.addStretch()
        
        bg_layout.addLayout(btn_layout)
        bg_layout.addSpacing(20)

        # 6. 底部装饰图
        bottom_img = QLabel()
        bottom_img.setFixedHeight(38)
        img_pix = QPixmap("assets/icons/line_bottom.png")
        if not img_pix.isNull():
            bottom_img.setPixmap(img_pix)
            bottom_img.setScaledContents(True)
            bottom_img.setStyleSheet("background: transparent; border-bottom-left-radius: 12px; border-bottom-right-radius: 12px;")
        bg_layout.addWidget(bottom_img)

    def create_title_bar(self, parent_layout):
        title_container = QWidget()
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(20, 15, 20, 5)

        icon_lbl = QLabel()
        logo_pix = QPixmap("assets/icons/logo_icon.png")
        if not logo_pix.isNull():
            icon_lbl.setPixmap(logo_pix.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            icon_lbl.setFixedSize(28, 28)

        # 【修改】移除了 Merge 选项
        title_map = {
            "pred_loc": "Generate Prediction Points",
            "pred_depth": "Generate Prediction Depth",
            "terrain": "Water Terrain Generation",
            "elevation": "Lake Elevation Adjustment",
            "mosaic": "Mosaic DEM"
        }
        title_text = title_map.get(self.mode, "Bathymetry Tool")
        
        title_lbl = QLabel(title_text)
        title_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #fff; background: transparent; margin-left: 5px;")

        btn_close = QPushButton()
        btn_close.setFixedSize(24, 24)
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.setStyleSheet("QPushButton { background: transparent; border: none; } QPushButton:hover { background: rgba(255,255,255,0.1); border-radius: 12px; }")
        icon_close = QIcon("assets/icons/icon_dialog_close.png")
        if not icon_close.isNull():
            btn_close.setIcon(icon_close)
        btn_close.clicked.connect(self.close)

        title_layout.addWidget(icon_lbl)
        title_layout.addWidget(title_lbl)
        title_layout.addStretch()
        title_layout.addWidget(btn_close)
        parent_layout.addWidget(title_container)

    def setup_dynamic_content(self):
        """
        根据 mode 添加对应的输入行
        【修改】移除了 Merge 相关代码
        """
        # 1. 生成预测点位置 OR 2. 生成预测点深度 (UI基本一致)
        if self.mode in ["pred_loc", "pred_depth"]:
            self.widgets['work_path'] = self.create_input_row("Workspace Path:", "D:/input_data/", browse=True, folder_mode=True)
            if self.mode == "pred_loc":
                self.widgets['dem_path'] = self.create_input_row("Input DEM:", "Select .tif...", browse=True)
                self.widgets['survey_path'] = self.create_input_row("In-situ Bath Points:", "Select .shp...", browse=True)
            else:
                self.widgets['model'] = self.create_combo_row(
                    "Prediction Model:",
                    ["XGBoost", "Random Forest", "LightGBM"]
                )
            self.widgets['interval'] = self.create_input_row("Interval (m):", "5", style="Gold", is_value=True)
            self.widgets['win_size'] = self.create_input_row("Window Size:", "5", style="Gold", is_value=True)
            self.widgets['cell_size'] = self.create_input_row("Cell Size (m):", "90", style="Gold", is_value=True)

        # 3. 水下地形生成
        elif self.mode == "terrain":
            self.widgets['depth_shp'] = self.create_input_row("Depth Points SHP:", "Select .shp...", browse=True)
            self.widgets['z_field'] = self.create_input_row("Z Field Name:", "Depth", is_value=True)
            self.widgets['breakline'] = self.create_input_row("Shoreline SHP:", "Select .shp...", browse=True)
            self.widgets['polygon'] = self.create_input_row("Lake Polygon:", "Select .shp...", browse=True)
            self.widgets['out_dem'] = self.create_input_row(
                "Output DEM:",
                "Save as .tif...",
                browse=True,
                save_mode=True,
                file_filter="GeoTIFF Files (*.tif *.tiff);;All Files (*)",
                default_ext=".tif"
            )
            self.widgets['resolution'] = self.create_input_row("Resolution (m):", "2", style="Gold", is_value=True)

        # 4. 湖泊高程调整
        elif self.mode == "elevation":
            self.widgets['base_elev'] = self.create_input_row("Base Elevation (m):", "Optional (Leave empty)", style="Gold")
            self.widgets['surround_dem'] = self.create_input_row("Surrounding DEM:", "Select .tif...", browse=True)
            self.widgets['lake_shp'] = self.create_input_row("Lake Polygon:", "Select .shp...", browse=True)
            self.widgets['depth_raster'] = self.create_input_row("Depth Raster:", "Select .tif...", browse=True)
            self.widgets['out_raster'] = self.create_input_row(
                "Output Raster:",
                "Save as .tif...",
                browse=True,
                save_mode=True,
                file_filter="GeoTIFF Files (*.tif *.tiff);;All Files (*)",
                default_ext=".tif"
            )

        # 5. DEM镶嵌
        elif self.mode == "mosaic":
            self.widgets['lake_dem'] = self.create_input_row("Lake DEM:", "Select .tif...", browse=True)
            self.widgets['mosaic_dem'] = self.create_input_row("Mosaic To DEM:", "Select .tif...", browse=True)
            self.widgets['cell_size'] = self.create_input_row("Cell Size (m):", "10", style="Gold", is_value=True)
            
            ops = ["First", "Maximum", "Minimum", "Mean"]
            self.widgets['operator'] = self.create_combo_row("Mosaic Operator:", ops)
            
            self.widgets['out_raster'] = self.create_input_row(
                "Output Raster:",
                "Save as .tif...",
                browse=True,
                save_mode=True,
                file_filter="GeoTIFF Files (*.tif *.tiff);;All Files (*)",
                default_ext=".tif"
            )

    def create_input_row(
        self,
        label_text,
        placeholder,
        browse=False,
        style="Green",
        folder_mode=False,
        save_mode=False,
        file_filter="All Files (*)",
        default_ext=None,
        is_value=False
    ):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        lbl = QLabel(label_text)
        lbl.setWordWrap(True) 
        lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        lbl.setStyleSheet("font-size: 16px; font-weight: 600; color: #FFFFFF; background: transparent;")

        le = QLineEdit()
        le.setFixedHeight(42)
        le.setMinimumWidth(150)
        le.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        if is_value:
            le.setText(placeholder)
        else:
            le.setPlaceholderText(placeholder)

        border_color = "#FBDC58" if style == "Gold" else "#27C77B"
        le.setStyleSheet(f"""
            QLineEdit {{
                border-radius: 4px; padding: 0 12px; font-size: 16px; font-weight: 600;
                background-color: rgba(22, 29, 32, 0.8);
                border: 1px solid {border_color}; color: #FFFFFF;
            }}
            QLineEdit::placeholder {{ color: rgba(255, 255, 255, 0.56); }}
            QLineEdit:focus {{ border: 1px solid #00ffcc; background-color: rgba(13, 38, 31, 0.9); }}
        """)

        row_layout.addWidget(lbl)
        row_layout.addWidget(le)

        if browse:
            btn_browse = QPushButton()
            btn_browse.setFixedSize(50, 42)
            btn_browse.setCursor(Qt.PointingHandCursor)
            btn_browse.setStyleSheet("""
                QPushButton {
                    background-color: rgba(22, 29, 32, 0.8);
                    border: 1px solid #27C77B;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: rgba(13, 38, 31, 0.9);
                    border: 1px solid #00ffcc;
                }
            """)
            icon = QIcon("assets/icons/icon_folder.png")
            if not icon.isNull():
                btn_browse.setIcon(icon)
                btn_browse.setIconSize(QSize(22, 22))
            else:
                btn_browse.setText("...")

            btn_browse.clicked.connect(lambda: self.browse_action(le, folder_mode, save_mode, file_filter, default_ext))
            row_layout.addWidget(btn_browse)
        
        self.form_layout.addWidget(row_widget)
        return le

    def create_combo_row(self, label_text, items):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        lbl = QLabel(label_text)
        lbl.setWordWrap(True)
        lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        lbl.setStyleSheet("font-size: 16px; font-weight: 600; color: #FFFFFF; background: transparent;")

        combo = QComboBox()
        combo.setFixedHeight(42)
        combo.addItems(items)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        combo.setStyleSheet("""
            QComboBox {
                border-radius: 4px; padding: 0 12px; font-size: 16px; font-weight: 600;
                background-color: rgba(22, 29, 32, 0.8);
                border: 1px solid #27C77B; color: #FFFFFF;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #161D20; color: #FFFFFF; selection-background-color: #009377;
            }
        """)

        row_layout.addWidget(lbl)
        row_layout.addWidget(combo)
        self.form_layout.addWidget(row_widget)
        return combo

    def browse_action(self, line_edit, is_folder, save_mode=False, file_filter="All Files (*)", default_ext=None):
        if is_folder:
            dialog = QFileDialog(self, "Select Directory")
            dialog.setFileMode(QFileDialog.Directory)
            dialog.setOption(QFileDialog.ShowDirsOnly, True)
            dialog.setOption(QFileDialog.DontUseNativeDialog, True)
            dialog.resize(760, 480)
            path = dialog.selectedFiles()[0] if dialog.exec_() == QFileDialog.Accepted else ""
        elif save_mode:
            dialog = QFileDialog(self, "Save File")
            dialog.setAcceptMode(QFileDialog.AcceptSave)
            dialog.setNameFilter(file_filter)
            dialog.setOption(QFileDialog.DontUseNativeDialog, True)
            dialog.resize(760, 480)
            path = dialog.selectedFiles()[0] if dialog.exec_() == QFileDialog.Accepted else ""
            if path and default_ext and not path.lower().endswith((".tif", ".tiff")):
                path += default_ext
        else:
            dialog = QFileDialog(self, "Select File")
            dialog.setFileMode(QFileDialog.ExistingFile)
            dialog.setOption(QFileDialog.DontUseNativeDialog, True)
            dialog.resize(760, 480)
            path = dialog.selectedFiles()[0] if dialog.exec_() == QFileDialog.Accepted else ""
        if path:
            line_edit.setText(path)

    def on_run_clicked(self):
        data = {}
        for key, widget in self.widgets.items():
            if isinstance(widget, QLineEdit):
                data[key] = widget.text().strip()
            elif isinstance(widget, QComboBox):
                data[key] = widget.currentText()
        self.run_signal.emit(self.mode, data)
        self.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragPos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.dragPos)
            event.accept()
