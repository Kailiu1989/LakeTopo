import xgboost as xgb
import pandas as pd
import numpy as np
import Common_Function as cf
import os
import csv
from sklearn.model_selection import train_test_split
from sklearn.model_selection import GridSearchCV
from sklearn.metrics import mean_absolute_error
from sklearn.ensemble import RandomForestRegressor
from osgeo import ogr


MODEL_CHOICES = ("XGBoost", "Random Forest", "LightGBM")


def _report_progress(progress_callback, value, message):
    """Report bounded integer progress without coupling the backend to Qt."""
    if progress_callback is not None:
        progress_callback(max(0, min(100, int(value))), message)

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

def _normalize_model_name(model_name):
    normalized = str(model_name or "XGBoost").strip().lower().replace("_", " ")
    aliases = {
        "xgb": "XGBoost",
        "xgboost": "XGBoost",
        "rf": "Random Forest",
        "rs": "Random Forest",
        "random forest": "Random Forest",
        "randomforest": "Random Forest",
        "lgbm": "LightGBM",
        "light gbm": "LightGBM",
        "lightgbm": "LightGBM",
    }
    if normalized not in aliases:
        raise ValueError(
            f"Unsupported model '{model_name}'. Choose one of: {', '.join(MODEL_CHOICES)}"
        )
    return aliases[normalized]


def _model_and_grid(model_name):
    threads = _xgb_thread_count()
    if model_name == "XGBoost":
        model = xgb.XGBRegressor(
            objective="reg:squarederror", random_state=42, n_jobs=threads
        )
        grid = {
            "learning_rate": [0.01, 0.05, 0.1],
            "n_estimators": [1000],
            "max_depth": [3, 6, 7],
            "min_child_weight": [3, 5, 6],
            "subsample": [0.6, 0.7, 0.8],
            "colsample_bytree": [0.6, 0.7, 0.8],
            "gamma": [0.2],
        }
        return model, grid

    if model_name == "Random Forest":
        model = RandomForestRegressor(random_state=42, n_jobs=threads)
        grid = {
            "n_estimators": [300],
            "max_depth": [None, 10, 20],
            "min_samples_split": [2, 5],
            "min_samples_leaf": [1, 2],
            "max_features": ["sqrt", 0.8],
        }
        return model, grid

    try:
        from lightgbm import LGBMRegressor
    except ImportError as exc:
        raise RuntimeError(
            "LightGBM is not installed. Install the 'lightgbm' package and rebuild LakeTopo."
        ) from exc
    model = LGBMRegressor(
        objective="regression",
        random_state=42,
        n_jobs=threads,
        verbosity=-1,
        subsample_freq=1,
    )
    grid = {
        "learning_rate": [0.03, 0.05, 0.1],
        "n_estimators": [500],
        "num_leaves": [15, 31, 63],
        "max_depth": [-1, 10],
        "min_child_samples": [10, 20],
        "subsample": [0.8],
        "colsample_bytree": [0.8],
    }
    return model, grid


def train_and_predict(
    model_name,
    training_data,
    test_data,
    predicted_data,
    progress_callback=None,
):
    """Train the selected regressor, report holdout MAE, and predict the lake grid."""
    model_name = _normalize_model_name(model_name)
    _report_progress(progress_callback, 28, "Loading model training and prediction data…")
    data = pd.read_csv(training_data)
    if "ele" not in data.columns:
        raise ValueError("Training data must contain an 'ele' target column.")
    if len(data) < 6:
        raise ValueError("At least 6 training samples are required for model validation.")

    feature_names = [column for column in data.columns if column != "ele"]
    data = data[feature_names + ["ele"]].apply(pd.to_numeric, errors="raise")
    prediction_features = pd.read_csv(test_data)
    missing = [name for name in feature_names if name not in prediction_features.columns]
    if missing:
        raise ValueError(f"Prediction data is missing fields: {', '.join(missing)}")
    prediction_features = prediction_features[feature_names].apply(
        pd.to_numeric, errors="raise"
    )

    X_train, X_holdout, y_train, y_holdout = train_test_split(
        data[feature_names],
        data["ele"],
        test_size=0.3,
        random_state=42,
    )
    model, param_grid = _model_and_grid(model_name)
    cv_folds = min(3, len(X_train))
    if cv_folds < 2:
        raise ValueError("Not enough training samples for cross-validation.")
    grid_search = GridSearchCV(
        estimator=model,
        param_grid=param_grid,
        cv=cv_folds,
        scoring="neg_mean_absolute_error",
        verbose=0,
        n_jobs=1,
        error_score="raise",
    )
    combination_count = int(np.prod([len(values) for values in param_grid.values()]))
    _report_progress(
        progress_callback,
        42,
        f"Optimizing {model_name} ({combination_count} parameter combinations)…",
    )
    grid_search.fit(X_train, y_train)

    _report_progress(progress_callback, 82, "Evaluating the selected model…")
    best_model = grid_search.best_estimator_
    holdout_prediction = best_model.predict(X_holdout)
    mae = float(mean_absolute_error(y_holdout, holdout_prediction))
    _report_progress(progress_callback, 87, "Predicting bathymetry depths…")
    prediction = best_model.predict(prediction_features)
    pd.DataFrame({"ele": prediction}).to_csv(
        predicted_data, index=False, encoding="utf-8"
    )
    print(f"Model = {model_name}")
    print(f"Best parameters = {grid_search.best_params_}")
    print(f"Holdout MAE = {mae}")
    return mae


def XGBoost(_trainingData, _testData, _predictedData):
    return train_and_predict("XGBoost", _trainingData, _testData, _predictedData)


def RandomForest(_trainingData, _testData, _predictedData):
    return train_and_predict("Random Forest", _trainingData, _testData, _predictedData)


def LightGBM(_trainingData, _testData, _predictedData):
    return train_and_predict("LightGBM", _trainingData, _testData, _predictedData)

# 处理结果数据
def results_processing(
    _workSP,
    _para_interval,
    lake_name,
    progress_callback=None,
    survey_file=None,
):
    # 假设处理结果文件路径和湖泊 Survey 文件路径
    predictedEleFile = _workSP + "temp_ML\\Predicted_" + str(_para_interval) + ".csv"
    sourceDataFile = _workSP + "MLData\\Test_" + str(_para_interval) + ".txt"
    processedFile = _workSP + "temp_ML\\PredictedPoints_" + str(_para_interval) + ".txt"
    shpFile = _workSP + "temp_ML\\PredictedPoints_" + str(_para_interval) + ".shp"  # 输出shp文件路径

    _report_progress(progress_callback, 91, "Preparing predicted point coordinates…")
    # 读取源数据的坐标
    CoordXY = []
    with open(sourceDataFile, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            CoordXY.append((float(row[2]), float(row[3])))  # 假设坐标在第三列和第四列

    # 读取预测值
    with open(predictedEleFile, 'r', encoding='utf-8') as f:
        rows = csv.DictReader(f)
        if not rows.fieldnames or 'ele' not in rows.fieldnames:
            raise ValueError(f"Prediction output has no 'ele' column: {predictedEleFile}")
        Ele = [str(row['ele']) for row in rows]
    if len(Ele) != len(CoordXY):
        raise ValueError(
            f"Prediction count ({len(Ele)}) does not match point count ({len(CoordXY)})."
        )

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

    # 使用用户选择的实测点 SHP 获取坐标系；未传入时保留旧命名规则兼容旧入口。
    surveyShpPath = (
        os.path.normpath(survey_file)
        if survey_file
        else _workSP + str(lake_name) + "_Survey.shp"
    )
    survey_ds = ogr.Open(surveyShpPath)
    if survey_ds is None:
        raise Exception(f"Failed to open the shapefile: {surveyShpPath}")
    survey_layer = survey_ds.GetLayer()
    if survey_layer is None:
        raise ValueError(f"The survey shapefile contains no readable layer: {surveyShpPath}")

    # 获取原始shp的投影
    spatial_ref = survey_layer.GetSpatialRef()
    if spatial_ref is None:
        raise ValueError(
            f"The survey shapefile has no spatial reference (.prj): {surveyShpPath}"
        )

    # 创建新的shp文件
    out_ds = driver.CreateDataSource(shpFile)
    out_layer = out_ds.CreateLayer("PredictedPoints", spatial_ref, ogr.wkbPoint)

    # 定义字段
    out_layer.CreateField(ogr.FieldDefn("Field1", ogr.OFTString))  # X坐标
    out_layer.CreateField(ogr.FieldDefn("Field2", ogr.OFTString))  # Y坐标
    out_layer.CreateField(ogr.FieldDefn("Depth", ogr.OFTString))  # 预测值

    # 遍历合并后的数据并写入shp
    feature_count = len(CoordXY)
    last_percent = -1
    for i in range(feature_count):
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

        percent = 94 + int(5 * (i + 1) / max(1, feature_count))
        if percent != last_percent:
            _report_progress(
                progress_callback,
                percent,
                f"Writing predicted depths ({i + 1}/{feature_count} points)…",
            )
            last_percent = percent

    # 清理
    out_ds = None
    survey_ds = None

    print(f"Shapefile created at {shpFile}")

# 调用函数
def runMLProcessing(
    param1,
    param2,
    param3,
    param4,
    param5,
    model_name="XGBoost",
    progress_callback=None,
    survey_file=None,
):
    print('++++++++++++++++start+++++++++++++++++++++')
    _report_progress(progress_callback, 0, "Preparing depth prediction…")

    ############## 输入数据 ####################
    workSPDir, resolved_lake = _resolve_workspace(param1, param2)
    lakeName = [resolved_lake]  # 输入需要进行处理的湖泊
    intervalList = [param3]  # 生成的预测点间隔
    para_Window = param4  # 窗口大小
    para_cellsize = param5  # 处理的像元大小
    model_name = _normalize_model_name(model_name)
    ############## 输入数据 ####################

    for lakeIndex in range(0, len(lakeName)):
        print(lakeName[lakeIndex])
        dataDir = workSPDir
        MLDir = dataDir + "MLData\\"
        tempDir = dataDir + "temp_ML\\"
        _report_progress(progress_callback, 7, "Preparing model output folder…")
        if os.path.exists(tempDir):
            cf.del_file(tempDir)
        else:
            os.makedirs(tempDir)
        for intervalIndex in range(0, len(intervalList)):
            trainingData = MLDir + "Training.txt"  # 训练数据路径
            testData = MLDir + "Test_" + str(intervalList[intervalIndex]) + ".txt"  # 测试数据路径
            PredictedData = tempDir + "Predicted_" + str(intervalList[intervalIndex]) + ".csv"  # 生成预测点csv文件
            _report_progress(progress_callback, 15, "Converting model input data…")
            MLdataProcessing(trainingData, testData)
            trainingData = MLDir + "Training.csv"
            testData = MLDir + "Test_" + str(intervalList[intervalIndex]) + ".csv"
            mae = train_and_predict(
                model_name,
                trainingData,
                testData,
                PredictedData,
                progress_callback,
            )
            results_processing(
                dataDir,
                intervalList[intervalIndex],
                lakeName[lakeIndex],
                progress_callback,
                survey_file=survey_file,
            )  # 生成shp文件
    _report_progress(progress_callback, 100, "Depth prediction completed.")
    return mae
