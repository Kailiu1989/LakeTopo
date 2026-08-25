"""Grid-preserving DEM mosaic operations for LakeTopo."""

import os
import uuid

import numpy as np
from osgeo import gdal


MOSAIC_OPERATORS = (
    "Lake DEM Priority",
    "Maximum",
    "Minimum",
    "Mean",
)


def _report_progress(progress_callback, value, message):
    if progress_callback is not None:
        progress_callback(max(0, min(100, int(value))), str(message))


def _normalize_operator(operator):
    normalized = str(operator or "Lake DEM Priority").strip().lower()
    aliases = {
        "first": "Lake DEM Priority",
        "lake dem priority": "Lake DEM Priority",
        "maximum": "Maximum",
        "max": "Maximum",
        "minimum": "Minimum",
        "min": "Minimum",
        "mean": "Mean",
        "average": "Mean",
    }
    if normalized not in aliases:
        raise ValueError(
            f"Unsupported mosaic operator: {operator}. "
            f"Choose one of: {', '.join(MOSAIC_OPERATORS)}."
        )
    return aliases[normalized]


def _valid_mask(values, nodata):
    mask = np.isfinite(values)
    if nodata is None:
        return mask
    try:
        if np.isnan(nodata):
            return mask
    except TypeError:
        pass
    return mask & (values != nodata)


def _open_dem(path, label):
    dataset = gdal.Open(path, gdal.GA_ReadOnly)
    if dataset is None:
        raise FileNotFoundError(f"Cannot open {label}: {path}")
    if dataset.RasterCount < 1:
        dataset = None
        raise ValueError(f"{label} contains no raster band: {path}")
    if not dataset.GetProjection():
        dataset = None
        raise ValueError(f"{label} has no spatial reference: {path}")
    return dataset


def _combine_block(base, lake, base_nodata, lake_nodata, operator, output_nodata):
    base_valid = _valid_mask(base, base_nodata)
    lake_valid = _valid_mask(lake, lake_nodata)
    both_valid = base_valid & lake_valid
    lake_only = lake_valid & ~base_valid

    result = np.full(base.shape, output_nodata, dtype=np.float64)
    result[base_valid] = base[base_valid]

    if operator == "Lake DEM Priority":
        result[lake_valid] = lake[lake_valid]
    else:
        result[lake_only] = lake[lake_only]
        if operator == "Maximum":
            result[both_valid] = np.maximum(base[both_valid], lake[both_valid])
        elif operator == "Minimum":
            result[both_valid] = np.minimum(base[both_valid], lake[both_valid])
        elif operator == "Mean":
            result[both_valid] = (
                base[both_valid] + lake[both_valid]
            ) / 2.0

    return result, base_valid, lake_valid, both_valid


def run_mosaic_dem(
    lake_dem,
    mosaic_to_dem,
    output_raster,
    operator="Lake DEM Priority",
    progress_callback=None,
):
    """Align a lake DEM to the target DEM grid and combine valid pixels."""
    lake_dem = os.path.abspath(os.path.normpath(lake_dem))
    mosaic_to_dem = os.path.abspath(os.path.normpath(mosaic_to_dem))
    output_raster = os.path.abspath(os.path.normpath(output_raster))
    operator = _normalize_operator(operator)

    for label, path in (
        ("Lake DEM", lake_dem),
        ("Mosaic To DEM", mosaic_to_dem),
    ):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{label} file not found: {path}")

    output_key = os.path.normcase(output_raster)
    input_keys = {os.path.normcase(lake_dem), os.path.normcase(mosaic_to_dem)}
    if output_key in input_keys:
        raise ValueError(
            "Output Raster must be a new file; it cannot overwrite either input DEM."
        )

    output_dir = os.path.dirname(output_raster)
    if not output_dir or not os.path.isdir(output_dir):
        raise FileNotFoundError(f"Output directory not found: {output_dir}")

    _report_progress(progress_callback, 0, "Opening lake and target DEMs…")
    lake_ds = target_ds = aligned_lake_ds = output_ds = None
    temp_output = os.path.join(
        output_dir,
        f".{os.path.basename(output_raster)}.{uuid.uuid4().hex}.tmp.tif",
    )

    try:
        lake_ds = _open_dem(lake_dem, "Lake DEM")
        target_ds = _open_dem(mosaic_to_dem, "Mosaic To DEM")
        target_band = target_ds.GetRasterBand(1)
        lake_band = lake_ds.GetRasterBand(1)
        target_nodata = target_band.GetNoDataValue()
        source_lake_nodata = lake_band.GetNoDataValue()

        width = target_ds.RasterXSize
        height = target_ds.RasterYSize
        target_projection = target_ds.GetProjection()
        target_geotransform = target_ds.GetGeoTransform()

        _report_progress(
            progress_callback,
            8,
            f"Target grid: {height} rows × {width} columns.",
        )

        working_nodata = np.finfo(np.float64).min
        aligned_lake_ds = gdal.GetDriverByName("MEM").Create(
            "", width, height, 1, gdal.GDT_Float64
        )
        if aligned_lake_ds is None:
            raise RuntimeError("Failed to allocate the aligned Lake DEM grid.")
        aligned_lake_ds.SetProjection(target_projection)
        aligned_lake_ds.SetGeoTransform(target_geotransform)
        aligned_band = aligned_lake_ds.GetRasterBand(1)
        aligned_band.SetNoDataValue(float(working_nodata))
        aligned_band.Fill(float(working_nodata))

        last_warp_progress = [10]

        def warp_progress(complete, _message, _data):
            value = max(
                last_warp_progress[0],
                10 + int(float(complete) * 35),
            )
            last_warp_progress[0] = value
            _report_progress(
                progress_callback,
                value,
                "Aligning Lake DEM to the target grid…",
            )
            return 1

        warp_kwargs = {
            "dstSRS": target_projection,
            "dstNodata": float(working_nodata),
            "resampleAlg": gdal.GRA_Bilinear,
            "multithread": True,
            "callback": warp_progress,
        }
        if source_lake_nodata is not None:
            warp_kwargs["srcNodata"] = source_lake_nodata

        warped = gdal.Warp(
            aligned_lake_ds,
            lake_ds,
            options=gdal.WarpOptions(**warp_kwargs),
        )
        if warped is None or warped == 0:
            raise RuntimeError("Failed to align Lake DEM to the target DEM grid.")
        aligned_lake_ds.FlushCache()
        if hasattr(warped, "FlushCache"):
            warped.FlushCache()
        warped = None

        output_type = target_band.DataType
        if output_type not in (gdal.GDT_Float32, gdal.GDT_Float64):
            output_type = gdal.GDT_Float32
        output_numpy_type = (
            np.float32 if output_type == gdal.GDT_Float32 else np.float64
        )
        output_nodata = (
            float(target_nodata) if target_nodata is not None else float("nan")
        )

        _report_progress(progress_callback, 48, "Creating the output GeoTIFF…")
        output_ds = gdal.GetDriverByName("GTiff").Create(
            temp_output,
            width,
            height,
            1,
            output_type,
            options=[
                "TILED=YES",
                "COMPRESS=DEFLATE",
                "PREDICTOR=3",
                "BIGTIFF=IF_SAFER",
            ],
        )
        if output_ds is None:
            raise RuntimeError(f"Failed to create output raster: {output_raster}")
        output_ds.SetProjection(target_projection)
        output_ds.SetGeoTransform(target_geotransform)
        output_ds.SetMetadata(target_ds.GetMetadata())
        output_band = output_ds.GetRasterBand(1)
        output_band.SetNoDataValue(output_nodata)
        output_band.SetDescription(target_band.GetDescription())
        band_metadata = {
            key: value
            for key, value in target_band.GetMetadata().items()
            if not key.upper().startswith("STATISTICS_")
        }
        output_band.SetMetadata(band_metadata)
        if target_band.GetUnitType():
            output_band.SetUnitType(target_band.GetUnitType())

        total_lake_pixels = 0
        overlap_pixels = 0
        changed_pixels = 0
        block_height = min(512, max(1, height))

        for y_offset in range(0, height, block_height):
            rows = min(block_height, height - y_offset)
            base_values = target_band.ReadAsArray(0, y_offset, width, rows)
            lake_values = aligned_band.ReadAsArray(0, y_offset, width, rows)
            if base_values is None or lake_values is None:
                raise RuntimeError(
                    f"Failed to read mosaic data near target row {y_offset}."
                )
            base_values = base_values.astype(np.float64, copy=False)
            lake_values = lake_values.astype(np.float64, copy=False)
            (
                result,
                base_valid,
                lake_valid,
                both_valid,
            ) = _combine_block(
                base_values,
                lake_values,
                target_nodata,
                working_nodata,
                operator,
                output_nodata,
            )
            write_values = result.astype(output_numpy_type, copy=False)
            changed = lake_valid & (
                ~base_valid
                | ~np.isclose(
                    write_values,
                    base_values,
                    rtol=0.0,
                    atol=1e-5,
                    equal_nan=True,
                )
            )
            output_band.WriteArray(write_values, 0, y_offset)
            total_lake_pixels += int(lake_valid.sum())
            overlap_pixels += int(both_valid.sum())
            changed_pixels += int(changed.sum())
            _report_progress(
                progress_callback,
                52 + int(43 * (y_offset + rows) / max(1, height)),
                f"Combining DEM rows ({y_offset + rows}/{height})…",
            )

        if total_lake_pixels == 0:
            raise ValueError(
                "Lake DEM has no valid pixels within the Mosaic To DEM extent."
            )

        output_band.FlushCache()
        output_ds.FlushCache()
        output_band = None
        output_ds = None
        aligned_band = None
        aligned_lake_ds = None
        lake_ds = None
        target_ds = None

        for sidecar_suffix in (".aux.xml", ".ovr"):
            sidecar = output_raster + sidecar_suffix
            if os.path.isfile(sidecar):
                os.remove(sidecar)
        os.replace(temp_output, output_raster)
        _report_progress(progress_callback, 100, "DEM mosaic completed.")
        return {
            "output": output_raster,
            "operator": operator,
            "lake_pixels": total_lake_pixels,
            "overlap_pixels": overlap_pixels,
            "changed_pixels": changed_pixels,
            "width": width,
            "height": height,
        }
    finally:
        output_ds = None
        aligned_lake_ds = None
        lake_ds = None
        target_ds = None
        if os.path.isfile(temp_output):
            os.remove(temp_output)
