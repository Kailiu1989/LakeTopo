# LakeTopo 打包说明

推荐使用 PyInstaller 的 `onedir` 模式打包。打包结果不是单个 exe，而是一个可复制的发布目录：

```text
dist/
  LakeTopo/
    LakeTopo.exe
    _internal/
      assets/
      cesiumTool/
      User_guide.pdf
      ...
```

## 构建步骤

1. 使用 Python 3.11 环境。推荐用 conda-forge 创建打包环境：

```powershell
conda env create -f environment.yml
conda activate laketopo-build
```

2. 如果不用 conda，也可以手动安装依赖：

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

3. 在项目根目录运行：

```powershell
.\build_release.bat
```

4. 将 `dist\LakeTopo` 整个文件夹拷贝给用户，用户运行其中的 `LakeTopo.exe`。

## 注意事项

- 项目依赖 `PyQtWebEngine`、`GDAL/osgeo` 和 Cesium 静态资源，建议使用文件夹发布，启动更稳定，也便于排查缺失 DLL 或数据文件。
- `User_guide.pdf` 已按打包资源处理，随发布目录一起分发。
- 如果目标电脑安全软件拦截本地端口，请允许 `LakeTopo.exe` 使用 `localhost:9001`，Cesium 视图需要通过本地 HTTP 服务加载。
