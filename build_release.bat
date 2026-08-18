@echo off
setlocal
cd /d "%~dp0"

python -c "import PyInstaller, numpy, lightgbm; from osgeo import gdal, gdal_array; from PyQt5 import QtWebEngineWidgets; from sklearn.ensemble import RandomForestRegressor"
if errorlevel 1 (
    echo.
    echo Build environment check failed.
    echo Please run: conda activate laketopo-build
    exit /b 1
)

python -m PyInstaller --noconfirm --clean LakeTopo.spec
if errorlevel 1 (
    echo.
    echo Build failed. Please check the error messages above.
    exit /b 1
)

echo.
echo Running packaged GDAL smoke test...
start "" /wait "%cd%\dist\LakeTopo\LakeTopo.exe" --packaging-smoke-test
if errorlevel 1 (
    echo.
    echo Build output failed the GDAL smoke test.
    echo Details: %cd%\dist\LakeTopo\packaging-smoke-test.txt
    exit /b 1
)

echo.
echo Build and GDAL smoke test complete:
echo %cd%\dist\LakeTopo\LakeTopo.exe
