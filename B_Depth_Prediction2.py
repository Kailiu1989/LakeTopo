import xgboost as xgb
import pandas as pd
import numpy as np
import os
import csv
import matplotlib.pyplot as plt
from sklearn.metrics import mean_absolute_error, r2_score
import Common_Function as cf


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

    return workspace, lake

# 处理训练数据和测试数据
def MLdataProcessing(_trainingData, _testData):
    sourceTraining = cf.readTXTStr(_trainingData)
    processedDataFile = os.path.splitext(_trainingData)[0] + ".csv"
    data = []
    headers = ['slope300', 'slope600', 'slope900', 'diffele300', 'diffele600', 'diffele900', 'gradient300', 'gradient600', 'gradient900', 'distance', 'ele']
    for curIndex in range(len(sourceTraining)):
        tempList = sourceTraining[curIndex].split(",")
        temp = [str(tempList[4]), str(tempList[5]), str(tempList[6]), str(tempList[7]), str(tempList[8]), str(tempList[9]), str(tempList[10]), str(tempList[11]), str(tempList[12]), str(tempList[13]), str(tempList[14])]
        data.append(temp)
    with open(processedDataFile, 'w', newline='') as f:
        f_csv = csv.writer(f)
        f_csv.writerow(headers)
        f_csv.writerows(data)

    sourceTest = cf.readTXTStr(_testData)
    processedDataFile = os.path.splitext(_testData)[0] + ".csv"
    data = []
    headers = ['slope300', 'slope600', 'slope900', 'diffele300', 'diffele600', 'diffele900', 'gradient300', 'gradient600', 'gradient900', 'distance']
    for curIndex in range(len(sourceTest)):
        tempList = sourceTest[curIndex].split(",")
        temp = [str(tempList[4]), str(tempList[5]), str(tempList[6]), str(tempList[7]), str(tempList[8]), str(tempList[9]), str(tempList[10]), str(tempList[11]), str(tempList[12]), str(tempList[13])]
        data.append(temp)
    with open(processedDataFile, 'w', newline='') as f:
        f_csv = csv.writer(f)
        f_csv.writerow(headers)
        f_csv.writerows(data)

# 使用XGBoost进行训练和预测
def XGBoost(_trainingData, _testData, _predictedData, _plotPath=None):
    data = pd.read_csv(_trainingData)
    test_data = data.sample(frac=0.3, random_state=42)
    train_data = data.drop(test_data.index)
    
    X_train = train_data.drop('ele', axis=1)
    X_test = test_data.drop('ele', axis=1)
    y_train = train_data['ele']
    y_test = test_data['ele']

    model = xgb.XGBRegressor(learning_rate=0.01, n_estimators=1000, max_depth=7, min_child_weight=6, subsample=0.7, colsample_bytree=0.6, gamma=0.2, n_jobs=_xgb_thread_count())
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    pred_data = pd.read_csv(_testData)
    pred = model.predict(pred_data)
    
    result_reg = pd.DataFrame({'ele': pred})
    result_reg.to_csv(_predictedData, index=False, encoding='utf-8')
    
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    # 绘制散点图
    plt.scatter(y_test, y_pred, alpha=0.5)
    plt.plot([min(y_test), max(y_test)], [min(y_test), max(y_test)], 'r--')
    plt.xlabel('实际值')
    plt.ylabel('预测值')
    plt.title(f'预测 vs 实际 (R²={r2:.3f}, MAE={mae:.3f})')
    if _plotPath:
        plt.savefig(_plotPath, dpi=300, bbox_inches='tight')
    plt.show()
    plt.close()

    return mae, r2

# 主函数：生成预测点并处理结果
def runMLProcessing(workSPDir, lakeName, interval, plot_path=None):
    dataDir, lakeName = _resolve_workspace(workSPDir, lakeName)
    MLDir = os.path.join(dataDir, "MLData")
    tempDir = os.path.join(dataDir, "temp_ML")
    if not os.path.exists(tempDir):
        os.makedirs(tempDir)
    
    trainingData = os.path.join(MLDir, "Training.txt")
    testData = os.path.join(MLDir, f"Test_{interval}.txt")
    PredictedData = os.path.join(tempDir, f"Predicted_{interval}.csv")
    
    MLdataProcessing(trainingData, testData)  # 处理数据
    trainingData = os.path.splitext(trainingData)[0] + ".csv"
    testData = os.path.splitext(testData)[0] + ".csv"
    mae, r2 = XGBoost(trainingData, testData, PredictedData, plot_path)  # 训练并预测

    return mae, r2  # 返回MAE和R²
