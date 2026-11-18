"""Regression tests for point-level filtering before GDAL rasterization."""
import os,sys,tempfile,json,unittest
from pathlib import Path
if os.name=='nt':
    os.environ['PATH']=str(Path(sys.executable).parent/'Library/bin')+os.pathsep+os.environ['PATH']
    _dll=os.add_dll_directory(str(Path(sys.executable).parent/'Library/bin'))
from osgeo import ogr,osr,gdal
import numpy as np
import Common_Function as cf
import A_PredictedPoints_Gen as a

class SurveyFilterTest(unittest.TestCase):
    def test_threshold_order_and_ties(self):
        values=[None,'bad',float('nan'),float('inf'),-1,0,0.1]+[1]*99+[2,100]
        depths,keep,s=cf.survey_depth_filter(values)
        self.assertEqual(s['p99'],2)
        self.assertEqual(s['retained'],100)
        self.assertEqual(s['excluded_le_0_1'],3)
        self.assertEqual(s['invalid'],4)
        self.assertEqual(s['excluded_gt_p99'],1)
        self.assertTrue(keep[-2]);self.assertFalse(keep[-1])
        self.assertEqual(cf.survey_depth_filter([3,3,3])[2]['retained'],3)
    def test_empty(self):
        for values in ([],[None,0,.1,-2]):
            with self.assertRaises(ValueError):cf.survey_depth_filter(values)
    def test_rasterization_filters_before_cell_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            src=str(Path(td)/'survey.shp');output=str(Path(td)/'survey.tif')
            ds=ogr.GetDriverByName('ESRI Shapefile').CreateDataSource(src)
            srs=osr.SpatialReference();srs.ImportFromEPSG(32651)
            layer=ds.CreateLayer('survey',srs,ogr.wkbPoint)
            layer.CreateField(ogr.FieldDefn('depth',ogr.OFTString))
            for v in [1]*99+[2,100,.1,'bad']:
                f=ogr.Feature(layer.GetLayerDefn());g=ogr.Geometry(ogr.wkbPoint);g.AddPoint(500015,4499985);f.SetGeometry(g);f.SetField('depth',str(v));layer.CreateFeature(f)
            ds=None
            original=Path(src).with_suffix('.dbf').read_bytes()
            class Grid:
                def NCol(self):return 2
                def NRow(self):return 2
                def XTopLeft(self):return 500000
                def YTopLeft(self):return 4500000
                def CellSize(self):return 30
                def CellSizeY(self):return 30
            a.rasterize_survey_to_template(src,output,Grid(),srs.ExportToWkt())
            rd=gdal.Open(output);self.assertEqual(float(rd.ReadAsArray()[0,0]),2)
            report=json.loads(Path(td,'survey_filter.json').read_text('utf-8'))
            self.assertEqual(report['p99'],2)
            self.assertEqual(report['retained'],100)
            self.assertEqual(Path(src).with_suffix('.dbf').read_bytes(),original)
            rd=None
if __name__=='__main__':unittest.main()
