# Retained TS and GBR legacy coastline clipping and review gate

## Status and purpose

This specification records the approach agreed on 30 October 2026 and revised on 31 October 2026. The proposed script is `02d-clip-TS-GBR-legacy.py`. It has not yet been implemented.

This stage runs after [02a-patch-TS-GBR-Features.py](02a-patch-TS-GBR-Features.py), when replacements and removals have determined which legacy features remain. It clips those surviving features to the coastline. A clipped feature that remains one polygon continues with its existing identifiers. A feature that splits must be corrected manually through Reef Edit before processing can continue.

Legacy features must not be excluded from clipping altogether. The distinction is between accepted singlepart clipping and a split that requires source correction. There is no dominant-child selection or legacy split-ID allocation in this stage. The only automatic removal is of clipping fragments below the 100 m² minimum area defined in the [Reef Edit clipping specification](01e-clip-TS-GBR-reef-edit-spec.md#geometry-processing).

New editing features are clipped before stage 02a under the [Reef Edit clipping specification](01e-clip-TS-GBR-reef-edit-spec.md). Historic lineage remains governed by the existing [02a design](02a-patch-TS-GBR-Features_design.md).

## Processing and identifier context

Stage 01e removes land from new Reef Edit polygons and separates their components before stage 02a. It warns on editing splits because they may indicate mapping errors and copied attributes may no longer be appropriate. In particular, an inherited `EdgeAcc_m` value requires per-feature assessment. A valid clipped geometry is not evidence that these attributes have been reviewed.

Stage 02a replaces old boundaries with the new mapping and evaluates their historic relationships. It distinguishes official identity (`ReefID`), previous association (`PrevReefID`) and dataset feature identity (`ReefFID`). A dominant successor can inherit an official identifier under the existing 3:1 rule. Other qualifying pieces retain the association as a previous identifier instead. This method applies to editing features, not automatically to legacy pieces created after allocation.

Stage 02d therefore operates only after superseded old features have been removed. This avoids flagging source polygons that will not reach the output. It may trim a surviving old polygon without changing its identity, but must not divide it into new records with copied ID fields. Stage 03 can resolve dataset feature-ID uniqueness; it cannot retrospectively decide the official identity of those pieces. A failed legacy split is instead resolved by recording a replacement in Reef Edit and letting stage 02a process it through the established lineage method.

Old source geometry remains available to stage 02a for matching, point checks and attachment calculation. Stage 02d does not alter that historical reference. This separates the geometry used to interpret editing history from the final coastline-trimmed geometry.

## Evidence and rationale

A temporary diagnostic on 30 October 2026 tested the existing stage 02a output last modified on 29 October at 18:32. It selected 5,485 retained legacy records: 3,393 `TS Features` and 2,092 `GBR Features`. All were singlepart, and none was an exempt cay.

Land subtraction changed 325 legacy records. Eighteen parents split into 50 parts, comprising thirteen TS parents and five GBR parents. One other feature disappeared entirely: TS Coral Reef `10-485a1`, with an original area of approximately 16.506 square metres. This sliver has since been marked for removal through the Remove-Move workflow. The remaining 306 changed features did not split or disappear. Some split parts were very small, but others were substantial. This diagnostic did not apply the 100 m² fragment threshold, so some of these splits may become trims.

The author manually reviewed approximately half the split parents. All reviewed cases were attributed to digitisation or positional mismatch against the newer coastline, including misaligned island holes in old reef polygons. The unreviewed cases have not been independently classified. The agreed response is to flag every retained legacy split for manual correction rather than introduce new automated ID rules for these cases.

One manual correction is to create a Reef Edit replacement from the old polygon and remove incorrect island holes. Stage 01e then reconstructs the land exclusions using the current coastline. Filling holes is a manual source decision, not an automatic geometry repair.

## Provenance

The geometry operation follows NW-Aus-Features [10-clip-land.py](../AU_NESP-MaC-3-17_AIMS_NW-Aus-Features/10-clip-land.py). The detection approach was exercised in the temporary `probe_legacy_land_splits.py` diagnostic. That diagnostic subtracted land from each original polygon component and detected newly disconnected results. The production adaptation requires singlepart feature input, adds the blocking review gate and publishes accepted clipped legacy features together with the existing edited features.

The NW script's fallback to an original geometry after a clipping error must not be copied. If subtraction fails, report the failure and prevent publication rather than silently substitute the unprocessed original. This does not require every feature to change. Offshore polygons with no land overlap, boundary-only contacts and intentionally exempt cay features can legitimately retain their geometry. Do not test output locks by rewriting an existing dataset. Do not use threading, for the reasons given in the [Reef Edit clipping specification](01e-clip-TS-GBR-reef-edit-spec.md#provenance-and-adaptations).

Both stages will use the shared coastline-preparation and single-Polygon clipping operations proposed for [reef_utils.py](reef_utils.py). Their responsibilities and limits are specified in the [Reef Edit clipping specification](01e-clip-TS-GBR-reef-edit-spec.md#shared-clipping-functions). Keep the legacy blocking rule in stage 02d, rather than embed a stage-specific policy in the geometry helpers. Existing L2 sliver repair and simplification are not substitutes for manual source correction.

## Inputs and outputs

Run from the repository root in the AusTropReef environment. Read `in_3p_path` and `version` from [config.ini](config.ini).

| Resource | Path |
|---|---|
| Patched TS and GBR features | `working/02/TS-GBR-Features-patched.shp` |
| Coastline landmask | `{in_3p_path}/Coastline50k/Split/AU_NESP-MaC-3-17_AIMS_Aus-Coastline-50k_2024_V1-1_split.shp` |
| Accepted input for stage 03 | `working/02/TS-GBR-Features-clipped.shp` |
| Original split parents | `working/02/legacy-land-split-parents.shp` |
| Clipped split parts | `working/02/legacy-land-splits.shp` |
| Original features with no retained marine remainder | `working/02/legacy-land-removed.shp` |

The primary output retains the stage 02a schema, including the intermediate `RE_row` and `RE_part` tracking fields, and EPSG:4283. These fields are null for legacy records. Source datasets and the stage 02a output remain unchanged. QA tracking fields are not added to the primary output.

## Selection and clipping

Select retained legacy records using `Dataset = GBR Features` or `Dataset = TS Features`. Recognise the current editing source as `Aus-Trop-Reef-Features_{version}`. Missing or unexpected source labels cause an error rather than silently choosing a processing path. Print any unexpected labels. No separate version-mismatch detection is required.

Only retained legacy marine records receive land subtraction here. Carry the edited records through unchanged; they have already been clipped and allocated identifiers upstream.

Exempt cay records in either source group. After stage 02a, cays are identified by `RB_Type_L3` values `Vegetated Cay` and `Unvegetated Cay`. For legacy records these classes are produced by the stage 02a crosswalk from the source classification `FEAT_NAME = 'Cay'`, which is not retained in the stage 02a output.

Keep retained GBR and TS cay features, consistent with retaining the separately mapped Coral Sea cays in stage 02c. The cay exemption is a scope limitation, not a quality endorsement. GBR cay remapping was outside this project. The author reports widespread inaccurate source positions and boundaries, including offsets of approximately 1 km, records that do not represent real cays, and little or no overlap with the actual cay. These are source limitations rather than measured error bounds for every record. Preserve retained cay records without claiming they have been corrected. Do not remove all cays because of poor mapping or reinstate records excluded by existing stage 02a filtering.

The automated coastline includes permanently dry cays as land. Marine reefs are clipped around that coastline even though separately retained cay polygons may be displaced. Land exclusion from a reef does not validate or relocate its associated cay record. Cay polygons may overlap land features. Summing cay area and land area without removing their overlap can double-count land. State these limitations explicitly in the published dataset documentation and technical report. Do not delete land features to accommodate mapped cays or introduce a cay-land reconciliation workflow. That work requires suitable cay mapping and is outside scope. See the [cay limitations](01e-clip-TS-GBR-reef-edit-spec.md#cay-scope-and-limitations) for the shared rationale.

Validate input CRS, required fields and non-empty valid polygon geometries. Require `Dataset`, `RB_Type_L3`, `ReefID`, `ReefFID`, `PrevReefID`, `CODES`, `Attachment` and `EdgeAcc_m`, plus the intermediate `RE_row` and `RE_part` fields. Require the stage 02a input to be in EPSG:4283. Transform the coastline from EPSG:4326 to EPSG:4283 at the start, validate it and then build its spatial index. Query and clip directly in that CRS, using a local union of the land polygons intersecting each candidate. There is no EPSG:4326 feature round trip. Retain the input geometry when there is no intersecting land or the valid difference is topologically equal to the input. This includes boundary-only contact and does not require a separate contact predicate. There is no vertex-count or coordinate-order requirement. Use EPSG:3577 for QA areas and minimum-area measurements. Do not buffer, simplify, fill holes or repair invalid geometry automatically.

Apply the shared result handling from stage 01e. Discard non-polygonal by-products and remove parts below 100 m² from altered features, using a strict less-than comparison without an equality tolerance. This is an approximate mapping-resolution threshold based on one original 10 m Sentinel-2 pixel, below the approximately 300-600 m² smallest intentionally mapped feature. Unchanged features and exempt cays are not filtered. Print the total number of removed fragments rather than writing a fragments QA layer. Review the remaining splits manually. Add a fragments layer or additional sliver processing only if actual counts and inspection demonstrate a need.

Validate results in EPSG:4283 before filtering. Apply the [no-automatic-repair policy](01e-clip-TS-GBR-reef-edit-spec.md#invalid-geometry-and-repair-policy). Check input validity before clipping, report invalid feature records with their `src_row` references and validity explanations, then stop. Invalid transformed coastline geometries, local unions or clipping results and failed geometry operations must also stop without a repair attempt. Report the source reference and processing step with the validity explanation or operation error. Coastline failures identify the coastline input and affected record or local union. Do not write invalid-source or attempted-result QA layers. Locate source features using the console references. Additional diagnostics or a repair approach will be considered only if actual failures demonstrate a need.

A surviving single Polygon is accepted, even when its area or holes have changed. Preserve all its attributes, including `ReefID`, `ReefFID`, `PrevReefID`, `CODES`, `Attachment`, classification, confidence and edge accuracy. This stage does not recalculate area-based edge accuracy or attachment, or rerun lineage decisions. Final national area attributes are calculated downstream.

Preserving legacy `EdgeAcc_m` means a trimmed feature keeps the default assigned by stage 02a from its pre-clip area. The value may be somewhat high for the trimmed feature. This is accepted, because the large changes that would matter most are splits, and those are corrected manually through Reef Edit. The stage is a coastline correction with a split check, not a new per-feature uncertainty assessment.

Stage 02a assigns `Attachment` only to legacy records. Reef Edit records keep their manually assigned values. For legacy records, stage 02a derives `Attachment` from a 200 m buffer of the legacy GBR polygons with `LEVEL_1` of `Island` or `Mainland`, not from Coastline50k. A legacy reef trimmed to Coastline50k can therefore be classed `Isolated` where the newer coastline shows land that the legacy island layer lacks, or the reverse. This stage does not resolve that difference. Features where it matters can be replaced through Reef Edit with a manually assigned `Attachment`.

## Blocking review conditions

Count surviving polygon parts after fragment removal. No surviving parts is a removal, one is a trim, and two or more is a split. Parts touching only at a point remain separate parts and follow the same split rule. There is no separate point-contact category or pairwise contact check. Save every surviving part of a split parent for review, regardless of dominance.

Any legacy split, complete removal, multipart source record, invalid geometry or failed geometry operation prevents publication of the primary output and causes a nonzero exit status. This is intentional: no accepted clipped output is produced until every case has been resolved. Collect splits and removals through the clipping loop, then write their QA layers before reporting the gate failure. Input-check failures and invalid intermediate results or failed geometry operations stop under the error-reporting rules above. A failure of coastline preparation or another shared prerequisite must also stop the run. A dominant retained part does not exempt a split from review.

For this gate, complete removal also includes a clipped feature whose remaining marine parts are all below 100 m² and are removed by the threshold. Use the same removal QA layer and corrective workflow for both cases. It is not necessary to distinguish them through separate review categories.

A MultiPolygon with a single component is treated as a Polygon. Before clipping, stop on legacy or editing records with two or more components and print their `src_row` references and existing identifiers. Do not create a pre-existing-multipart QA category or explode legacy records with copied official identifiers. Correct multipart legacy features through Reef Edit replacement or explicit removal. Correct multipart editing features in the Reef Edit source and rerun the upstream stages. Exempt cays must meet the same singlepart requirement.

The split QA retains original attributes and adds `SOURCE`, `src_row`, `after_n`, `part_n`, `area_m2` and `share`. `SOURCE` identifies `GBR Features` or `TS Features`. `src_row` is the 1-based stage 02a input record in file-read order for this run, not a persistent identifier or a QGIS feature ID. Use it as the within-run reference. Retain `ReefFID`, `ReefID` and `CODES` as descriptive identifiers, but do not assume they uniquely identify a legacy record before stage 03. `after_n` is the number of retained parts for the parent. `part_n` is the 1-based retained-part number. `share` is the fraction of surviving parent area. Original-parent and removal layers retain original geometry and source references; `part_n` is null there. A before-count is unnecessary because every accepted source has one polygon. The layers distinguish splits from removals, so no reason field is required.

IDs in QA are copied reference attributes only. They are not approved assignments to the clipped pieces.

Tracking supports visual QGIS review and automated inspection without introducing a separate relationship system. It need not encode every ambiguous association. Shared `ReefID` values are permitted even in the final dataset; stage 03 makes `ReefFID` unique. The existing allocation sequence is not an error and does not need changing.

## Operator guidance on failure

Print progress in the same way as stage 01e, as described in its [failure handling and regeneration](01e-clip-TS-GBR-reef-edit-spec.md#failure-handling-and-regeneration) section. Announce each major step, report record counts and the total removed-fragment count, and print the elapsed time at the end of the run. Add periodic progress only if actual processing proves slow.

When the split or removal gate blocks, the console must make the next steps clear without reference to this specification. Print a summary that gives the category, number of features, `src_row` references and existing `ReefFID` values, and the QA layers to load in QGIS together with the coastline. End with the required action: create a corrected Reef Edit replacement or an explicit Remove point for each listed feature, then rerun stages 01e, 02a and 02d. Mention [02a-PrevReefID-review-guide.md](02a-PrevReefID-review-guide.md) for checking that the intended historic links were retained. For multipart or invalid inputs and geometry-operation failures, identify the processing step and source records in the console and direct the operator to the source dataset rather than a diagnostic QA layer.

## Manual resolution and rerunning

For each flagged legacy feature, inspect the original parent, clipped parts, coastline and imagery. Add a corrected, fully attributed Reef Edit replacement where appropriate. Preserve a suitable overlap with the old feature or use the existing CODE and control-point workflow to record its relationship. If the feature was mapped in error, record an explicit removal using the existing workflow.

Where an old reef has misaligned island holes, an operator may remove those holes in its Reef Edit replacement. Stage 01e will cut the current coastline landmask out of that replacement. This does not justify automatically filling every hole; holes must be assessed against the intended reef and the available imagery.

The review can proceed progressively. Each corrected source feature is processed by stage 01e and replaces its legacy predecessor in stage 02a when the existing matching rules identify it. Stage 02d then evaluates the remaining legacy records. If a replacement no longer overlaps its old boundary after clipping, use the existing explicit relationship workflow and review the stage 02a identifier reports. Absence of a split warning alone does not prove that the intended historic link was retained.

Do not edit generated QA or clipped outputs as the fix. Rerun stages 01e, 02a and 02d after correcting the source. Stage 02a then replaces the old feature and applies its existing historic-ID logic to the new marine components. Repeat until no blocking legacy cases remain.

## Publication gate and downstream integration

Rebuild this stage's outputs on every run. Remove stale QA datasets owned by the stage and invalidate its previous primary output before processing. A failure must not leave an old accepted output available for the national merge. Write a new primary output only when all checks pass.

This stage is run in an editing loop with its QA layers open in QGIS, so locked files are expected. If an owned output or sidecar cannot be deleted or written, stop with a nonzero exit status. Print the affected path and a message such as "This file is probably open in QGIS or another program. Remove the layer or close the project, then rerun." Do not report this as a generic exception trace.

Change [03-merge-TS-GBR-CS-NW.py](03-merge-TS-GBR-CS-NW.py) to read `working/02/TS-GBR-Features-clipped.shp` by default, never automatically falling back to the raw stage 02a output. Stage 03 must drop the `RE_row` and `RE_part` tracking fields. The prescribed production workflow must stop on a failed stage 02d. Stage 03 continues to resolve national `ReefFID` uniqueness but does not allocate lineage to legacy clipping splits.

For development while manual corrections are in progress, provide an explicit `--allow-review` option in stage 03. This reads the raw stage 02a output instead of the accepted clipped path and writes all stage 03 outputs to `working/03-review`, not the production directory. Print a conspicuous warning that legacy coastline correction has been bypassed and the output is not for publication. This mode tests the merge without inventing assignments for clipped legacy pieces. It does not override stage 02d, imply acceptance of legacy cases or change the normal downstream inputs. It must not write to the production output directory. No automatic fallback or review-mode pipeline is required.

Rerun stage 02d whenever stage 02a is regenerated. Rerun both clipping stages and stage 02a whenever the coastline changes. Intermediates are not self-refreshing caches; skipping required upstream reruns is not supported. This specification does not introduce a general pipeline scheduler or cache-fingerprint system.

After implementation, update the README execution sequences, stage 02a input documentation and the identifier review guide to describe the two clipping stages. Document the development-only stage 03 option separately from the production sequence. Update the published dataset documentation and technical report with the cay retention, mapping-quality and land-overlap limitations. No change to the historic dominance thresholds or lineage method is intended.

## Planned validation

Synthetic tests will cover no land overlap, boundary-only contact, trimming to one polygon, trimming that leaves only sub-100 m² fragments besides the main part, island-hole changes, splits, complete land removal, removal of all below-threshold marine remnants and cay exemptions. Verify that a single-component MultiPolygon can be treated as a Polygon and multipart source records block before clipping. Test areas below and above 100 m² without requiring an exactly equal projected area. All splits must block, regardless of dominance or whether parts touch only at a point. Accepted singlepart trims must retain every ID attribute unchanged.

Check rejection of missing or unexpected source labels, QA source flags, 1-based source-row references, part areas and shares, output CRS, singlepart validity, unchanged edited geometry, geometric equality of non-intersecting legacy geometry and source-data immutability. Do not assert vertex counts or coordinate ordering. Test with a coastline initially in EPSG:4326 to verify it is transformed before querying EPSG:4283 features. Verify the removed-fragment count and that no fragments or invalid-geometry QA layers are written. Repeat-run tests must show that cleared issues remove stale QA and that a failed run cannot leave a previous merge-ready dataset. Verify that a locked output produces the QGIS message and that the split or removal summary lists source rows, existing `ReefFID` values and QA paths. Duplicate pre-03 identifiers must not make distinct QA records indistinguishable by source row.

Verify that unchanged offshore geometry is accepted and a failed subtraction cannot be disguised as an unchanged successful feature. Invalid inputs, simulated invalid results and failed operations must stop without automatic repair and identify the source and processing step in the console. Exercise the shared geometry operations through both stage callers without changing existing L2 dissolution or clustering behaviour.

An integration test must show that correcting a flagged legacy parent through Reef Edit removes it from the legacy check after stage 02a. The resulting editing parts must receive their identifiers through the existing stage 02a rules. Verify that stage 03 reads the new accepted path by default, fails when that output is absent, and drops the tracking fields. Verify that explicit `--allow-review` reads the raw stage 02a input, prints the non-publication warning and writes only to the separate review directory, leaving production outputs unchanged.

The diagnostic counts above are a baseline for the recorded input snapshot, not permanent expected counts. Regenerating stage 02a with pre-clipped editing polygons and applying the fragment threshold can change which legacy features remain or split, so validation must inspect the current results rather than require exactly eighteen split parents.
