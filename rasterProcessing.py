"""
自定义栅格处理库
"""

from osgeo import gdal
import numpy

class Raster:
    # 初始化栅格对象
    # 输入参数:
    # xTopLeft: 左上角X坐标
    # yTopLeft: 左上角Y坐标
    # cellSize: 栅格单元大小
    # nRow: 行数
    # nCol: 列数
    # noDataValue: 无效数据值
    def __init__(
        self,
        xTopLeft,
        yTopLeft,
        cellSize,
        nRow,
        nCol,
        noDataValue,
        yCellSize=None,
    ):
        self._xTopLeft = xTopLeft
        self._yTopLeft = yTopLeft
        self._cellSize = cellSize
        self._cellSizeY = abs(yCellSize) if yCellSize is not None else abs(cellSize)
        self._nRow = nRow
        self._nCol = nCol
        self._noDataValue = noDataValue
        totalNum = nRow * nCol
        self._data = numpy.array([[noDataValue] * nCol] * nRow)

    # 判断索引是否有效
    # 输入参数:
    # row: 行索引
    # col: 列索引
    # 输出结果:
    # 如果索引有效返回1，否则返回0
    def IsValidIndex(self, row, col):
        if row < 0 or row >= self._nRow or col < 0 or col >= self._nCol:
            return 0
        else:
            return 1

    # 设置指定位置的值
    # 输入参数:
    # row: 行索引
    # col: 列索引
    # value: 要设置的值
    def SetValue(self, row, col, value):
        if self.IsValidIndex(row, col):
            self._data[int(row), int(col)] = float(value)

    # 获取指定位置的值
    # 输入参数:
    # row: 行索引
    # col: 列索引
    # 输出结果:
    # 返回指定位置的值，如果索引无效则返回无效数据值
    def GetValue(self, row, col):
        if self.IsValidIndex(row, col):
            tempValue = self._data[row, col]
            return tempValue
        else:
            return self._noDataValue

    # 获取窗口内的中值
    # 输入参数:
    # row: 中心行索引
    # col: 中心列索引
    # winSize: 窗口大小
    # 输出结果:
    # 返回窗口内的中值
    def GetMeduimValueInWindow(self, row, col, winSize):
        array = [0] * 100
        count = 0
        for r in range(row - int(winSize / 2), row + int(winSize / 2)):
            for c in range(col - int(winSize / 2), col + int(winSize / 2)):
                array[count] = self.GetValue(r, c)
                count += 1
        if count != 0:
            bubblesort(array, count)
            if count % 2 == 1:
                return array[int(count / 2)]
            else:
                return (array[int(count / 2) - 1] + array[int(count / 2)]) / 2

    # 获取窗口内的平均值
    # 输入参数:
    # row: 中心行索引
    # col: 中心列索引
    # winSize: 窗口大小
    # 输出结果:
    # 返回窗口内的平均值
    def GetMeanValueInWindow(self, row, col, winSize):
        sum = 0.0
        count = 0.0
        for r in range(row - int(winSize / 2), row + int(winSize / 2)):
            for c in range(col - int(winSize / 2), col + int(winSize / 2)):
                tempvale = self.GetValue(r, c)
                if tempvale != self.NodataValue():
                    sum += tempvale
                    count += 1
        if count != 0:
            return sum / count
        else:
            return self.NodataValue()

    # 获取栅格单元大小
    def CellSize(self):
        return self._cellSize

    # 获取Y方向栅格单元大小（正值）
    def CellSizeY(self):
        return self._cellSizeY

    # 获取无效数据值
    def NodataValue(self):
        return self._noDataValue

    # 获取左上角X坐标
    def XTopLeft(self):
        return self._xTopLeft

    # 获取左上角Y坐标
    def YTopLeft(self):
        return self._yTopLeft

    # 获取行数
    def NRow(self):
        return self._nRow

    # 获取列数
    def NCol(self):
        return self._nCol

    # 根据列索引获取X坐标
    def GetXCoordByCol(self, col):
        return col * self._cellSize + self._xTopLeft

    # 根据行索引获取Y坐标
    def GetYCoordByRow(self, row):
        return self._yTopLeft - row * self._cellSizeY

    # 根据Y坐标获取行索引
    def GetRowbyYCoord(self, yCoord):
        return int((self._yTopLeft - yCoord) / self._cellSizeY)

    # 根据X坐标获取列索引
    def GetColbyXCoord(self, xCoord):
        return int((xCoord - self._xTopLeft) / self._cellSize)

    # 获取栅格数据矩阵
    def GetMatrix(self):
        return self._data

    # 设置栅格数据矩阵
    def SetMatrix(self, im_raster):
        self._data = im_raster

class RasterIO:
    # 读取栅格影像文件
    # 输入参数:
    # filename: 栅格影像文件路径
    # 输出结果:
    # 返回投影信息、地理变换参数和栅格对象
    def read_img(self, filename):
        dataset = gdal.Open(filename)
        im_geotrans = dataset.GetGeoTransform()
        im_width = dataset.RasterXSize
        im_height = dataset.RasterYSize
        im_geotrans = dataset.GetGeoTransform()
        im_xTopLeft = im_geotrans[0]
        im_yTopLeft = im_geotrans[3]
        im_cellsize = im_geotrans[1]
        band = dataset.GetRasterBand(1)
        im_nodatavalue = band.GetNoDataValue()
        im_proj = dataset.GetProjection()
        im_data = band.ReadAsArray(0, 0, im_width, im_height)
        del dataset
        imRaster = Raster(
            im_xTopLeft,
            im_yTopLeft,
            im_cellsize,
            im_height,
            im_width,
            im_nodatavalue,
            yCellSize=abs(im_geotrans[5]),
        )
        imRaster.SetMatrix(im_data)
        return im_proj, im_geotrans, imRaster

    # 写入栅格影像文件
    # 输入参数:
    # filename: 输出栅格影像文件路径
    # proj: 投影信息
    # im_geotrans: 地理变换参数
    # raster: 栅格对象
    # nodataValue: 无效数据值
    def write_Tif(self, filename, proj, im_geotrans, raster, nodataValue):
        im_data = raster.GetMatrix()
        if 'int8' in im_data.dtype.name:
            datatype = gdal.GDT_Byte
        elif 'int16' in im_data.dtype.name:
            datatype = gdal.GDT_UInt16
        else:
            datatype = gdal.GDT_Float32
        if len(im_data.shape) == 3:
            im_bands, im_height, im_width = im_data.shape
        else:
            im_bands, (im_height, im_width) = 1, im_data.shape

        driver = gdal.GetDriverByName("GTiff")
        dataset = driver.Create(filename, im_width, im_height, im_bands, gdal.GDT_Float32)
        dataset.SetGeoTransform(im_geotrans)
        dataset.SetProjection(proj)
        if im_bands == 1:
            dataset.GetRasterBand(1).WriteArray(im_data)
            dataset.GetRasterBand(1).SetNoDataValue(nodataValue)
        else:
            for i in range(im_bands):
                dataset.GetRasterBand(i + 1).WriteArray(im_data[i])
        del dataset

# 冒泡排序
# 输入参数:
# array: 要排序的数组
# len: 数组长度
# 输出结果:
# 返回排序后的数组中值
def bubblesort(array, len):
    for i in range(0, len - 1):
        for j in range(0, len - i - 1):
            if array[j + 1] < array[j]:
                tempValue = array[j + 1]
                array[j + 1] = array[j]
                array[j] = tempValue
    if len % 2 == 1:
        return array[int(len / 2)]
    else:
        return (array[int(len / 2) - 1] + array[int(len / 2)]) / 2
