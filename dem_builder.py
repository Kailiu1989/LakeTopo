# dem_build.py

from osgeo import ogr, osr, gdal
import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter
from matplotlib.path import Path
from scipy.spatial import cKDTree
import os
import math

def meters_to_degree_resolution(meters, latitude):
    lat_rad = math.radians(latitude)
    meters_per_degree_lat = (
        111132.92
        - 559.82 * math.cos(2 * lat_rad)
        + 1.175 * math.cos(4 * lat_rad)
        - 0.0023 * math.cos(6 * lat_rad)
    )
    if meters_per_degree_lat <= 0:
        meters_per_degree_lat = 111320.0
    return meters / meters_per_degree_lat

def resolution_to_srs_units(resolution_meters, spatial_ref, sample_points):
    if spatial_ref is None:
        return resolution_meters

    if spatial_ref.IsGeographic():
        latitude = float(np.nanmean(sample_points[:, 1])) if len(sample_points) else 0.0
        return meters_to_degree_resolution(resolution_meters, latitude)

    linear_units = spatial_ref.GetLinearUnits() or 1.0
    return resolution_meters / linear_units

def reproject_shapefile(input_shp, output_shp, target_epsg):

    driver = ogr.GetDriverByName(
        "ESRI Shapefile"
    )

    if os.path.exists(output_shp):
        driver.DeleteDataSource(output_shp)

    in_ds = driver.Open(input_shp)

    in_layer = in_ds.GetLayer()

    source_srs = in_layer.GetSpatialRef()

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(target_epsg)

    transform = osr.CoordinateTransformation(source_srs, target_srs)

    out_ds = driver.CreateDataSource(output_shp)

    out_layer = out_ds.CreateLayer(in_layer.GetName(), target_srs, in_layer.GetGeomType())

    layer_defn = in_layer.GetLayerDefn()

    for i in range(layer_defn.GetFieldCount()):
        out_layer.CreateField(layer_defn.GetFieldDefn(i))

    out_defn = out_layer.GetLayerDefn()

    for feat in in_layer:

        geom = feat.GetGeometryRef().Clone()

        geom.Transform(transform)

        out_feat = ogr.Feature(out_defn)

        out_feat.SetGeometry(geom)

        for i in range(out_defn.GetFieldCount()):
            out_feat.SetField(i, feat.GetField(i))

        out_layer.CreateFeature(out_feat)

    out_ds = None
    in_ds = None

    print(f"Projected: {output_shp}")
    
def buildLakeDEM(
    point_file, z_field_name, breakline_file, lake_polygon_file, output_dem,
    resolution, smooth_sigma=2.0, interp_method='cubic', densify_interval=1.0, breakline_z_value=0.0
):
    """
    构建湖泊DEM，全部路径参数为str，数值参数为float/int
    """
    print("▶ 读取测深点...")
    depth_points = read_points_with_z(point_file, z_field=z_field_name)

    print("▶ 获取坐标参考系...")
    spatial_ref = get_spatial_reference_from_shapefile(point_file)
    resolution_units = resolution_to_srs_units(float(resolution), spatial_ref, depth_points)
    densify_interval_units = resolution_to_srs_units(float(densify_interval), spatial_ref, depth_points)

    print("▶ 读取隔断线高密采样（z=0） ...")
    breakline_points = densify_breakline_points(
        breakline_file, target_srs=spatial_ref,
        interval=densify_interval_units, z_value=breakline_z_value
    )

    print("▶ 合并所有点（测深+隔断线）...")
    all_points = np.vstack([depth_points, breakline_points])

    print("▶ 读取湖区polygon ...")
    polygon_coords = get_polygon_coords(lake_polygon_file)
    if polygon_coords is None:
        raise RuntimeError("未能读取到湖区面数据，请检查 polygon shp 文件！")

    print("▶ griddata插值 DEM ...")
    xi, yi, zi = griddata_dem(all_points, resolution=resolution_units, method=interp_method)

    print("▶ 构建湖区polygon mask ...")
    lake_mask = build_lake_mask_from_polygon(xi, yi, polygon_coords)
    
    # 二次平滑处理，提高表面细腻度
    zi_smooth = gaussian_filter(zi, sigma=smooth_sigma)
    
    # 只保留湖区内插值，湖外全部NoData
    zi_masked = np.where(lake_mask, zi_smooth, np.nan)

    # 数值裁剪，约束在测深点实际最大/最小水深
    min_depth = np.nanmin(depth_points[:,2])
    max_depth = np.nanmax(depth_points[:,2])
    zi_masked = np.where(zi_masked < min_depth, min_depth, zi_masked)
    zi_masked = np.where(zi_masked > max_depth, max_depth, zi_masked)

    # 保证湖岸线（polygon边界）为0
    px, py = polygon_coords[:,0], polygon_coords[:,1]
    polykdtree = cKDTree(np.c_[px, py])
    flat_xy = np.c_[xi.flatten(), yi.flatten()]
    dists, _ = polykdtree.query(flat_xy)
    border_mask = (dists.reshape(xi.shape) < resolution_units*1.5) & lake_mask  # 边界像元
    zi_masked[border_mask] = 0

    print("▶ 保存 DEM 为 GeoTIFF ...")
    save_dem_to_geotiff(xi, yi, zi_masked, output_dem, spatial_ref)

    print("🎉 构建完成！湖岸线为0，湖外NoData，湖内插值表面平滑")
    return output_dem

# --- 以下是内部调用函数，保持和你的风格一致 ---
def read_points_with_z(shapefile_path, z_field=None):
    ds = ogr.Open(shapefile_path)
    layer = ds.GetLayer()
    points = []
    for feature in layer:
        geom = feature.GetGeometryRef()
        if geom.GetGeometryType() in [ogr.wkbPoint, ogr.wkbPoint25D]:
            x, y = geom.GetX(), geom.GetY()
            z = float(geom.GetZ()) if geom.GetGeometryType() == ogr.wkbPoint25D else float(feature.GetField(z_field))
            points.append([x, y, z])
    return np.array(points, dtype=np.float64)

def get_spatial_reference_from_shapefile(shapefile_path):
    ds = ogr.Open(shapefile_path)
    layer = ds.GetLayer()
    srs = layer.GetSpatialRef()
    return srs.Clone() if srs else None

def densify_breakline_points(shapefile_path, target_srs, interval=1.0, z_value=0.0):
    ds = ogr.Open(shapefile_path)
    layer = ds.GetLayer()
    source_srs = layer.GetSpatialRef()
    points = []
    for feature in layer:

        geom = feature.GetGeometryRef()

        if geom is None:
            continue

        gtype = geom.GetGeometryType()

    # LineString
        if gtype in (ogr.wkbLineString, ogr.wkbLineString25D):
            lines = [geom]

    # MultiLineString
        elif gtype in (ogr.wkbMultiLineString, ogr.wkbMultiLineString25D):
            lines = [geom.GetGeometryRef(i) for i in range(geom.GetGeometryCount())]

        else:
            print("跳过类型:", geom.GetGeometryName())
            continue

        for line in lines:

            transform = osr.CoordinateTransformation(source_srs, target_srs)

            geom_proj = line.Clone()
            geom_proj.Transform(transform)

            npts = geom_proj.GetPointCount()

            total_len = 0.0

            for i in range(npts - 1):
                x0, y0 = geom_proj.GetX(i), geom_proj.GetY(i)
                x1, y1 = geom_proj.GetX(i + 1), geom_proj.GetY(i + 1)

                total_len += np.hypot(x1 - x0, y1 - y0)

            n_sample = max(int(total_len // interval), 2)

            dists = np.linspace(0, total_len, n_sample)

            seg_lengths = [0.0]

            for i in range(npts - 1):
                x0, y0 = geom_proj.GetX(i), geom_proj.GetY(i)
                x1, y1 = geom_proj.GetX(i + 1), geom_proj.GetY(i + 1)

                seg_lengths.append(seg_lengths[-1] + np.hypot(x1 - x0, y1 - y0))

            for d in dists:

                for i in range(len(seg_lengths) - 1):

                    if seg_lengths[i] <= d <= seg_lengths[i + 1]:

                        frac = (d - seg_lengths[i]) / (seg_lengths[i + 1] - seg_lengths[i])

                        x0, y0 = geom_proj.GetX(i), geom_proj.GetY(i)
                        x1, y1 = geom_proj.GetX(i + 1), geom_proj.GetY(i + 1)

                        x = x0 + (x1 - x0) * frac
                        y = y0 + (y1 - y0) * frac

                        points.append([x, y, z_value])

                        break
    return np.array(points, dtype=np.float64)

def get_polygon_coords(shapefile_path):
    ds = ogr.Open(shapefile_path)
    layer = ds.GetLayer()
    for feat in layer:
        geom = feat.GetGeometryRef()
        if geom.GetGeometryType() == ogr.wkbPolygon:
            ring = geom.GetGeometryRef(0)
            coords = [(ring.GetX(i), ring.GetY(i)) for i in range(ring.GetPointCount())]
            return np.array(coords)
        elif geom.GetGeometryType() == ogr.wkbMultiPolygon:
            poly = geom.GetGeometryRef(0)
            ring = poly.GetGeometryRef(0)
            coords = [(ring.GetX(i), ring.GetY(i)) for i in range(ring.GetPointCount())]
            return np.array(coords)
    return None

def griddata_dem(points, resolution=2.0, method='cubic'):
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    xmin, xmax = x.min(), x.max()
    ymin, ymax = y.min(), y.max()
    ncols = int((xmax - xmin) / resolution) + 1
    nrows = int((ymax - ymin) / resolution) + 1
    xi = np.linspace(xmin, xmax, ncols)
    yi = np.linspace(ymin, ymax, nrows)
    xi, yi = np.meshgrid(xi, yi)
    print(f"插值格网大小：{nrows} x {ncols}")
    zi = griddata((x, y), z, (xi, yi), method=method)
    #监测插值结果中的NaN数量，帮助调试
    print("NaN count:",
      np.isnan(zi).sum())

    print("Total cells:",
      zi.size)
    return xi, yi, zi

def build_lake_mask_from_polygon(xi, yi, polygon_coords):
    path = Path(polygon_coords)
    grid_points = np.vstack((xi.flatten(), yi.flatten())).T
    inside = path.contains_points(grid_points)
    mask = inside.reshape(xi.shape)
    return mask

def save_dem_to_geotiff(xi, yi, zi, output_path, srs):
    zi = np.flipud(zi)
    nrows, ncols = zi.shape
    xres = (xi.max() - xi.min()) / (ncols - 1)
    yres = (yi.max() - yi.min()) / (nrows - 1)
    xmin, ymax = xi.min(), yi.max()
    driver = gdal.GetDriverByName('GTiff')
    dst = driver.Create(output_path, ncols, nrows, 1, gdal.GDT_Float32)
    dst.SetGeoTransform((xmin, xres, 0, ymax, 0, -yres))
    if srs:
        dst.SetProjection(srs.ExportToWkt())
    zi = np.where(np.isnan(zi), -9999, zi)
    dst.GetRasterBand(1).WriteArray(zi)
    dst.GetRasterBand(1).SetNoDataValue(-9999)
    dst.FlushCache()
    dst = None
    print(f"✅ DEM 已保存为：{output_path}")

def runLakeDEM(param1, param2, param3, param4, param5, param6):
    """
    param1: point_file
    param2: z_field_name
    param3: breakline_file
    param4: lake_polygon_file
    param5: output_dem
    param6: resolution (由用户设置)
    其余参数用默认值:
        smooth_sigma=2.0
        interp_method='cubic'
        densify_interval=1.0
        breakline_z_value=0.0
    """
    print("开始执行湖泊DEM构建...")
    result = buildLakeDEM(
        param1, param2, param3, param4, param5,
        resolution=float(param6),
        smooth_sigma=2.0,
        interp_method='cubic',
        densify_interval=1.0,
        breakline_z_value=0.0
    )
    if result:
        print("✅ DEM 已生成：", result)
    else:
        print("❌ DEM生成失败！")
