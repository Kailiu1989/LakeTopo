import xgboost as xgb
import pandas as pd
import numpy as np
from xgboost import plot_importance
from xgboost import plot_tree
import Common_Function as cf
import os
import csv
from sklearn.model_selection import train_test_split
from sklearn.model_selection import GridSearchCV
from sklearn.metrics import mean_absolute_error
from osgeo import ogr

def _with_sep(path):
    return os.path.normpath(path) + os.sep


def _xgb_thread_count():
    return max(1, min((os.cpu_count() or 2) - 1, 4))


def _resolve_workspace(workSPDir, lakeName=None):
    workspace = os.path.normpath(workSPDir)
    lake = str(lakeName).strip() if lakeName else os.path.basename(workspace)
    legacy_workspace = os.path.join(workspace, lake) if lake else workspace

    if lake and os.path.basename(workspace) != lake and os.path.isdir(legacy_workspace):
        workspace = legacy_workspace
    else:
        lake = os.path.basename(workspace)

    return _with_sep(workspace), lake

# 处理训练数据和测试数据
def MLdataProcessing(_trainingData, _testData):
    sourceTraining = cf.readTXTStr(_trainingData)
    fname, extension = os.path.splitext(_trainingData)
    processedDataFile = fname + ".csv"
    data = []
    headers = ['slope300', 'slope600', 'slope900', 'diffele300', 'diffele600', 'diffele900', 'gradient300', 'gradient600', 'gradient900', 'distance', 'ele']
    for curIndex in range(0, len(sourceTraining)):
        tempList = sourceTraining[curIndex].split(",")
        temp = [str(tempList[4]), str(tempList[5]), str(tempList[6]), str(tempList[7]), str(tempList[8]), str(tempList[9]), str(tempList[10]), str(tempList[11]), str(tempList[12]), str(tempList[13]), str(tempList[14])]
        data.append(temp)
    with open(processedDataFile, 'w', newline='') as f:
        f_csv = csv.writer(f)
        f_csv.writerow(headers)
        f_csv.writerows(data)

    sourceTest = cf.readTXTStr(_testData)
    fname, extension = os.path.splitext(_testData)
    processedDataFile = fname + ".csv"
    data = []
    headers = ['slope300', 'slope600', 'slope900', 'diffele300', 'diffele600', 'diffele900', 'gradient300', 'gradient600', 'gradient900', 'distance']
    for curIndex in range(0, len(sourceTest)):
        tempList = sourceTest[curIndex].split(",")
        temp = [str(tempList[4]), str(tempList[5]), str(tempList[6]), str(tempList[7]), str(tempList[8]), str(tempList[9]), str(tempList[10]), str(tempList[11]), str(tempList[12]), str(tempList[13])]
        data.append(temp)

    with open(processedDataFile, 'w', newline='') as f:
        f_csv = csv.writer(f)
        f_csv.writerow(headers)
        f_csv.writerows(data)

# 使用XGBoost进行训练和预测
def XGBoost(_trainingData, _testData, _predictedData):
    data = pd.read_csv(_trainingData)

    test_data = data.sample(
        frac=0.3,
        replace=False,
        random_state=42,
        axis=0
    )

    train_data = data.drop(test_data.index)

    X_train = train_data.drop('ele', axis=1)
    X_test = test_data.drop('ele', axis=1)

    y_train = train_data['ele']
    y_test = test_data['ele']

    # 定义XGBoost模型
    model = xgb.XGBRegressor(objective='reg:squarederror', seed=42, n_jobs=_xgb_thread_count())

    # 设定网格搜索的参数范围
    param_grid = {
        'learning_rate': [0.01, 0.05, 0.1],
        'n_estimators': [1000],
        'max_depth': [3, 6, 7],
        'min_child_weight': [6, 3, 5],
        'subsample': [0.6, 0.7, 0.8],
        'colsample_bytree': [0.6, 0.7, 0.8],
        'gamma': [ 0.2]
    }

    # 使用GridSearchCV进行超参数调优
    grid_search = GridSearchCV(estimator=model, param_grid=param_grid, cv=3, verbose=0, n_jobs=1)
    grid_search.fit(X_train, y_train)

    # 打印最优参数
    print(f"Best parameters: {grid_search.best_params_}")

    # 使用最佳参数训练模型
    best_model = grid_search.best_estimator_
    ans = best_model.predict(X_test)

    # 计算MAE
    mae = mean_absolute_error(y_test, ans)
    print(f"MAE = {mae}")

    # 对测试数据进行预测
    pred_data = pd.read_csv(_testData)
    index = pred_data.index
    pred = best_model.predict(pred_data)

    # 保存预测结果到CSV文件
    result_reg = pd.DataFrame(index)
    result_reg['ele'] = pred
    result_reg.to_csv(_predictedData, encoding='gb2312')

    return mae  # 返回MAE

# 处理结果数据
def results_processing(_workSP, _para_interval, lake_name):
    # 假设处理结果文件路径和湖泊 Survey 文件路径
    predictedEleFile = _workSP + "temp_ML\\Predicted_" + str(_para_interval) + ".csv"
    sourceDataFile = _workSP + "MLData\\Test_" + str(_para_interval) + ".txt"
    processedFile = _workSP + "temp_ML\\PredictedPoints_" + str(_para_interval) + ".txt"
    shpFile = _workSP + "temp_ML\\PredictedPoints_" + str(_para_interval) + ".shp"  # 输出shp文件路径

    # 读取源数据的坐标
    CoordXY = []
    with open(sourceDataFile, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            CoordXY.append((float(row[2]), float(row[3])))  # 假设坐标在第三列和第四列

    # 读取预测值
    Ele = []
    with open(predictedEleFile, 'r') as f:
        rows = csv.reader(f)
        next(rows)  # Skip header row
        for r in rows:
            Ele.append(str(r[2]))  # 假设预测值在第三列

    # 合并坐标和预测值，写入到新的文本文件
    mergedList = []
    for index in range(len(Ele)):
        mergedList.append(f"{CoordXY[index][0]},{CoordXY[index][1]},{Ele[index]}")

    with open(processedFile, 'w') as f:
        for line in mergedList:
            f.write(f"{line}\n")

    # 创建点数据框 (GeoDataFrame)
    driver = ogr.GetDriverByName("ESRI Shapefile")
    if driver is None:
        raise Exception("Shapefile driver not available.")

    # 使用lakeName_Survey.shp来获取坐标系
    surveyShpPath = _workSP + str(lake_name) + "_Survey.shp"
    survey_ds = ogr.Open(surveyShpPath)
    if survey_ds is None:
        raise Exception(f"Failed to open the shapefile: {surveyShpPath}")
    survey_layer = survey_ds.GetLayer()

    # 获取原始shp的投影
    spatial_ref = survey_layer.GetSpatialRef()

    # 创建新的shp文件
    out_ds = driver.CreateDataSource(shpFile)
    out_layer = out_ds.CreateLayer("PredictedPoints", spatial_ref, ogr.wkbPoint)

    # 定义字段
    out_layer.CreateField(ogr.FieldDefn("Field1", ogr.OFTString))  # X坐标
    out_layer.CreateField(ogr.FieldDefn("Field2", ogr.OFTString))  # Y坐标
    out_layer.CreateField(ogr.FieldDefn("Depth", ogr.OFTString))  # 预测值

    # 遍历合并后的数据并写入shp
    for i in range(len(CoordXY)):
        x = CoordXY[i][0]
        y = CoordXY[i][1]
        ele = Ele[i]

        # 创建点几何对象
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint(x, y)

        # 创建特征
        feature = ogr.Feature(out_layer.GetLayerDefn())
        feature.SetGeometry(point)
        feature.SetField("Field1", str(x))
        feature.SetField("Field2", str(y))
        feature.SetField("Depth", str(ele))

        # 将特征写入图层
        out_layer.CreateFeature(feature)

    # 清理
    out_ds = None
    survey_ds = None

    print(f"Shapefile created at {shpFile}")

# 调用函数
def runMLProcessing(param1, param2, param3, param4, param5):
    print('++++++++++++++++start+++++++++++++++++++++')

    ############## 输入数据 ####################
    workSPDir, resolved_lake = _resolve_workspace(param1, param2)
    lakeName = [resolved_lake]  # 输入需要进行处理的湖泊
    intervalList = [param3]  # 生成的预测点间隔
    para_Window = param4  # 窗口大小
    para_cellsize = param5  # 处理的像元大小
    ############## 输入数据 ####################

    for lakeIndex in range(0, len(lakeName)):
        print(lakeName[lakeIndex])
        dataDir = workSPDir
        MLDir = dataDir + "MLData\\"
        tempDir = dataDir + "temp_ML\\"
        if os.path.exists(tempDir):
            cf.del_file(tempDir)
        else:
            os.makedirs(tempDir)
        for intervalIndex in range(0, len(intervalList)):
            trainingData = MLDir + "Training.txt"  # 训练数据路径
            testData = MLDir + "Test_" + str(intervalList[intervalIndex]) + ".txt"  # 测试数据路径
            PredictedData = tempDir + "Predicted_" + str(intervalList[intervalIndex]) + ".csv"  # 生成预测点csv文件
            MLdataProcessing(trainingData, testData)
            trainingData = MLDir + "Training.csv"
            testData = MLDir + "Test_" + str(intervalList[intervalIndex]) + ".csv"
            XGBoost(trainingData, testData, PredictedData)
            results_processing(dataDir, intervalList[intervalIndex], lakeName[lakeIndex])  # 生成shp文件
