# 02a-patch-TS-GBR-Features Design

Integrates newly mapped reef features (Reef Edit) with a refreshed GBR and
Torres Strait source layer, replacing, removing and retaining features as
appropriate.

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

### Refreshing the GBR source

The 2016 integrated Torres Strait and GBR Features dataset contains the
authoritative remapped Torres Strait features, but its GBR component is based on
an older GBRMPA release. Before this script runs,
`01d-refresh-TS-GBR-Features.py` retains the records marked
`DATASET='TS Features'` and replaces all records marked
`DATASET='GBR Features'` with the latest GBRMPA GBR Features.

The latest GBRMPA records with a `LABEL_ID` beginning with `99-` are excluded
because they overlap the remapped Torres Strait coverage. Both records with
`LABEL_ID='99-000'` are retained because they represent the mainland and closely
associated islands. The refresh stage reconstructs the `LEVEL_1`, `LEVEL_2` and
`LEVEL_3` fields from `FEAT_NAME`, transforms the source from GDA2020 to GDA94,
repairs invalid source geometries, and validates the written intermediate. The
result is `working/01/TS-GBR-Features-latest.shp`.

### Overlap assessment

Every pair of old and new polygons that intersect is scored once, in EPSG:3577.
For an intersection of area `A_int` between an old polygon of area `A_old` and a
new polygon of area `A_new`, two shares are recorded: `share_old = A_int/A_old`
and `share_new = A_int/A_new`. Two shares are used rather than a single symmetric
measure such as IoU, because IoU falls away whenever the polygons differ greatly
in size and therefore misses splits and merges.

An intersection is discarded as a digitising sliver if it disappears when eroded
by `SLIVER_TOLERANCE_M`. This measures how deeply the polygons interpenetrate
rather than how much area they share, which is what distinguishes a long thin
contact from a genuine overlap. A multipart intersection survives if any part
survives erosion, and the shares are then computed from the whole intersection.

A surviving pair becomes a candidate lineage relationship if either share reaches
`CANDIDATE_SHARE`. A `CODE` on a new feature forces a candidate relationship
regardless of geometry, because a moved feature need not overlap its original
boundary at all. An `ACTION='Link'` point forces a candidate relationship that can
only ever produce a previous identifier.

Any non-zero overlap, including a rejected sliver, still triggers deletion of the
old feature, because the presence of a new feature at that location means the old
boundary is superseded. Deletion and lineage are decided independently, so an old
feature can be deleted without its identifier being carried forward. Those cases
are reported as orphaned identifiers.

### Reef identification

The output separates polygon identity from official reef identity:

- `ReefFID` identifies an individual polygon feature in this dataset. Every
   feature must have a value. It uses the official identifier where this script
   can retain one unambiguously, otherwise it uses a provisional centroid-based
   value prefixed with `PROV-`.
- `ReefID` contains an official persistent reef identifier. For GBR features,
   GBRMPA is the minting authority. It is null for genuinely new, split, merged,
   or otherwise ambiguous GBR features that require an authority decision.
- `PrevReefID` records the official identifiers of previous features that were
   candidates for this location but whose identity was not carried forward here.

Candidates are grouped by official identifier and the identifier passes to the
single new feature that overlaps it most, provided that overlap is at least
`DOMINANCE_RATIO` times the next best candidate. A relationship with only one
candidate has no runner up and always inherits, which reproduces the intended
treatment of one-to-one replacements without a separate rule. Where there is no
clear winner the identifier is not carried forward and is instead recorded as a
previous identifier on every candidate, leaving the determination to GBRMPA.

Grouping is by identifier rather than by polygon because `LABEL_ID` is not unique
in the source. A reef and its associated rock or island are separate polygons
with one identifier, and grouping by polygon would let the same official
identifier pass to two new features.

A new feature that wins exactly one identifier takes it as both `ReefID` and
`ReefFID` and records its remaining candidates in `PrevReefID`. A feature that
wins two or more has merged several old reefs. It keeps the identifier of the
constituent it overlaps most, provided that overlap is at least `DOMINANCE_RATIO`
times the next, and records the rest in `PrevReefID`. Where no constituent
dominates it takes none of them. A feature that wins none records its candidates
in `PrevReefID`, or null where it has no candidates at all and is therefore
genuinely new. An identifier held as `ReefID` is never repeated in `PrevReefID`
on the same feature.

`02a` does not make `ReefFID` unique across the complete national dataset.
Stage 03 performs that allocation after the regional datasets are merged. Where
several polygons share an official `ReefID`, stage 03 assigns feature suffixes
such as `15-010-F01` and `15-010-F02`. These suffixes are dataset identifiers,
not official GBRMPA subfeature identifiers.

For v1.0 there is no earlier `ReefFID` history. Stage 03 therefore establishes
the baseline deterministically from source identifiers, feature type, location,
area and geometry. It does not use v0.9 as an identifier reference because v0.9
does not contain `ReefFID`. On later updates, the allocation utility preserves
published `ReefFID` values when regional inputs supply them and allocates only
missing or conflicting values. Automatic spatial matching to a previous
national release is not currently implemented.

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
| `working/01/TS-GBR-Features-latest.shp` | Derived | Torres Strait features combined with the latest filtered GBRMPA GBR Features by `01d-refresh-TS-GBR-Features.py` (EPSG:4283) |
| `{in_path}/Reef-edit/AIMS_GBR-TS-Features_Edit_{version}.shp` | Project | Newly mapped reef polygons with full attributes (EPSG:4326) |
| `{in_path}/Reef-remove-move/AIMS_GBR-TS-Features_remove-move_{version}.shp` | Project | Points indicating features to remove or move (EPSG:4283) |
| `{in_3p_path}/NW-Aus-Feat_{nw_aus_feat_version}/in/RB_Type_L3_crosswalk.csv` | Third-party | Classification lookup for old features |
| `data/{version}/extras/inshore-extent/inshore-extent.shp` | Project | Area of comprehensive inshore remapping, used for the gap report |

Paths resolve via `config.ini`: `in_3p_path`, `in_path`, `version`.

## Output

`working/02/TS-GBR-Features-patched.shp` (EPSG:4283)

`working/02/debug-reefid-review.gpkg` (EPSG:4283) holds the identifier review
layers described under processing step 6. A GeoPackage is used because it holds
several layers in one file and does not truncate field names to ten characters.
Empty layers are not written.

## Constants

| Name | Value | Purpose |
|---|---|---|
| `SLIVER_TOLERANCE_M` | 10 | Erosion distance below which an intersection is treated as a digitising artefact |
| `CANDIDATE_SHARE` | 0.1 | Minimum share of either polygon's area for a candidate relationship |
| `DOMINANCE_RATIO` | 3.0 | Factor by which the best candidate must exceed the next best to inherit the identifier |
| `SIZE_CHANGE_REPORT` | 5.0 | Area ratio above which an inherited relationship is reported for review |
| `VALID_ACTIONS` | Move, Remove, Link | Recognised `ACTION` values in the Remove-Move point file |

The first three affect the output. `SIZE_CHANGE_REPORT` affects only the review
layers. None of these values has been validated against manual assessment. The
sub-threshold overlap layer exists so that `CANDIDATE_SHARE` can be reviewed
against real cases before publication.

## Processing steps

### 1. Load and prepare inputs

1. Read GBR features, assign CRS EPSG:4283.
2. Read Reef Edit, reproject from EPSG:4326 to EPSG:4283.
3. Read Remove-Move points.
4. Load crosswalk CSV.
5. Error on null geometries in any input. Error on invalid Reef Edit polygons
   and save them to `working/02/debug-invalid-reef-edit.shp` with the validity
   reason in `geom_issue`.
6. Save a copy of island/mainland features (LEVEL_1 in {Island, Mainland}) for
   Attachment calculation.
7. Normalise empty CODE values to null.

Move and Remove points are matched against the GBR dataset **before** the
Island/Mainland/Other filter is applied. Some move and removal points target
island or cay features that would otherwise be filtered out. Matching against
the unfiltered dataset ensures these points resolve correctly.

### 2. Process move operations

Move operations identify features whose position has changed so significantly
that they would not be matched by overlap.

`ACTION` values are validated against `VALID_ACTIONS` and the script exits on any
unrecognised value.

For each Reef Edit feature where CODE is not null, look up the matching GBR
features by CODE and mark them for deletion. The CODE does not by itself decide
which feature inherits the identifier; it contributes a forced candidate to
step 5.

**Validation:** Every `ACTION='Move'` point in Remove-Move must spatially
intersect a GBR feature whose CODE appears in the Reef Edit CODE column. A Reef
Edit CODE without a Move point is allowed because CODE is also used to
disambiguate replacements. Move points outside all source features are saved to
`working/02/debug-unmatched-move-points.shp`. Move points whose source CODE is
absent from Reef Edit are saved to
`working/02/debug-unmatched-move-codes.shp`. The script then exits so the inputs
can be corrected in QGIS.

### 3. Process removals

For each `ACTION='Remove'` point in Remove-Move:
- Spatially join to GBR features (point-in-polygon).
- Mark matched GBR features for deletion.
- All unmatched points are collected and saved to
  `working/02/debug-unmatched-remove-points.shp` before the script errors.

### 4. Score old and new polygon pairs

Scoring runs before any deletion is applied, on an old layer that excludes
Island, Mainland and Other features and Remove-point targets, but retains Move
targets so that their identifiers remain available.

1. Reproject both layers to EPSG:3577.
2. For each Reef Edit feature, find intersecting old features and record the
   intersection geometry, its area, `share_old`, `share_new`, and whether the
   intersection survives erosion by `SLIVER_TOLERANCE_M`.
3. Mark **every** intersecting old feature for deletion, including slivers.
4. A surviving pair becomes a candidate where either share reaches
   `CANDIDATE_SHARE`.
5. Each `CODE` on a Reef Edit feature forces a candidate against every old
   feature carrying that CODE, whether or not they intersect.
6. Each `ACTION='Link'` point forces a candidate for the old and new polygons it
   falls inside. Link points are validated on every run. A point that does not
   fall inside both an old and a new polygon, or whose polygons no longer
   intersect, is reported as obsolete. A point on a pair that already qualifies
   on its own, or that is already established by CODE, is reported as
   unnecessary. Reported points are not applied and do not stop the run.

### 5. Assign ReefFID, ReefID, PrevReefID and CODES

Candidates are grouped by the old feature's `LABEL_ID`. Within each group the
intersection areas of candidates sharing a new feature are summed, and the
candidates are ranked by area. The top-ranked candidate inherits the official
identifier where its area is at least `DOMINANCE_RATIO` times the next best, or
where it is the only candidate. It does not inherit where it was forced by a Link
point, or where the group has several candidates and none of them overlap.

For each Reef Edit feature:
- `CODES` = semicolon-separated CODEs of its candidate old features, or null.
- Won exactly one identifier, or won several with one dominant: `ReefID` and
  `ReefFID` = that identifier; `PrevReefID` = its remaining candidate
  identifiers, or null.
- Won several with none dominant, or won none: `ReefID` = null, `ReefFID` =
  provisional centroid-based ID, `PrevReefID` = all candidate identifiers, or
  null where there are none.

**Provisional ID format:** `PROV-{lat}-{lon}` where lat and lon are the
absolute centroid coordinates multiplied by 100 and rounded to integers
(e.g., PROV-1479-14514 for centroid at -14.79, 145.14). Append a letter
suffix (a, b, c, ...) if collisions occur.

### 6. Review outputs

Written to `working/02/debug-reefid-review.gpkg`. None of these layers stops the
run.

- `orphaned-identifiers`: deleted old features whose identifier appears in no
  `ReefID` and no `PrevReefID`, with the deletion reason.
- `sub-threshold-overlaps`: intersections that survived the sliver test but
  failed `CANDIDATE_SHARE`, with both areas, both shares, and a `sole_pair` flag
  marking old features with no other candidate.
- `extreme-size-changes`: inherited relationships where the areas differ by more
  than `SIZE_CHANGE_REPORT`.
- `override-problems`: obsolete and unnecessary override points with the reason.
- `inshore-gaps`: old features that survive inside
  `data/{version}/extras/inshore-extent/inshore-extent.shp`. The inshore area is
  comprehensively remapped, so every old feature there should have been removed,
  moved or replaced. Anything left is a gap in the new mapping.
- `shared-reefid`: output features that share an official identifier, which
  arises because `LABEL_ID` is not unique in the source. Stage 03 resolves these
  with `-Fnn` suffixes.

### 7. Apply deletions and filter

Drop the move, remove and overlap targets together with Island, Mainland and
Other features.

### 8. Prepare retained old features

For GBR features that survived step 7:

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
   available, else None), with `LowHigh` standardised to `Low`.
   Other confidence values and blanks are unchanged. `DepthCat` = None,
   `DepthCatSr` = None. This corrects the ambiguous source value in the
   retained Torres Strait features without rewriting the source dataset.
5. **OrigType** = LEVEL_3 (if not empty) or FEAT_NAME.
6. **Rename:** IMG_SRC → EdgeSrc, LABEL_ID → ReefID.
7. **ReefFID** = ReefID. Duplicate values are resolved nationally in stage 03.
8. **Dataset:** Retain original DATASET value.
9. **CODES** = CODE (single value, copied from original).
10. **PrevReefID** = null.

### 9. Prepare new features (Reef Edit)

1. **OrigType** = RB_Type_L3.
2. **Dataset** = `Aus-Trop-Reef-Features_{version}`.
3. **EdgeAcc_m:** If null, assign using the same area-based table as old
   features.
4. **DepthCat:** Leave as-is (null values handled by 05-add-depth.py).
5. **Attachment:** Leave as-is (mapper-assigned, no overrides).
6. Assign the computed `ReefFID`, `ReefID`, `PrevReefID` and `CODES` values.
7. Drop `Note`, `FEAT_NAME` and the original singular `CODE` columns.

### 10. Merge and output

1. Align column schemas (superset of all columns, missing filled with None).
2. Concatenate old and new features.
3. Set CRS to EPSG:4283.
4. Report any official identifier held by more than one feature to the
   `shared-reefid` review layer.
5. Save to `working/02/TS-GBR-Features-patched.shp`.

## Output attribute schema

| Attribute | Type | Source (old) | Source (new) |
|---|---|---|---|
| `RB_Type_L3` | str | Crosswalk | Reef Edit |
| `Attachment` | str | Computed (buffer) | Reef Edit |
| `DepthCat` | str | None (set later) | Reef Edit or None |
| `DepthCatSr` | str | None | Reef Edit |
| `FeatConf` | str | None | Reef Edit |
| `TypeConf` | str | CLASS_CONF, with LowHigh mapped to Low | Reef Edit |
| `EdgeSrc` | str | IMG_SRC | Reef Edit |
| `EdgeAcc_m` | int | Area-based | Reef Edit or area-based |
| `OrigType` | str | LEVEL_3 / FEAT_NAME | RB_Type_L3 |
| `Dataset` | str | Original DATASET | `Aus-Trop-Reef-Features_{version}` |
| `ReefFID` | str | LABEL_ID | Inherited LABEL_ID or PROV-{centroid} |
| `ReefID` | str | LABEL_ID | Inherited LABEL_ID or null |
| `CODES` | str | CODE | Semicolon-separated candidate CODEs or null |
| `PrevReefID` | str | None | Semicolon-separated candidate LABEL_IDs or null |

## Validation checks

1. Every Move point matches a GBR feature (matched against the unfiltered
   dataset, before Island/Mainland/Other removal), and every matched Move-point
   CODE exists in Reef Edit. Extra Reef Edit CODEs are allowed.
2. Every Remove point matches at least one GBR feature (also matched against
   the unfiltered dataset).
3. Every old feature maps to a valid RB_Type_L3 via crosswalk.
4. No null geometries in any input.
5. No invalid geometries in Reef Edit. Invalid features and validity reasons
   are saved for inspection.
6. Every `ACTION` value in Remove-Move is one of `VALID_ACTIONS`.
7. Script errors on any validation failure (data should be fixed upstream).
8. On failure, unmatched Move and Remove points are saved to debug shapefiles
   in `working/02/` for inspection in QGIS.

Identifier outcomes that are interpretable but may be wrong do not stop the run.
They are written to the review GeoPackage instead, because halting on them would
mean the script could not complete until every marginal case had been dismissed.
