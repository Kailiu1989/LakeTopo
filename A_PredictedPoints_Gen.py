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
# para_cellsize = 90 #处理的像元大小（由 runPredictedPoints 传入并设为全局）


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


class _ShorelineKDTree:
    """Exact nearest-shoreline lookup in raster row/column space."""

    def __init__(self, shoreline_raster):
        if cKDTree is None:
            raise RuntimeError(
                "SciPy is required for shoreline KDTree lookup. Install the 'scipy' package."
            )
        cells = numpy.argwhere(_valid_raster_mask(shoreline_raster))
        if cells.size == 0:
            raise ValueError("The shoreline raster contains no valid cells.")
        self._cells = cells.astype(numpy.float64, copy=False)
        self._tree = cKDTree(self._cells)

    def __len__(self):
        return len(self._cells)

    def nearest(self, row, col, cell_size):
        """Return nearest shoreline row, column, and distance in configured metres."""
        distance_pixels, cell_index = self._tree.query(
            (float(row), float(col)), k=1
        )
        target_row, target_col = self._cells[int(cell_index)]
        return (
            int(target_row),
            int(target_col),
            float(distance_pixels) * float(cell_size),
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
        print(f"{name}: size=({R.NRow()},{R.NCol()}), cell={R.CellSize()}, origin=({R.XTopLeft()},{R.YTopLeft()})")
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
        lakeareaRaster.NCol(), -9999
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
    proj, im_geotrans, lakeRaster = raster.read_img(lakeshorelineFile)
    proj, im_geotrans, slopeRaster = raster.read_img(slopeFile)
    proj, im_geotrans, demRaster = raster.read_img(demFile)
    boundaryList = []
    for row in range(0, lakeRaster.NRow()):
        for col in range(0, lakeRaster.NCol()):
            if lakeRaster.GetValue(row, col) == 1 and slopeRaster.GetValue(row, col) < 1:
                boundaryList.append(float(demRaster.GetValue(row, col)))

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
):
    demFile = _resolve_dem_file(_with_sep(_workSP), _lakename, _demFile)
    slopeFile = _workSP + "\\" + _lakename + "_Slope.tif"
    lakeareaFile = _workSP + "\\" + _lakename + "_extent.tif"
    lakeshorelineFile = _workSP + "\\" + _lakename + "_shoreline.tif"
    raster = rasterProcessing.RasterIO()
    proj, im_geotrans, demRaster = raster.read_img(demFile)
    proj, im_geotrans, slopeRaster = raster.read_img(slopeFile)
    proj, im_geotrans, lakeRaster = raster.read_img(lakeareaFile)
    proj, im_geotrans, lakeshorelineRaster = raster.read_img(lakeshorelineFile)
    _txtFile = _workSP + "\\" + _lakename + "\\MLData\\Test_" + str(_para_intervalList[0]) + ".txt"
    topoinfoList = []
    nodataLakeShoreline = lakeshorelineRaster.NodataValue()

    _report_progress(progress_callback, 69, "Preparing prediction-point terrain data…")
    if shoreline_index is None:
        shoreline_index = _ShorelineKDTree(lakeshorelineRaster)
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
                if tempValue != lakeRaster.NodataValue() and abs(tempLakeSL - nodataLakeShoreline) < EPS:
                    targetRow, targetCol, distance = shoreline_index.nearest(
                        row, col, para_cellsize
                    )
                    if distance < 100:
                        continue
                    xLake = lakeRaster.GetXCoordByCol(col)
                    yLake = lakeRaster.GetYCoordByRow(row)
                    xBoundary = lakeRaster.GetXCoordByCol(targetCol)
                    yBoundary = lakeRaster.GetYCoordByRow(targetRow)
                    angle = cf.cal_angle(xLake, yLake, xBoundary, yBoundary)
                    info = get_topoInfo(
                        lakeRaster,
                        lakeshorelineRaster,
                        demRaster,
                        slopeRaster,
                        angle,
                        distance,
                        xBoundary,
                        yBoundary,
                        xLake,
                        yLake,
                        lakelevel,
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
        -template_raster.CellSize(),
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
    proj, im_geotrans, demRaster = raster.read_img(demFile)
    proj, im_geotrans, slopeRaster = raster.read_img(slopeFile)
    proj, im_geotrans, lakeRaster = raster.read_img(lakeareaFile)
    proj, im_geotrans, lakeshorelineRaster = raster.read_img(lakeshorelineFile)

    # ★ 用湖区模板进行重栅格化，确保逐像元对齐
    _report_progress(progress_callback, 34, "Rasterizing in-situ bathymetry points…")
    rasterize_survey_to_template(survey_file, surveyRasterFile, lakeRaster, proj)
    proj, im_geotrans, surveyLineRaster = raster.read_img(surveyRasterFile)

    # 自检信息（需要可保留）
    _print_grid_info("lake", lakeRaster)
    _print_grid_info("shore", lakeshorelineRaster)
    _print_grid_info("survey", surveyLineRaster)
    _print_grid_info("dem", demRaster)
    _print_grid_info("slope", slopeRaster)
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
    shoreline_index = _ShorelineKDTree(lakeshorelineRaster)
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
        targetRow, targetCol, distance = shoreline_index.nearest(
            row, col, para_cellsize
        )

        # 业务阈值：过近则跳过（你原来用 <10）
        if distance < 10:
            tooClose += 1
        else:
            xBoundary = lakeRaster.GetXCoordByCol(targetCol)
            yBoundary = lakeRaster.GetYCoordByRow(targetRow)
            xLake = lakeRaster.GetXCoordByCol(col)
            yLake = lakeRaster.GetYCoordByRow(row)
            angle = cf.cal_angle(xLake, yLake, xBoundary, yBoundary)
            info = get_topoInfo(
                lakeRaster,
                lakeshorelineRaster,
                demRaster,
                slopeRaster,
                angle,
                distance,
                xBoundary,
                yBoundary,
                xLake,
                yLake,
                lakelevel,
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
    return shoreline_index, float(lakelevel)

# =========================
# 7) 计算沿射线的地形信息（原逻辑保留）
# =========================
def get_topoInfo(
    _lakeRaster,
    _lakeshorelineRaster,
    _demRaster,
    _slopeRaster,
    _angle,
    _distance,
    _coordX,
    _coordY,
    _coordLX,
    _coordLY,
    _lakelevel=None,
):
    maxBuffer = 1000
    lakelevel = (
        float(_lakelevel)
        if _lakelevel is not None
        else get_lakeLevel(_lakeshorelineRaster, _demRaster, _slopeRaster)
    )
    maxNum = int(maxBuffer / para_cellsize)
    if _angle >= 0 and _angle < math.pi / 4:
        position = 1
        xflag = 1
        yflag = 1
    elif _angle >= math.pi / 4 and _angle < math.pi / 2:
        position = 2
        xflag = 1
        yflag = 1
        _angle = math.pi / 2 - _angle
    elif _angle >= math.pi / 2 and _angle < math.pi * 3 / 4:
        position = 3
        xflag = -1
        yflag = 1
        _angle = _angle - math.pi / 2
    elif _angle >= math.pi * 3 / 4 and _angle < math.pi:
        position = 4
        xflag = -1
        yflag = 1
        _angle = math.pi - _angle
    elif _angle >= math.pi and _angle < math.pi * 5 / 4:
        position = 5
        xflag = -1
        yflag = -1
        _angle = _angle - math.pi
    elif _angle >= math.pi * 5 / 4 and _angle < math.pi * 6 / 4:
        position = 6
        xflag = -1
        yflag = -1
        _angle = math.pi * 6 / 4 - _angle
    elif _angle >= math.pi * 6 / 4 and _angle < math.pi * 7 / 4:
        position = 7
        xflag = 1
        yflag = -1
        _angle = _angle - math.pi * 6 / 4
    elif _angle >= math.pi * 7 / 4 and _angle <= 2 * math.pi:
        position = 8
        xflag = 1
        yflag = -1
        _angle = 2 * math.pi - _angle

    curNum = 0
    cellsize = _demRaster.CellSize()
    nodataDEM = _demRaster.NodataValue()

    rowIndex = []
    colIndex = []
    eleList = []
    slopeList = []
    distanceList = []
    coordList = []
    curRow = _lakeRaster.GetRowbyYCoord(_coordY)
    curCol = _lakeRaster.GetColbyXCoord(_coordX)
    xCoordCur = _coordX
    yCoordCur = _coordY
    index = curRow * _lakeRaster.NCol() + curCol
    while curNum < maxNum and abs(_demRaster.GetValue(curRow, curCol) - nodataDEM) > EPS:
        pixelisChange = 0
        while pixelisChange == 0:
            if position == 1 or position == 8 or position == 4 or position == 5:
                xCoordCur = xCoordCur + xflag * cellsize
                yCoordCur = yCoordCur + yflag * cellsize * math.tan(_angle)
            elif position == 2 or position == 3 or position == 6 or position == 7:
                yCoordCur = yCoordCur + yflag * cellsize
                xCoordCur = xCoordCur + xflag * cellsize * math.tan(_angle)
            nextRow = _lakeRaster.GetRowbyYCoord(yCoordCur)
            nextCol = _lakeRaster.GetColbyXCoord(xCoordCur)
            if (curRow != nextRow or curCol != nextCol):
                pixelisChange = 1
        if curNum == 0:
            distanceList.append(90)
        else:
            distanceList.append(distanceList[curNum - 1] + cf.isDiagonalDirection(curRow, curCol, nextRow, nextCol) * para_cellsize)
        coordInfo = str(xCoordCur) + " " + str(yCoordCur) + " " + str(index)
        coordList.append(coordInfo)

        curRow = nextRow
        curCol = nextCol
        curNum = curNum + 1
        rowIndex.append(curRow)
        colIndex.append(curCol)
        if abs(_demRaster.GetValue(curRow, curCol) - _demRaster.NodataValue()) > EPS:
            eleList.append(_demRaster.GetValue(curRow, curCol))
        if abs(_slopeRaster.GetValue(curRow, curCol) - _slopeRaster.NodataValue()) > EPS:
            slopeList.append(_slopeRaster.GetValue(curRow, curCol))

    index1 = int(300 / para_cellsize)
    index2 = int(600 / para_cellsize)
    index3 = int(900 / para_cellsize)

    preIndex = 0
    if index1 >= len(slopeList) - 1 or len(eleList) == 0:
        return -1
    for index in range(0, len(slopeList)):

        if preIndex <= index1 and index > index1:
            slope_300 = numpy.mean(slopeList[:preIndex]) if preIndex > 0 else numpy.mean(slopeList[:index1+1])
            diffEle_300 = numpy.mean(eleList[:preIndex]) - lakelevel if preIndex > 0 else numpy.mean(eleList[:index1+1]) - lakelevel
            gradient_300 = float((eleList[preIndex] - eleList[0]) / distanceList[preIndex]) if preIndex > 0 else 0.0
            slope_600 = slope_300
            diffEle_600 = diffEle_300
            gradient_600 = gradient_300
            slope_900 = slope_300
            diffEle_900 = diffEle_300
            gradient_900 = gradient_300
        elif preIndex <= index2:
            slope_600 = numpy.mean(slopeList[:preIndex]) if preIndex > 0 else numpy.mean(slopeList[:index2+1])
            diffEle_600 = numpy.mean(eleList[:preIndex]) - lakelevel if preIndex > 0 else numpy.mean(eleList[:index2+1]) - lakelevel
            gradient_600 = float((eleList[preIndex] - eleList[0]) / distanceList[preIndex]) if preIndex > 0 else 0.0
            slope_900 = slope_600
            diffEle_900 = diffEle_600
            gradient_900 = gradient_600
        elif preIndex <= index3:
            slope_900 = numpy.mean(slopeList[:preIndex]) if preIndex > 0 else numpy.mean(slopeList[:index3+1])
            diffEle_900 = numpy.mean(eleList[:preIndex]) - lakelevel if preIndex > 0 else numpy.mean(eleList[:index3+1]) - lakelevel
            gradient_900 = float((eleList[preIndex] - eleList[0]) / distanceList[preIndex]) if preIndex > 0 else 0.0
        preIndex = index
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
    nodataLakeshoreline = _lakeshorelineRaster.NodataValue()
    LakeShoreLine = []
    for row in range(0, _lakeshorelineRaster.NRow()):
        for col in range(0, _lakeshorelineRaster.NCol()):
            tempLake = _lakeshorelineRaster.GetValue(row, col)
            tempSlope = _slopeRaster.GetValue(row, col)
            tempEle = _demRaster.GetValue(row, col)
            if tempLake != nodataLakeshoreline and tempSlope < 1:
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
    param5,
    param6=None,
    param7=None,
    progress_callback=None,
    lake_polygon_file=None,
):
    global para_cellsize  # 处理的像元大小（米）
    print('++++++++++++++++start+++++++++++++++++++++')
    
    ############## 输入数据 ####################
    workSPDir, resolved_lake = _resolve_workspace(param1, param2)
    lakeName = [resolved_lake]       # 输入需要进行处理的湖泊
    intervalList = [param3]   # 生成的预测点间隔（像元）
    para_Window = param4      # 窗口大小（未使用）
    para_cellsize = param5    # 处理的像元大小（米）
    demFile = param6
    surveyFile = param7
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
        shoreline_index, lakelevel = determine_surveypoints_info(
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
        )
    _report_progress(progress_callback, 100, "Prediction points completed.")
