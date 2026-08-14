from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QFrame, QFileDialog,
                             QGraphicsDropShadowEffect, QWidget, QSizePolicy)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QPoint
from PyQt5.QtGui import QIcon, QColor, QPixmap, QPainter, QBrush


class BackgroundFrame(QFrame):
    """
    自定义黑色半透明圆角背景
    """
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


class ValidationDialog(QDialog):
    # 信号：传回 (功能模式, 参数字典)
    run_signal = pyqtSignal(str, dict)

    def __init__(self, mode="accuracy", parent=None):
        """
        :param mode: 
            - 'accuracy': 预测点精度 (Prediction Accuracy)
            - 'check': 测深线检查 (Depth Line Check)
        """
        super().__init__(parent)
        self.mode = mode
        self.setObjectName("ValidationDialog")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 1. 【关键】强制固定窗口大小 (与 Volume/Preprocess 保持一致)
        self.setFixedSize(660, 430)

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

        # 3. 动态内容容器 (存放输入框)
        self.form_container = QWidget()
        self.form_layout = QVBoxLayout(self.form_container)
        # 左右 30px 边距，上下适中
        self.form_layout.setContentsMargins(30, 20, 30, 10)
        self.form_layout.setSpacing(15) 

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

        # 标题映射
        title_map = {
            "accuracy": "Prediction Accuracy",
            "check": "Depth Line Check"
        }
        title_text = title_map.get(self.mode, "Validation Tool")
        
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
        使用 self.form_layout.addWidget() 直接添加
        """
        # 模式 1: 预测点精度 (Prediction Accuracy)
        if self.mode == "accuracy":
            # 1) 工作路径 (选择文件夹)
            self.widgets['work_path'] = self.create_input_row("Workspace Path:", "D:/input_data/", browse=True, folder_mode=True)
            
            # 2) 湖泊名称
            # 3) 间隔 (数值类型，Gold 样式)
            self.widgets['interval'] = self.create_input_row("Interval (m):", "5", style="Gold", is_value=True)

        # 模式 2: 测深线检查 (Depth Line Check)
        elif self.mode == "check":
            # 1) 输入检查线 SHP
            self.widgets['check_line'] = self.create_input_row("Input In-situ Line:", "Select .shp...", browse=True)
            
            # 2) 输入栅格 TIF
            self.widgets['input_raster'] = self.create_input_row("Predicted DEM:", "Select .tif...", browse=True)
            self.widgets['surface_dem'] = self.create_input_row("Surface DEM:", "Select .tif...", browse=True)
            # 3) 实测水深字段名
            self.widgets['depth_field'] = self.create_input_row("Depth Field:", "Depth", is_value=True)
            
            # 4) 输出 TXT (保存文件模式)
            self.widgets['output_txt'] = self.create_input_row("Output TXT:", "Save as .txt...", browse=True, save_mode=True)

    def create_input_row(self, label_text, placeholder, browse=False, style="Green", save_mode=False, folder_mode=False, is_value=False):
        """
        创建一行输入框：[Label] [LineEdit] [Button]
        """
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        # 标签：宽度自适应
        lbl = QLabel(label_text)
        lbl.setWordWrap(True) 
        lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        lbl.setStyleSheet("font-size: 16px; font-weight: 600; color: #FFFFFF; background: transparent;")

        # 输入框：占据剩余空间
        le = QLineEdit()
        le.setFixedHeight(42)
        le.setMinimumWidth(150)
        le.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        if is_value:
            le.setText(placeholder)
        else:
            le.setPlaceholderText(placeholder)

        # 边框颜色
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

        # 浏览按钮 (可选)
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
                QPushButton:pressed {
                    background-color: rgba(0, 147, 119, 0.43);
                }
            """)
            icon = QIcon("assets/icons/icon_folder.png")
            if not icon.isNull():
                btn_browse.setIcon(icon)
                btn_browse.setIconSize(QSize(22, 22))
            else:
                btn_browse.setText("...")

            # 绑定选择逻辑
            btn_browse.clicked.connect(lambda: self.browse_action(le, save_mode, folder_mode))
            row_layout.addWidget(btn_browse)
        
        self.form_layout.addWidget(row_widget)
        return le

    def browse_action(self, line_edit, save_mode, folder_mode):
        if folder_mode:
            dialog = QFileDialog(self, "Select Directory")
            dialog.setFileMode(QFileDialog.Directory)
            dialog.setOption(QFileDialog.ShowDirsOnly, True)
            dialog.setOption(QFileDialog.DontUseNativeDialog, True)
            dialog.resize(760, 480)
            path = dialog.selectedFiles()[0] if dialog.exec_() == QFileDialog.Accepted else ""
        elif save_mode:
            dialog = QFileDialog(self, "Save File")
            dialog.setAcceptMode(QFileDialog.AcceptSave)
            dialog.setNameFilter("Text Files (*.txt);;All Files (*)")
            dialog.setOption(QFileDialog.DontUseNativeDialog, True)
            dialog.resize(760, 480)
            path = dialog.selectedFiles()[0] if dialog.exec_() == QFileDialog.Accepted else ""
            if path and not path.lower().endswith(".txt"):
                path += ".txt"
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
            data[key] = widget.text().strip()
        
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
