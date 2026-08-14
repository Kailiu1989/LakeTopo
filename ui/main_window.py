import sys
import os
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QStackedWidget, QLabel, QLineEdit, QFrame,
                             QSizePolicy, QApplication, QCheckBox, QGroupBox, QComboBox)
from PyQt5.QtCore import Qt, QFile, QTextStream, QSize, QPoint, QRect, QByteArray, QTimer, QUrl
from PyQt5.QtGui import QIcon, QPainter, QPen, QColor, QFont, QLinearGradient, QPixmap, QMouseEvent, QPainterPath
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtSvg import QSvgRenderer
import numpy as np

from ui.widgets.volume_visualization import VolumeVisualizationWidget

try:
    from cesiumTool.startCesium import initCesiumViewer, drawCube, cubeData, drawCube2, drawGeoJson, changeViewerLanguage
except ImportError:
    
    def initCesiumViewer(self): pass
    def drawCube(*args): pass
    def cubeData(*args): pass
    def drawCube2(*args): pass
    def drawGeoJson(*args): pass
    def changeViewerLanguage(*args): pass

# --- Page imports with per-page fallback ---
class ImportErrorPage(QWidget):
    def __init__(self, page_name, error):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        label = QLabel(f"{page_name} load failed:\n{error}")
        label.setWordWrap(True)
        label.setStyleSheet("color: #ff6b6b; background: transparent;")
        layout.addWidget(label)
        layout.addStretch()

    def reset_buttons(self):
        pass


def _load_page_class(page_name, import_func):
    try:
        return import_func()
    except Exception as exc:
        print(f"[Import Error] {page_name}: {exc}")
        load_error = exc

        class FailedPage(ImportErrorPage):
            def __init__(self):
                super().__init__(page_name, load_error)

        return FailedPage


PagePreprocess = _load_page_class(
    "Preprocess",
    lambda: __import__("ui.pages.page_preprocess", fromlist=["PagePreprocess"]).PagePreprocess,
)
PageBathymetry = _load_page_class(
    "Bathymetry",
    lambda: __import__("ui.pages.page_bathymetry", fromlist=["PageBathymetry"]).PageBathymetry,
)
PageVolume = _load_page_class(
    "Volume",
    lambda: __import__("ui.pages.page_volume", fromlist=["PageVolume"]).PageVolume,
)
PageValidation = _load_page_class(
    "Validation",
    lambda: __import__("ui.pages.page_validation", fromlist=["PageValidation"]).PageValidation,
)
PageHelp = _load_page_class(
    "Help",
    lambda: __import__("ui.pages.page_help", fromlist=["PageHelp"]).PageHelp,
)

# -----------------------------------------------------------------------------
# SVG 
# -----------------------------------------------------------------------------
SVG_MINIMIZE = """
<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="{color}">
    <path d="M14 8v1H2V8h12z"/>
</svg>
"""

SVG_MAXIMIZE = """
<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="{color}">
    <path d="M2 2v12h12V2H2zm1 1h10v10H3V3z"/>
</svg>
"""

SVG_RESTORE = SVG_MAXIMIZE

SVG_CLOSE = """
<svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="{color}">
    <path d="M9.41 8l3.29-3.29-1.41-1.41L8 6.59l-3.29-3.3-1.41 1.41L6.59 8 3.3 11.29l1.41 1.41L8 9.41l3.29 3.29 1.41-1.41L9.41 8z"/>
</svg>
"""


# -----------------------------------------------------------------------------
# ChartWidget 
# -----------------------------------------------------------------------------
class ChartWidget(QWidget):
    def __init__(self, color_hex="#2EE075", line_width=2, has_second_curve=False,
                 x_labels=None, show_right_axis=False):
        super().__init__()
        self.main_color = QColor(color_hex)
        self.line_width = line_width
        self.has_second_curve = has_second_curve
        self.x_labels = x_labels if x_labels else ["4", "5", "6", "7", "8"]
        self.show_right_axis = show_right_axis
        # 
        self.data_points_1 = self.generate_high_res_data(offset=0, freq=0.1)
        self.data_points_2 = self.generate_high_res_data(offset=2.5, freq=0.08)
        self.setAttribute(Qt.WA_TranslucentBackground)

    # -------------------------------------------------------------------------
    # 
    # -------------------------------------------------------------------------
    def update_chart_data(self, data_list_1, data_list_2=None):
        self.data_points_1 = data_list_1
        if data_list_2 and self.has_second_curve:
            self.data_points_2 = data_list_2
        self.update()

    def generate_high_res_data(self, offset=0, freq=0.1):
        import math, random
        points = []
        steps = 500
        for i in range(steps):
            x = i
            val = math.sin((x * freq * 0.2) + offset) * 0.4 + 0.5
            val += random.uniform(-0.005, 0.005)
            val = max(0.05, min(0.95, val))
            points.append(val)
        return points

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        h = self.height()
        margin_left = 40
        margin_right = 40 if self.show_right_axis else 20
        margin_top = 10
        margin_bottom = 25
        draw_x = margin_left
        draw_y = margin_top
        draw_w = w - margin_left - margin_right
        draw_h = h - margin_top - margin_bottom

        painter.setPen(QPen(QColor(255, 255, 255, 30), 1, Qt.DotLine))
        for i in range(5):
            y_pos = draw_y + (draw_h / 4) * i
            painter.drawLine(int(draw_x), int(y_pos), int(draw_x + draw_w), int(y_pos))

        y_labels = ["1200", "900", "600", "300", "0"]
        font = painter.font()
        font.setPixelSize(10)
        font.setFamily("Arial")
        painter.setFont(font)
        painter.setPen(QColor(180, 180, 180))

        for i, text in enumerate(y_labels):
            y_pos = draw_y + (draw_h / 4) * i
            text_y = int(y_pos + 4)
            rect_left = QRect(0, text_y - 10, margin_left - 5, 20)
            painter.drawText(rect_left, Qt.AlignRight | Qt.AlignVCenter, text)
            if self.show_right_axis:
                rect_right = QRect(w - margin_right + 5, text_y - 10, margin_right - 5, 20)
                painter.drawText(rect_right, Qt.AlignLeft | Qt.AlignVCenter, text)

        if self.x_labels:
            count = len(self.x_labels)
            if count > 1:
                step_w = draw_w / (count - 1)
                for i, text in enumerate(self.x_labels):
                    x_pos = draw_x + i * step_w
                    rect_x = QRect(int(x_pos - 20), int(draw_y + draw_h + 2), 40, 20)
                    painter.drawText(rect_x, Qt.AlignCenter, text)

        self.draw_smooth_curve(painter, self.data_points_1, self.main_color,
                               draw_x, draw_y, draw_w, draw_h, fill=True)

        if self.has_second_curve:
            self.draw_smooth_curve(painter, self.data_points_2, QColor("#FFA500"),
                                   draw_x, draw_y, draw_w, draw_h, fill=False)

    def draw_smooth_curve(self, painter, data, color, dx, dy, dw, dh, fill=True):
        if not data: return
        path = QPainterPath()
        step_x = dw / (len(data) - 1)
        start_y = dy + dh - (data[0] * dh)
        path.moveTo(dx, start_y)
        for i, val in enumerate(data):
            x = dx + i * step_x
            y = dy + dh - (val * dh)
            path.lineTo(x, y)
        if fill:
            path_fill = QPainterPath(path)
            path_fill.lineTo(dx + dw, dy + dh)
            path_fill.lineTo(dx, dy + dh)
            path_fill.closeSubpath()
            gradient = QLinearGradient(0, dy, 0, dy + dh)
            gradient.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 80))
            gradient.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
            painter.setBrush(gradient)
            painter.setPen(Qt.NoPen)
            painter.drawPath(path_fill)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(color, self.line_width))
        painter.drawPath(path)


# -----------------------------------------------------------------------------
# MainWindow
# -----------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LakeTopo Project")

        # ---------------------------------------------------------------------
        # 
        # ---------------------------------------------------------------------
        self.current_language = 'en'
        self.translations = self.load_translations()

        screen_geometry = QApplication.primaryScreen().availableGeometry()
        initial_width = int(screen_geometry.width() * 0.85)
        initial_height = int(screen_geometry.height() * 0.85)
        self.setMinimumSize(1280, 720)
        self.resize(initial_width, initial_height)

        frame_geo = self.frameGeometry()
        frame_geo.moveCenter(screen_geometry.center())
        self.move(frame_geo.topLeft())

        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.dragPos = QPoint()

        self.load_stylesheet()

        self.central_widget = QWidget()
        self.central_widget.setObjectName("MainCentralWidget")
        self.central_widget.setStyleSheet("background-color: #050a0c; border-radius: 12px;")
        self.setCentralWidget(self.central_widget)

        self.create_cesium_widget()
        self.init_ui()

        # ---------------------------------------------------------------------
        # 
        # ---------------------------------------------------------------------
        self.add_language_switch_button()
        self.apply_translations()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and event.pos().y() < 70:
            self.dragPos = event.globalPos()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.LeftButton and self.dragPos is not None:
            self.move(self.pos() + event.globalPos() - self.dragPos)
            self.dragPos = event.globalPos()
            event.accept()

    def closeEvent(self, event):
        if hasattr(self, 'page_volume') and hasattr(self.page_volume, 'shutdown'):
            self.page_volume.shutdown()
        if hasattr(self, 'webViewer'):
            self.webViewer.setUrl(QUrl("about:blank"))
            self.webViewer.deleteLater()
        if hasattr(self, 'server_thread'):
            self.server_thread.stop()
            self.server_thread.join(timeout=1)
        event.accept()
        QTimer.singleShot(0, QApplication.instance().quit)
        super().closeEvent(event)

    def get_svg_icon(self, svg_str, color="#FFFFFF"):
        formatted_svg = svg_str.replace("currentColor", color).format(color=color)
        renderer = QSvgRenderer(QByteArray(formatted_svg.encode()))
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    def create_window_button(self, svg_code, slot, is_close=False):
        btn = QPushButton()
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(46, 32)

        icon = self.get_svg_icon(svg_code)
        btn.setIcon(icon)
        btn.setIconSize(QSize(16, 16))

        hover_color = '#E81123' if is_close else 'rgba(255, 255, 255, 0.1)'

        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 0px; 
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:pressed {{
                background-color: {'#B80D1A' if is_close else 'rgba(255, 255, 255, 0.2)'};
            }}
        """)

        btn.clicked.connect(slot)
        return btn

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self.central_widget.setStyleSheet("background-color: #050a0c; border-radius: 12px;")
            self.btn_maximize.setIcon(self.get_svg_icon(SVG_MAXIMIZE))
        else:
            self.showMaximized()
            self.central_widget.setStyleSheet("background-color: #050a0c; border-radius: 0px;")
            self.btn_maximize.setIcon(self.get_svg_icon(SVG_RESTORE))

    def create_cesium_widget(self):
        self.map_container = QWidget()
        self.map_container.setObjectName("CesiumMapContainer")
        self.map_container.setStyleSheet("background-color: #000000;")
        self.map_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self.map_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        try:
            initCesiumViewer(self)
            if hasattr(self, 'webViewer'):
                self.webViewer.setStyleSheet("background-color: #000000;")
                layout.addWidget(self.webViewer)
                
                # -----------------------------------------------------------------
                # 
                # -----------------------------------------------------------------
                self.webViewer.loadFinished.connect(self.on_cesium_load_finished)
            else:
                err_label = QLabel("Map initialization failed: No WebViewer created.")
                err_label.setStyleSheet("color: red;")
                layout.addWidget(err_label)
        except Exception as e:
            error_label = QLabel(f"Map Load Error:\n{str(e)}\n\nPlease check cesiumTool/startCesium.py")
            error_label.setStyleSheet("color: red; padding: 20px;")
            layout.addWidget(error_label)

    def on_cesium_load_finished(self, ok):
        if not ok:
            print(f"Cesium map failed to load: {self.webViewer.url().toString()}")
            return
        changeViewerLanguage(isEn=(self.current_language == 'en'))

    # =========================================================================
    # [API SECTION] Cesium 
    # =========================================================================
    def api_cesium_load_geojson(self, geojson_path):
        if hasattr(self, 'webViewer'):
            drawGeoJson(self, geojson_path)

    def api_cesium_add_cube(self, x, y, z, val, min_val, max_val):
        drawCube2(self, x, y, z, val, min_val, max_val)

    def api_cesium_clear(self):
        if hasattr(self, 'webViewer'):
            self.webViewer.reload()

    def load_stylesheet(self):
        file = QFile("ui/style.qss")
        if file.open(QFile.ReadOnly | QFile.Text):
            stream = QTextStream(file)
            self.setStyleSheet(stream.readAll())
            file.close()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.init_header()
        self.init_divider()

        middle_layout = QHBoxLayout()
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(0)

        left_container = QWidget()
        left_container.setFixedWidth(320)
        left_container.setStyleSheet("background-color: #0b1215; border-right: 1px solid rgba(255,255,255,0.05);")

        lv = QVBoxLayout(left_container)
        lv.setContentsMargins(0, 10, 0, 0)
        lv.setSpacing(0)

        lv.addWidget(self.create_subheader_widget("SUB FUNCTIONS", is_left=True))

        self.init_pages_stack()
        self.stack.setFixedWidth(320)
        lv.addWidget(self.stack)

        middle_layout.addWidget(left_container)
        middle_layout.addWidget(self.map_container, 1)

        self.main_layout.addLayout(middle_layout, 1)
        self.init_bottom_charts()

    def init_header(self):
        header = QFrame()
        header.setFixedHeight(70)
        header.setObjectName("HeaderFrame")
        header.setStyleSheet("background-color: rgba(5, 10, 12, 1); border-bottom: 1px solid rgba(0, 255, 204, 0.1);")

        hl = QHBoxLayout(header)
        hl.setContentsMargins(15, 0, 0, 0)

        # 1. Logo
        logo = QHBoxLayout()
        icon = QLabel()
        pix = QPixmap("assets/icons/logo_icon.png")
        if not pix.isNull():
            self.setWindowIcon(QIcon(pix))
            icon.setPixmap(pix.scaled(100, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icon.setStyleSheet("background: transparent; border: none; padding:0;")
        txt = QLabel("LakeTopo")
        txt.setStyleSheet(
            "font-size: 22px; font-weight: 900; font-style: italic; color: #fff; background: transparent; border: none;")
        logo.addWidget(icon)
        logo.addSpacing(12)
        logo.addWidget(txt)
        hl.addLayout(logo)
        hl.addSpacing(15)

        # 2. Tabs
        self.main_function_buttons = [] # Store buttons for translation updates
        tabs = [("Preprocess", "assets/icons/nav_preprocess.png", 0),
                ("Lake Bathymetry", "assets/icons/nav_bathymetry.png", 1),
                ("Volume Calculation", "assets/icons/nav_volume.png", 2),
                ("Accuracy Validation", "assets/icons/nav_validation.png", 3),
                ("Help", "assets/icons/nav_help.png", 4)]
        
        for n, p, i in tabs:
            b = QPushButton(f"  {n}")
            b.setObjectName("navButton")
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(QIcon(p))
            b.setIconSize(QSize(20, 20))
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setFixedSize(220 if len(n) > 12 else 150, 50)
            if i == 2: b.setChecked(True)
            b.clicked.connect(lambda c, x=i: self.switch_page(x))
            
            # Store the original English key for translation
            b.setProperty("trans_key", n)
            self.main_function_buttons.append(b)
            
            hl.addWidget(b)

        # 3. Spacer
        hl.addStretch()

        # 4. Search Bar
        ICON_BOX_WIDTH = 54
        INPUT_BOX_WIDTH = 220
        TOTAL_WIDTH = ICON_BOX_WIDTH + INPUT_BOX_WIDTH

        sw = QWidget()
        sw.setFixedSize(TOTAL_WIDTH, 34)
        sw.setStyleSheet("background: transparent;")

        sl = QHBoxLayout(sw)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        si = QLabel()
        si.setFixedSize(ICON_BOX_WIDTH, 34)
        si.setAlignment(Qt.AlignCenter)
        si.setPixmap(QIcon("assets/icons/icon_search.png").pixmap(16, 16))
        si.setStyleSheet("background-color: #1A5036;")

        se = QLineEdit()
        se.setFixedSize(INPUT_BOX_WIDTH, 34)
        se.setStyleSheet("""
            QLineEdit { 
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 rgba(7, 84, 43, 102), stop:1 #005A1C); 
                border: none; 
                color: #fff; 
                padding-left: 10px; 
                border-top-right-radius: 6px; 
                border-bottom-right-radius: 6px; 
            }
        """)
        sl.addWidget(si)
        sl.addWidget(se)
        hl.addWidget(sw)

        hl.addSpacing(20)

        # 5. Window Controls
        win_ctrl_container = QWidget()
        win_ctrl_container.setFixedWidth(46 * 3)
        win_ctrl_container.setFixedHeight(32)

        wc_layout = QHBoxLayout(win_ctrl_container)
        wc_layout.setContentsMargins(0, 0, 0, 0)
        wc_layout.setSpacing(0)

        btn_min = self.create_window_button(SVG_MINIMIZE, self.showMinimized)
        wc_layout.addWidget(btn_min)

        self.btn_maximize = self.create_window_button(SVG_MAXIMIZE, self.toggle_maximize)
        wc_layout.addWidget(self.btn_maximize)

        btn_close = self.create_window_button(SVG_CLOSE, self.close, is_close=True)
        wc_layout.addWidget(btn_close)

        hl.addWidget(win_ctrl_container)

        self.main_layout.addWidget(header)

    def init_divider(self):
        l = QLabel()
        l.setFixedHeight(12)
        p = QPixmap("assets/icons/line_green_bottom.png")
        if not p.isNull():
            l.setPixmap(p)
            l.setScaledContents(True)
        else:
            l.setStyleSheet("background-color: #00ffcc;")
        self.main_layout.addWidget(l)

    def create_subheader_widget(self, text, is_left):
        f = QFrame()
        f.setFixedHeight(36)
        style = """
            QFrame {
                border-image: url(assets/icons/icon_date_arrow.png) 0 0 0 0 stretch stretch;
                background-color: transparent;
                border: none;
            }
        """
        f.setStyleSheet(style)

        l = QHBoxLayout(f)
        l.setContentsMargins(0, 0, 10, 0)
        l.setSpacing(0)
        lbl = QLabel(text)
        lbl.setObjectName("CommonHeaderLabel")
        lbl.setStyleSheet(
            "font-family: 'Microsoft YaHei'; font-weight: 600; font-size: 16px; color: #EFFFF7; padding-left: 35px; background: transparent;")
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        l.addWidget(lbl)
        l.addStretch()

        if not is_left:
            l.addSpacing(10)
            for i in ["assets/icons/icon_date_add.png", "assets/icons/icon_date_maximize.png"]:
                b = QPushButton()
                b.setObjectName("DateSmallBtn")
                b.setFixedSize(24, 24)
                b.setIcon(QIcon(i))
                b.setIconSize(QSize(20, 20))
                b.setStyleSheet(
                    "QPushButton { background: transparent; border: none; } QPushButton:hover { background-color: rgba(255,255,255,0.1); }")
                l.addWidget(b)
                l.addSpacing(8)
        return f

    def init_pages_stack(self):
        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")
        self.page_preprocess = PagePreprocess()
        self.page_bathymetry = PageBathymetry()
        self.page_volume = PageVolume()
        self.page_validation = PageValidation()
        self.page_help = PageHelp()
        self.stack.addWidget(self.page_preprocess)
        self.stack.addWidget(self.page_bathymetry)
        self.stack.addWidget(self.page_volume)
        self.stack.addWidget(self.page_validation)
        self.stack.addWidget(self.page_help)
        if hasattr(self.page_volume, "curve_calculation_started"):
            self.page_volume.curve_calculation_started.connect(self._on_volume_curve_started)
        if hasattr(self.page_volume, "curve_ready"):
            self.page_volume.curve_ready.connect(self._on_volume_curve_ready)
        if hasattr(self.page_volume, "curve_calculation_failed"):
            self.page_volume.curve_calculation_failed.connect(self._on_volume_curve_failed)
        if hasattr(self.page_volume, "curve_calculation_cancelled"):
            self.page_volume.curve_calculation_cancelled.connect(self._on_volume_curve_cancelled)
        self.stack.setCurrentIndex(2)

    def switch_page(self, i):
        self.stack.setCurrentIndex(i)
        current_page = self.stack.currentWidget()

        if hasattr(current_page, 'reset_buttons'):
            current_page.reset_buttons()

        if hasattr(self, "bottom_panel_stack"):
            self.bottom_panel_stack.setCurrentIndex(1 if i == 2 else 0)

        print(f"[Page Logic] Switched to page index: {i}")

    def init_bottom_charts(self):
        self.bottom_panel_stack = QStackedWidget()
        self.bottom_panel_stack.setFixedHeight(260)
        self.bottom_panel_stack.setStyleSheet(
            "background-color: #0b1215; border-top: 1px solid rgba(255,255,255,0.05);"
        )

        bp = QWidget()
        bp.setStyleSheet("background-color: #0b1215; border-top: 1px solid rgba(255,255,255,0.05);")
        l = QHBoxLayout(bp)
        l.setContentsMargins(20, 10, 20, 10)
        l.setSpacing(20)

        c1 = self.create_chart_container("Example")
        self.chart_left = ChartWidget("#2EE075", 1, x_labels=["4", "5", "6", "7", "8"])
        c1.layout().addWidget(self.chart_left)
        l.addWidget(c1, 1)

        c2 = self.create_chart_container("Example")
        self.chart_center = ChartWidget("#66DC95", 2, True,
                                        x_labels=["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
                                        show_right_axis=True)
        c2.layout().addWidget(self.chart_center)
        l.addWidget(c2, 2)

        c3 = self.create_chart_container("Example")
        self.chart_right = ChartWidget("#2EE075", 1, x_labels=["4", "5", "6", "7", "8"])
        c3.layout().addWidget(self.chart_right)
        l.addWidget(c3, 1)

        self.volume_visualization = VolumeVisualizationWidget()
        self.bottom_panel_stack.addWidget(bp)
        self.bottom_panel_stack.addWidget(self.volume_visualization)
        self.bottom_panel_stack.setCurrentIndex(1 if self.stack.currentIndex() == 2 else 0)
        self.main_layout.addWidget(self.bottom_panel_stack)

    def _on_volume_curve_started(self):
        if hasattr(self, "bottom_panel_stack"):
            self.bottom_panel_stack.setCurrentIndex(1)
        if hasattr(self, "volume_visualization"):
            self.volume_visualization.set_busy(True)

    def _on_volume_curve_ready(self, result):
        if hasattr(self, "bottom_panel_stack"):
            self.bottom_panel_stack.setCurrentIndex(1)
        if hasattr(self, "volume_visualization"):
            self.volume_visualization.set_result(result)

    def _on_volume_curve_failed(self, message):
        if hasattr(self, "volume_visualization"):
            self.volume_visualization.set_error(message)

    def _on_volume_curve_cancelled(self):
        if hasattr(self, "volume_visualization"):
            self.volume_visualization.set_error("Calculation cancelled; previous result retained.")

    def api_update_left_chart(self, data_list):
        if hasattr(self, 'chart_left'):
            self.chart_left.update_chart_data(data_list)

    def api_update_center_chart(self, data_list_1, data_list_2=None):
        if hasattr(self, 'chart_center'):
            self.chart_center.update_chart_data(data_list_1, data_list_2)

    def api_update_right_chart(self, data_list):
        if hasattr(self, 'chart_right'):
            self.chart_right.update_chart_data(data_list)

    def create_chart_container(self, t):
        c = QFrame()
        c.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(c)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        hf = QFrame()
        hf.setObjectName("ChartHeaderWidget")
        hf.setFixedSize(140, 30)
        hf.setStyleSheet("border-image: url(assets/icons/icon_date_arrow.png) 0 0 0 0 stretch stretch; border: none;")

        hl = QHBoxLayout(hf)
        hl.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(t)
        lbl.setObjectName("ChartHeaderLabel")
        lbl.setStyleSheet(
            "font-family: 'Microsoft YaHei'; font-weight: 600; font-size: 16px; color: #EFFFF7; padding-left: 35px;")
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hl.addWidget(lbl)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(hf)
        top.addStretch()
        vl.addLayout(top)
        return c

    # =========================================================================
    # [Translation Logic]
    # =========================================================================
    def load_translations(self):
        """Return UI translations.

        The original Chinese translation table in this file is encoding-damaged.
        Keep English labels stable for packaged releases until the translation
        strings are restored from a clean source.
        """
        return {
            "zh": {},
            "en": {}
        }

    def translate(self, text):

        if not text or not isinstance(text, str):
            return text
            
        clean_text = text.rstrip(":")
        
        # 
        if self.current_language == 'en':
            res = clean_text
        else:
            res = self.translations['zh'].get(clean_text, clean_text)
            
        if text.endswith(":") and not res.endswith(":"):
            res += ":"
            
        return res
    
    def add_language_switch_button(self):

        bar = getattr(self, 'status_bar', None) or self.statusBar()
        
        if getattr(self, "lang_btn", None) is None:
            # 
            btn_text = '中文' if self.current_language == 'en' else 'English'
            
            self.lang_btn = QPushButton(btn_text, self)
            self.lang_btn.setFixedWidth(80)
            self.lang_btn.setCursor(Qt.PointingHandCursor)
            self.lang_btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #00e5ff;
                    border: 1px solid #00e5ff;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(0, 229, 255, 0.1);
                }
            """)
            self.lang_btn.setToolTip('Switch Language / 转换语言')
            self.lang_btn.clicked.connect(self.toggle_language)
            bar.addPermanentWidget(self.lang_btn)
        else:
            self.lang_btn.setText('中文' if self.current_language == 'en' else 'English')
            
    def toggle_language(self):

        self.current_language = 'zh' if self.current_language == 'en' else 'en'
        
        new_btn_text = '中文' if self.current_language == 'en' else 'English'
        if hasattr(self, "lang_btn"):
            self.lang_btn.setText(new_btn_text)

        self.apply_translations()
        
        #  Cesium
        if hasattr(self, 'webViewer'):
            try:
                changeViewerLanguage(isEn=(self.current_language == 'en'))
            except:
                pass

    def apply_translations(self):

        self.setWindowTitle(self.translate("LakeTopo V2.1.0"))
        
        if hasattr(self, "status_bar"):
            self.status_bar.showMessage(self.translate("Ready"))

        if hasattr(self, "main_function_buttons"):
            for btn in self.main_function_buttons:
                key = btn.property("trans_key") 
                if key:
                    btn.setText("  " + self.translate(key))

        # 
        for i in range(self.stack.count()):
            widget = self.stack.widget(i)
            self._refresh_translations_in_widget(widget)

    def _refresh_translations_in_widget(self, widget):

        from PyQt5.QtWidgets import QLabel, QPushButton, QLineEdit, QCheckBox, QGroupBox

        children = widget.findChildren((QLabel, QPushButton, QCheckBox, QGroupBox))
        for w in children:
            if w.property("orig_text") is None:
                w.setProperty("orig_text", w.text().strip())
            
            key = w.property("orig_text")
            if key:
                trans_text = self.translate(key)
                
                if isinstance(w, QLabel):
                    if w.text().strip().endswith(":") and not trans_text.endswith(":"):
                        trans_text += ":"
                    w.setText(trans_text)
                elif isinstance(w, (QPushButton, QCheckBox)):
                    w.setText(trans_text)
                elif isinstance(w, QGroupBox):
                    w.setTitle(trans_text)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = MainWindow()
    ex.show()
    sys.exit(app.exec_())
