# GBR and Torres Strait remapping statistics

## Purpose

Approved and implemented on 8 November 2026 in [A07-gbr-ts-remap-stats.py](A07-gbr-ts-remap-stats.py). Count updated, newly mapped and explicitly removed features in the GBR and Torres Strait. Use the final dataset's recorded lineage rather than repeating the replacement process. List both processed feature counts and original Reef Edit counts in a Markdown report so the author can select appropriate statistics for the paper.

## Inputs and output

Run from the repository root in the `AusTropReef` environment. Read `version`, `in_path` and `in_3p_path` from [config.ini](config.ini), respecting configured absolute and relative paths.

| Resource | Path |
| --- | --- |
| Final full-classification dataset | `data/{version}/out/full-classes/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp` |
| Original Reef Edit polygons | `{in_path}/Reef-edit/AIMS_GBR-TS-Features_Edit_{version}.shp` |
| Remove-Move points | `{in_path}/Reef-remove-move/AIMS_GBR-TS-Features_remove-move_{version}.shp` |
| Refreshed legacy reference, for removal targets only | `working/{version}/01/TS-GBR-Features-latest.shp` |
| Analysis regions | `{in_3p_path}/nesp-3-17-analysis-regions/analysis-regions.shp` |
| Inshore remapping extent | `data/{version}/extras/inshore-extent/inshore-extent.shp` |
| Markdown report | `data/{version}/out/stats/A07-gbr-ts-remap-stats_{version}.md` |
| Invalid polygon locations | `working/{version}/A07/invalid-polygons.shp` |

Use the full-classification output, not dissolved L2 polygons. Inputs must belong to the same processing build and remain unchanged. No CSV or figure is required. The diagnostic shapefile is generated when invalid polygons are found; stale diagnostic files are removed on a clean run.

## Regional scope

Use Analysis-Regions to retain features and control points in `GBR` and `Torres Strait`. Use the inshore remapping extent to separate inshore GBR from the remaining GBR and Torres Strait.

Report GBR inshore, GBR outside inshore and Torres Strait separately, plus the combined subtotal, GBR outside inshore + Torres Strait, and the overall GBR + Torres Strait total. Here "outside inshore" includes mid-shelf and offshore mapping, not a separate official offshore region.

Apply the same spatial assignment to final features, Reef Edit polygons and legacy removal targets. Count each record once without dissolving, exploding or clipping. Report the number excluded from GBR + Torres Strait in the validation notes, not as additional result regions.

The inshore boundary was chosen not to cross reefs, and control points are not expected on shared boundaries. Keep allocation safeguards simple: largest-area region assignment in EPSG:3577, including the unassigned remainder; at least 50% inside for inshore polygons; boundary-inclusive coverage for points. Exact ties use alphabetical region order, with named regions preferred over unassigned. These rules require no separate boundary-review workflow or routine tie and crossing diagnostics.

## Feature status

Identify processed Reef Edit features using `Dataset == "Aus-Trop-Reef-Features_{version}"`. Other final records are retained source mapping, not manual updates, even if later processing clipped their coastline.

| Status | Rule for final records |
| --- | --- |
| Updated | Editing provenance and a non-empty `ReefID` **or** `PrevReefID` |
| Newly mapped, no recorded predecessor | Editing provenance and both identifier fields empty |
| Retained legacy/source mapping | Non-editing provenance |

Treat null and whitespace-only identifiers as empty. Count records, not individual identifiers in semicolon-separated lists. Break updated counts into ReefID only, PrevReefID only and both, so the lineage interpretation can be checked.

`PrevReefID` alone is insufficient: [stage 02a](02a-patch-TS-GBR-Features.py) stores a clear inherited identity in `ReefID` and may leave `PrevReefID` empty. Its lineage threshold is at least 10% of either polygon's area after the sliver test, with explicit CODE and Link overrides. Replacement itself can occur below that threshold. Therefore "newly mapped" means no recorded predecessor in the processed output, not proof that no old polygon overlapped. The reference includes both refreshed GBR Features and existing TS Features.

Count all feature classes. Also provide final-data reef-only subtotals using `RB_Type_L2` values `Coral Reef` and `Rocky Reef`, so sediment and cay edits are not presented as newly mapped reefs.

## Removals and source comparison

Count Remove, Move and Link point instructions separately. For explicit removals, intersect Remove points with the refreshed legacy reference, using the same point-intersection rule as stage 02a. Count distinct targeted legacy source rows once, even when multiple points hit them. Apply the regional filter to the targets themselves. Report both in-scope Remove-point counts and distinct in-scope removed-feature counts.

Move instructions identify reefs whose old outlines did not overlap their corrected mapping. They indicate substantial positional errors in the old mapping, rather than routine boundary adjustments. These reefs belong among updated features, not newly mapped features or explicit removals. Report Move-point counts as recorded correction instructions, not as an independent positional-accuracy assessment.

The legacy reference is needed because removed features are absent from the final dataset. This point lookup does not rerun overlap replacement or identifier allocation. Do not count replaced outlines or Move targets as explicit removals, and do not infer removals by subtracting release totals. Stop on an in-scope Remove point with no legacy target.

Compare original Reef Edit record counts with processed editing-record counts, including their difference. Do not force equality: coastline clipping can split or discard polygons, and changes in geometry can change regional assignment. Source counts measure digitised polygons; final counts measure resulting features. Raw Reef Edit records do not contain lineage, so updated/new status comes only from the processed output.

## Markdown contents

Follow [A01-summary-stats.py](A01-summary-stats.py) for captioned Markdown tables and provenance, without requiring `tabulate`.

| Table | Columns, using the regional rows defined above |
| --- | --- |
| 1. Source and processed counts | Original Reef Edit polygons; final editing features; difference; updated; newly mapped; retained source features; total final features; retained source (%) |
| 2. Lineage and reef-only counts | Updated with ReefID only, PrevReefID only, both; updated, newly mapped, retained and total coral/rocky reef features; retained coral/rocky reef (%) |
| 3. Explicit controls | Remove points; distinct removed legacy features; Move points; Link points |

Mark combined rows as subtotals. Include zero counts, repository-relative input paths, version, generation time, source record counts, CRS, counting definitions and reconciliation checks. For external inputs, show the filename and refer to local config.ini, without exposing machine-specific directories. Full paths may appear in local console diagnostics. Add a short results paragraph with computed values:

> Mapping revisions in the GBR and Torres Strait updated [updated] previously mapped features and added [new] features to the mapping. The inshore GBR contained [inshore updated] revised features and [inshore new] additions. In the inshore GBR, [inshore retained] features ([inshore retained %] of mapped features) remained based on legacy mapping without manual revision. Outside the inshore GBR, [remaining GBR retained] features ([remaining GBR retained %]) retained legacy mapping. In Torres Strait, [TS retained] features ([TS retained %]) retained legacy mapping. The revisions also explicitly excluded [removed] legacy features. In [moves] recorded positional corrections, the old reef outlines did not overlap the revised outlines, indicating substantial positional errors in the old mapping.

Retained percentages use all current mapped features, including additions, as the denominator. Provide the equivalent reef-only percentage using coral and rocky reef features. Display one decimal place and recalculate combined-region percentages from counts. Where the denominator is zero, display Not applicable. Keep identifiers, Link instructions and source-count comparisons in the tables and methods, not the reader-facing paragraph. These percentages describe reliance on legacy mapping, not a measured error rate or the proportion of original polygons unchanged.

Use "features" for all-class counts, not "reefs". Explain that newly mapped features are additions to the recorded mapping, not physical reef formation or independently verified discoveries.

## Validation

Require the listed files, defined CRS, non-empty geometries, region labels and relevant fields: final `Dataset`, `ReefID`, `PrevReefID`, `RB_Type_L2`; control `ACTION`; region `subregion`. Reject unsupported actions, null or wrong-type geometries and missing fields explicitly. Empty editing or control layers with valid schemas produce zero counts.

Repair invalid polygons in memory with Shapely `make_valid` for spatial allocation. Retain polygonal parts within the original record and stop if no valid polygon remains. Export the original problem polygons in EPSG:4283 with input, source row, identifiers, validity reason, repair type and omitted-remnant count. `Check_at` distinguishes stored Source CRS failures from EPSG:3577 projection issues; one source record can appear at both stages. Print warnings and the diagnostic shapefile path to the console, not the Markdown report. Do not modify source shapefiles. Invalid stored boundaries require review before publication.

Check updated + newly mapped = final editing features, and editing + retained = all selected final features. Lineage subdivisions must sum to updated. Regional detail must equal both combined subtotals and the overall total. Reef-only counts must not exceed all-class counts.

Focus tests on identifier classification, provenance, regional and inshore grouping, distinct removal targets, source/final comparison and count reconciliation. Cover allocation safeguards with small synthetic cases, without adding special production workflows. After tests pass, run on the configured inputs and verify the reported counts directly against the filtered source tables. Complete validation before replacing an existing report.
