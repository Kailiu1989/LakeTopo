# Validation figure contract and QA notes

- Core conclusion: The paired 1:25,000 and 1:250,000 endpoints directly show
  how strong survey thinning changes both XGBoost-reconstructed 5 m lake-basin
  morphology and independent predictive accuracy.
- Figure 7-like archetype: mixed-modality figure pairing two terrain rasters
  with their two observed-versus-predicted validation panels.
- Model-comparison archetype: quantitative grid comparing LightGBM, Random
  Forest, and XGBoost at 1:25,000.
- Backend: Python (matplotlib) for drawing, previewing, exporting, and visual QA.
- Typography: Times New Roman is applied globally to titles, panel labels,
  lake names, axes, tick labels, metric annotations, and colorbars in both
  Figure 7 and Figure 10.
- Evidence hierarchy: terrain rasters are the representative spatial evidence;
  independent check-line scatter plots and MAE/RMSE annotations are the
  quantitative validation evidence; the three-model grid is the model control.
- Figure 7 lake selection: the six user-specified lakes are plotted in the
  requested order: Zhupohu, Aletaiwurenhu6, Wanghuapao, BajiucuoS, Jiangcuo,
  and Qionghai.  All six have complete endpoint-scale XGBoost evidence; their
  identifiers and summary errors are recorded in `Figure_7_selected_lakes.csv`.
  Visible English labels use `Aletaiwuren Lake No.6`, `Wanghua Lake`, and
  `Qionghai Lake` for the three user-revised names.
- Figure 7 terrain panels: shallow-to-deep depths use the requested
  red-yellow-light-blue sequence, with red shoreline values and blue deep-water
  values; each lake row uses one shared depth range across the two displayed
  scales.  The two DEM columns use identical fixed outer frames, while the
  frameless lake rasters are centered and scaled without changing aspect ratio.
- Figure 7 scatter panels: MAE, RMSE, and the number of finite independent
  validation pairs (N) are shown.  The top and right marginal curves are
  Gaussian kernel-density estimates of observed and predicted depths,
  respectively, normalized to unit peak height for compact visual comparison.
  The marginal-grid geometry is matched to the equal-aspect main axis, so the
  top density curve spans exactly the plotted x range.
- Figure 10 scatter panels: only MAE and RMSE are shown, as requested.
- Scatter axes in both figures use identical x/y limits and ticks within each
  panel, one decimal place on every tick label, and no internal grid lines.
- Figure 7 layout revision (2026-09-10): only the 1:25,000 and 1:250,000 DEMs
  and their matching validation panels are retained.  The six-row, four-panel
  layout uses reduced within-group column spacing, a narrow
  terrain/validation gutter, and reduced inter-row spacing, while retaining
  clearance for titles, tick labels, metric boxes, marginal density curves,
  and colorbar units.
- Figure 7 spacing revision (2026-09-18): the figure canvas now matches the
  square row-container width, eliminating unused horizontal GridSpec space.
  DEM frames are wider, and only narrow annotation-sized gutters remain between
  the DEM/validation and the two validation columns.  The depth unit sits above
  each colorbar inside its panel rather than projecting into the next column.
- Figure 7 layout revision (2026-09-21): the six lakes are arranged as two
  side-by-side blocks with three lake rows per block (first three lakes at
  left, remaining three at right).  Each lake retains the two DEM and two
  validation panels.  The former `a` and `b` group labels are removed, and
  scale/validation headings are repeated above both blocks.
- Source data: `validation_predictions/` CSV files and XGBoost terrain TIFFs in
  this result tree.
- Export bundle: editable SVG and PDF, 300 dpi PNG preview, and 600 dpi LZW TIFF.
- Integrity: raster values are displayed without local image edits; each lake
  row uses a shared depth normalization across its two displayed scales.
- Reviewer risks checked: shared axes within each scatter panel, identity line,
  matched marginal ranges, requested per-panel metrics, model names, scale
  labels, readable labels, editable SVG text, and traceable source paths.
