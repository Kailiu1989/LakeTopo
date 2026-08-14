"""Embedded E-V curve and lake-level 3-D visualisation widgets."""

from __future__ import annotations

import numpy as np

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator


BACKGROUND = "#0b1215"
PANEL_BACKGROUND = "#081014"
GRID_COLOR = "#233239"
TEXT_COLOR = "#a9bdc5"
CYAN = "#00d9f5"
WATER = "#2dd4ff"


def _style_2d_axes(ax):
    ax.set_facecolor(PANEL_BACKGROUND)
    ax.tick_params(colors=TEXT_COLOR, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)
    ax.grid(True, color=GRID_COLOR, linewidth=0.6, alpha=0.75)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)


class EVCurveCanvas(FigureCanvas):
    """Interactive elevation-volume curve embedded in the Qt window."""

    level_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        self.figure = Figure(facecolor=PANEL_BACKGROUND)
        super().__init__(self.figure)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.levels = np.array([], dtype=float)
        self.volumes = np.array([], dtype=float)
        self.selected_index = 0
        self.mpl_connect("button_press_event", self._on_click)
        self._draw_empty()

    def _new_axes(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        _style_2d_axes(ax)
        return ax

    def _draw_empty(self):
        ax = self._new_axes()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_xlabel("Water level (m)")
        ax.set_ylabel("Volume (10⁸ m³)")
        ax.text(
            0.5,
            0.5,
            "Run E-V Curve to generate results",
            color="#607780",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        self.figure.subplots_adjust(left=0.12, right=0.98, bottom=0.20, top=0.95)
        self.draw_idle()

    def set_data(self, levels, volumes, selected_index=None):
        self.levels = np.asarray(levels, dtype=float)
        self.volumes = np.asarray(volumes, dtype=float)
        if self.levels.size == 0 or self.levels.size != self.volumes.size:
            self.levels = np.array([], dtype=float)
            self.volumes = np.array([], dtype=float)
            self._draw_empty()
            return
        if selected_index is None:
            selected_index = int(round((self.levels.size - 1) * 0.70))
        self.selected_index = int(np.clip(selected_index, 0, self.levels.size - 1))
        self._redraw()

    def select_index(self, index):
        if self.levels.size == 0:
            return
        index = int(np.clip(index, 0, self.levels.size - 1))
        if index == self.selected_index:
            return
        self.selected_index = index
        self._redraw()
        self.level_selected.emit(index)

    def _redraw(self):
        ax = self._new_axes()
        ax.plot(
            self.levels,
            self.volumes,
            color=CYAN,
            linewidth=1.6,
            marker="o",
            markersize=3.2,
            markerfacecolor=PANEL_BACKGROUND,
            markeredgecolor=CYAN,
            markeredgewidth=0.8,
        )
        ax.fill_between(self.levels, self.volumes, 0, color="#007d8d", alpha=0.32)
        idx = self.selected_index
        ax.scatter(
            [self.levels[idx]],
            [self.volumes[idx]],
            s=35,
            color="#ff5a56",
            edgecolor="white",
            linewidth=0.8,
            zorder=5,
        )
        ax.annotate(
            f"{self.levels[idx]:.2f} m\n{self.volumes[idx]:.4g} ×10⁸ m³",
            (self.levels[idx], self.volumes[idx]),
            xytext=(8, -8),
            textcoords="offset points",
            color="#d7edf2",
            fontsize=7,
            ha="left",
            va="top",
        )
        ax.set_xlabel("Water level (m)", fontsize=8)
        ax.set_ylabel("Volume (10⁸ m³)", fontsize=8)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=7))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.margins(x=0.03, y=0.12)
        self.figure.subplots_adjust(left=0.12, right=0.98, bottom=0.20, top=0.95)
        self.draw_idle()

    def _on_click(self, event):
        if event.inaxes is None or event.xdata is None or self.levels.size == 0:
            return
        nearest = int(np.argmin(np.abs(self.levels - float(event.xdata))))
        self.select_index(nearest)


class Lake3DCanvas(FigureCanvas):
    """Interactive 3-D terrain with a water surface at the selected level."""

    def __init__(self, parent=None):
        self.figure = Figure(facecolor=PANEL_BACKGROUND)
        super().__init__(self.figure)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.x = None
        self.y = None
        self.z = None
        self.x_label = "X"
        self.y_label = "Y"
        self._draw_empty()

    def _new_axes(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111, projection="3d")
        ax.set_facecolor(PANEL_BACKGROUND)
        self.figure.patch.set_facecolor(PANEL_BACKGROUND)
        ax.tick_params(colors=TEXT_COLOR, labelsize=6, pad=0)
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis.label.set_color(TEXT_COLOR)
            try:
                axis.pane.set_facecolor((0.04, 0.08, 0.10, 1.0))
                axis.pane.set_edgecolor(GRID_COLOR)
            except AttributeError:
                pass
        try:
            ax.xaxis._axinfo["grid"]["color"] = GRID_COLOR
            ax.yaxis._axinfo["grid"]["color"] = GRID_COLOR
            ax.zaxis._axinfo["grid"]["color"] = GRID_COLOR
        except (AttributeError, KeyError):
            pass
        return ax

    def _draw_empty(self):
        ax = self._new_axes()
        ax.set_xlabel("X", fontsize=7, labelpad=2)
        ax.set_ylabel("Y", fontsize=7, labelpad=2)
        ax.set_zlabel("Elevation (m)", fontsize=7, labelpad=2)
        ax.text2D(
            0.5,
            0.52,
            "3-D simulation will appear here",
            transform=ax.transAxes,
            color="#607780",
            ha="center",
        )
        self.figure.subplots_adjust(left=0.0, right=1.0, bottom=0.02, top=0.98)
        self.draw_idle()

    def set_terrain(self, x, y, z, x_label="X", y_label="Y"):
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y, dtype=float)
        self.z = np.asarray(z, dtype=float)
        self.x_label = x_label
        self.y_label = y_label

    def set_water_level(self, level):
        if self.z is None or self.z.size == 0 or not np.isfinite(self.z).any():
            self._draw_empty()
            return

        ax = self._new_axes()
        terrain = np.ma.masked_invalid(self.z)
        ax.plot_surface(
            self.x,
            self.y,
            terrain,
            cmap="turbo",
            linewidth=0,
            antialiased=False,
            alpha=0.82,
            rcount=min(90, self.z.shape[0]),
            ccount=min(90, self.z.shape[1]),
        )

        flooded = np.isfinite(self.z) & (self.z <= float(level))
        if flooded.any():
            water_surface = np.ma.masked_where(~flooded, np.full(self.z.shape, float(level)))
            ax.plot_surface(
                self.x,
                self.y,
                water_surface,
                color=WATER,
                linewidth=0,
                antialiased=True,
                alpha=0.62,
                shade=True,
                rcount=min(90, self.z.shape[0]),
                ccount=min(90, self.z.shape[1]),
            )

        ax.set_xlabel(self.x_label, fontsize=7, labelpad=2)
        ax.set_ylabel(self.y_label, fontsize=7, labelpad=2)
        ax.set_zlabel("Elevation (m)", fontsize=7, labelpad=2)
        ax.view_init(elev=28, azim=-58)
        ax.set_box_aspect((1.35, 1.0, 0.65))
        ax.xaxis.set_major_locator(MaxNLocator(4))
        ax.yaxis.set_major_locator(MaxNLocator(4))
        ax.zaxis.set_major_locator(MaxNLocator(5))
        self.figure.subplots_adjust(left=0.0, right=1.0, bottom=0.02, top=0.98)
        self.draw_idle()


class VolumeVisualizationWidget(QWidget):
    """Two-panel E-V/3-D result area used on the Volume Calculation page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.setStyleSheet(f"background-color: {BACKGROUND};")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 7, 18, 8)
        layout.setSpacing(18)

        curve_panel, curve_body, self.curve_status = self._create_panel(
            "E-V Curve (Interactive)", "Click a curve point to change the simulated water level"
        )
        self.curve_canvas = EVCurveCanvas(curve_body)
        curve_body.layout().addWidget(self.curve_canvas)
        layout.addWidget(curve_panel, 3)

        simulation_panel, simulation_body, self.simulation_status = self._create_panel(
            "3D Simulation", "Waiting for E-V results"
        )
        self.simulation_canvas = Lake3DCanvas(simulation_body)
        simulation_body.layout().addWidget(self.simulation_canvas)
        layout.addWidget(simulation_panel, 2)

        self.curve_canvas.level_selected.connect(self._select_level)

    @staticmethod
    def _create_panel(title, status):
        panel = QFrame()
        panel.setStyleSheet("QFrame { background: transparent; border: none; }")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(1)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 8, 0)
        header_layout.setSpacing(8)
        title_label = QLabel(f"›  {title}")
        title_label.setStyleSheet("color: #dffdf6; font-size: 12px; font-weight: 600;")
        status_label = QLabel(status)
        status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_label.setStyleSheet("color: #55b8c8; font-size: 9px;")
        status_label.setMinimumWidth(0)
        status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(status_label)
        panel_layout.addWidget(header)

        body = QWidget()
        body.setStyleSheet(f"background-color: {PANEL_BACKGROUND}; border-top: 1px solid #203036;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        panel_layout.addWidget(body, 1)
        return panel, body, status_label

    def set_busy(self, busy=True):
        if busy:
            self.curve_status.setText("Calculating elevation-volume samples…")
            self.simulation_status.setText("Preparing terrain model…")

    def set_error(self, message):
        self.curve_status.setText(message)
        if self.result:
            self.simulation_status.setText("Previous 3-D result retained")
        else:
            self.simulation_status.setText("No simulation result available")

    def set_result(self, result):
        self.result = result
        levels = np.asarray(result["levels"], dtype=float)
        volumes = np.asarray(result["volumes"], dtype=float)
        default_index = int(round((len(levels) - 1) * 0.70)) if len(levels) else 0
        self.simulation_canvas.set_terrain(
            result["terrain_x"],
            result["terrain_y"],
            result["terrain_z"],
            result.get("x_label", "X"),
            result.get("y_label", "Y"),
        )
        self.curve_canvas.set_data(levels, volumes, default_index)
        self._select_level(default_index)
        self.curve_status.setText("Click a point on the curve to update the 3-D water surface")

    def _select_level(self, index):
        if not self.result:
            return
        levels = np.asarray(self.result["levels"], dtype=float)
        volumes = np.asarray(self.result["volumes"], dtype=float)
        if levels.size == 0:
            return
        index = int(np.clip(index, 0, levels.size - 1))
        level = float(levels[index])
        volume = float(volumes[index])
        self.simulation_canvas.set_water_level(level)
        self.simulation_status.setText(
            f"Water level: {level:.2f} m   Volume: {volume:.4g} ×10⁸ m³"
        )
