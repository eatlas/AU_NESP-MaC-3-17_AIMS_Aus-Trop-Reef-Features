# National L2 reef polygons

## Purpose and provenance

[08-make-RB_Type_L2.py](08-make-RB_Type_L2.py) creates a reusable national L2 dataset from the full-classification output of [06-crosswalk.py](06-crosswalk.py). It is adapted from NW-Aus-Features `13-make-RB_Type_L2.py`. The shared dissolution and countable-reef functions in [reef_utils.py](reef_utils.py) are copied from the same project.

L3 records describe reef parts. This step joins touching parts within each `RB_Type_L2` class and exports singlepart polygons. It does not merge reefs separated by water or apply a minimum size. [A05-reef-distribution.py](A05-reef-distribution.py) subsequently groups nearby polygons and removes small clusters to create countable reefs. Named reefs, L2 polygons and countable reefs are different units.

## Inputs and validation

The version is read from `[general] version` in [config.ini](config.ini). The input is `data/{version}/out/full-classes/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp`. All L2 classes are processed across the national dataset, without a sovereignty filter.

Required fields are `RB_Type_L2`, `RB_Type_L3`, `Attachment`, `DepthCat`, `DepthCatSr`, `FeatConf`, `TypeConf`, `EdgeSrc`, `EdgeAcc_m`, `ReefID`, `ReefFID` and geometry. L2 and L3 classifications must be non-empty. Attachment must be Land, Fringing, Oceanic or Isolated. Depth category must be Land, Surface, Intertidal, Very Shallow, Shallow or Deep. Edge accuracy must be a non-negative 32-bit integer. Missing fields, invalid enumerations outside confidence fields, undefined CRS and missing or empty geometries cause explicit errors.

Blank confidence values are allowed. They occur in the GBR source mapping. The supported confidence scale is Very Low, Low, Medium and High. Other non-empty values, including `Very high`, `LowHigh` and `HighLow`, are flagged for source cleanup rather than normalised or ranked. The script prints a warning and writes the source row, identifiers, field and value to `working/{version}/08/confidence-issues.csv`. This file is replaced on each run, including a header-only file when no issues exist.

Coral Sea `Very high` values in both confidence fields are standardised to `High` upstream by [02c-patch-CS-Features.py](02c-patch-CS-Features.py). Stage 08 retains its validation so stale national outputs or unexpected values from other sources remain visible. Regenerate stage 02c and downstream national outputs before rebuilding L2 polygons to apply this standardisation.

For retained Torres Strait and GBR features, [02a-patch-TS-GBR-Features.py](02a-patch-TS-GBR-Features.py) maps source `CLASS_CONF` = `LowHigh` to `TypeConf` = `Low`. Other source confidence values and blanks remain unchanged. Rerun stage 02a and downstream national stages before rebuilding L2 polygons to propagate this correction.

## Geometry processing

Input geometry is reprojected to EPSG:4283 and cleaned using `buffer(0)`. Empty or invalid results cause an error rather than being dropped. Multipart source features are exploded before dissolution so that each disjoint part can be assigned to its own L2 component. The original source row is retained.

Features are dissolved independently by L2 class. The NW seam-repair method applies a positive and negative buffer of `1e-6` degrees, approximately 0.1 m in the study area, followed by simplification at the same tolerance. Repairs that empty the geometry or change its area by more than one part per million are rejected in favour of the original geometry. A class-wide area tolerance alone can miss the complete loss of a small source part. After both repair and simplification, each cleaned source part is checked for intersection with the resulting components. Any wholly lost source part is restored from its cleaned geometry, without further simplification. The script prints a warning with the source-part indices and unions restored parts with the prepared geometry so overlapping restored parts do not introduce invalid geometry.

Dissolved geometries are split into singlepart polygons. Source parts are assigned using representative points, with an intersection fallback for precision cases. Any source part still unassigned causes an error. There is no minimum-size filter in this step. Tiny detached parts retain their geometry and source membership even if their area rounds to zero at four decimal places. A05 applies the countable-reef size rules later.

Output geometry remains in EPSG:4283. Area is recalculated from geometry in GDA94 / Australian Albers, EPSG:3577, and rounded to four decimal places in `Area_km2`.

## Attribute aggregation

Each component receives a temporary integer `L2FID`, starting at one. This is local to the generated dataset and may change after inputs change. It is not a persistent reef identifier.

`RB_L3_Agg`, `DepthCatSr` and `EdgeSrc` contain sorted unique non-empty source values separated by semicolons. Attachment uses Land, Fringing, Oceanic, then Isolated priority. Depth category uses Land, Surface, Intertidal, Very Shallow, Shallow, then Deep priority. `EdgeAcc_m` takes the largest source value.

Each confidence field takes the lowest source value on the supported scale only when every constituent has a supported value. If any constituent is blank or non-standard, the aggregated field is blank. This avoids assigning a known confidence to a whole polygon when part of it has unknown confidence. Original confidence values remain in the membership CSV.

National ReefIDs do not follow a single NW suffix convention. Source identifiers are not stripped, rewritten or required to match within a dissolved component. The membership CSV links every `L2FID` to `SourceRow`, `ReefID`, `ReefFID`, `FeatConf` and `TypeConf`. `SourceRow` is the 1-based input record, not a persistent identifier. A multipart source record can belong to several L2 polygons. Duplicate memberships from parts of the same source record within one L2 polygon are removed.

The L2 product does not aggregate national sovereignty percentages, depth percentiles or external classification crosswalks. These remain available in the source dataset through the membership links. Aggregated shapefile text fields exceeding 254 UTF-8 bytes cause an explicit error rather than truncation.

## Outputs and execution

The primary output is `data/{version}/out/simp-classes/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_L2_{version}.shp`. Its fields are `L2FID`, `RB_Type_L2`, `RB_L3_Agg`, `Attachment`, `DepthCat`, `DepthCatSr`, `FeatConf`, `TypeConf`, `EdgeSrc`, `EdgeAcc_m`, `Area_km2` and geometry. The accompanying membership file has the same stem followed by `_members.csv`.

Polygons containing several source Attachment values are saved to `working/{version}/08/multi-attachment-values.shp`. This layer adds `AttSet`, the sorted unique source attachments. An empty layer replaces any previous QA output when no mixed attachments remain.

Run `python 08-make-RB_Type_L2.py` after stage 06, then `python A05-reef-distribution.py`. Stage 08 rebuilds its outputs on every run. A05 caches are separate and must be invalidated manually after regenerating L2 geometry. Delete the affected cached shapefiles and their sidecars in `working/{version}/A05/`.

Focused synthetic tests cover attribute priorities, source membership, multipart input, confidence QA, invalid input, file exports, clustering thresholds and regional allocation. Run `python -m unittest discover -s tests -p "test_*.py"` in the AusTropReef environment. These tests do not download data or run the full national analysis.
