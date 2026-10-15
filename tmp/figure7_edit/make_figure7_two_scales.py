"""Regenerate Figure 7 with the two endpoint survey scales only.

The script is deliberately kept inside ``result_0828`` and reuses the
existing validation-figure readers, statistics, scatter styling, and export
helpers.  It does not modify LakeTopo's core modules or the metrics table.

The six lakes are arranged as two side-by-side blocks with three lake rows in
each block.  Within every lake row, the panel contract is:

1. XGBoost 1:25,000 predicted-only 5 m depth DEM.
2. XGBoost 1:250,000 predicted-only 5 m depth DEM.
3. Independent 1:25,000 observed-versus-predicted validation.
4. Independent 1:250,000 observed-versus-predicted validation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


RESULT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = RESULT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from validation_batch.make_validation_figures import (  # noqa: E402
    FIG7_LAKES,
    SCALE_LABELS,
    add_scatter_with_marginals,
    lake_display_name,
    read_csv_rows,
    read_raster,
    read_validation,
    resolve_result_path,
    write_csv_rows,
)


DEM_SCALES = ("1_25000", "1_250000")
VALIDATION_SCALES = ("1_25000", "1_250000")
VALIDATION_COLORS = {
    "1_25000": "#2278B5",
    "1_250000": "#2E8B57",
}
FIGURE7_DISPLAY_NAMES = {
    "Aletaiwurenhu6": "Aletaiwuren Lake No.6",
    "Wanghuapao": "Wanghua Lake",
    "Qionghai": "Qionghai Lake",
}


def figure7_display_name(lake: str) -> str:
    return FIGURE7_DISPLAY_NAMES.get(lake, lake_display_name(lake))


def refresh_selection_display_names(figure_dir: Path) -> None:
    """Keep the Figure 7 selection table consistent with visible labels."""
    selection_path = figure_dir / "Figure_7_selected_lakes.csv"
    if not selection_path.is_file():
        return
    rows = read_csv_rows(selection_path)
    if not rows:
        return
    for row in rows:
        row["display_name"] = figure7_display_name(row["lake"])
    write_csv_rows(selection_path, rows, list(rows[0]))


def export_figure(figure: plt.Figure, destination: Path) -> None:
    """Write editable/vector exports plus a memory-safe 600 dpi TIFF."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination.with_suffix(".svg"), format="svg")
    figure.savefig(destination.with_suffix(".pdf"), format="pdf")
    figure.savefig(destination.with_suffix(".png"), dpi=300)

    high_resolution_png = destination.with_name(
        f"{destination.name}_600dpi_working.png"
    )
    figure.savefig(high_resolution_png, dpi=600)
    plt.close(figure)
    with Image.open(high_resolution_png) as rendered:
        rendered.convert("RGB").save(
            destination.with_suffix(".tif"),
            # The LakeTopo environment's libtiff build is unstable with LZW
            # on this large plate; raw TIFF is lossless and reproducible.
            compression="raw",
            dpi=(600, 600),
        )
    high_resolution_png.unlink()


def add_equal_frame_terrain_panel(
    figure: plt.Figure,
    subplot_spec,
    values: np.ndarray,
    maximum: float,
    *,
    title: str | None,
    row_label: str | None,
) -> None:
    """Draw a lake inside a fixed-size outer DEM frame.

    The outer frame and colorbar geometry are identical for every lake and
    scale.  Only the frameless image inset changes size to preserve each
    raster's native aspect ratio.
    """
    holder = figure.add_subplot(subplot_spec)
    holder.set_axis_off()
    holder.set_box_aspect(1)

    frame_left = 0.080
    frame_bottom = 0.225
    frame_width = 0.900
    frame_height = 0.655

    frame = holder.inset_axes(
        [frame_left, frame_bottom, frame_width, frame_height]
    )
    frame.set_xlim(0, 1)
    frame.set_ylim(0, 1)
    frame.set_xticks([])
    frame.set_yticks([])
    frame.patch.set_facecolor("white")
    for spine in frame.spines.values():
        spine.set_visible(True)
        spine.set_color("#606060")
        spine.set_linewidth(0.45)

    raster_aspect = values.shape[0] / values.shape[1]
    available_width = frame_width * 0.965
    available_height = frame_height * 0.955
    if raster_aspect <= available_height / available_width:
        image_width = available_width
        image_height = image_width * raster_aspect
    else:
        image_height = available_height
        image_width = image_height / raster_aspect
    image_left = frame_left + (frame_width - image_width) / 2.0
    image_bottom = frame_bottom + (frame_height - image_height) / 2.0

    image_axis = holder.inset_axes(
        [image_left, image_bottom, image_width, image_height]
    )
    image = image_axis.imshow(
        values,
        cmap="RdYlBu",
        vmin=0,
        vmax=maximum,
        interpolation="nearest",
        aspect="auto",
    )
    image_axis.set_xticks([])
    image_axis.set_yticks([])
    image_axis.patch.set_alpha(0)
    for spine in image_axis.spines.values():
        spine.set_visible(False)

    colorbar_axis = holder.inset_axes(
        [frame_left, 0.125, frame_width, 0.038]
    )
    colorbar = figure.colorbar(image, cax=colorbar_axis, orientation="horizontal")
    colorbar.set_ticks([0.0, maximum])
    colorbar.set_ticklabels(["0", f"{maximum:.2f}"])
    colorbar.ax.tick_params(labelsize=5, length=1.5, pad=1)
    colorbar.outline.set_linewidth(0.4)
    colorbar.ax.text(
        0.99,
        1.45,
        "(m)",
        transform=colorbar.ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=5,
    )

    if title:
        holder.text(
            0.512,
            0.975,
            title,
            transform=holder.transAxes,
            ha="center",
            va="top",
            fontsize=8,
            fontweight="bold",
        )
    if row_label:
        holder.text(
            0.018,
            frame_bottom + frame_height / 2.0,
            row_label,
            transform=holder.transAxes,
            rotation=90,
            ha="center",
            va="center",
            fontsize=8,
            fontweight="bold",
        )


def make_figure7(output_root: Path, figure_dir: Path) -> None:
    metrics = read_csv_rows(output_root / "metrics" / "validation_metrics.csv")
    lookup = {
        (row["zone"], row["lake"], row["scale"], row["model"]): row
        for row in metrics
    }

    selected = list(FIG7_LAKES)
    lake_blocks = (selected[:3], selected[3:])
    figure = plt.figure(figsize=(13.90, 5.65))
    outer_layout = figure.add_gridspec(
        3,
        2,
        left=0.022,
        right=0.998,
        bottom=0.025,
        top=0.965,
        wspace=0.035,
        hspace=0.070,
    )

    for block_index, block_lakes in enumerate(lake_blocks):
        for row_index, (zone, lake) in enumerate(block_lakes):
            row_layout = outer_layout[row_index, block_index].subgridspec(
                1,
                6,
                # Narrow label/marginal gutters only; plotted panels have no
                # additional GridSpec whitespace inside either lake block.
                width_ratios=(1.0, 1.0, 0.11, 1.0, 0.05, 1.0),
                wspace=0.0,
            )

            raster_data: dict[str, np.ndarray] = {}
            for scale in DEM_SCALES:
                key = (zone, lake, scale, "XGBoost")
                if key not in lookup:
                    raise RuntimeError(f"Missing Figure 7 metric row: {key}")
                raster_path = resolve_result_path(
                    output_root, lookup[key]["topography_tif"]
                )
                raster_data[scale], _ = read_raster(raster_path)

            finite_values = np.concatenate(
                [array[np.isfinite(array)] for array in raster_data.values()]
            )
            maximum = max(float(np.nanmax(finite_values)), 0.1)

            for column_index, scale in enumerate(DEM_SCALES):
                add_equal_frame_terrain_panel(
                    figure,
                    row_layout[column_index],
                    raster_data[scale],
                    maximum,
                    title=SCALE_LABELS[scale] if row_index == 0 else None,
                    row_label=(
                        figure7_display_name(lake)
                        if column_index == 0
                        else None
                    ),
                )

            for offset, scale in enumerate(VALIDATION_SCALES):
                key = (zone, lake, scale, "XGBoost")
                prediction_path = resolve_result_path(
                    output_root, lookup[key]["validation_predictions"]
                )
                observed, predicted = read_validation(prediction_path)
                add_scatter_with_marginals(
                    figure,
                    row_layout[3 + 2 * offset],
                    observed,
                    predicted,
                    VALIDATION_COLORS[scale],
                    (
                        f"Validation {SCALE_LABELS[scale]}"
                        if row_index == 0
                        else None
                    ),
                )

    export_figure(
        figure,
        figure_dir / "Figure_7_XGBoost_25000_vs_250000",
    )


def main() -> None:
    output_root = RESULT_ROOT
    figure_dir = output_root / "figures"
    refresh_selection_display_names(figure_dir)
    make_figure7(output_root, figure_dir)
    print(f"Updated Figure 7 exports: {figure_dir}")


if __name__ == "__main__":
    main()
