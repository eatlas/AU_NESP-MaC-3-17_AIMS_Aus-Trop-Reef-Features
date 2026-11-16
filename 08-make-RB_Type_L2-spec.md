# National L2 reef polygons

## Purpose and provenance

[08-make-RB_Type_L2.py](08-make-RB_Type_L2.py) creates a reusable national L2 dataset from the full-classification output of [06-crosswalk.py](06-crosswalk.py). It is adapted from NW-Aus-Features `13-make-RB_Type_L2.py`. The shared dissolution and countable-reef functions in [reef_utils.py](reef_utils.py) are copied from the same project.

L3 records describe reef parts. This step joins touching parts within each `RB_Type_L2` class and exports singlepart polygons. It does not merge reefs separated by water or apply a minimum size. [A05-reef-distribution.py](A05-reef-distribution.py) subsequently groups nearby polygons and removes small clusters to create countable reefs. Named reefs, L2 polygons and countable reefs are different units.

## Inputs and validation

The version is read from `[general] version` in [config.ini](config.ini). The input is `data/{version}/out/full-classes/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp`. All L2 classes are processed across the national dataset, without a sovereignty filter.

Required fields are `RB_Type_L2`, `RB_Type_L3`, `Attachment`, `DepthCat`, `DepthCatSr`, `FeatConf`, `TypeConf`, `EdgeSrc`, `EdgeAcc_m`, `ReefID`, `ReefFID`, `PrevReefID`, `Dataset`, `Sovereign1` and geometry. L2 and L3 classifications must be non-empty. Attachment must be Land, Fringing, Oceanic or Isolated. Depth category must be Land, Surface, Intertidal, Very Shallow, Shallow or Deep. Edge accuracy must be a non-negative 32-bit integer. Missing fields, invalid enumerations outside confidence fields, undefined CRS and missing or empty geometries cause explicit errors.

Blank confidence values are allowed. They occur in the GBR source mapping. The supported confidence scale is Very Low, Low, Medium and High. Other non-empty values, including `Very high`, `LowHigh` and `HighLow`, are flagged for source cleanup rather than normalised or ranked. The script prints a warning and writes the source row, identifiers, field and value to `working/{version}/08/confidence-issues.csv`. This file is replaced on each run, including a header-only file when no issues exist.

Coral Sea `Very high` values in both confidence fields are standardised to `High` upstream by [02c-patch-CS-Features.py](02c-patch-CS-Features.py). Stage 08 retains its validation so stale national outputs or unexpected values from other sources remain visible. Regenerate stage 02c and downstream national outputs before rebuilding L2 polygons to apply this standardisation.

For retained Torres Strait and GBR features, [02a-patch-TS-GBR-Features.py](02a-patch-TS-GBR-Features.py) maps source `CLASS_CONF` = `LowHigh` to `TypeConf` = `Low`. Other source confidence values and blanks remain unchanged. Rerun stage 02a and downstream national stages before rebuilding L2 polygons to propagate this correction.

## Geometry processing

Input geometry is reprojected to EPSG:4283 and cleaned using `buffer(0)`. Empty or invalid results cause an error rather than being dropped. Multipart source features are exploded before dissolution so that each disjoint part can be assigned to its own L2 component. The original source row is retained.

Features are dissolved independently by L2 class. The NW seam-repair method applies a positive and negative buffer of `1e-6` degrees, approximately 0.1 m in the study area, followed by simplification at the same tolerance. Repairs that empty the geometry or change its area by more than one part per million are rejected in favour of the original geometry. A class-wide area tolerance alone can miss the complete loss of a small source part. After both repair and simplification, each cleaned source part is checked for intersection with the resulting components. Any wholly lost source part is restored from its cleaned geometry, without further simplification. The script prints a warning with the source-part indices and unions restored parts with the prepared geometry so overlapping restored parts do not introduce invalid geometry.

For multipart geometry, the outward buffer is calculated in bounded groups of at most 1000 polygons. The expanded polygons are unioned before applying the inward buffer in bounded groups. This retains seam closing between nearby parts, including across group boundaries, while avoiding the expensive whole-dataset multipart buffer operations. Buffer resolution, tolerance and the class-wide area guard remain unchanged. Processing is serial and requires no additional dependencies.

Simplification also uses groups of at most 1000 polygons for large multipart geometries, with topology preservation enabled. The combined result is checked for validity because simplification must not introduce overlaps across group boundaries. If it is invalid, the script prints a warning and retains the unsimplified, seam-repaired geometry. Smaller geometries retain the original whole-geometry simplification.

Console messages identify union, seam repair, simplification, source coverage checking, membership assignment and attribute aggregation. Buffering, grouped simplification, component construction and attribute aggregation report counts every 1000 items and at completion. Geometry-stage milestones include elapsed time for the current L2 class. Individual GEOS calls do not expose percentage progress; their start and completion are reported instead.

Dissolved geometries are split into singlepart polygons. Source parts are assigned using representative points, with an intersection fallback for precision cases. Any source part still unassigned causes an error. There is no minimum-size filter in this step. Tiny detached parts retain their geometry and source membership even if their area rounds to zero at four decimal places. A05 applies the countable-reef size rules later.

Output geometry remains in EPSG:4283. Area is recalculated from geometry in GDA94 / Australian Albers, EPSG:3577, and rounded to four decimal places in `Area_km2`.

## Attribute aggregation

Each component receives a temporary integer `L2FID`, starting at one. This is local to the generated dataset and may change after inputs change. It is not a persistent reef identifier.

`ReefFID`, `ReefID`, `PrevReefID`, `Dataset`, `Sovereign1`, `RB_L3_Agg`, `DepthCatSr` and `EdgeSrc` contain sorted unique non-empty source values separated by semicolons. Existing semicolon-separated lists are split, whitespace is trimmed and duplicate entries are removed. A list with no non-empty values is blank. Attachment uses Land, Fringing, Oceanic, then Isolated priority. Depth category uses Land, Surface, Intertidal, Very Shallow, Shallow, then Deep priority. `EdgeAcc_m` takes the largest source value.

Each confidence field takes the lowest source value on the supported scale only when every constituent has a supported value. If any constituent is blank or non-standard, the aggregated field is blank. This avoids assigning a known confidence to a whole polygon when part of it has unknown confidence. Original confidence values remain in the full-classification source dataset.

National ReefIDs do not all follow the NW suffix convention. Source identifiers are not renamed or required to share a base within a dissolved component. They are retained losslessly in the three identifier attributes rather than a separate membership CSV, using the compact notation below where applicable. Each attribute is an independent set, not a positionally aligned list of source records. Use the full-classification dataset for source-record relationships and original attributes. A multipart source record can contribute its attributes to several L2 polygons. Parts of the same source record within one L2 polygon are deduplicated before aggregation.

`Sovereign1` records the set of primary sovereign attribute values from the source records. No spatial sovereignty calculation, area weighting or ranking is performed. The L2 product does not aggregate sovereignty percentages, secondary sovereigns or external classification crosswalks; these remain available in the full-classification source dataset. Aggregated shapefile text fields exceeding 254 UTF-8 bytes, including separators, cause an explicit error rather than truncation.

Text lengths are checked immediately after attribute aggregation, before raster preparation or DEM sampling. Errors identify every overflowing field, the number of affected polygons and the first ten affected `L2FID` values, L2 classes, byte lengths and unique-value counts per field. Text is checked again after depth calculation to validate the recalculated `DEMSr` values.

### Compact identifier notation

`ReefFID`, `ReefID` and `PrevReefID` use lossless shorthand for recognised NW identifiers: `R-`, four grid digits, a hyphen, at least three sequence digits and a lowercase alphabetic suffix. Identifiers are grouped by their actual base, without assuming that an L2 polygon has only one base. Each grouped base is followed by braces containing comma-separated suffixes or inclusive ranges. For example, `R-8137-034{a-c,f}` expands to `R-8137-034a`, `R-8137-034b`, `R-8137-034c` and `R-8137-034f`. Missing suffixes are never filled in.

Ranges vary only the final letter, with the preceding letters fixed. Thus `aa-az` is valid, but `az-ba` is not. Suffixes are ordered by length, then alphabetically. Groups and literal identifiers are sorted and separated by semicolons. Grouping is used only when it shortens the value. Unsuffixed identifiers and unrecognised formats, including national `-Fnn` feature suffixes, remain literal. Braces are reserved for this output notation; a source identifier containing a brace causes an explicit error. `Dataset` and `Sovereign1` remain ordinary semicolon-separated values.

Examples from the national dataset are `R-8137-034{a-z,aa-at}` for the 46 Ningaloo parts, `R-8342-000{a-z,aa-aq}` for the 43 Scott Reef parts and `R-8238-367{a-z,aa-az,ba-bz,ca-cn}` for the 92 rocky parts of the Montebello reef complex. A component with several families can instead contain `GBR-123;R-8137-034{a-c,f};R-8137-035{b,d}`. The braces denote an exact set, not a wildcard or a newly allocated identifier.

`expand_identifier_list` in stage 08 expands this notation into sorted unique source identifiers and rejects malformed groups or ranges. Tests check exact set recovery, preservation of gaps and unrelated identifier formats, deterministic ordering and shapefile export. Overflow diagnostics count expanded identifiers, not compressed groups. The 254 UTF-8 byte limit still applies after compression.

## DEM depth statistics

After dissolution, stage 08 recalculates `DEM10pMSL`, `DEM50pMSL`, `DEM90pMSL`, `DEM10pLAT`, `DEM50pLAT`, `DEM90pLAT` and `DEMSr` over each output L2 polygon. Source L3 percentile values are not aggregated or reused. A percentile over a dissolved polygon is not the same as an aggregation of its constituent percentiles.

The raster preparation, LPT lookup, polygon sampling, DEM fallback and percentile calculations are shared with [05-add-depth.py](05-add-depth.py) through [reef_utils.py](reef_utils.py). Raster inputs are read from `[general] in_3p_path` in [config.ini](config.ini), resolved relative to the project root. MultiResBathyEEZ 2024 is tried first, followed by AusBathyTopo 250 m 2024 if no valid MSL values are found. Stage 08 reuses `working/{version}/05/MultiRes-Bathy-EEZ_2024.vrt`, creating it from `01_shallow_bathy.tif` and `02_mesophotic_bathy.tif` when absent.

Depth processing remains serial. Available DEMs are opened once for the polygon pass and closed on completion or error. Coordinate transformers are reused through a bounded in-memory cache rather than recreated for each polygon. These optimisations apply to both stages 05 and 08 without changing sampling, percentiles or category handling. No multiprocessing or additional execution settings are required.

The EOT20 LPT raster is `EOT20-tides/AU_AIMS_EOT20-tide-stats_LPT_2021-01-2025-12.tif` under the third-party input directory. For each valid DEM pixel whose centre falls inside the polygon, LAT elevation is calculated as MSL elevation minus the LPT value at that location. The 10th, 50th and 90th percentiles are calculated separately for MSL and LAT and rounded to one decimal place in metres. Positive values are above the datum; negative values are below it. The 90th percentile describes the shallower part of the feature.

Geometry and lookup coordinates are reprojected for sampling as needed; the output geometry remains in EPSG:4283. Polygons with no valid DEM pixel centres use centroid sampling, including sub-pixel polygons. Missing LPT values do not discard valid MSL statistics. LAT statistics are null where no valid LPT samples exist. When neither DEM provides data, all seven DEM attributes are null and a warning identifies the feature. Unexpected raster processing errors stop execution rather than producing apparently successful null statistics.

`DEMSr` records the DEM selected for the L2 polygon, followed by `;EOT20` when valid LAT statistics are available (for example `MultiResBathyEEZ_2024;EOT20`). It is not an aggregation of source values. With no valid LPT samples, only the DEM name is recorded. `DepthCat` and `DepthCatSr` retain the aggregation described above. These categories provide an independent assessment, typically from satellite imagery, and are not overwritten or reclassified from the recalculated DEM values. Stage 05's L3 category overrides are not applied to L2 polygons.

## Outputs and execution

The primary output is `data/{version}/out/simp-classes/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_L2_{version}.shp`. Its fields are `L2FID`, `ReefFID`, `ReefID`, `PrevReefID`, `Dataset`, `Sovereign1`, `RB_Type_L2`, `RB_L3_Agg`, `Attachment`, `DepthCat`, `DepthCatSr`, `DEM10pMSL`, `DEM50pMSL`, `DEM90pMSL`, `DEM10pLAT`, `DEM50pLAT`, `DEM90pLAT`, `DEMSr`, `FeatConf`, `TypeConf`, `EdgeSrc`, `EdgeAcc_m`, `Area_km2` and geometry. No membership CSV is generated. Any `_members.csv` from an earlier run is obsolete and can be removed manually.

Polygons containing several source Attachment values are saved to `working/{version}/08/multi-attachment-values.shp`. This layer includes the recalculated DEM attributes and adds `AttSet`, the sorted unique source attachments. An empty layer replaces any previous QA output when no mixed attachments remain.

Run `python 08-make-RB_Type_L2.py` after stage 06 with the same DEM and LPT inputs required by stage 05 available, then run `python A01-summary-stats.py` and `python A05-reef-distribution.py` as needed. A01 reuses these L2 polygons without modifying or dissolving geometry, recalculating unrounded areas in EPSG:3577 for its tables. Stage 08 rebuilds its outputs, including DEM statistics, on every run. A05 caches are separate and must be invalidated manually after regenerating L2 geometry. Delete the affected cached shapefiles and their sidecars in `working/{version}/A05/`.

Focused synthetic tests cover attribute priorities, source membership, multipart input, confidence QA, invalid input, file exports, clustering thresholds and regional allocation. Depth tests also cover DEM and LAT percentiles, raster fallback, centroid sampling, missing data, CRS conversion and preservation of independent categories. Run `python -m unittest discover -s tests -p "test_*.py"` in the AusTropReef environment. These tests do not download data or run the full national analysis.
