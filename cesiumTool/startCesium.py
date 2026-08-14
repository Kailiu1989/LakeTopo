from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading
import traceback
import tempfile
from pathlib import Path
from PyQt5.QtCore import QUrl, pyqtSlot, pyqtSignal, QObject, QFileInfo
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog, QWidget
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt5.QtWebChannel import QWebChannel
from osgeo import gdal, osr, ogr
import os, sys, random
import json
import numpy as np
from app_paths import resource_path


HTTP_LOG_PATH = Path(tempfile.gettempdir()) / "LakeTopo_http_server.log"


def _log_http(message):
    try:
        with open(HTTP_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(str(message) + "\n")
    except Exception:
        pass


class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def _to_jsonable(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _to_js_literal(value):
    return json.dumps(_to_jsonable(value), ensure_ascii=False, allow_nan=False, default=str)


def _ogr_feature_type(geom_type):
    if hasattr(ogr, "wkbFlatten"):
        geom_type = ogr.wkbFlatten(geom_type)
    elif hasattr(ogr, "GT_Flatten"):
        geom_type = ogr.GT_Flatten(geom_type)
    else:
        geom_type = int(geom_type) & 0x7fffffff
    if geom_type in (ogr.wkbPoint, ogr.wkbMultiPoint):
        return "point"
    if geom_type in (ogr.wkbLineString, ogr.wkbMultiLineString):
        return "polyline"
    if geom_type in (ogr.wkbPolygon, ogr.wkbMultiPolygon):
        return "polygon"
    return "unknown"


def _use_traditional_axis_order(srs):
    if srs is not None and hasattr(srs, "SetAxisMappingStrategy") and hasattr(osr, "OAMS_TRADITIONAL_GIS_ORDER"):
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)


class NoCacheHTTPRequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        try:
            super().do_GET()
        except Exception:
            _log_http(traceback.format_exc())
            try:
                self.send_error(500, "LakeTopo local map server error")
            except Exception:
                pass

    def log_message(self, format, *args):
        _log_http("%s - %s" % (self.address_string(), format % args))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def make_static_handler(directory):
    directory = str(Path(directory).resolve())
    _log_http(f"Static root: {directory}")

    class StaticHTTPRequestHandler(NoCacheHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

    return StaticHTTPRequestHandler


# Local HTTP server with disabled client caching.
class HttpServerThread(threading.Thread):
    def __init__(self, host, port=0):
        super(HttpServerThread, self).__init__()
        self.daemon = True
        self.host = host
        static_root = resource_path()
        _log_http(f"Starting HTTP server from {static_root}")
        self.httpd = ReusableHTTPServer((self.host, port), make_static_handler(str(static_root)))
        self.port = self.httpd.server_address[1]
        _log_http(f"HTTP server listening on {self.host}:{self.port}")

    def run(self):
        try:
            self.httpd.serve_forever()
        except Exception as e:
            print(f"Server Error: {e}")

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None


gWebView = ''


# WebChannel bridge called from JavaScript.
class pyjsCon(QObject):
    @pyqtSlot(str)
    def jsMethod(self, value):
        pass

    @pyqtSlot(str)
    def jsMethod_GetPickData(self, value):
        QMessageBox.information(None, "提示", "点击的数据: {}".format(value))

    @pyqtSlot(str)
    def jsMethod_ReadFile(self, value):
        widget = QWidget()
        openFile(widget)


# Initialize the Cesium web view and local server.
def initCesiumViewer(self):
    self.channel = QWebChannel()

    con1 = pyjsCon(self)
    self.channel.registerObject("pyjsCon", con1)

    url = QUrl(QFileInfo("./webchannel.html").absoluteFilePath())

    self.webViewer = QWebEngineView()

    self.webViewer.settings().setAttribute(QWebEngineSettings.WebGLEnabled, True)
    self.webViewer.settings().setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
    self.webViewer.settings().setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, False)
    self.webViewer.settings().setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, True)

    self.webViewer.page().setWebChannel(self.channel)

    profile = self.webViewer.page().profile()
    profile.clearHttpCache()
    profile.setHttpCacheType(QWebEngineProfile.NoCache)
    profile.setCachePath("./cache")
    profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
    profile.setHttpCacheMaximumSize(0)

    global gWebView
    gWebView = self.webViewer

    self.server_thread = HttpServerThread('127.0.0.1')
    self.server_thread.start()

    self.cesiumUrl = QUrl("http://127.0.0.1:" + str(self.server_thread.port) + "/cesiumTool/index.html")

    self.webViewer.load(self.cesiumUrl)


# Read raster min and max values while ignoring invalid pixels.
def get_min_max_exclude_zero_and_nodata(file_path, exclude_zero=True):
    dataset = gdal.Open(file_path, gdal.GA_ReadOnly)
    if not dataset:
        raise ValueError("无法打开文件")

    band = dataset.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    data = band.ReadAsArray()
    if data is None:
        dataset = None
        raise ValueError("无有效像素（全为 0/NoData）")

    data = np.asarray(data, dtype=float)
    mask = np.isfinite(data)
    if exclude_zero:
        mask &= data != 0
    if nodata is not None:
        mask &= data != nodata

    valid_data = data[mask]
    if valid_data.size == 0:
        dataset = None
        raise ValueError("无有效栅格像元")

    min_val = float(valid_data.min())
    max_val = float(valid_data.max())
    dataset = None
    return min_val, max_val


# Rendering one Cesium BoxGeometry for every source pixel exhausts the
# QtWebEngine/Chromium process for ordinary high-resolution DEMs.  Keep the
# interactive preview bounded; analysis tools continue to use the source DEM.
MAX_CESIUM_RASTER_CELLS = 100_000


def _bounded_raster_size(width, height, max_cells=MAX_CESIUM_RASTER_CELLS):
    """Preserve aspect ratio while limiting the number of preview cells."""
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        raise ValueError("栅格尺寸无效")
    if width * height <= max_cells:
        return width, height
    scale = (float(max_cells) / float(width * height)) ** 0.5
    target_width = max(1, int(width * scale))
    target_height = max(1, int(height * scale))
    while target_width * target_height > max_cells:
        if target_width >= target_height:
            target_width -= 1
        else:
            target_height -= 1
    return target_width, target_height


def prepare_raster_for_cesium(file_path, max_cells=MAX_CESIUM_RASTER_CELLS):
    """Create a small, WGS84, NoData-aware raster payload for Cesium."""
    source_ds = gdal.Open(file_path, gdal.GA_ReadOnly)
    if source_ds is None:
        raise ValueError("无法打开栅格文件")
    if source_ds.RasterCount < 1:
        source_ds = None
        raise ValueError("栅格文件没有可用波段")
    if not source_ds.GetProjection():
        source_ds = None
        raise ValueError("栅格缺少坐标系，无法定位到三维地图")

    source_width = source_ds.RasterXSize
    source_height = source_ds.RasterYSize
    preview_width, preview_height = _bounded_raster_size(
        source_width, source_height, max_cells
    )
    source_band = source_ds.GetRasterBand(1)
    source_nodata = source_band.GetNoDataValue()

    warp_kwargs = {
        "format": "MEM",
        "dstSRS": "EPSG:4326",
        "width": preview_width,
        "height": preview_height,
        "outputType": gdal.GDT_Float32,
        "resampleAlg": gdal.GRA_Bilinear,
        "dstNodata": float("nan"),
        "multithread": True,
    }
    if source_nodata is not None:
        warp_kwargs["srcNodata"] = source_nodata

    preview_ds = gdal.Warp(
        "", source_ds, options=gdal.WarpOptions(**warp_kwargs)
    )
    source_ds = None
    if preview_ds is None:
        raise ValueError("生成三维地图预览栅格失败")

    preview_band = preview_ds.GetRasterBand(1)
    elevation_data = preview_band.ReadAsArray()
    if elevation_data is None:
        preview_ds = None
        raise ValueError("栅格中没有可读取的数据")
    elevation_data = np.asarray(elevation_data, dtype=np.float32)
    finite_mask = np.isfinite(elevation_data)
    preview_nodata = preview_band.GetNoDataValue()
    if preview_nodata is not None and np.isfinite(preview_nodata):
        finite_mask &= elevation_data != preview_nodata
    if not finite_mask.any():
        preview_ds = None
        raise ValueError("栅格中没有有效像元")

    # Zero has historically represented the background in this viewer.  Do
    # not allocate geometry for it; retain zero only for an all-zero raster.
    nonzero_mask = finite_mask & (elevation_data != 0)
    render_mask = nonzero_mask if nonzero_mask.any() else finite_mask
    rendered_values = elevation_data[render_mask]
    min_val = float(rendered_values.min())
    max_val = float(rendered_values.max())

    # JSON null is used as a sparse cell marker.  The Cesium side must skip it
    # instead of turning NoData into millions of zero-height boxes.
    flat_values = elevation_data.ravel()
    flat_mask = render_mask.ravel()
    height_data = [
        float(value) if keep else None
        for value, keep in zip(flat_values, flat_mask)
    ]

    geo_transform = preview_ds.GetGeoTransform()
    rendered_width = preview_ds.RasterXSize
    rendered_height = preview_ds.RasterYSize
    x0 = geo_transform[0]
    y0 = geo_transform[3]
    x1 = x0 + rendered_width * geo_transform[1] + rendered_height * geo_transform[2]
    y1 = y0 + rendered_width * geo_transform[4] + rendered_height * geo_transform[5]
    west, east = sorted((float(x0), float(x1)))
    south, north = sorted((float(y0), float(y1)))
    preview_ds = None

    value_range = max_val - min_val
    return {
        "heightData": height_data,
        "bounds": {"west": west, "south": south, "east": east, "north": north},
        "extent": [west, east, south, north],
        "width": int(rendered_width),
        "height": int(rendered_height),
        "sourceWidth": int(source_width),
        "sourceHeight": int(source_height),
        "renderedCellCount": int(render_mask.sum()),
        "downsampled": bool(
            rendered_width != source_width or rendered_height != source_height
        ),
        "fName": os.path.basename(file_path),
        "minValue": min_val,
        "maxValue": max_val,
        "maxColor": "rgb(255,0,0)",
        "minColor": "rgb(0,0,255)",
        "scaleValue": 100,
        "dataCount": (
            f"{source_width}x{source_height} → {rendered_width}x{rendered_height}"
        ),
        "type": "tiff",
        "baseHeight": float(-value_range * 20),
        "pixelHeight": float(max(value_range * 20, 1.0)),
    }


import pandas as pd


# Open a raster, vector, or CSV file and send it to Cesium.
def openFile(self):
    options = QFileDialog.Options()
    options |= QFileDialog.DontUseNativeDialog
    fileName, _ = QFileDialog.getOpenFileName(self, fileSelect, "",
                                              fileType, options=options)
    if not fileName:
        return

    _, ext = os.path.splitext(fileName)
    ext = ext.lower()

    if ext in ('.tif', '.tiff'):
        try:
            output_data = prepare_raster_for_cesium(fileName)
            print(
                "Cesium raster preview:",
                output_data["dataCount"],
                f"({output_data['renderedCellCount']} visible cells)",
            )
            drawCube2(output_data)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Raster Load Error",
                f"Unable to add raster to the 3D map:\n{exc}",
            )


    elif ext == '.shp':
        driver = ogr.GetDriverByName("ESRI Shapefile")
        in_ds = driver.Open(fileName, 0)
        if in_ds is None:
            raise Exception(f"无法打开文件: {fileName}")
        in_layer = in_ds.GetLayer()

        source_srs = in_layer.GetSpatialRef()
        if source_srs is None:
            source_srs = osr.SpatialReference()
            source_srs.ImportFromEPSG(4326)
        _use_traditional_axis_order(source_srs)

        target_srs = osr.SpatialReference()
        target_srs.ImportFromEPSG(4326)
        _use_traditional_axis_order(target_srs)
        transform = osr.CoordinateTransformation(source_srs, target_srs)
        layer_defn = in_layer.GetLayerDefn()
        feature_type = _ogr_feature_type(layer_defn.GetGeomType())

        geojson = {
            "type": "FeatureCollection",
            "features": [],
            "extent": [0, 0, 0, 0],
            "fName": os.path.basename(fileName),
            "dtype": "shp",
            "dType": "shp",
            "dataCount": "0",
            "showExtent": True,
            "scaleValue": 1,
            "maxValue": 1,
            "minValue": 0,
            "maxColor": "rgb(0,255,0)",
            "minColor": "rgb(0,128,0)",
            "color": "rgb(0,255,0)",
            "width": 2,
            "baseHeight": 0,
            "pixelHeight": 0,
            "featureType": feature_type
        }
        transformed_extent = None
        feature_count = 0

        for feature in in_layer:
            geom = feature.GetGeometryRef()
            if geom is None or geom.IsEmpty():
                continue
            geom = geom.Clone()
            geom.Transform(transform)
            envelope = geom.GetEnvelope()
            if transformed_extent is None:
                transformed_extent = [envelope[0], envelope[1], envelope[2], envelope[3]]
            else:
                transformed_extent[0] = min(transformed_extent[0], envelope[0])
                transformed_extent[1] = max(transformed_extent[1], envelope[1])
                transformed_extent[2] = min(transformed_extent[2], envelope[2])
                transformed_extent[3] = max(transformed_extent[3], envelope[3])

            properties = {}
            for i in range(feature.GetFieldCount()):
                field_defn = feature.GetFieldDefnRef(i)
                field_name = field_defn.GetName()
                field_value = feature.GetField(i)
                properties[field_name] = _to_jsonable(field_value)

            feature_geojson = {
                "type": "Feature",
                "geometry": json.loads(geom.ExportToJson()),
                "properties": properties
            }
            geojson["features"].append(feature_geojson)
            feature_count += 1

        if transformed_extent is not None:
            geojson["extent"] = [float(v) for v in transformed_extent]
        geojson["dataCount"] = str(feature_count)
        geojsonStr = _to_js_literal(geojson)
        drawGeoJson(geojsonStr)

    elif ext == '.csv':
        df = pd.read_csv(fileName)
        coords_df = df[['Lon', 'Lat', 'Z', 'cluster_id']]
        dataArray = coords_df.to_dict(orient='records')
        drawCsvJson(dataArray, fileName)


# Data holder for drawing a simple cube.
class cubeData:
    def __init__(self, lonPara, latPara, wPara, hPara, heightPara):
        self.lonPara = lonPara
        self.latPara = latPara
        self.wPara = wPara
        self.hPara = hPara
        self.heightPara = heightPara


# Execute JavaScript drawing helpers.
def drawCube(iData=None):
    if iData is None:
        iData = cubeData(116, 39, 2, 2, 100)

    html_code = f"drawEntityCube({iData.lonPara},{iData.latPara},{iData.wPara},{iData.hPara},{iData.heightPara});"
    gWebView.page().runJavaScript(html_code)


def drawCube2(iData=None):
    if isinstance(iData, dict) and iData.get("type") == "tiff":
        width = int(iData.get("width", 0))
        height = int(iData.get("height", 0))
        height_data = iData.get("heightData", [])
        if width <= 0 or height <= 0 or width * height > MAX_CESIUM_RASTER_CELLS:
            raise ValueError("三维栅格预览超过安全像元上限")
        if len(height_data) != width * height:
            raise ValueError("三维栅格预览数据长度与网格尺寸不一致")
    html_code = f"window.drawEntityCube2({_to_js_literal(iData)});"
    gWebView.page().runJavaScript(html_code)


def drawGeoJson(iData):
    html_code = f"window.drawGeoJson({iData});"
    gWebView.page().runJavaScript(html_code)


def drawCsvJson(iData, fileName):
    iColor = {
        "colors": [
            [0, 128, 255],
            [0, 0, 128],
            [128, 0, 128],
            [200, 160, 220],
            [0, 128, 100],
            [255, 255, 0],
            [255, 165, 0],
            [0, 255, 0],
            [160, 230, 120],
        ],
        "types": 9
    }
    fileName1 = os.path.basename(fileName)

    csvData = {
        "type": "csvData",
        "data": iData,
        "fName": os.path.basename(fileName)
    }

    html_code = f"window.drawCsvJson({_to_js_literal(csvData)},{_to_js_literal(iColor)});"
    gWebView.page().runJavaScript(html_code)


# Viewer label settings（chinese）.
fileSelect = "选择数据Shp或Tiff"
fileType = "*;;Shapefile文件 (*.shp);;TIFF文件 (*.tif *.tiff);;CSV文件(*.csv)"

dataTitle = "Data"
dataSelect = "查看"
dataDelete = "移除"
dataProperty = "属性"
pFileName = "文件名称"
pDataType = "数据类型"
pDataNum = "数据量"
pDataExtent = "显示边界范围"
pScale = "拉伸比例"
pBaseHeight = "基础高度"
pHeight = "拉伸高度"
pMaxValue = "最大值"
pMinValue = "最小值"
pOk = "确认"
pLengend = "图例"


def changeViewerLanguage(isEn=True):
    global fileSelect, fileType
    if isEn is True:
        fileSelect = "select Data Shp/Tiff"
        fileType = "*;;Shapefile(*.shp);;TIFF(*.tif *.tiff);;CSV(*.csv)"
        dataTitle = "Data"
        dataSelect = "Select"
        dataDelete = "Delete"
        dataProperty = "Info"
        pFileName = "File"
        pDataType = "Type"
        pDataNum = "Count"
        pDataExtent = "Extent"
        pScale = "Scale"
        pBaseHeight = "Base Height"
        pHeight = "Scale Height"
        pMaxValue = "Max Value"
        pMinValue = "Min Value"
        pOk = "OK"
        pLengend = "Legend"

    else:
        fileSelect = "select Data Shp/Tiff"
        fileType = "*;;Shapefile(*.shp);;TIFF(*.tif *.tiff);;CSV(*.csv)"
        dataTitle = "Data"
        dataSelect = "Select"
        dataDelete = "Delete"
        dataProperty = "Info"
        pFileName = "File"
        pDataType = "Type"
        pDataNum = "Count"
        pDataExtent = "Extent"
        pScale = "Scale"
        pBaseHeight = "Base Height"
        pHeight = "Scale Height"
        pMaxValue = "Max Value"
        pMinValue = "Min Value"
        pOk = "OK"
        pLengend = "Legend"
        
    labelText = {
        "dataTitle": dataTitle,
        "dataSelect": dataSelect,
        "dataDelete": dataDelete,
        "dataProperty": dataProperty,
        "pFileName": pFileName,
        "pDataType": pDataType,
        "pDataNum": pDataNum,
        "pDataExtent": pDataExtent,
        "pScale": pScale,
        "pBaseHeight": pBaseHeight,
        "pHeight": pHeight,
        "pMaxValue": pMaxValue,
        "pMinValue": pMinValue,
        "pOk": pOk,
        "pLengend": pLengend
    }

    html_code = (
        "(function(labelText){"
        "if (typeof window.changeViewerLanguage === 'function') {"
        "window.changeViewerLanguage(labelText);"
        "} else {"
        "window.labelText = labelText;"
        "}"
        f"}})({_to_js_literal(labelText)});"
    )
    gWebView.page().runJavaScript(html_code)
