# TS and GBR Reef Edit coastline clipping

## Status and purpose

This specification records the approach agreed on 30 October 2026 and revised on 31 October 2026. The proposed script is `01e-clip-TS-GBR-reef-edit.py`. It was implemented on 31 October 2026.

Manually digitised marine features may extend over land because their landward boundaries were drawn approximately to reduce editing effort. This stage removes those overhangs before [02a-patch-TS-GBR-Features.py](02a-patch-TS-GBR-Features.py) assigns historic identifiers. The L3 dataset requires one polygon per feature record. Disconnected marine parts must therefore enter stage 02a as separate records rather than inherit identifiers from a multipart parent after allocation.

Coastline subtraction was omitted from the original TS and GBR processing workflow. The manual boundaries were not necessarily intended to describe the landward edge accurately. Treating them as finished boundaries therefore allowed marine features to extend across land in the final dataset. This stage separates rapid manual mapping of the marine feature from the construction of its landward boundary using the coastline.

The complementary [legacy clipping specification](02d-clip-TS-GBR-legacy-spec.md) covers retained legacy features after stage 02a. No new legacy split-allocation method is required.

## How the processing stages fit together

Stage 01e trims the new Reef Edit mapping to the coastline. It produces valid singlepart geometries for stage 02a, but does not certify that their interpretation or attributes have been manually checked. A split remains a quality-control warning even when its geometry is valid.

Stage 02a compares these clipped editing features with the original refreshed legacy mapping. It applies the existing replacement, move and removal rules and records the historic relationships. Stage 02d then clips only the legacy features that survived replacement. A legacy trim that leaves one polygon continues with its identifiers unchanged. A legacy split requires a corrected Reef Edit replacement or an explicit removal before the national merge.

This order avoids changing the old reference geometries before historic matching. It also avoids reviewing legacy features that stage 02a will replace anyway. After a manual correction, the new editing polygon passes through stage 01e and replaces the problematic legacy polygon in stage 02a. The correction becomes part of the reproducible input record rather than a change made directly to an exported dataset.

Stages 01e, 02a and 02d are expected to be run repeatedly in an editing loop until no blocking issues remain. Their console messages must therefore tell the operator what failed, which layers to load in QGIS and what source to correct.

## Provenance and adaptations

The implementation will be adapted from NW-Aus-Features [10-clip-land.py](../AU_NESP-MaC-3-17_AIMS_NW-Aus-Features/10-clip-land.py), available from [github](https://github.com/eatlas/AU_NESP-MaC-3-17_AIMS_NW-Aus-Features/blob/main/10-clip-land.py). Its coastline subtraction, geometry validation, intersection pre-filter and singlepart output provide the starting point. The adaptation changes input and output paths, preserves intentional cay classes, removes sub-mapping-unit fragments, and reports split parents and parts before ID allocation.

The NW script unions the whole coastline and clips with a `ThreadPoolExecutor`. This adaptation does not use threading. A trial on 31 October 2026 with the current inputs found 1,342 of 4,607 Reef Edit records intersecting the coastline. Clipping each against a union of only its intersecting coastline polygons took approximately 11 seconds sequentially. Threading would add complexity and make error reporting harder for little gain. The trial supports this processing approach; it is not a timing guarantee for the final EPSG:4283 implementation.

The NW script clips in EPSG:4326. This adaptation instead transforms inputs to EPSG:4283 before spatial queries and clipping. That is the CRS used by stage 02a and the national pipeline. Using one processing CRS avoids transforming legacy features to EPSG:4326 and back. EPSG:3577 is used separately for square-metre measurements.

The original NW script can return the original geometry after a clipping operation raises an error and its recovery attempt also fails. This adaptation must report the affected feature and stop instead of substituting that original polygon into an output presented as successfully clipped.

An unchanged geometry is not a failure. Offshore features that do not overlap land are valid without modification. Features that touch the land boundary without losing polygon area can also remain unchanged. Cay classes are deliberately exempt from subtraction. The failure rule concerns a clipping operation that could not be completed, not a requirement for every feature to change. Its output lock check must not rewrite an existing shapefile simply to test whether it is locked.

## Inputs and outputs

Run from the repository root in the AusTropReef environment. Read `in_path`, `in_3p_path` and `version` from [config.ini](config.ini).

| Resource | Path |
|---|---|
| Reef Edit source | `{in_path}/Reef-edit/AIMS_GBR-TS-Features_Edit_{version}.shp` |
| Coastline landmask | `{in_3p_path}/Coastline50k/Split/AU_NESP-MaC-3-17_AIMS_Aus-Coastline-50k_2024_V1-1_split.shp` |
| Required pier exclusions | `{in_path}/Land-exclusion/Land-exclusion-piers.shp` |
| Clipped editing input for stage 02a | `working/{version}/01/Reef-Edit-clipped.shp` |
| Split original parents | `working/{version}/01/reef-edit-land-split-parents.shp` |
| Split output parts | `working/{version}/01/reef-edit-land-splits.shp` |
| Original features with no retained marine remainder | `working/{version}/01/reef-edit-land-removed.shp` |

Source datasets are read-only. On 31 October 2026 the Reef Edit source was in EPSG:4326 and contained 4,604 Polygon and 3 MultiPolygon records. The Coastline50k landmask is also in EPSG:4326 and represents approximately mean high water.

The main output must retain every Reef Edit source attribute with unchanged values and field types. The current source fields are `CODE`, `EdgeSrc`, `FeatConf`, `EdgeAcc_m`, `DepthCat`, `DepthCatSr`, `RB_Type_L3`, `Attachment`, `TypeConf` and `Note`. `EdgeAcc_m` is currently stored as text and must not be converted. The script must stop if any of these fields is missing, rather than relying on a hard-coded subset. The main output is written in EPSG:4283 to match stage 02a.

## Traceability attributes

The outputs of stages 01e and 02a are intermediate products, so they may carry tracking attributes that are removed before the final dataset. Stage 01e adds two fields to the main output and QA layers. These are lightweight diagnostic references, mainly to help automated or AI-assisted inspection. Manual review will primarily locate features visually in QGIS using the parent and part layers. Complete tracking of every relationship is not required.

| Field | Meaning |
|---|---|
| `RE_row` | 1-based record number in source-file read order for this run. It is independent of QGIS table sorting and is not a QGIS feature ID. |
| `RE_part` | 1-based number of the surviving output part within that source record. It is 1 for unsplit features and null for original-parent or complete-removal QA records. |

These are run-specific references, not persistent identifiers. Stage 02a must retain them on editing records in `working/{version}/02/TS-GBR-Features-patched.shp`. Legacy records leave them null. Stage 02a error messages and identifier review layers do not need these references and remain unchanged. No new relationship table is required. [03-merge-TS-GBR-CS-NW.py](03-merge-TS-GBR-CS-NW.py) must drop the two fields so they never reach the published dataset.

## Geometry processing

Require defined CRS, valid non-empty polygon geometry and the fields listed above. Report invalid, null or non-polygon input records for correction rather than dropping or repairing them automatically. Treat a MultiPolygon with one component as a Polygon. Stop on source records with two or more components and print their `RE_row` references. The source snapshot contains only three MultiPolygon records. Any genuinely multipart records should be separated manually in QGIS into individually attributed Reef Edit records before rerunning. This avoids per-component clipping and tracking rules for a small source-cleanup task. The singlepart requirement applies to exempt cays as well as marine features, but not to the coastline landmask.

Transform the coastline and Reef Edit geometries to EPSG:4283 at the start and validate them after transformation. Build the coastline spatial index only after this transformation. All spatial-index queries, local coastline unions and subtraction operations use EPSG:4283. Features with no intersecting land keep their EPSG:4283 geometry without a difference operation. Otherwise union only the intersecting land polygons, validate the union, subtract it and validate the result. If the valid result is topologically equal to the input, retain the input geometry and do not apply the fragment filter. This also handles boundary-only contact without a separate contact predicate. There is no vertex-count or coordinate-order requirement. Do not buffer, simplify or fill holes.

Before building the coastline index, subtract the required pier-exclusion polygons from the working landmask. These manually assessed footprints describe elevated piers beneath which the reef continues. They are local clipping exceptions, not exemptions for an entire reef or corrections to the published coastline. Require a defined CRS and valid, non-empty Polygon or MultiPolygon records, then transform the exclusions to EPSG:4283 and validate them again. An empty layer with a defined CRS represents no exclusions. Missing or invalid input, an invalid exclusion union or a failed subtraction blocks publication and identifies the input or coastline record in the console. Do not repair geometry automatically.

Subtract the union of the exclusions only from intersecting coastline records. Validate each result before extracting its polygon parts. Entirely excluded coastline records are omitted from the working mask. No minimum-area filter is applied to the remaining land. Preserve normal reef clipping, fragment filtering, cay exemptions and split-review rules elsewhere. Report the exclusion count and number of changed coastline records. Neither the source coastline nor the exclusion layer is modified. Stages 01e and 02d must use the same exclusion layer; after changing it, rerun stages 01e, 02a and 02d before stage 03.

Exempt cay records from land subtraction. In Reef Edit these are `RB_Type_L3` values `Vegetated Cay` and `Unvegetated Cay`. Three `Unvegetated Cay` records were present on 31 October 2026. Preserve their mapped extent subject to the limitations below.

Validate each clipped result before fragment filtering. Do not attempt automatic geometry repair. An invalid result or a failed geometry operation must be reported under the policy below and must block publication. For valid results, retain polygon geometry and discard any line or point by-products. This extraction is not permission to repair an invalid result by discarding its problematic parts.

Remove clipping parts below 100 m², measured in EPSG:3577. The cutoff is an approximate mapping-resolution threshold, based on the area of one 10 m by 10 m pixel in the original Sentinel-2 imagery. No feature was intentionally mapped at that size; the smallest intentionally mapped features are approximately 300-600 m². Use a strict less-than comparison, without an equality tolerance. Report the total number of removed fragments in the console rather than writing a fragments QA layer. Fragment removal is informative and does not block or warn on its own.

Apply the threshold to all polygon parts of an altered feature, even when clipping leaves only one part. Unchanged features and exempt cays are not filtered. Long thin fragments above the area threshold may remain. Review splits manually before adding a width-based filter or another sliver rule. If there are too many cases to correct manually, inspect the actual fragments before choosing additional processing. A fragments QA layer can be added later if the console count warrants investigation.

Explode multipart clipping results so every exported feature is a single Polygon. Copy source attributes to each part. Results are already in EPSG:4283; no final datum transformation is needed. Validate the final geometries before publishing.

A clipped source feature with no surviving marine part of 100 m² or more is treated as a land-only or below-mapping-resolution feature for this review. This includes complete land subtraction and removal of all tiny marine overhangs by the threshold. Save the original feature to the same removed QA layer and stop with a nonzero exit status. A separate review category or workflow for the two cases is not required. The coastline has been manually inspected, so correct or delete the Reef Edit source rather than alter the coastline to accommodate it.

## Invalid geometry and repair policy

The agreed initial policy is no automatic repair. Do not call `make_valid`, `buffer(0)` or another geometry-repair operation on inputs, transformed geometries, local coastline unions or clipping results. Invalid geometry and failed geometry operations must prevent publication, even when a repair might be possible.

Check input validity before clipping. Report invalid input records with their `RE_row` references and validity explanations, then stop with a nonzero exit status. For a failed geometry operation or invalid intermediate result, print the source reference, failing processing step and operation error or validity explanation, then stop. Coastline failures must identify the coastline input and affected record or local union. Do not write invalid-source or attempted-result QA layers. The operator can locate the original source records using the console references. Never substitute an unprocessed original geometry into a successful production output.

Valid inputs should normally produce valid difference results, but this is not guaranteed. Investigate actual failures before adding diagnostic exports or deciding whether a repair rule is needed. A future repair method must be justified against those examples and documented separately. There is no outstanding repair tolerance to select for this implementation because automatic repair is not permitted.

The 100 m² fragment filter is an intentional mapping-resolution rule applied to valid clipping results. It remains enabled and is not a geometry-repair tolerance. Valid results continue through the trim, split and removal rules.

## Cay scope and limitations

Remapping GBR cays was outside the scope of this project. The author's assessment is that nearly all existing mapped GBR cays have poor boundaries or positions. Some are displaced by approximately 1 km, some do not represent real cays, and many do not overlap the actual feature. This assessment describes a known source-data limitation, not a measured positional-accuracy statistic for every cay.

Keep retained GBR and TS cay features, consistent with retaining the separately mapped Coral Sea cays in stage 02c. The cay exemption preserves these classes where they are included by the existing workflow. It does not validate their existence, location, boundary or classification. It does not add cay records excluded by other stage 02a rules. The known poor GBR mapping is not grounds for automatically removing all cays. The technical report must not describe their passage through processing as a completed cay remapping or correction. This limitation must be explicit in the published dataset documentation, not only in this processing specification.

The automated coastline mapping includes the boundaries of permanently dry cays as land. Marine reef polygons are therefore trimmed around those landmask boundaries. The separately mapped cay features are exempt from subtraction. Correctly excluding dry land from a marine reef does not correct a displaced cay polygon or establish a correspondence with it. The resulting cay layer and the land exclusions in the marine mapping can remain spatially inconsistent. Cay polygons may overlap land features, so summing cay area and land area without removing their overlap can double-count land. Document this limitation explicitly. Reconciling the two representations would require suitable cay mapping and is outside scope. Do not delete land features to accommodate mapped cays. This limitation also applies to the legacy clipping stage.

## Split review

Count surviving polygon parts after fragment removal. No surviving parts is a removal, one is a trim, and two or more is a split. Multipart source records have already been rejected, so there is no need to track changes within original components.

Parts that touch only at a point remain separate polygon parts and receive the same split warning as disconnected parts. Do not introduce a separate point-contact category, pairwise contact check or blocking rule.

The split-parts QA layer contains all surviving parts of a flagged parent. Retain the source attributes and add `RE_row`, `RE_part`, `after_n`, `area_m2` and `share`. `after_n` is the number of retained parts for that parent. Areas use EPSG:3577. `share` is the part's fraction of the surviving parent area. A before-count is unnecessary because every accepted source has one polygon. The layer itself identifies the split category, so no reason field is required. The parent layer retains the original geometry with the same `RE_row` reference.

Clipping-created editing splits are review outputs, not automatic failures. Ideally the manual mapping should be constructed so that clipping does not create unintended disconnected pieces. A split may indicate digitisation error, imprecise landward boundaries or misaligned holes. The script must save the parent and part QA layers for checking in QGIS. It must print a conspicuous `WARNING` with the number of affected parents and resulting parts, their `RE_row` values, the review file paths, and an instruction to check the geometry and per-feature attributes.

The canonical edge-accuracy field in this dataset is `EdgeAcc_m`. Copying a parent's value to its children does not establish that the value is appropriate for each resulting feature. Stage 02a retains supplied non-null editing values and only fills null values using its existing area-based defaults. It therefore does not automatically correct inherited edge accuracy after a split. The same caution applies to other attributes assessed for the original mapped feature, including the manually assigned `Attachment`.

The warning must explicitly name `EdgeAcc_m` as requiring review. An operator should correct the source geometry if the split is unintended. If the parts are genuine separate features, they should be mapped as separate Reef Edit records with individually assessed attributes. Do not edit the generated split output as the permanent correction. Rerun stages 01e, 02a and 02d after source changes.

Processing may continue with split parts so stage 02a can allocate identifiers. This permission is not an assertion that the parts or their copied attributes have passed manual review.

## Identifier and pipeline integration

Stage 01e does not allocate or copy final identifiers from a parent into its children as an allocation decision. Stage 02a remains responsible for `ReefID`, `PrevReefID` and provisional `ReefFID` assignment through its existing overlap, CODE and dominance rules.

`ReefID` is the official persistent reef identifier. `PrevReefID` records a historic association without asserting that the new polygon retains that official identity. `ReefFID` identifies a feature record in this dataset. Stage 02a proposes feature identifiers; stage 03 resolves their uniqueness across the regional inputs. `ReefID` may legitimately remain shared by several polygon records in the final dataset. Only `ReefFID` must be unique there, and neither field is guaranteed to identify one record unambiguously before stage 03. Dataset feature suffixes allocated in stage 03 are not new official GBRMPA reef identifiers.

Removing an old polygon and carrying its identity forward are separate decisions in stage 02a. An overlap can supersede an old boundary without passing the tests for a historic relationship. Meaningful candidates are identified using the existing sliver and overlap-share tests, or an explicit `CODE` relationship. A `Link` control point can establish a previous-ID relationship without awarding the official ID.

Candidates are grouped by old official identifier because multiple old polygons can share one `LABEL_ID`. A sole qualifying successor normally inherits it. Where successors compete, the largest candidate overlap must be at least three times the next-largest to inherit the identifier. Other qualifying children record the old identifier in `PrevReefID` and receive provisional feature identifiers. If none dominates, none automatically receives that official ID. The existing merge rule also determines which identifier, if any, a new feature may retain when it relates to several old identifiers. The [02a design](02a-patch-TS-GBR-Features_design.md) remains the authoritative definition of these rules and their exceptions.

Every part of a split coded source feature carries the same `CODE`. Stage 02a treats each as a forced `CODE` candidate for the old feature. The 3:1 dominance rule then decides whether one part inherits the official identifier, and the others record it in `PrevReefID`. This is the intended behaviour.

Clipping before allocation lets these rules operate on the marine components that will actually become L3 records. Exploding an already identified editing polygon afterwards would merely copy its ID fields into several rows. Making those rows' feature IDs unique would not resolve their official identity or historic lineage.

Change stage 02a's Reef Edit input to `working/{version}/01/Reef-Edit-clipped.shp`. Stage 02a must reset to a unique row index on reading, because its identifier maps are keyed by index. Its refreshed legacy input and Remove-Move source remain unchanged. This preserves the original old geometries used for move/remove matching, attachment calculation and historical comparison. No clipping is inserted into those supporting operations.

Clipping can remove an overlap previously used to link an editing polygon to an old feature. Existing `CODE` relationships remain available, but overlap-only relationships and `Link` points may change. Review the existing stage 02a identifier reports after regeneration. Resolve missing relationships through the established editing and control-point workflow, not through a new matching rule.

The intended execution order is stage 01d, stage 01e, stage 02a, then stage 02d before the national merge. Stages 02b and 02c remain independent regional preparation steps.

## Shared clipping functions

Stages 01e and 02d will use substantial shared geometry operations in [reef_utils.py](reef_utils.py), rather than duplicate the clipping algorithm. Its existing functions address L2 dissolution, seam repair and countable-reef clustering. They do not currently provide coastline subtraction. The existing buffering and simplification operations must not be used to hide clipping fragments.

Factor coastline preparation into a shared operation that reads and validates the polygon landmask, transforms it to EPSG:4283, validates the transformed geometry, subtracts the validated pier exclusions and builds its spatial index. Factor clipping of one single Polygon into another shared operation. It finds intersecting land with the spatial index, unions only that land, subtracts it and validates results without automatic repair. It returns the original polygon as one part when unchanged. For altered valid results it discards non-polygonal by-products and filters polygon parts using the minimum-area rule. Return the retained polygon parts and the number of removed fragments. The caller infers trim, split or removal from the retained-part count. No component relationship structure or point-contact analysis is required. Geometry failures must retain their processing step for reporting with the caller's source reference and must not be returned as successful clips. The operation must not mutate source data or silently recover by returning an original polygon after a failed subtraction. The minimum area is a parameter with a default of 100 m², measured in EPSG:3577.

Their final function names and return types can be chosen during implementation. Do not extract small expressions or introduce a general processing framework merely to share code. Process features sequentially.

Source selection, cay exemptions, source singlepart checks, file paths, warning or blocking policy, QA writing and output publication remain in the calling scripts. In particular, the shared clipping operation must not allocate IDs, decide whether a split is acceptable, or write a successful production output. Stage 01e warns on editing splits but blocks on multipart source records, complete removals, invalid geometry and failed geometry operations. Stage 02d also blocks on all legacy splits. Both consume the same geometric evidence.

## Failure handling and regeneration

Rebuild outputs on each run. Remove stale QA datasets owned by this stage, including their shapefile sidecars, so an absent QA layer means there are no current records. Invalidate this stage's previous primary output before processing; a failed run must not leave an old output available as though it had passed. Write the new primary output only after validation succeeds.

These stages are run in an editing loop with the outputs open in QGIS, so locked files are expected. If any owned output or sidecar cannot be deleted or written, stop with a nonzero exit status and print the affected path with a message such as "This file is probably open in QGIS or another program. Remove the layer or close the project, then rerun." Do not report this as a generic exception trace.

Announce each major step, including reading inputs, initial EPSG:4283 transformation and validation, building the coastline spatial index, clipping and writing each output. Report record counts as each step completes, the total removed-fragment count and the elapsed time at the end of the run. Do not add a progress callback or periodic clipping messages initially. Add more detailed progress only if an actual stage proves slow.

Collect split warnings and complete removals through the clipping loop, then write the applicable QA layers before reporting any removal gate failure. The final console summary must give the category, count, affected `RE_row` values, QA layers to load in QGIS and required source correction. Multipart or invalid inputs and failed geometry operations stop under the input-check and error-reporting rules above. For those failures, direct the operator to the source dataset using the console references rather than a diagnostic QA layer.

After editing Reef Edit, rerun stages 01e, 02a and 02d before stage 03. After changing the coastline, rerun both clipping stages and the intervening stage 02a. Do not reuse stale intermediate outputs.

## Planned validation

Synthetic tests will cover unchanged offshore features, coastal trimming, splits, boundary-only contact, cay exemptions, removal of fragments below 100 m² and of line or point by-products, and complete removal. Verify that sources with two or more polygon components block and a single-component MultiPolygon can be treated as a Polygon. Test areas below and above 100 m² without requiring an exactly equal projected area. Check that an unchanged small feature is not filtered, while an altered feature with only a below-threshold remainder is reported as removed. Check that every source attribute, including `CODE` and text `EdgeAcc_m`, survives clipping and explosion unchanged, that source references follow the conventions above, that QA areas and shares agree with exported geometry, and that main outputs contain only valid singlepart features. Check geometric equality for unchanged offshore features without asserting vertex counts or coordinate ordering. Do not introduce a feature datum round trip.

Capture console output to verify that editing splits produce an explicit `WARNING`, identify the review paths and request assessment of `EdgeAcc_m`. A split alone must not block publication, including parts touching only at a point. Complete removals, multipart source records, invalid geometry and failed geometry operations must block. Verify the removed-fragment count and that no fragments or invalid-geometry QA layers are written. Verify that a locked output produces the QGIS message. Test the shared clipping operations directly and exercise both calling stages against the same synthetic coastline.

An integration test will pass clipped editing parts through stage 02a. A dominant successor must retain the historic identifier under the existing 3:1 rule; the other qualifying children must receive the appropriate provisional and previous identifiers. With no dominant successor, no child may inherit the official identifier automatically. Check that `RE_row` and `RE_part` reach the stage 02a output and are absent from the stage 03 output. Stage 02a error messages and review layers need no tracking-field changes. Also test missing inputs, repeat runs and source-data immutability. Verify that invalid inputs and simulated invalid results or failed geometry operations stop without attempting repair and identify the source and processing step in the console.
