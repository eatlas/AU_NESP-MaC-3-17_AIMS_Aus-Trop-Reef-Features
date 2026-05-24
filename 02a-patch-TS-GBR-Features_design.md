# 02a-patch-TS-GBR-Features Design

Integrates newly mapped reef features (Reef Edit) with the existing GBR-TS
features dataset, replacing, removing and retaining features as appropriate.

## Rationale and context

### Why remapping replaced the v0-1 override approach

The v0-1 workflow used two auxiliary files: a point shapefile of classification
overrides (Bank, Rock, Move, Remove, Reshape, Merge) and a polygon shapefile of
replacement geometries. This allowed quick reclassification of existing features
but could not record uncertainty attributes (FeatConf, TypeConf, DepthCat,
Attachment) because the original GBR feature boundaries were reused without
review. From v0-9 onward every correction is a full remapping: the operator
digitises a new boundary and assigns all attributes directly. This removes the
need for a crosswalk on new features and ensures that boundary quality and
classification confidence are assessed together. The trade-off is that simple
reclassifications (e.g. tagging an existing reef as a sand bank) now require
redrawing the feature.

### Three integration scenarios

Most corrections are straightforward replacements: a newly mapped feature sits
at approximately the same location as the original and replaces it by spatial
overlap. When an original feature was mapped in the wrong position (offsets of
500 to 1000 m are not uncommon in the legacy dataset) the new feature cannot be
matched by overlap. These are handled as explicit move operations: the CODE of
the original feature is recorded in the new feature so the script can link them.
A small number of original features are false positives (visible seafloor with
no reef present). These are flagged for removal via a separate point shapefile
and deleted with no replacement.

### Processing order

Move operations are applied before overlap-based matching. This is necessary
because a moved feature can sometimes overlap a different newly mapped feature
at the old location, leading to an incorrect CODE assignment. Removals are
applied next to prevent removed features from being picked up by the overlap
test. Overlap replacements are then computed on the remaining features.

### Overlap threshold

A 10 % IoU threshold is used when deciding whether a new feature inherits the
identity (CODE, LABEL_ID) of an overlapping old feature. This is intentionally
generous: in cluttered reef areas a reshaped boundary often touches neighbouring
features, and a low threshold avoids accumulating unnecessary CODE groups.
Any non-zero overlap (even below the threshold) still triggers deletion of the
old feature, because the presence of a new feature at that location means the
old boundary is superseded.

### Reef identification

Existing GBR and Torres Strait features carry a LABEL_ID that has been in use
for decades. These identifiers are preserved for any feature that is retained or
replaced one-to-one. When a single new feature replaces multiple old features
(a merge) or when a genuinely new reef is added, no authoritative identifier
exists. The script assigns a provisional centroid-based ID (prefixed PROV-) to
make these features individually addressable for downstream analysis, while
clearly signalling that the identifier is not permanent. The LABEL_IDs of all
replaced features are recorded in a PrevReefID attribute to maintain
traceability to the historical record.

### Classification of retained features

Newly mapped features carry a full RB_Type_L3 classification assigned during
digitisation. Features retained from the original dataset have only the coarse
FEAT_NAME (Reef, Bank, Rock) or, in the Torres Strait subset, the more detailed
LEVEL_3 attribute. These are mapped to RB_Type_L3 via a crosswalk table.
Because the original dataset does not record depth information, the crosswalk
cannot distinguish depth-dependent types; DepthCat is left unset and resolved
in a later processing step (05-add-depth.py).

## Inputs

| File | Source | Description |
|---|---|---|
| `{in_3p_path}/TS-GBR-Feat/TS_AIMS_NESP_Torres_Strait_Features_V1b_with_GBR_Features.shp` | Third-party | Original GBR-TS features (CRS unset, assumed EPSG:4283) |
| `{in_path}/Reef-edit/AIMS_GBR-TS-Features_Edit_{version}.shp` | Project | Newly mapped reef polygons with full attributes (EPSG:4326) |
| `{in_path}/Reef-remove-move/AIMS_GBR-TS-Features_remove-move_{version}.shp` | Project | Points indicating features to remove or move (EPSG:4283) |
| `{in_3p_path}/NW-Aus-Feat_v0-4/in/RB_Type_L3_crosswalk.csv` | Third-party | Classification lookup for old features |

Paths resolve via `config.ini`: `in_3p_path`, `in_path`, `version`.

## Output

`working/02/TS-GBR-Features-patched.shp` (EPSG:4283)

## Constants

| Name | Value | Purpose |
|---|---|---|
| `IOU_THRESHOLD` | 0.1 | Minimum IoU for a Reef Edit feature to inherit CODEs/ReefID from an overlapping GBR feature |

## Processing steps

### 1. Load and prepare inputs

1. Read GBR features, assign CRS EPSG:4283.
2. Read Reef Edit, reproject from EPSG:4326 to EPSG:4283.
3. Read Remove-Move points.
4. Load crosswalk CSV.
5. Save a copy of island/mainland features (LEVEL_1 in {Island, Mainland}) for
   Attachment calculation.
6. Remove features with LEVEL_1 in {Island, Mainland, Other} from GBR features.

Move and Remove points are matched against the GBR dataset **before** the
Island/Mainland/Other filter is applied. Some move and removal points target
island or cay features that would otherwise be filtered out. Matching against
the unfiltered dataset ensures these points resolve correctly.

### 2. Process move operations

Move operations identify features whose position has changed so significantly
that they would not be matched by overlap.

For each Reef Edit feature where CODE is not null:
- Look up the matching GBR feature by CODE.
- Record the GBR feature's LABEL_ID and CODE for the new feature.
- Mark the GBR feature for deletion.

**Validation:** Every `ACTION='Move'` point in Remove-Move must spatially
intersect a GBR feature whose CODE appears in the Reef Edit CODE column. Every
Move-point CODE must have a corresponding Reef Edit CODE, and vice versa.
All unmatched points are collected and saved to
`working/02/debug-unmatched-move-points.shp` before the script errors, so they
can be inspected in QGIS.

Apply deletions to GBR features.

### 3. Process removals

For each `ACTION='Remove'` point in Remove-Move:
- Spatially join to GBR features (point-in-polygon).
- Mark matched GBR features for deletion.
- All unmatched points are collected and saved to
  `working/02/debug-unmatched-remove-points.shp` before the script errors.

Apply deletions to GBR features.

### 4. Process overlap replacements

For each remaining Reef Edit feature (CODE is null):
1. Find all remaining GBR features with any geometric intersection.
2. Compute IoU for each pair. Record CODEs and LABEL_IDs of GBR features with
   IoU >= `IOU_THRESHOLD`.
3. Mark **all** intersecting GBR features for deletion (regardless of IoU).

Apply deletions to GBR features.

### 5. Assign ReefID and CODES for new features

For each Reef Edit feature, assign attributes based on how it was matched:

**Move features** (CODE was set):
- `CODES` = the CODE value.
- `ReefID` = LABEL_ID of the matched GBR feature.

**Overlap features** (CODE was null, matched by overlap):
- `CODES` = semicolon-separated CODEs of all GBR features with IoU >= threshold.
- `ReefID` assignment depends on how many LABEL_IDs are involved:
  - Exactly one LABEL_ID, claimed by exactly one new feature: `ReefID` = that
    LABEL_ID.
  - Multiple LABEL_IDs, or the same LABEL_ID claimed by multiple new features:
    `ReefID` = provisional centroid-based ID (see below).
    `PrevReefID` = semicolon-separated LABEL_IDs.

**Genuinely new features** (no CODE, no overlaps):
- `CODES` = null.
- `ReefID` = provisional centroid-based ID.

**Provisional ID format:** `PROV-{lat}-{lon}` where lat and lon are the
absolute centroid coordinates multiplied by 100 and rounded to integers
(e.g., PROV-1479-14514 for centroid at -14.79, 145.14). Append a letter
suffix (a, b, c, ...) if collisions occur.

### 6. Prepare retained old features

For GBR features that survived steps 2-4:

1. **Crosswalk:** Map LEVEL_3 (preferred) or FEAT_NAME (fallback) to
   `RB_Type_L3` using the crosswalk CSV. Error if any feature cannot be mapped.
2. **Attachment:** Project to EPSG:3577. Buffer island/mainland geometries by
   200 m. Features intersecting the buffer are Fringing, otherwise Isolated.
   Override to Land for RB_Type_L3 = Unvegetated Cay.
3. **EdgeAcc_m:** Assign based on area (projected to EPSG:3577):
   - \>30 km^2: 800
   - \>10 km^2: 600
   - \>1 km^2: 300
   - \>0.1 km^2: 200
   - else: 150
4. **Other defaults:** `FeatConf` = None, `TypeConf` = CLASS_CONF (if
   available, else None), `DepthCat` = None, `DepthCatSr` = None.
5. **OrigType** = LEVEL_3 (if not empty) or FEAT_NAME.
6. **Rename:** IMG_SRC → EdgeSrc, LABEL_ID → ReefID.
7. **Dataset:** Retain original DATASET value.
8. **CODES** = CODE (single value, copied from original).
9. **PrevReefID** = null.

### 7. Prepare new features (Reef Edit)

1. **OrigType** = RB_Type_L3.
2. **Dataset** = `Aus-Trop-Reef-Features_{version}`.
3. **EdgeAcc_m:** If null, assign using the same area-based table as old
   features.
4. **DepthCat:** Leave as-is (null values handled by 05-add-depth.py).
5. **Attachment:** Leave as-is (mapper-assigned, no overrides).
6. Drop `Note`, `FEAT_NAME` columns.

### 8. Merge and output

1. Align column schemas (superset of all columns, missing filled with None).
2. Concatenate old and new features.
3. Set CRS to EPSG:4283.
4. Save to `working/02/TS-GBR-Features-patched.shp`.

## Output attribute schema

| Attribute | Type | Source (old) | Source (new) |
|---|---|---|---|
| `RB_Type_L3` | str | Crosswalk | Reef Edit |
| `Attachment` | str | Computed (buffer) | Reef Edit |
| `DepthCat` | str | None (set later) | Reef Edit or None |
| `DepthCatSr` | str | None | Reef Edit |
| `FeatConf` | str | None | Reef Edit |
| `TypeConf` | str | CLASS_CONF | Reef Edit |
| `EdgeSrc` | str | IMG_SRC | Reef Edit |
| `EdgeAcc_m` | int | Area-based | Reef Edit or area-based |
| `OrigType` | str | LEVEL_3 / FEAT_NAME | RB_Type_L3 |
| `Dataset` | str | Original DATASET | `Aus-Trop-Reef-Features_{version}` |
| `ReefID` | str | LABEL_ID | LABEL_ID (1:1) or PROV-{centroid} |
| `CODES` | str | CODE | Semicolon-separated CODEs or null |
| `PrevReefID` | str | None | Semicolon-separated LABEL_IDs or null |

## Validation checks

1. Every Move point matches exactly one GBR feature (matched against the
   unfiltered dataset, before Island/Mainland/Other removal), and that CODE
   exists in Reef Edit. Every Reef Edit CODE appears as a Move-point match.
2. Every Remove point matches at least one GBR feature (also matched against
   the unfiltered dataset).
3. Every old feature maps to a valid RB_Type_L3 via crosswalk.
4. No null geometries in any input.
5. Script errors on any validation failure (data should be fixed upstream).
6. On failure, unmatched Move and Remove points are saved to debug shapefiles
   in `working/02/` for inspection in QGIS.
