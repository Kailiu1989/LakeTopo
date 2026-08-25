import rasterProcessing
import Common_Function as cf
import math
import gc
import numpy
from osgeo import gdal, ogr, osr
import os
from collections import Counter

try:
    from scipy.spatial import cKDTree
except ImportError:
    cKDTree = None

# 避免除零错误
EPS = 0.0001
EARTH_RADIUS_M = 6371008.8


def _report_progress(progress_callback, value, message):
    """Report bounded integer progress without coupling the backend to Qt."""
    if progress_callback is not None:
        progress_callback(max(0, min(100, int(value))), message)


def _valid_raster_mask(raster):
    """Return a boolean mask for finite, non-NoData raster cells."""
    data = numpy.asarray(raster.GetMatrix())
    mask = numpy.isfinite(data)
    nodata = raster.NodataValue()
    if nodata is not None:
        try:
            nodata_is_nan = bool(numpy.isnan(nodata))
        except TypeError:
            nodata_is_nan = False
        if not nodata_is_nan:
            mask &= data != nodata
    return mask


def _is_valid_raster_value(raster, value):
    """Return True only for finite values that are not the raster NoData value."""
    if value is None:
        return False
    try:
        if not numpy.isfinite(value):
            return False
    except TypeError:
        return False
    nodata = raster.NodataValue()
    if nodata is None:
        return True
    try:
        if numpy.isnan(nodata):
            return True
    except TypeError:
        pass
    return value != nodata


def _sample_raster_at_xy(raster, x_coord, y_coord):
    """Sample one raster using that raster's own coordinate-to-index mapping."""
    relative_row = (raster.YTopLeft() - y_coord) / raster.CellSizeY()
    relative_col = (x_coord - raster.XTopLeft()) / raster.CellSize()
    if (
        relative_row < 0
        or relative_row >= raster.NRow()
        or relative_col < 0
        or relative_col >= raster.NCol()
    ):
        return None
    row = int(math.floor(relative_row))
    col = int(math.floor(relative_col))
    value = raster.GetValue(row, col)
    return float(value) if _is_valid_raster_value(raster, value) else None


def _spatial_reference(projection_wkt, label):
    if not projection_wkt:
        raise ValueError(f"{label} raster has no coordinate reference system.")
    spatial_ref = osr.SpatialReference()
    if spatial_ref.ImportFromWkt(projection_wkt) != 0:
        raise ValueError(f"Cannot read the coordinate reference system of {label} raster.")
    if hasattr(spatial_ref, "SetAxisMappingStrategy"):
        spatial_ref.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return spatial_ref


def _validate_matching_crs(named_projections):
    """Fail early when rasters cannot be sampled in one shared coordinate space."""
    items = list(named_projections.items())
    if not items:
        return
    base_name, base_wkt = items[0]
    base_ref = _spatial_reference(base_wkt, base_name)
    for name, projection_wkt in items[1:]:
        candidate_ref = _spatial_reference(projection_wkt, name)
        if not bool(base_ref.IsSame(candidate_ref)):
            raise ValueError(
                f"Raster projection mismatch: {base_name} and {name}. "
                "Reproject the rasters to one CRS before generating prediction points."
            )


class _SpatialMetric:
    """Convert raster coordinates to a local metric space derived from the raster CRS."""

    def __init__(self, projection_wkt, reference_raster):
        spatial_ref = _spatial_reference(projection_wkt, "reference")
        self._reference_x = (
            reference_raster.XTopLeft()
            + reference_raster.CellSize() * (reference_raster.NCol() - 1) / 2.0
        )
        self._reference_y = (
            reference_raster.YTopLeft()
            - reference_raster.CellSizeY() * (reference_raster.NRow() - 1) / 2.0
        )
        self._is_geographic = bool(spatial_ref.IsGeographic())
        if self._is_geographic:
            self._angular_to_radians = float(spatial_ref.GetAngularUnits() or (math.pi / 180.0))
            reference_latitude = self._reference_y * self._angular_to_radians
            self._cos_reference_latitude = max(abs(math.cos(reference_latitude)), 1e-12)
            self._linear_units_to_metres = None
        elif spatial_ref.IsProjected():
            self._linear_units_to_metres = float(spatial_ref.GetLinearUnits() or 1.0)
            self._angular_to_radians = None
            self._cos_reference_latitude = None
        else:
            raise ValueError("Unsupported raster coordinate reference system.")

    def to_metric(self, x_coord, y_coord):
        x_values = numpy.asarray(x_coord, dtype=numpy.float64)
        y_values = numpy.asarray(y_coord, dtype=numpy.float64)
        if self._is_geographic:
            x_metres = (
                (x_values - self._reference_x)
                * self._angular_to_radians
                * EARTH_RADIUS_M
                * self._cos_reference_latitude
            )
            y_metres = (
                (y_values - self._reference_y)
                * self._angular_to_radians
                * EARTH_RADIUS_M
            )
        else:
            x_metres = (x_values - self._reference_x) * self._linear_units_to_metres
            y_metres = (y_values - self._reference_y) * self._linear_units_to_metres
        return x_metres, y_metres

    def from_metric(self, x_metres, y_metres):
        x_values = numpy.asarray(x_metres, dtype=numpy.float64)
        y_values = numpy.asarray(y_metres, dtype=numpy.float64)
        if self._is_geographic:
            x_coord = self._reference_x + x_values / (
                self._angular_to_radians
                * EARTH_RADIUS_M
                * self._cos_reference_latitude
            )
            y_coord = self._reference_y + y_values / (
                self._angular_to_radians * EARTH_RADIUS_M
            )
        else:
            x_coord = self._reference_x + x_values / self._linear_units_to_metres
            y_coord = self._reference_y + y_values / self._linear_units_to_metres
        return x_coord, y_coord

    def distance(self, x1, y1, x2, y2):
        metric_x1, metric_y1 = self.to_metric(x1, y1)
        metric_x2, metric_y2 = self.to_metric(x2, y2)
        return float(numpy.hypot(metric_x2 - metric_x1, metric_y2 - metric_y1))

    def pixel_size_metres(self, raster):
        center_x = raster.GetXCoordByCol(raster.NCol() // 2)
        center_y = raster.GetYCoordByRow(raster.NRow() // 2)
        x_size = self.distance(
            center_x,
            center_y,
            center_x + raster.CellSize(),
            center_y,
        )
        y_size = self.distance(
            center_x,
            center_y,
            center_x,
            center_y - raster.CellSizeY(),
        )
        return x_size, y_size


class _ShorelineKDTree:
    """Exact nearest-shoreline lookup in CRS-aware local metric space."""

    def __init__(self, shoreline_raster, spatial_metric):
        if cKDTree is None:
            raise RuntimeError(
                "SciPy is required for shoreline KDTree lookup. Install the 'scipy' package."
            )
        cells = numpy.argwhere(_valid_raster_mask(shoreline_raster))
        if cells.size == 0:
            raise ValueError("The shoreline raster contains no valid cells.")
        self._cells = cells.astype(numpy.float64, copy=False)
        self._raster = shoreline_raster
        self._spatial_metric = spatial_metric
        x_coords = (
            shoreline_raster.XTopLeft()
            + self._cells[:, 1] * shoreline_raster.CellSize()
        )
        y_coords = (
            shoreline_raster.YTopLeft()
            - self._cells[:, 0] * shoreline_raster.CellSizeY()
        )
        x_metres, y_metres = spatial_metric.to_metric(x_coords, y_coords)
        self._tree = cKDTree(numpy.column_stack([x_metres, y_metres]))

    def __len__(self):
        return len(self._cells)

    def nearest(self, x_coord, y_coord):
        """Return nearest shoreline row, column, and automatically derived metric distance."""
        x_metres, y_metres = self._spatial_metric.to_metric(x_coord, y_coord)
        distance_metres, cell_index = self._tree.query(
            (float(x_metres), float(y_metres)), k=1
        )
        target_row, target_col = self._cells[int(cell_index)]
        return (
            int(target_row),
            int(target_col),
            float(distance_metres),
        )


def _ensure_real_field(layer, field_name, source_path):
    """Create one real-valued field only when it is not already present."""
    layer_definition = layer.GetLayerDefn()
    existing_names = {
        layer_definition.GetFieldDefn(index).GetName().lower()
        for index in range(layer_definition.GetFieldCount())
    }
    if field_name.lower() in existing_names:
        return False
    result = layer.CreateField(ogr.FieldDefn(field_name, ogr.OFTReal))
    if result != 0:
        raise RuntimeError(f"Failed to create the {field_name} field in: {source_path}")
    return True

# =========================
# 工具函数：栅格自检（可选）
# =========================
def _print_grid_info(name, R):
    try:
        print(
            f"{name}: size=({R.NRow()},{R.NCol()}), "
            f"cell=({R.CellSize()},{R.CellSizeY()}), "
            f"origin=({R.XTopLeft()},{R.YTopLeft()})"
        )
    except Exception as e:
        print(f"{name}: print grid info failed: {e}")

def _with_sep(path):
    return os.path.normpath(path) + os.sep

def _resolve_workspace(workSPDir, lakeName=None):
    workspace = os.path.normpath(workSPDir)
    lake = str(lakeName).strip() if lakeName else os.path.basename(workspace)
    legacy_workspace = os.path.join(workspace, lake) if lake else workspace

    if lake and os.path.basename(workspace) != lake and os.path.isdir(legacy_workspace):
        workspace = legacy_workspace
    else:
        lake = os.path.basename(workspace)

    return _with_sep(workspace), lake

def _lake_file(workSPDir, lakeName, suffix):
    lower_path = workSPDir + str(lakeName) + suffix
    upper_path = workSPDir + str(lakeName) + suffix.replace("_slope", "_Slope")
    if suffix.startswith("_slope") and os.path.exists(upper_path):
        return upper_path
    return lower_path

def _resolve_dem_file(workSPDir, lakeName, demFile=None):
    if demFile:
        return os.path.normpath(demFile)
    lower_path = workSPDir + str(lakeName) + "_merit.tif"
    legacy_path = workSPDir + str(lakeName) + "_Merit.tif"
    if os.path.exists(lower_path):
        return lower_path
    if os.path.exists(legacy_path):
        return legacy_path
    return lower_path

def _resolve_survey_file(workSPDir, lakeName, surveyFile=None):
    if surveyFile:
        return os.path.normpath(surveyFile)
    return workSPDir + str(lakeName) + "_Survey.shp"

def _remove_file_if_exists(path):
    if os.path.exists(path):
        os.remove(path)

# =========================
# 1) 判断边界像元（更稳健，含防越界）
# =========================
def isBoundary(Raster, row, col, lake_value):
    # 中心像元必须是湖值，否则不是边界
    if Raster.GetValue(row, col) != lake_value:
        return 0
    # 8 邻域，只要越界或邻居≠湖值即为边界
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            r, c = row + dr, col + dc
            if r < 0 or r >= Raster.NRow() or c < 0 or c >= Raster.NCol():
                return 1
            if Raster.GetValue(r, c) != lake_value:
                return 1
    return 0

# =========================
# 2) 提取湖泊边界（自动识别主湖值）
# =========================
def boundary_extraction(lakeareaRaster, progress_callback=None):
    boundaryRaster = rasterProcessing.Raster(
        lakeareaRaster.XTopLeft(), lakeareaRaster.YTopLeft(),
        lakeareaRaster.CellSize(), lakeareaRaster.NRow(),
        lakeareaRaster.NCol(), -9999, yCellSize=lakeareaRaster.CellSizeY()
    )
    nodataValue = lakeareaRaster.NodataValue()

    # 自动推断湖区主值（若你确定湖区值=1，可直接 LAKE_VALUE = 1）
    vals = []
    row_count = lakeareaRaster.NRow()
    last_percent = -1
    for r in range(row_count):
        for c in range(lakeareaRaster.NCol()):
            v = lakeareaRaster.GetValue(r, c)
            if v != nodataValue:
                vals.append(int(v))
        percent = 4 + int(6 * (r + 1) / max(1, row_count))
        if percent != last_percent:
            _report_progress(progress_callback, percent, "Scanning the lake extent…")
            last_percent = percent
    LAKE_VALUE = Counter(vals).most_common(1)[0][0] if vals else 1

    last_percent = -1
    for row in range(row_count):
        for col in range(lakeareaRaster.NCol()):
            if isBoundary(lakeareaRaster, row, col, LAKE_VALUE):
                boundaryRaster.SetValue(row, col, 1)
            else:
                boundaryRaster.SetValue(row, col, -9999)
        percent = 10 + int(8 * (row + 1) / max(1, row_count))
        if percent != last_percent:
            _report_progress(progress_callback, percent, "Extracting the lake boundary…")
            last_percent = percent
    return boundaryRaster

# =========================
# 3) 处理湖泊边界并更新属性
# =========================
def boundary_processing(
    workSPDir,
    lakeName,
    demFile=None,
    progress_callback=None,
    lakePolygonFile=None,
):
    workSPDir, lakeName = _resolve_workspace(workSPDir, lakeName)
    LakePoly = (
        os.path.normpath(lakePolygonFile)
        if lakePolygonFile
        else workSPDir + str(lakeName) + ".shp"
    )
    raster = rasterProcessing.RasterIO()
    lakeareaFile =  workSPDir + str(lakeName) + "_extent.tif"
    lakeshorelineFile =  workSPDir + str(lakeName) + "_shoreline.tif"
    _report_progress(progress_callback, 2, "Opening the lake extent raster…")
    proj, im_geotrans, lakeRaster = raster.read_img(lakeareaFile)
    boundaryRaster = boundary_extraction(lakeRaster, progress_callback)
    _report_progress(progress_callback, 19, "Writing the shoreline raster…")
    raster.write_Tif(lakeshorelineFile, proj, im_geotrans, boundaryRaster, -9999)
    
    # 打开湖泊shp文件 shapefile
    driver = ogr.GetDriverByName("ESRI Shapefile")
    dataSource = driver.Open(LakePoly, 1)  # 1 means writable
    if dataSource is None:
        raise FileNotFoundError(f"Cannot open lake polygon: {LakePoly}")
    layer = dataSource.GetLayer()
    
    # 仅在字段不存在时创建，避免重复运行生成 Ele_1、Ele_2 等字段。
    _ensure_real_field(layer, "Ele", LakePoly)
    
    # 获取湖泊水位
    _report_progress(progress_callback, 23, "Calculating the shoreline elevation…")
    lakelevel = getLakelevel(workSPDir, lakeName, demFile)
    
    # 更新字段值为湖泊水位
    for feature in layer:
        feature.SetField("Ele", float(lakelevel))
        layer.SetFeature(feature)
    
    # Clean up
    dataSource = None
    _report_progress(progress_callback, 29, "Lake boundary processing completed.")
    return float(lakelevel)

# =========================
# 4) 计算湖泊水位（路径统一 _Slope.tif）
# =========================
def getLakelevel(_workSP, lakeName, demFile=None):
    _workSP, lakeName = _resolve_workspace(_workSP, lakeName)
    slopeFile = _lake_file(_workSP, lakeName, "_slope.tif")
    lakeshorelineFile = _lake_file(_workSP, lakeName, "_shoreline.tif")
    demFile = _resolve_dem_file(_workSP, lakeName, demFile)
    raster = rasterProcessing.RasterIO()
    lake_proj, im_geotrans, lakeRaster = raster.read_img(lakeshorelineFile)
    slope_proj, im_geotrans, slopeRaster = raster.read_img(slopeFile)
    dem_proj, im_geotrans, demRaster = raster.read_img(demFile)
    _validate_matching_crs(
        {
            "shoreline": lake_proj,
            "slope": slope_proj,
            "DEM": dem_proj,
        }
    )
    boundaryList = []
    for row in range(0, lakeRaster.NRow()):
        for col in range(0, lakeRaster.NCol()):
            if lakeRaster.GetValue(row, col) != 1:
                continue
            x_coord = lakeRaster.GetXCoordByCol(col)
            y_coord = lakeRaster.GetYCoordByRow(row)
            slope_value = _sample_raster_at_xy(slopeRaster, x_coord, y_coord)
            dem_value = _sample_raster_at_xy(demRaster, x_coord, y_coord)
            if slope_value is not None and dem_value is not None and slope_value < 1:
                boundaryList.append(dem_value)

    if len(boundaryList) == 0:
        return float('nan')

    mean = numpy.mean(boundaryList)
    std = numpy.std(boundaryList)
    revisedValue = []
    for i in range(0, len(boundaryList)):
        if boundaryList[i] <= (mean + 2 * std) and boundaryList[i] >= (mean - 2 * std):
            revisedValue.append(boundaryList[i])
    return float(numpy.median(revisedValue)) if len(revisedValue) > 0 else float(numpy.median(boundaryList))

# =========================
# 5) 预测点 topo 信息（保持原逻辑）
# =========================
def determine_predictedpoints_info(
    _workSP,
    _lakename,
    _para_intervalList,
    _demFile=None,
    progress_callback=None,
    shoreline_index=None,
    lakelevel=None,
    spatial_metric=None,
):
    demFile = _resolve_dem_file(_with_sep(_workSP), _lakename, _demFile)
    slopeFile = _workSP + "\\" + _lakename + "_Slope.tif"
    lakeareaFile = _workSP + "\\" + _lakename + "_extent.tif"
    lakeshorelineFile = _workSP + "\\" + _lakename + "_shoreline.tif"
    raster = rasterProcessing.RasterIO()
    dem_proj, im_geotrans, demRaster = raster.read_img(demFile)
    slope_proj, im_geotrans, slopeRaster = raster.read_img(slopeFile)
    lake_proj, im_geotrans, lakeRaster = raster.read_img(lakeareaFile)
    shoreline_proj, im_geotrans, lakeshorelineRaster = raster.read_img(lakeshorelineFile)
    _validate_matching_crs(
        {
            "lake extent": lake_proj,
            "shoreline": shoreline_proj,
            "DEM": dem_proj,
            "slope": slope_proj,
        }
    )
    if spatial_metric is None:
        spatial_metric = _SpatialMetric(lake_proj, lakeRaster)
    _txtFile = _workSP + "\\" + _lakename + "\\MLData\\Test_" + str(_para_intervalList[0]) + ".txt"
    topoinfoList = []
    _report_progress(progress_callback, 69, "Preparing prediction-point terrain data…")
    if shoreline_index is None:
        shoreline_index = _ShorelineKDTree(lakeshorelineRaster, spatial_metric)
    if lakelevel is None:
        lakelevel = get_lakeLevel(lakeshorelineRaster, demRaster, slopeRaster)
    interval_count = max(1, len(_para_intervalList))
    for i in range(0, len(_para_intervalList)):
        curInterval = _para_intervalList[i]
        topoinfoList = []
        rows = range(0, lakeRaster.NRow(), curInterval)
        row_count = len(rows)
        interval_start = 70 + (28 * i / interval_count)
        interval_end = 70 + (28 * (i + 1) / interval_count)
        last_percent = -1
        for row_index, row in enumerate(rows):
            for col in range(0, lakeRaster.NCol(), curInterval):
                tempValue = lakeRaster.GetValue(row, col)
                tempLakeSL = lakeshorelineRaster.GetValue(row, col)
                if (
                    _is_valid_raster_value(lakeRaster, tempValue)
                    and not _is_valid_raster_value(lakeshorelineRaster, tempLakeSL)
                ):
                    xLake = lakeRaster.GetXCoordByCol(col)
                    yLake = lakeRaster.GetYCoordByRow(row)
                    targetRow, targetCol, distance = shoreline_index.nearest(xLake, yLake)
                    if distance < 100:
                        continue
                    xBoundary = lakeshorelineRaster.GetXCoordByCol(targetCol)
                    yBoundary = lakeshorelineRaster.GetYCoordByRow(targetRow)
                    info = get_topoInfo(
                        lakeRaster,
                        lakeshorelineRaster,
                        demRaster,
                        slopeRaster,
                        distance,
                        xBoundary,
                        yBoundary,
                        xLake,
                        yLake,
                        lakelevel,
                        spatial_metric,
                    )
                    if info != -1:
                        topoinfoList.append(info)
            percent = int(
                interval_start
                + (interval_end - interval_start) * (row_index + 1) / max(1, row_count)
            )
            if percent != last_percent:
                _report_progress(
                    progress_callback,
                    percent,
                    f"Generating prediction points ({row_index + 1}/{row_count} rows)…",
                )
                last_percent = percent
        _txtFile = _workSP + "MLData\\Test_" + str(curInterval) + ".txt"
        _remove_file_if_exists(_txtFile)
        print("processing:" + str(_txtFile))
        cf.writeToTXT(topoinfoList, len(topoinfoList), _txtFile)
    gc.collect()
    _report_progress(progress_callback, 99, "Prediction-point data written.")

# =========================
# 6) Survey 点 topo 信息（关键改动：对齐与兜底）
# =========================
def rasterize_survey_to_template(survey_shp, out_tif, template_raster, proj_wkt):
    """将 Survey.shp 栅格化到模板栅格（湖区）的同一网格/投影上"""
    x_res = template_raster.NCol()
    y_res = template_raster.NRow()
    gt = (
        template_raster.XTopLeft(),
        template_raster.CellSize(),
        0.0,
        template_raster.YTopLeft(),
        0.0,
        -template_raster.CellSizeY(),
    )
    srs = osr.SpatialReference()
    srs.ImportFromWkt(proj_wkt)

    dst = gdal.GetDriverByName('GTiff').Create(out_tif, x_res, y_res, 1, gdal.GDT_Float32)
    dst.SetGeoTransform(gt)
    dst.SetProjection(srs.ExportToWkt())
    band = dst.GetRasterBand(1)
    band.SetNoDataValue(-9999)
    band.Fill(-9999)

    ds = ogr.Open(survey_shp)
    lyr = ds.GetLayer()
    # 若只需“有无点”，可改为 options=["BURN_VALUES=1","ALL_TOUCHED=TRUE"]
    gdal.RasterizeLayer(dst, [1], lyr, options=["ATTRIBUTE=Depth", "ALL_TOUCHED=TRUE"])
    dst = None
    ds = None

def determine_surveypoints_info(
    _workSP,
    _lakename,
    _demFile=None,
    _surveyFile=None,
    progress_callback=None,
    lakelevel=None,
):
    demFile = _resolve_dem_file(_with_sep(_workSP), _lakename, _demFile)
    slopeFile = _workSP + _lakename + "_Slope.tif"
    lakeareaFile = _workSP + _lakename + "_extent.tif"
    survey_file = _resolve_survey_file(_with_sep(_workSP), _lakename, _surveyFile)
    surveyRasterFile = _workSP + _lakename + "_Survey.tif"
    lakeshorelineFile = _workSP + _lakename + "_shoreline.tif"
    _txtFile = _workSP + "MLData\\Training.txt"

    # 统计计数器
    total = used = tooClose = noBoundary = failedTopo = 0

    # 读入模板栅格并对齐栅格化 Survey
    _report_progress(progress_callback, 30, "Opening survey terrain rasters…")
    raster = rasterProcessing.RasterIO()
    dem_proj, im_geotrans, demRaster = raster.read_img(demFile)
    slope_proj, im_geotrans, slopeRaster = raster.read_img(slopeFile)
    lake_proj, im_geotrans, lakeRaster = raster.read_img(lakeareaFile)
    shoreline_proj, im_geotrans, lakeshorelineRaster = raster.read_img(lakeshorelineFile)
    _validate_matching_crs(
        {
            "lake extent": lake_proj,
            "shoreline": shoreline_proj,
            "DEM": dem_proj,
            "slope": slope_proj,
        }
    )
    spatial_metric = _SpatialMetric(lake_proj, lakeRaster)

    # ★ 用湖区模板进行重栅格化，确保逐像元对齐
    _report_progress(progress_callback, 34, "Rasterizing in-situ bathymetry points…")
    rasterize_survey_to_template(survey_file, surveyRasterFile, lakeRaster, lake_proj)
    proj, im_geotrans, surveyLineRaster = raster.read_img(surveyRasterFile)

    # 自检信息（需要可保留）
    _print_grid_info("lake", lakeRaster)
    _print_grid_info("shore", lakeshorelineRaster)
    _print_grid_info("survey", surveyLineRaster)
    _print_grid_info("dem", demRaster)
    _print_grid_info("slope", slopeRaster)
    lake_pixel_x, lake_pixel_y = spatial_metric.pixel_size_metres(lakeRaster)
    dem_pixel_x, dem_pixel_y = spatial_metric.pixel_size_metres(demRaster)
    print(
        "automatic metric pixel size: "
        f"lake=({lake_pixel_x:.3f},{lake_pixel_y:.3f}) m, "
        f"DEM=({dem_pixel_x:.3f},{dem_pixel_y:.3f}) m"
    )
    # 岸线非空抽样统计
    shore_cnt = 0
    step_r = max(1, lakeshorelineRaster.NRow() // 200)
    step_c = max(1, lakeshorelineRaster.NCol() // 200)
    for r in range(0, lakeshorelineRaster.NRow(), step_r):
        for c in range(0, lakeshorelineRaster.NCol(), step_c):
            if lakeshorelineRaster.GetValue(r, c) != lakeshorelineRaster.NodataValue():
                shore_cnt += 1
    print("shoreline non-nodata samples:", shore_cnt)

    if lakelevel is None:
        lakelevel = get_lakeLevel(lakeshorelineRaster, demRaster, slopeRaster)

    _report_progress(progress_callback, 38, "Building the shoreline KDTree…")
    shoreline_index = _ShorelineKDTree(lakeshorelineRaster, spatial_metric)
    print("shoreline KDTree cells:", len(shoreline_index))

    topoinfoList = []
    survey_data = numpy.asarray(surveyLineRaster.GetMatrix())
    survey_mask = _valid_raster_mask(surveyLineRaster) & (survey_data > 0)
    survey_cells = numpy.argwhere(survey_mask)
    total = len(survey_cells)
    report_stride = max(1, total // 200)

    for point_index, (row, col) in enumerate(survey_cells):
        row = int(row)
        col = int(col)
        xLake = lakeRaster.GetXCoordByCol(col)
        yLake = lakeRaster.GetYCoordByRow(row)
        targetRow, targetCol, distance = shoreline_index.nearest(xLake, yLake)

        # 业务阈值：过近则跳过（你原来用 <10）
        if distance < 10:
            tooClose += 1
        else:
            xBoundary = lakeshorelineRaster.GetXCoordByCol(targetCol)
            yBoundary = lakeshorelineRaster.GetYCoordByRow(targetRow)
            info = get_topoInfo(
                lakeRaster,
                lakeshorelineRaster,
                demRaster,
                slopeRaster,
                distance,
                xBoundary,
                yBoundary,
                xLake,
                yLake,
                lakelevel,
                spatial_metric,
            )

            if info == -1:
                failedTopo += 1
            else:
                info = info + "," + str(survey_data[row, col])
                topoinfoList.append(info)
                used += 1

        processed = point_index + 1
        if processed % report_stride == 0 or processed == total:
            percent = 43 + int(24 * processed / max(1, total))
            _report_progress(
                progress_callback,
                percent,
                f"Extracting survey-point terrain data ({processed}/{total} points)…",
            )

    _report_progress(progress_callback, 68, "Writing model training data…")
    _remove_file_if_exists(_txtFile)
    cf.writeToTXT(topoinfoList, len(topoinfoList), _txtFile)

    # 输出统计信息
    print("\n===== Survey 点使用情况统计 =====")
    print(f"总点数: {total}")
    print(f"✅ 参与训练的点: {used}")
    print(f"❌ 距离边界过近: {tooClose}")
    print(f"❌ 找不到边界: {noBoundary}")
    print(f"❌ 提取地形失败: {failedTopo}")
    print("================================\n")
    return shoreline_index, float(lakelevel), spatial_metric

# =========================
# 7) 计算沿真实米制射线的地形信息
# =========================
def get_topoInfo(
    _lakeRaster,
    _lakeshorelineRaster,
    _demRaster,
    _slopeRaster,
    _distance,
    _coordX,
    _coordY,
    _coordLX,
    _coordLY,
    _lakelevel=None,
    _spatial_metric=None,
):
    max_buffer_metres = 1000.0
    target_distances = (300.0, 600.0, 900.0)
    lakelevel = (
        float(_lakelevel)
        if _lakelevel is not None
        else get_lakeLevel(_lakeshorelineRaster, _demRaster, _slopeRaster)
    )
    if not numpy.isfinite(lakelevel):
        return -1

    spatial_metric = _spatial_metric
    if spatial_metric is None:
        raise ValueError("Spatial metric is required for terrain-feature extraction.")

    boundary_x_metres, boundary_y_metres = spatial_metric.to_metric(_coordX, _coordY)
    lake_x_metres, lake_y_metres = spatial_metric.to_metric(_coordLX, _coordLY)
    direction_x = float(boundary_x_metres - lake_x_metres)
    direction_y = float(boundary_y_metres - lake_y_metres)
    direction_length = math.hypot(direction_x, direction_y)
    if direction_length <= EPS:
        return -1
    direction_x /= direction_length
    direction_y /= direction_length

    dem_pixel_sizes = spatial_metric.pixel_size_metres(_demRaster)
    slope_pixel_sizes = spatial_metric.pixel_size_metres(_slopeRaster)
    sample_step_metres = max(
        1.0,
        min(dem_pixel_sizes + slope_pixel_sizes),
    )
    regular_distances = numpy.arange(
        0.0,
        max_buffer_metres + sample_step_metres * 0.5,
        sample_step_metres,
        dtype=numpy.float64,
    )
    sample_distances = sorted(
        set(float(distance) for distance in regular_distances)
        | {0.0, *target_distances, max_buffer_metres}
    )

    samples = []
    samples_by_distance = {}
    for distance_metres in sample_distances:
        sample_x_metres = float(boundary_x_metres) + direction_x * distance_metres
        sample_y_metres = float(boundary_y_metres) + direction_y * distance_metres
        x_coord, y_coord = spatial_metric.from_metric(sample_x_metres, sample_y_metres)
        x_coord = float(x_coord)
        y_coord = float(y_coord)
        elevation = _sample_raster_at_xy(_demRaster, x_coord, y_coord)
        slope = _sample_raster_at_xy(_slopeRaster, x_coord, y_coord)
        if elevation is None or slope is None:
            break
        sample = (distance_metres, elevation, slope)
        samples.append(sample)
        samples_by_distance[distance_metres] = sample

    # At least the first 300 m must be present.  For legacy workspaces whose
    # surrounding DEM ends between 300 and 900 m, later windows use the
    # farthest genuinely sampled metric distance instead of inventing pixels.
    if 0.0 not in samples_by_distance or target_distances[0] not in samples_by_distance:
        return -1

    boundary_elevation = samples_by_distance[0.0][1]
    slopes = []
    elevation_differences = []
    gradients = []
    for target_distance in target_distances:
        effective_sample = samples_by_distance.get(target_distance)
        if effective_sample is None:
            candidates = [sample for sample in samples if sample[0] < target_distance]
            if not candidates:
                return -1
            effective_sample = candidates[-1]
        effective_distance = effective_sample[0]
        target_samples = [sample for sample in samples if sample[0] <= effective_distance]
        target_elevation = effective_sample[1]
        slopes.append(float(numpy.mean([sample[2] for sample in target_samples])))
        elevation_differences.append(
            float(numpy.mean([sample[1] for sample in target_samples]) - lakelevel)
        )
        gradients.append(
            float((target_elevation - boundary_elevation) / effective_distance)
            if effective_distance > 0
            else 0.0
        )

    slope_300, slope_600, slope_900 = slopes
    diffEle_300, diffEle_600, diffEle_900 = elevation_differences
    gradient_300, gradient_600, gradient_900 = gradients
    topoInfo = (
        str(_coordX) + "," + str(_coordY) + "," + str(_coordLX) + "," + str(_coordLY) + "," +
        str(slope_300) + "," + str(slope_600) + "," + str(slope_900) + "," +
        str(diffEle_300) + "," + str(diffEle_600) + "," + str(diffEle_900) + "," +
        str(gradient_300) + "," + str(gradient_600) + "," + str(gradient_900) + "," +
        str(_distance)
    )
    return topoInfo

# =========================
# 8) 湖泊水位（边界中位高程）
# =========================
def get_lakeLevel(_lakeshorelineRaster, _demRaster, _slopeRaster):
    LakeShoreLine = []
    for row in range(0, _lakeshorelineRaster.NRow()):
        for col in range(0, _lakeshorelineRaster.NCol()):
            tempLake = _lakeshorelineRaster.GetValue(row, col)
            if not _is_valid_raster_value(_lakeshorelineRaster, tempLake):
                continue
            x_coord = _lakeshorelineRaster.GetXCoordByCol(col)
            y_coord = _lakeshorelineRaster.GetYCoordByRow(row)
            tempSlope = _sample_raster_at_xy(_slopeRaster, x_coord, y_coord)
            tempEle = _sample_raster_at_xy(_demRaster, x_coord, y_coord)
            if tempSlope is not None and tempEle is not None and tempSlope < 1:
                LakeShoreLine.append(tempEle)
    if len(LakeShoreLine) == 0:
        return float('nan')
    medianValue = numpy.median(LakeShoreLine)
    return medianValue

# =========================
# 9) 主入口
# =========================
def runPredictedPoints(
    param1,
    param2,
    param3,
    param4,
    param5=None,
    param6=None,
    param7=None,
    progress_callback=None,
    lake_polygon_file=None,
    survey_file=None,
):
    print('++++++++++++++++start+++++++++++++++++++++')
    
    ############## 输入数据 ####################
    workSPDir, resolved_lake = _resolve_workspace(param1, param2)
    lakeName = [resolved_lake]       # 输入需要进行处理的湖泊
    intervalList = [param3]   # 生成的预测点间隔（像元）
    para_Window = param4      # 窗口大小（未使用）
    demFile = param6
    surveyFile = survey_file if survey_file is not None else param7
    ############# 输入数据 ####################

    _report_progress(progress_callback, 0, "Preparing prediction-point generation…")

    for lakeIndex in range(0, len(lakeName)):
        dataDir = workSPDir
        tempDir = workSPDir + "MLData\\"
        os.makedirs(tempDir, exist_ok=True)
        print("+++++++++++++++processing:" + str(lakeName[lakeIndex]))
        lakelevel = boundary_processing(
            workSPDir,
            lakeName[lakeIndex],
            demFile,
            progress_callback,
            lakePolygonFile=lake_polygon_file,
        )
        shoreline_index, lakelevel, spatial_metric = determine_surveypoints_info(
            dataDir,
            lakeName[lakeIndex],
            demFile,
            surveyFile,
            progress_callback,
            lakelevel=lakelevel,
        )
        determine_predictedpoints_info(
            dataDir,
            lakeName[lakeIndex],
            intervalList,
            demFile,
            progress_callback,
            shoreline_index=shoreline_index,
            lakelevel=lakelevel,
            spatial_metric=spatial_metric,
        )
    _report_progress(progress_callback, 100, "Prediction points completed.")
