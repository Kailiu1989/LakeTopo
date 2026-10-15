"""Exercise prediction-point generation on a disposable copy of the real inputs."""
import os
import sys
from pathlib import Path
import shutil
import tempfile

runtime = Path(r'C:\Users\DELL\anaconda3\envs\laketopo-build')
dll_handle = os.add_dll_directory(str(runtime / 'Library/bin'))
os.environ['PATH'] = str(runtime / 'Library/bin') + os.pathsep + os.environ['PATH']
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import A_PredictedPoints_Gen as prediction
import B_Depth_Prediction as depth
import dem_builder
import pandas as pd

source = Path('E:/\u629a\u4ed9\u6e56')
lake = source.name
with tempfile.TemporaryDirectory(prefix='fuxian_depth_fix_', dir=Path(__file__).parent) as folder:
    workspace = Path(folder) / lake
    workspace.mkdir()
    for suffix in ('_extent.tif', '_merit.tif', '_slope.tif'):
        shutil.copy2(source / (lake + suffix), workspace)
    for stem in (lake + '_wgs84', lake + '_survey'):
        for extension in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
            shutil.copy2(source / (stem + extension), workspace)
    survey = str(workspace / (lake + '_survey.shp'))
    points = dem_builder.read_points_with_z(survey, 'Depth')
    assert len(points) == 170409
    print('Terrain SHP reader:', len(points), 'points; depth range', points[:, 2].min(), points[:, 2].max(), flush=True)
    prediction.runPredictedPoints(
        str(workspace), lake, 5, 5,
        lake_polygon_file=str(workspace / (lake + '_wgs84.shp')),
        survey_file=survey,
    )
    training = workspace / 'MLData/Training.txt'
    testing = workspace / 'MLData/Test_5.txt'
    depth.MLdataProcessing(str(training), str(testing))
    data = pd.read_csv(training.with_suffix('.csv'))
    test_data = pd.read_csv(testing.with_suffix('.csv'))
    assert len(data) >= 6
    assert len(test_data) > 0
    assert data.notna().all().all()
    assert (data['ele'] > 0).all()
    print('Verified training samples:', len(data), '; prediction points:', len(test_data), flush=True)
    print('Source E: data was not modified.', flush=True)
