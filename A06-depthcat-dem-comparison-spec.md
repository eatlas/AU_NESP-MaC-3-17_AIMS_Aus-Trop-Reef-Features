# A06 DepthCat vs DEM depth comparison: specification

Status: Implemented (2026-11-03). Script: `A06-depthcat-dem-comparison.py`.

## 1. Purpose

The `DepthCat` attribute (Intertidal, Very Shallow, Shallow, Deep) is assumed to correspond to approximately fixed depth ranges of the reef peak. These ranges were calibrated only for the clear oceanic water of the Coral Sea. This analysis provides a first approximation of the depth ranges that each `DepthCat` corresponds to in each analysis region, by comparing `DepthCat` against the automatically derived DEM depth of each feature (`DEM90pLAT`).

The analysis aims to answer:

1. What distribution of DEM depths does each `DepthCat` correspond to in each region?
2. What are the approximate transition depths between adjacent categories in each region, and how do they compare with the clear-water Coral Sea thresholds?
3. Where is the available bathymetry adequate to support this type of calibration, and where is it not?

This is not a full calibration. A full calibration would require a manual assessment of each reef to confirm that the available bathymetry resolves the reef peak. The results are intended as an indication of regional variation and as a guide to where a full calibration would be worthwhile.

## 2. Background (for the final report)

### 2.1 How DepthCat was assigned

`DepthCat` records the depth of the shallowest part of each feature. It was predominantly assigned from the visibility of the feature in contrast-enhanced Sentinel 2 composites:

| DepthCat | Detection rule | Imagery tide state |
|---|---|---|
| Intertidal | Visible in the infrared band (B8) | Low tide composite |
| Very Shallow | Visible in the red band (B4), not infrared | Low tide composite |
| Shallow | Visible in the green band (B3), not red | All tide composite (approx. MSL) |
| Deep | Not visible in green | All tide composite (approx. MSL) |

Detection is relative to the local brightness and noise of the surrounding water, rather than a fixed brightness threshold. This makes the method adapt to local conditions, but it also means the depth of each transition varies with water clarity and substrate albedo. Turbid water and dark substrates are expected to make features appear deeper (shallower transition depths). Because the low tide imagery approximates LAT, the Intertidal/Very Shallow and Very Shallow/Shallow transitions are referenced approximately to LAT. The Shallow/Deep transition is determined from all tide imagery and is therefore referenced approximately to MSL. In macrotidal regions this transition, expressed relative to LAT, is expected to be shallower by approximately the local MSL to LAT offset.

### 2.2 Clear-water reference thresholds (Coral Sea)

In the Coral Sea the thresholds were calibrated against AHO marine chart soundings for 880 reefs where the chart mapping aligned closely with the mapped reef (Lawrey et al., 2026). Sweeping candidate thresholds and maximising the F1 score gave optimal thresholds of 2.4 m (Very Shallow) and 24 m (Deep). These were retained at 2.5 m and 25 m for consistency with chart-derived classifications, giving 87.6% overall accuracy. The reference thresholds used in this analysis are:

| Boundary | Clear-water depth (m LAT) |
|---|---|
| Intertidal / Very Shallow | 0 |
| Very Shallow / Shallow | -2.5 |
| Shallow / Deep | -25 |

### 2.3 Limitations of the DEM as a reference

`DEM90pLAT` is the 90th percentile of DEM elevation (relative to LAT) within each feature polygon (05-add-depth.py), so it approximates the shallowest part of the feature as seen by the DEM. The DEM is a gridded, pixel-averaged product (MultiResBathyEEZ_2024, or AusBathyTopo-250m_2024 where not available). Where the DEM does not resolve the reef, the value is dominated by the surrounding seabed and is too deep. This is most severe for small, steep features such as lagoonal patch reefs, whose peaks are averaged down. The Coral Sea report found differences of more than 5 m between chart peak depths and 30 m pixel-averaged depths for small lagoonal reefs.

Errors are not only in the deep direction. In nearshore areas DEM positional offsets, coastal smoothing and land or intertidal contamination can make features appear shallower than they are. Exploratory analysis found nearshore Shallow features with `DEM90pLAT` well above LAT. The comparison must therefore be robust to noise in both directions.

### 2.4 Coral Sea as a cautionary case

The Coral Sea is the only region where the true thresholds are known reasonably well, so it is retained as a test of the method. However, exploratory analysis indicates that for most Coral Sea reefs the DEM is too coarse to resolve reef peaks (30 m bathymetry only covers the western Coral Sea). Estimated thresholds are far deeper than the calibrated values (approximately -20 m for Very Shallow/Shallow and -43 m for Shallow/Deep, compared with -2.5 m and -25 m). This is a demonstration of how the approach fails where bathymetry is inadequate, and should be reported as such.

### 2.5 GBR as a secondary calibration

The GBR has reasonably good bathymetry and reefs spanning the full range of depths, so it can serve as a secondary calibration reference. Torres Strait also has good bathymetry, but its reefs cover only a limited range of depths and it has no Deep features.

## 3. Inputs

| Input | Path |
|---|---|
| Reef features | `data/{version}/out/full-classes/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp` |
| Analysis regions | `{in_3p_path}/nesp-3-17-analysis-regions/analysis-regions.shp` (field `region`) |
| Version and paths | `config.ini` (`[general] version`, `in_3p_path`), as in A05 |

Run after `08-make-RB_Type_L2.py` (requires `RB_Type_L2`).

Attributes used: `DepthCat`, `DepthCatSr`, `RB_Type_L2`, `DEM90pLAT`, `DEM10pLAT`, `DEMSr`, `Area_km2`.

## 4. Feature selection

| Step | Rule | Reason |
|---|---|---|
| DepthCat | Intertidal, Very Shallow, Shallow, Deep | Land and Surface are not depth classes |
| DepthCatSr | Sentinel 2 Infrared, Sentinel 2 Red, Sentinel 2 Green, Sentinel 2 Blue, Sentinel 2 Intertidal, S2 Low tide Infrared, Google Earth, Queensland Globe | Image-based sources only. Bathymetry-derived classifications (MultiResBathyEEZ, AusBathyTopo) would be circular. AHO chart and `RB_Type_L3 rule` sources are excluded as they do not reflect optical visibility |
| RB_Type_L2 | Coral Reef, Rocky Reef, Sediment | Main mapped types; Sediment Reef and Microbial Reef have too few features |
| DEM | `DEM90pLAT` not null | |

Approximately 18,400 features remain.

## 5. Regionalisation

Features are assigned to the `region` field of the analysis regions (Nearshore and Offshore combined). The region polygons are dissolved by `region`, and each feature is assigned by a spatial join (`within`) of its representative point, both in EPSG:3577. If a point falls in more than one region, the first match is kept. Features outside all regions are counted and reported, then dropped. Combining Nearshore and Offshore increases sample sizes and allows the Shallow/Deep boundary to be estimated where Deep features occur only offshore. It also mixes turbid nearshore and clearer offshore water, which broadens the distributions. The region field is a configurable constant so that `subregion` can be used later.

Regions are sorted alphabetically before joining, making the first match deterministic. Invalid feature boundaries are reported as a warning, but may be used if their projected representative points are valid: this analysis does not overlay feature polygons. Null or empty geometries, missing CRS, invalid regions or invalid representative points stop the analysis.

Feature counts after selection (v1-0; these are the class sizes used for the thresholds):

| Region | Intertidal | Very Shallow | Shallow | Deep | All |
|---|---|---|---|---|---|
| Coral Sea | 0 | 189 | 539 | 1492 | 2220 |
| GBR | 1511 | 1148 | 1547 | 31 | 4237 |
| North | 1426 | 1587 | 701 | 8 | 3722 |
| North-west | 2303 | 2828 | 2017 | 10 | 7158 |
| Oceanic | 0 | 10 | 9 | 0 | 19 |
| Papua New Guinea | 0 | 33 | 24 | 0 | 57 |
| South-west | 20 | 43 | 152 | 136 | 351 |
| Temperate East | 24 | 26 | 110 | 5 | 165 |
| Timor East / Indonesia | 5 | 26 | 193 | 31 | 255 |
| Torres Strait | 61 | 66 | 92 | 0 | 219 |

The Shallow/Deep boundary can only be estimated for the Coral Sea, GBR, South-west and Timor East / Indonesia.

## 6. Extreme DEM values (no trim)

No physical-plausibility trim is applied. An earlier version removed values that the optical method could not produce in any water clarity (for example, Very Shallow below -15 m). Because the limits differed by class, the trim removed the overlap between adjacent classes by construction. This inflated the balanced accuracy and narrowed the bootstrap intervals, and in the Coral Sea it fixed the thresholds at the trim limits. The sweep depends only on the rank order of depths, so extreme values affect it only through their count. Values outside the plot range are clipped into the end bins of the histograms and counted in the legend.

## 7. Quality filter search (not applied)

Quality filters were tested to see whether selecting features more likely to be resolved by the DEM would improve the results:

| Filter | Constant | Search values |
|---|---|---|
| Minimum feature area (`Area_km2` attribute) | `SEARCH_AREA_KM2` | 0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0 km² |
| Minimum DEM relief (`DEM90pLAT - DEM10pLAT`) | `SEARCH_RELIEF_M` | 0, 1, 2, 4, 8 m |
| Exclude AusBathyTopo-250m DEM source (`DEMSr` starts with `AusBathyTopo`; null `DEMSr` is kept) | `SEARCH_AUSBATHYTOPO` | include, exclude |

Each parameter is varied independently, with the others at their neutral value (0 or include). Filters keep features with values `>=` the setting. For each value, for each region and for all regions combined, the search reports:

- the percentage of features retained, overall and per DepthCat,
- the interquartile range of `DEM90pLAT` per DepthCat (only where at least `MIN_N` features remain),
- per region only, the sweep threshold and balanced accuracy for each boundary (Section 8, without bootstrap).

The aim was to find filter values that remove roughly 30 to 50% of features and to see whether filtering tightens the distributions or moves the estimated DepthCat thresholds closer to the clear-water thresholds calibrated from marine charts in the Coral Sea. Feature area, within-feature DEM relief and DEM source are tested as proxies for whether the bathymetry resolves the feature well enough to estimate its depth.

Outcome of the search (v1-0): area >= 0.05 km² removes 37% of features nationally. Relief >= 2 m removes 44% but increases the spread. Neither filter materially reduces the interquartile range of any DepthCat, so feature size and DEM relief are weak proxies for whether the DEM resolves a reef. Excluding AusBathyTopo-250m removes only 2% nationally, but it removes nearly all features in Papua New Guinea and Timor East / Indonesia, where no higher resolution DEM is available. Filtering does shift some regional thresholds (for example, Torres Strait Very Shallow/Shallow) and removes some estimates by dropping a class below `MIN_N` (GBR Shallow/Deep, Timor East / Indonesia). These shifts reflect smaller samples rather than better data, so no filter is applied. The search is retained as a plot and CSV for the report appendix, but is not included in the markdown tables.

## 8. Threshold estimation

### 8.1 Threshold sweep (primary estimator)

This adapts the Coral Sea calibration method, with the DEM in place of AHO chart depths. For each pair of adjacent categories (upper = shallower class, lower = deeper class) in each region:

1. Sweep candidate thresholds `t` from -60 to +10 m inclusive in 0.1 m steps (701 values).
2. Classify features with `DEM90pLAT >= t` as the upper class and `< t` as the lower class.
3. Compute balanced accuracy = (recall of upper + recall of lower) / 2.
4. The threshold is the `t` with maximum balanced accuracy. Where the maximum is reached over a run of consecutive `t` values, use the midpoint of the longest run (the first if tied), rounded to 0.01 m. Values within 1e-12 of the maximum count as maximal.
5. F1 for each class is calculated at the selected threshold, treating that class as positive.

The Coral Sea calibration maximised the F1 score. Balanced accuracy is used here instead, so the method is an adaptation rather than a repeat. F1 depends on which class is treated as positive and on class prevalence. With very unequal classes (for example, 1,547 Shallow and 31 Deep features in the GBR), the F1-optimal threshold moves towards the larger class. Balanced accuracy weights both classes equally and is symmetric, so one threshold serves both classes and regions with different class proportions can be compared. In the Coral Sea calibration the classes were more balanced and the reference depths were accurate, so the two objectives would give similar results there. The F1 score of each class at the selected threshold is also reported.

Boundaries estimated:

| Boundary | Upper class | Lower class |
|---|---|---|
| Intertidal / Very Shallow | Intertidal | Very Shallow |
| Very Shallow / Shallow | Very Shallow | Shallow |
| Shallow / Deep | Shallow | Deep |

The Intertidal/Very Shallow boundary depends on the lower part of the Intertidal distribution and the upper part of the Very Shallow distribution. The upper tail of the Intertidal distribution is not used as a threshold.

A boundary is only estimated if both classes have at least `MIN_N = 30` features. Otherwise the table shows the counts only.

If the maximum balanced accuracy is no better than chance (0.5), for example when both classes have identical depths, no threshold is identified and the boundary is reported as n/a. Bootstrap resamples with no identified threshold are excluded from the interval.

Where the DEM is too deep for most features in the upper class, the threshold is pulled deep. In the Coral Sea the estimates are about -20 m (Very Shallow/Shallow) and -43 m (Shallow/Deep), with balanced accuracy of about 0.8. These reflect inadequate bathymetry, not the optical thresholds.

### 8.2 Uncertainty

A bootstrap gives a 95% interval for each threshold. Each of `N_BOOT = 500` resamples draws, with replacement, the same number of features as the original from each class within the region (and reef type), then re-runs the sweep. The interval is the 2.5th and 97.5th percentiles of the resampled thresholds (linear interpolation). A wide interval indicates that the classes overlap heavily or n is small. The bootstrap is only run where a point estimate exists.

The random generator is `numpy.random.default_rng(20261103)`. A single generator is shared across all estimates in this order: regions sorted alphabetically; within each region the subsets All, Coral Reef, Rocky Reef, Sediment; within each subset the boundaries in the order of Section 8.1; within each resample the upper class then the lower class. Thresholds should reproduce exactly. Interval bounds will differ slightly (typically by a few tenths of a metre) unless the same generator and draw order are used.

### 8.3 Descriptive statistics

For context, per region and DepthCat: n, median, and 25th and 75th percentiles of `DEM90pLAT` (linear interpolation). The MSL to LAT offset was dropped from the tables to keep them simple.

### 8.4 Split by feature type

Thresholds and descriptive statistics are also calculated separately for Coral Reef, Rocky Reef and Sediment where `MIN_N` allows.

## 9. Outputs

All outputs are written to `data/{version}/out/stats/`. Plots go in `data/{version}/out/stats/A06-plots/`. Markdown tables are written without the `tabulate` package (not installed in the environment).

### 9.1 Plots

All depth axes run from -60 to +10 m LAT, with major ticks every 5 m and minor ticks every 1 m. Values outside the range are clipped into the end bins, and the number clipped is shown in the legend. Histograms use 1 m bins.

1. **Per region, by feature type** (`A06_{region}_by-type.png`): four histogram rows (Intertidal, Very Shallow, Shallow, Deep) sharing the depth axis. Bars are stacked by RB_Type_L2 using Coral Reef `#e75ad6`, Rocky Reef `#b88169`, Sediment `#f8ec5c`.
2. Per-region plots of all vs filtered features were dropped. Filtering did not materially change the distributions, so they added detail without adding to the main message.
3. Each row shows the depth band the category is expected to cover:
   - the clear-water band as a hatched span (for example, the Shallow row spans -2.5 to -25 m),
   - the regional estimated band from the sweep thresholds as a light shaded span, with the threshold values as solid vertical lines and the bootstrap interval as a narrow band.
4. **Filter search** (`A06_filter-search.png`, report appendix): for each independently varied filter parameter, the percentage of features retained and the absolute sweep thresholds (m LAT), by region. Dashed lines show the clear-water Coral Sea thresholds calibrated from marine charts. Common y-axis limits within each row allow regional and filter comparisons. Feature area and DEM relief use logarithmic spacing for positive settings, with a linear step to retain zero as the baseline. Every tested setting is labelled. Relief means the within-feature 90th minus 10th percentile DEM elevation. The AusBathyTopo panel is narrow, and the figure is 8.3 by 9 inches with the space above the legend based on its rendered height, leaving room for a caption when scaled to an A4 page. The filters remain exploratory and are not applied to the main results.
5. **Overview** (`A06_thresholds-overview.png`): one compact panel showing the estimated thresholds and 95% bootstrap intervals for each region. Each adjacent-category boundary has a distinct colour, shared by its regional points, interval bars and dashed Coral Sea clear-water reference line. The reference label specifies the Coral Sea because the calibration reflects both its water conditions and its predominantly small lagoonal reefs. Small vertical offsets separate boundaries within each region. Regions with no threshold estimates are omitted. Figure height scales with the number of displayed regions. The x-axis starts at -45 m LAT; its upper limit includes the shallowest estimate, interval and reference.

All figures are sized for an A4 page width (about 8 to 8.5 inches wide, 150 dpi), with text of at least 9 pt.

### 9.2 Tables

`A06_DepthCat-DEM-comparison_{version}.md` contains captioned tables, each recording the dataset version and script name (as in A05):

1. Feature selection summary: counts removed at each selection step, and features outside regions.
2. Counts per region and DepthCat.
3. Descriptive statistics per region and DepthCat (Section 8.3).
4. **DepthCat thresholds per region**: one row per region; columns for each boundary showing threshold, 95% interval, balanced accuracy and n (upper/lower). Clear-water reference values are shown in the header row.
5. Thresholds split by RB_Type_L2.

`A06_DepthCat-DEM-comparison_{version}.csv` holds the threshold estimates in long form, one row per region, RB_Type_L2 (`All` or a type) and boundary. Columns: Region, RB_Type_L2, Boundary, Upper, Lower, Clear_water_m, N_upper, N_lower, Threshold_m, CI_low_m, CI_high_m, Balanced_accuracy, F1_upper, F1_lower. `A06_filter-search_{version}.csv` holds the filter search detail (Section 7).

## 10. Configuration constants

Defined at the top of the script:

| Constant | Default |
|---|---|
| `REGION_FIELD` | `"region"` |
| `DEPTHCAT_SOURCES` | Section 4 list |
| `REEF_TYPES` | Coral Reef, Rocky Reef, Sediment |
| `SEARCH_AREA_KM2`, `SEARCH_RELIEF_M`, `SEARCH_AUSBATHYTOPO` | Section 7 search values |
| `MIN_N` | 30 |
| `SWEEP_RANGE`, `SWEEP_STEP` | -60 to +10 m, 0.1 m |
| `N_BOOT`, `RANDOM_SEED` | 500, 20261103 |
| `BOUNDARIES` (clear-water thresholds) | 0, -2.5, -25 m LAT |
| `PLOT_RANGE` | -60 to +10 m |

## 11. Interpretation notes and limitations

- DEM values that are too deep (unresolved reefs) pull the estimated thresholds deeper. DEM values that are too shallow (nearshore contamination) pull them shallower. The sweep is affected by both, but less so than a percentile of a single class.
- Regions where balanced accuracy is low have inadequate bathymetry for this comparison. Their thresholds should not be interpreted as calibrations.
- Water clarity varies within regions. Combining Nearshore and Offshore features broadens the distributions and can blur the thresholds.
- The Shallow/Deep transition is referenced approximately to MSL, so in macrotidal regions it will appear shallower relative to LAT.
- Substrate albedo affects visibility. Sand-rich features can be visible deeper than dark coral or rock, which the type split partly addresses.
- The thresholds indicate the depth that best separates adjacent classes given the DEM. They are not a direct measurement of optical detection depth.

## 12. References

Lawrey, E., Bycroft, R., Hammerton, M. (2026). Mapping the reef and island features of the Coral Sea Marine Park. Report prepared for Parks Australia. Australian Institute of Marine Science. https://doi.org/10.26274/96ft-5236
