"""
自定义基础操作库
"""
import numpy as np
import math
import os

try:
    from osgeo import gdal, ogr, osr
except ImportError:
    gdal = None
    ogr = None
    osr = None

def get_dataset_srs(path):
    if not path or not os.path.exists(path):
        return None, f"File not found: {path}"

    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".tif", ".tiff"):
            if gdal is None:
                return None, "GDAL is not available."
            ds = gdal.Open(path)
            if ds is None:
                return None, f"Cannot open raster: {path}"
            projection = ds.GetProjection()
            ds = None
            if not projection:
                return None, f"Raster has no projection: {path}"
            srs = osr.SpatialReference()
            srs.ImportFromWkt(projection)
            return srs, None

        if ext == ".shp":
            if ogr is None:
                return None, "OGR is not available."
            ds = ogr.Open(path)
            if ds is None:
                return None, f"Cannot open shapefile: {path}"
            layer = ds.GetLayer()
            srs = layer.GetSpatialRef()
            srs = srs.Clone() if srs else None
            ds = None
            if srs is None:
                return None, f"Shapefile has no projection: {path}"
            return srs, None

        return None, f"Unsupported spatial file type: {path}"
    except Exception as e:
        return None, f"Failed to read projection from {path}: {e}"

def srs_to_compare_text(srs):
    if srs is None:
        return ""
    srs = srs.Clone()
    try:
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    except Exception:
        pass
    try:
        authority = srs.GetAuthorityName(None)
        code = srs.GetAuthorityCode(None)
        if authority and code:
            return f"{authority}:{code}"
    except Exception:
        pass
    try:
        srs.MorphToESRI()
    except Exception:
        pass
    return srs.ExportToWkt()

def spatial_references_match(srs_a, srs_b):
    if srs_a is None or srs_b is None:
        return False
    try:
        if srs_a.IsSame(srs_b):
            return True
    except Exception:
        pass
    return srs_to_compare_text(srs_a) == srs_to_compare_text(srs_b)

def check_spatial_references_match(paths):
    valid_paths = [p for p in paths if p]
    if len(valid_paths) < 2:
        return True, ""

    first_path = valid_paths[0]
    first_srs, error = get_dataset_srs(first_path)
    if error:
        return False, error

    mismatches = []
    for path in valid_paths[1:]:
        srs, error = get_dataset_srs(path)
        if error:
            return False, error
        if not spatial_references_match(first_srs, srs):
            mismatches.append(path)

    if mismatches:
        message = "Input file projections are inconsistent:\n"
        message += f"Reference: {first_path}\n"
        message += "Mismatch:\n" + "\n".join(mismatches)
        return False, message

    return True, ""


def iter_polygon_parts(geometry):
    """Yield Polygon members from Polygon/MultiPolygon geometries, ignoring Z/M."""
    if ogr is None or geometry is None or geometry.IsEmpty():
        return

    geometry_type = ogr.GT_Flatten(geometry.GetGeometryType())
    if geometry_type == ogr.wkbPolygon:
        yield geometry
        return

    if geometry_type == ogr.wkbMultiPolygon:
        for part_index in range(geometry.GetGeometryCount()):
            polygon = geometry.GetGeometryRef(part_index)
            if (
                polygon is not None
                and not polygon.IsEmpty()
                and ogr.GT_Flatten(polygon.GetGeometryType()) == ogr.wkbPolygon
            ):
                yield polygon


def iter_polygon_exterior_rings(geometry):
    """Yield exterior LinearRings from 2-D, Z, or M polygon geometries."""
    for polygon in iter_polygon_parts(geometry):
        if polygon.GetGeometryCount() == 0:
            continue
        exterior_ring = polygon.GetGeometryRef(0)
        if exterior_ring is not None and not exterior_ring.IsEmpty():
            yield exterior_ring

# 删除指定路径下的所有文件和文件夹
# 输入参数:
# path: 需要删除文件和文件夹的路径
# 输出结果:
# 无返回值，函数内部删除指定路径下的所有文件和文件夹
def del_file(path):
    for i in os.listdir(path):
        path_file = os.path.join(path, i)
        if os.path.isfile(path_file):
            os.remove(path_file)
        else:
            del_file(path_file)

# 计算栅格中两个像元之间的距离
# 输入参数:
# curRaster: 当前栅格对象
# row1, col1: 第一个像元的行列索引
# row2, col2: 第二个像元的行列索引
# 输出结果:
# 返回两个像元之间的距离，如果索引无效则返回-1
def calDistancebyRowCol(curRaster, row1, col1, row2, col2):
    if curRaster.IsValidIndex(row1, col1) and curRaster.IsValidIndex(row2, col2):
        xCoord1 = curRaster.GetXCoordByCol(col1)
        xCoord2 = curRaster.GetXCoordByCol(col2)
        yCoord1 = curRaster.GetYCoordByRow(row1)
        yCoord2 = curRaster.GetYCoordByRow(row2)
        return math.sqrt((xCoord1 - xCoord2) ** 2 + (yCoord1 - yCoord2) ** 2)
    else:
        return -1

# 计算两个点之间的角度
# 输入参数:
# x1, y1: 第一个点的坐标
# x2, y2: 第二个点的坐标
# 输出结果:
# 返回两个点之间的角度
def cal_angle(x1, y1, x2, y2):
    xx = x2 - x1
    yy = y2 - y1
    if xx == 0:
        angle_temp = math.pi / 2
    else:
        angle_temp = math.atan(abs(yy / xx))

    if xx < 0 and yy >= 0:
        angle_temp = math.pi - angle_temp
    elif xx < 0 and yy < 0:
        angle_temp = math.pi + angle_temp
    elif xx >= 0 and yy < 0:
        angle_temp = 2 * math.pi - angle_temp
    return angle_temp

# 计算中心线某一点的角度
# 输入参数:
# rowList, colList: 行列索引列表
# _centerline: 中心线栅格对象
# index: 当前索引
# para_Windows: 窗口大小
# 输出结果:
# 返回中心线某一点的角度
def cal_anglebyRowCol(rowList, colList, _centerline, index, para_Windows):
    preRow = rowList[index - para_Windows]
    preCol = colList[index - para_Windows]
    nextRow = rowList[index + para_Windows]
    nextCol = colList[index + para_Windows]
    xCoordPre = _centerline.GetXCoordByCol(preCol)
    yCoordPre = _centerline.GetYCoordByRow(preRow)
    xCoordNext = _centerline.GetXCoordByCol(nextCol)
    yCoordNext = _centerline.GetYCoordByRow(nextRow)
    angleCenterLine = cal_angle(xCoordPre, yCoordPre, xCoordNext, yCoordNext)
    return angleCenterLine

# 计算两个坐标点之间的距离
# 输入参数:
# x1, y1: 第一个点的坐标
# x2, y2: 第二个点的坐标
# 输出结果:
# 返回两个坐标点之间的距离
def calDistancebyCoord(x1, y1, x2, y2):
    return math.sqrt(pow((float(x1) - float(x2)), 2) + pow((float(y1) - float(y2)), 2))

# 判断两个像元是否为对角方向
# 输入参数:
# rowCur, colCur: 当前像元的行列索引
# rowNext, colNext: 下一个像元的行列索引
# 输出结果:
# 返回1或1.41，如果两个像元在对角方向上则返回1.41，否则返回1
def isDiagonalDirection(rowCur, colCur, rowNext, colNext):
    if rowCur == rowNext or colCur == colNext:
        return 1
    else:
        return 1.41

# 将列表数据写入TXT文件
# 输入参数:
# a: 数据列表
# num: 数据数量
# textFile: 输出TXT文件路径
# 输出结果:
# 无返回值，函数内部将数据写入指定的TXT文件
def writeToTXT(a, num, textFile):
    if os.path.exists(textFile):
        f = open(textFile, 'a')
        for i in range(0, num):
            f.write(str(a[i]))
            f.write("\n")
    else:
        f = open(textFile, 'w')
        for i in range(0, num):
            f.write(str(a[i]))
            f.write("\n")
    f.close()

# 以指定间隔将列表数据写入TXT文件
# 输入参数:
# a: 数据列表
# num: 数据数量
# textFile: 输出TXT文件路径
# interval: 间隔
# 输出结果:
# 无返回值，函数内部将数据以指定间隔写入指定的TXT文件
def writeToTXTbyInterval(a, num, textFile, interval):
    if os.path.exists(textFile):
        f = open(textFile, 'a')
        for i in range(0, num, interval):
            f.write(str(a[i]))
            f.write("\n")
    else:
        f = open(textFile, 'w')
        for i in range(0, num, interval):
            f.write(str(a[i]))
            f.write("\n")
    f.close()

# 读取TXT文件中的字符串数据
# 输入参数:
# textFile: 输入TXT文件路径
# 输出结果:
# 返回文件中的字符串列表
def readTXTStr(textFile):
    array = []
    f = open(textFile, "r")
    lines = f.readlines()
    for line in lines:
        tempvalue = line.strip()
        array.append(tempvalue)
    f.close()
    return array
