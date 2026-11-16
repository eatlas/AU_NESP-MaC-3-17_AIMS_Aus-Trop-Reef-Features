# Dataset creation workflow diagrams

## Status and deliverables

Specification revised on 3 November 2026. Both figures are implemented, including the subsequent layout revisions. An earlier single-figure version was implemented and reviewed, then superseded by these two figures. That earlier generator was renamed to `Old-Opus-A03-create-workflow-diagram.py`. It is not a reference for the current implementation.

Running `python A03-create-workflow-diagram.py` generates two figures.

| Figure | Output | Purpose |
|---|---|---|
| Overview | [figures/A03-dataset-creation-workflow.svg](figures/A03-dataset-creation-workflow.svg) | How the regional datasets are combined into the national dataset, enriched, and published. |
| GBR + TS update | [figures/A03-gbr-ts-update-workflow.svg](figures/A03-gbr-ts-update-workflow.svg) | How the updated GBR and Torres Strait mapping is created from the existing mapping and the new Reef Edits. |

The generator is independent of [A02-create-diagrams.py](A02-create-diagrams.py), which generates the identifier-method diagrams. It uses only the Python standard library and writes to `figures/` beside the script, regardless of the working directory. It does not read scientific source datasets. After writing both figures, it removes the superseded output `figures/dataset-creation-workflow.svg` if present.

Both figures are intended for A4 portrait pages in the project technical report. Each has a physical width of 160 mm and a viewBox width of 900 units. The height of each figure is set by its content, up to a maximum of 1240 units (about 220 mm). Neither figure is expected to need the full height. This specification includes a report-ready explanation and a proposed caption for each figure. The explanation is supporting report text, not text to be placed inside the figures.

## Why two figures

The single-figure version had to show the national flow and the detailed GBR and Torres Strait processing in the same space. The GBR + TS operations were spread across the page and did not read as one coherent update, and the crowding forced uneven box widths and several side columns. Separating the two allows the overview to have a clear downward flow with standardised boxes, and allows the GBR + TS update to be shown at a readable level of detail.

The overview shows `Update GBR + TS mapping` as a single high-level step. The second figure expands that step. The two figures share the input names `GBR + TS Features` and `Reef Edits`, while the overview's `GBR + TS update` outline identifies the scope of the detailed figure.

## Purpose and main message

The Australian Tropical Reef Features dataset combines existing regional mapping with new GBR and Torres Strait mapping. New mapping and interpretive boundary adjustments were confined to the GBR and Torres Strait. The regional datasets are prepared and merged, then supplemented with sovereignty, depth and external classification attributes. A simplified classification product is derived from the completed national dataset.

The overview must distinguish existing mapping, the new mapping contribution, processing, and published outputs. The GBR + TS update figure must not suggest that the satellite imagery automatically generated the Reef Edit boundaries. It must show that the edits are applied to, and largely retain, the existing mapping rather than replacing the whole regional dataset.

## Report-ready explanation

The Australian Tropical Reef Features dataset combines North and West Australian Features, Coral Sea Features, and the integrated GBR and Torres Strait Features dataset (Figure X). The GBR and Torres Strait mapping is updated with new and revised reef boundaries before the regional datasets are merged (Figure Y).

The GBR component of the integrated dataset is first replaced with the latest supplied GBRMPA GBR Features. The Torres Strait mapping is retained. This refresh provides the reference mapping against which the new GBR and Torres Strait edits are applied.

Boundary adjustments in this compilation were confined to the GBR and Torres Strait. The bulk of the modifications were in the inshore GBR, where reefs were comprehensively remapped. Offshore work focused on adding reefs missing from the original GBR mapping and correcting some large mid-shelf features previously mapped as reefs that were actually Halimeda banks. Updates outside the inshore GBR, including those in Torres Strait, were partial rather than comprehensive.

New and revised boundaries are recorded in the Reef Edit dataset. These polygons were digitised by interpreting Sentinel-2 All Tide and Low Tide composite imagery, Queensland Globe aerial imagery, and bathymetry. The bathymetric evidence includes the MultiRes-Bathy-EEZ_2024 composite. Its GBR and Torres Strait source surfaces include the Great Barrier Reef DEM 2020 at 30 m resolution and the Torres Strait DEM 2023 at 30 m resolution. These surfaces are constituent sources of the composite, not three separate bathymetry layers assembled by this project's processing scripts.

The Australian Coastline 50K landmask is used to clip the landward side of reef boundaries. In three cases, piers represented as land in the coastline crossed reefs extending beneath them. Clipping against these pier footprints would split the reef polygons. Manually defined exclusion polygons are therefore subtracted from the working landmask to remove the pier footprints before reef clipping. This preserves the reef beneath each pier without changing the source coastline dataset.

Reef Edit polygons are clipped to this landmask before integration. The clipped Reef Edit polygons replace any existing GBR or Torres Strait reef polygons they overlap. Reef Edit polygons in locations with no existing reef polygon are added as new features. Other existing reef polygons are retained unless explicitly moved or removed. Move, Remove and Link control points, together with codes recorded on replacement polygons, document explicit corrections and identifier relationships. These control points were digitised manually during the same interpretation as the Reef Edits. Source classifications on retained legacy features are crosswalked to the common Reef Boundary Type v0.4 classification.

ReefID provides a persistent reference to a reef over time, serving a similar role to its name. This is particularly important for unnamed reefs, which can be identified in policy documents and scientific research by their ReefID. Preserving existing identifiers where the relationship is clear maintains the connection between these references and the revised mapping.

Retained legacy features keep their existing ReefID. Clear replacements inherit the identifier through overlap matching or an explicit link using the old feature's code. For splits and merges, overlap is used to identify a dominant successor or constituent. Other recognised associations are recorded in PrevReefID, preserving the mapping history without claiming that the features have the same identity. A Link control point can explicitly preserve a previous identifier without transferring ReefID. Where identity remains ambiguous, the existing identifiers are recorded as PrevReefID rather than assigned as ReefID. New or ambiguous GBR identities are left for GBRMPA to determine.

A separate ReefFID uniquely identifies each polygon in the national dataset. All features without an assigned ReefID, including new features, receive a provisional identifier in ReefFID. These provisional identifiers provide unique polygon references within the dataset. They are not permanent reef identifiers and do not replace official ReefIDs.

The legacy reef boundaries were originally trimmed to an earlier coastline that contains occasional positional offsets and errors relative to the new coastline mapping. Some retained reef polygons therefore extend over land in the new landmask. These polygons are clipped again using the same landmask as the Reef Edits to align their landward boundaries with the new coastline. Where the new landmask cuts across a legacy reef polygon, clipping can split it into separate parts. Every legacy feature split by land clipping is manually reviewed and corrected by creating additional entries in Reef Edit. The processing is then rerun to incorporate these replacements before the national merge.

The North and West Australian mapping already used Reef Boundary Type v0.4, the classification chosen for the national dataset. No classification crosswalk was needed for this input. The Coral Sea mapping used an earlier version, Reef Boundary Type v0.3. A Coral Sea-specific crosswalk was therefore required to align its classes with v0.4. This crosswalk involved few changes, so it is not shown in the overview figure.

The Coral Sea mapping is supplied as separate Reefs and Cays and Atoll Platforms layers. The platforms are included in the national dataset to represent important shallow marine areas beyond the mapped coral reefs. Reef and cay footprints are removed from the platform polygons before the layers are combined. The remaining platform areas consist predominantly of soft sediment over the atoll-platform framework. These sediments support Halimeda and other algae and are biologically active. Although these areas are not Coral Reef, they are retained as Oceanic Platform so that the mapping includes these shallow sediment habitats.

The prepared regional datasets are then merged into one national layer, with dataset feature identifiers allocated or preserved as required.

Sovereignty attributes are assigned using the union of country land areas and Exclusive Economic Zones.

Bathymetric statistics are calculated using the MultiRes-Bathy-EEZ_2024 digital elevation model (DEM), with AusBathyTopo Australia 250 m 2024 as a fallback. These raster surfaces provide seabed elevations relative to mean sea level (MSL). EOT20 is a global ocean tide model used to predict sea-level variations caused by astronomical tides. A raster of the lowest predicted tide at each location over January 2021 to December 2025 is used to estimate the local offset between MSL and lowest astronomical tide (LAT). LAT represents the lowest water level expected from astronomical tides. The minimum over this finite prediction period is treated as an approximation to LAT.

Each DEM pixel is converted to an estimated LAT elevation by subtracting the local lowest predicted tide, expressed relative to MSL, from its MSL elevation. For example, a seabed elevation of -5 m MSL and a lowest predicted tide of -1 m MSL give an elevation of -4 m LAT, equivalent to a depth of 4 m below LAT. The adjustment is applied to individual pixels before calculating the polygon statistics because the tidal offset varies spatially.

Valid bathymetry values within each reef polygon are summarised by their 10th, 50th and 90th percentiles against MSL and estimated LAT. Values are stored as signed elevations in metres, with negative values below the reference level. The percentiles therefore describe the deeper, median and shallower elevations, respectively.

The main limitation of these estimates is the variable quality and spatial detail of the source bathymetry. Bathymetry is generally good over most of the GBR and Torres Strait, but is less reliable near the coast. Across most of the Coral Sea, it has insufficient detail to adequately represent the shallow portions of small patch reefs. In northern and western Australia, bathymetry is generally of low quality and often indicates the seabed surrounding a reef rather than the profile of the reef itself.

Existing depth categories, including those estimated manually from satellite imagery, are therefore retained rather than replaced by DEM-based estimates. The raster-derived statistics are provided alongside these categories as a separate source of depth information. Missing depth categories are assigned using feature rules and bathymetry.

The Reef Boundary Type v0.4 class, attachment and depth category are used together to crosswalk each feature to external classifications, including the Natural Values Common Language, Seamap Australia and Queensland Wetlands schemes.

The resulting full classification national dataset is the primary output. A separate simplified classification product joins touching parts within each broad Reef Boundary Type L2 class. Its bathymetric statistics are recalculated over the dissolved polygons using the same bathymetry and tide inputs, rather than aggregated from the source statistics. A membership table links the simplified polygons to the source features, so sovereignty and external classification attributes remain accessible through the full classification dataset. This derivative simplifies the spatial representation; it is not just an additional classification column and is not the countable-reef analysis.

## Proposed figure captions

**Figure X. Creation of the Australian Tropical Reef Features dataset.** Existing North and West Australian (NW) and Coral Sea (CS) mapping is combined with updated GBR and Torres Strait (TS) mapping, in which new Reef Edits are applied to the existing GBR and Torres Strait Features (Figure Y). The merged national dataset is supplemented with sovereignty, depth and external classification attributes. A simplified classification product is derived by joining touching features within each broad reef type class. The dotted outline marks the GBR and Torres Strait update shown in detail in Figure Y. Gold boxes show datasets created in this project.

**Figure Y. Update of the GBR and Torres Strait mapping.** The GBR component of the existing mapping is refreshed from the latest GBRMPA GBR Features. New and revised boundaries were digitised as Reef Edits from satellite imagery, aerial imagery and bathymetry, together with control points for explicit corrections. Inshore GBR reefs were comprehensively remapped; updates elsewhere in the GBR and Torres Strait were partial. Reef Edits are clipped to the coastline and replace the existing features they overlap. Overlap matching and explicit control points preserve existing ReefIDs where the relationship is clear. Retained legacy features are clipped to the same coastline.

## Overview figure

### Content

The overview has four regional source boxes in a top row. `North and West Australian Features`, `Coral Sea Features` and `GBR + TS Features` are existing mapping. Expand NW and CS in the visible source labels for readability, using line breaks within the standard column width. `Reef Edits` is the new mapping and uses the gold new-dataset style. A short subordinate line such as `New GBR + TS mapping` may be added to `Reef Edits` if it fits.

| Branch | Process | Inputs | Meaning |
|---|---|---|---|
| NW | `Prepare attributes` | North and West Australian Features | Prepare attributes for the national schema. Do not imply that this project remaps the NW boundaries. |
| CS | `Combine reefs and platforms` | Coral Sea Features | Combine the Reefs and Cays and Atoll Platforms layers without overlapping footprints, retaining the platform sediment areas. |
| GBR + TS | `Update GBR + TS mapping` | GBR + TS Features, Reef Edits | The whole of Figure Y, shown as one process. |

Enclose `GBR + TS Features`, `Reef Edits` and `Update GBR + TS mapping` in a dotted outline with the short label `GBR + TS update`. The outline marks the part of the overview that Figure Y expands. The label repeats the name of the detailed figure rather than a figure number, because the SVG does not carry report numbering. The caption makes the link explicit. The outline must enclose only these three boxes and their connectors. The connector from `Update GBR + TS mapping` to the merge leaves the outline. Leave a clear gap between the outline and the neighbouring CS boxes so that the CS branch does not appear to be part of the update.

The overview deliberately omits the refresh from the latest GBRMPA GBR Features, coastline clipping, correction controls, identifier preservation and the Reef Boundary Type classification crosswalk. The NW input needed no crosswalk and the CS crosswalk involved few changes. The GBR + TS crosswalk is shown in Figure Y, where it matters more. Omitting the crosswalk from both the NW and CS branches keeps its treatment consistent within the overview.

All three regional processes meet at one process labelled `Merge regional datasets`. A single downward spine then follows.

| Process label | Side input | Main result |
|---|---|---|
| `Assign sovereignty` | `Country + EEZ union, 2024` | Country associations and area shares. |
| `Add depth statistics and categories` | Bathymetry and tides box | MSL and LAT statistics, with missing depth categories completed. |
| `Add external classifications` | None | Subordinate line `NVCL / Seamap / Qld Wetlands`. |
| Product: `Australian Tropical Reef Features` with subordinate line `Full classification` | | Primary output, gold product style. |
| `Dissolve by L2 class` with subordinate line `Recalculate depth statistics` | Bathymetry and tides box | Dissolved polygons. |
| Product: `Australian Tropical Reef Features` with subordinate line `Simplified classification` | | Derived output, gold product style. |

The external classification stage is labelled `Add external classifications` rather than `Add classification crosswalks`. This avoids confusion with the Reef Boundary Type crosswalk that is omitted from the overview. It has no separate input box because the stage label and scheme line carry the meaning.

The bathymetry and tides box lists `MultiRes-Bathy-EEZ_2024`, `AusBathyTopo Australia 250 m 2024 (fallback)` and `EOT20 tides`, on as many lines as needed. It appears once, on the left of the spine. One connector leaves its top edge, turns right and enters `Add depth statistics and categories` from the left. The other leaves its bottom edge, turns right and enters `Dissolve by L2 class` from the left. Neither connector crosses spine boxes or other connectors. The 250 m surface is a fallback, not an equal-weight blend.

The membership table is described in the report text and caption rather than in the product label. Do not add the A05 countable-reef analysis, regional statistics, preview maps or animations.

### Layout

Use a strict top-to-bottom flow. Place the four source boxes in a single row of equal-width columns. Place the NW and CS processes directly below their sources. Place `Update GBR + TS mapping` below `GBR + TS Features` and `Reef Edits`, spanning both columns so that both sources feed straight down into it. Place the dotted `GBR + TS update` outline around these two columns, with its label in the top margin of the outline so that it does not collide with the box text. `Merge regional datasets` spans the full width of the regional columns. Each regional process feeds straight down into it.

Below the merge, the spine processes and products are stacked in one centred column. Put `Country + EEZ union, 2024` and the bathymetry and tides box on the left, so their inputs read left to right. The bathymetry and tides box should be positioned so that its connector to the dissolve stage is short and clear. Set `Australian Tropical Reef Features` in bold in both gold product boxes, with the classification subtitle in regular weight.

## GBR + TS update figure

### Content

This figure expands `Update GBR + TS mapping` from the overview. It needs no group container or scope annotations, because the whole figure is the update. The statements about comprehensive inshore remapping and partial updates elsewhere belong in the caption and report text, not in the figure.

Existing mapping inputs and the refresh process are shown as follows.

| Element | Style | Notes |
|---|---|---|
| `GBR + TS Features` | Input | Same label as in the overview. |
| `Latest GBRMPA GBR Features` | Input | Feeds the refresh. |
| `Refresh GBR mapping` with subordinate lines `Retain TS mapping` and `Standardise legacy classes` | Process | Replace the GBR component with the latest GBRMPA GBR Features and keep the TS component. Apply the RB classification crosswalk to the legacy mapping, not the Reef Edits. This high-level box groups the refresh in 01d with legacy classification preparation in 02a. |

The new mapping uses two evidence boxes, headed `Imagery` and `Bathymetry`, each feeding `Digitise edits and controls`, with subordinate line `Manual interpretation`. The imagery box contains the two Sentinel-2 products and Queensland Globe aerial imagery. The bathymetry box contains the composite and its nested regional DEM provenance. Digitising produces two gold new datasets, `Reef Edits` and `Move / Remove / Link + CODE`, each with its own connector. Both are manually digitised. The evidence arrows must terminate at digitising, not at an automatic polygon-extraction process.

| Evidence label | Treatment |
|---|---|
| S2 All Tide | Imagery used for manual interpretation. |
| S2 Low Tide | Imagery used for manual interpretation. |
| Queensland Globe aerial imagery | Aerial evidence used for manual interpretation. |
| MultiRes-Bathy-EEZ_2024 | Bathymetric evidence used for manual interpretation. |
| GBR DEM 2020, 30 m | Nested provenance within the composite bathymetry source. |
| Torres Strait DEM 2023, 30 m | Nested provenance within the composite bathymetry source. |

The two regional DEMs are written as indented subordinate lines below `MultiRes-Bathy-EEZ_2024`, with a thin bracket or rule to show nesting. They have no separate arrows. The composite is an existing external dataset, not an output made here from those two DEMs. MultiRes-Bathy-EEZ_2024 appears in this figure only as interpretation evidence. Its use for depth statistics is shown in the overview.

The integration chain must preserve this dependency order.

| Process label | Inputs and output |
|---|---|
| `Clip Reef Edits to coastline` | Reef Edits and the coastline landmask produce the clipped editing polygons. |
| `Integrate edits`, subordinate line `Preserve ReefIDs` | Refreshed and classification-standardised legacy mapping, clipped edits and correction controls produce the patched regional mapping. The Reef Edits already use the correct classification. |
| `Clip retained legacy features` | Trim only surviving legacy marine features. Carry the already clipped edits through unchanged. |

The chain ends at `Updated GBR + TS Features`, which is the input to the national merge. Use the ordinary input dataset style for it, since it is an intermediate dataset rather than a published product.

Show `Coastline50k landmask` as the land-clipping input to both clipping processes. Prefer a single box with two connectors, consistent with the reused bathymetry box in the overview. Repeat the box only if a single box would force a connector to cross the main flow. Keep the pier exclusions in the report explanation only.

`Move / Remove / Link + CODE` is produced by digitising and feeds integration directly, without coastline clipping. The label is shorthand: Move and Remove points lie on old features, Link points lie in shared areas, and CODE is an attribute on a replacement polygon. Show `RB classification crosswalk` as an ordinary input to `Refresh GBR mapping`, rather than to integration.

Omit the legacy-split review and rerun as a feedback arrow. It is described in the report text. Do not split integration into a long chain of identifier operations. Detailed rules remain in the identifier-method diagrams.

### Layout

Use two upper columns that converge into one lower column. The left column holds compact, side-by-side `GBR + TS Features` and `Latest GBRMPA GBR Features` boxes feeding straight down into `Refresh GBR mapping`. Place the RB crosswalk between those connectors above the refresh. The right column holds side-by-side `Imagery` and `Bathymetry` boxes feeding `Digitise edits and controls`, with `Reef Edits` and `Move / Remove / Link + CODE` side by side below it.

`Clip Reef Edits to coastline` sits below `Reef Edits`. `Integrate edits` spans both columns and receives the refreshed mapping, the clipped edits and the correction controls from above. The refreshed mapping follows a direct vertical connector to integration as the main flow. Place the coastline input to edit clipping beside, rather than across, that flow. The controls connector runs straight down beside `Clip Reef Edits to coastline` without touching it. `Clip retained legacy features` and `Updated GBR + TS Features` continue the downward flow.

## Common design rules

Use standardised box sizes. Within each figure, boxes with the same role and position share one width: regional source columns, spine processes and products, and side inputs each have a standard width. Within each role and layout tier, use a shared height sufficient for the longest label, even if a neighbouring box has fewer lines. Different roles and tiers may use different heights. Choose label wording and line breaks to fit the standard sizes rather than resizing individual boxes. Boxes that must span columns, such as `Update GBR + TS mapping`, `Merge regional datasets` and `Integrate edits`, span whole columns exactly.

Prefer straight vertical connectors along the main flow. Side inputs use short horizontal connectors. Where a reused box feeds two stages, route its connectors through a clear corridor. Connectors must not cross each other, touch unrelated boxes or pass through text. Provide clear gaps between groups and between parallel connectors.

The figures communicate the overall process. They carry no title, step numbers or appendix references. The Word captions supply the titles, and the Methods text provides the cross-references to the detailed appendices.

Aim for approximately 150 visible words or fewer in each figure. Use short labels and explicit line breaks. Avoid paragraphs inside boxes, implementation filenames, paths, release-specific feature counts and step-by-step validation rules. At the 900-unit width, ordinary labels must be at least 18 units, equivalent to approximately 9 pt at 160 mm insertion width. Use 20-unit bold text for process titles. Increase the allocated space or shorten wording before reducing text below the minimum.

## Styling

The palette follows the supplied presentation guidance. The values are visual approximations, not verified brand specifications.

| Element | Style |
|---|---|
| Ordinary text and headings | Deep blue `#005A9C`. |
| Process | Cyan `#00A3DF` rounded rectangle, thin blue-grey `#354054` outline, centred white text. Bold title line, regular subordinate lines. |
| Input dataset | White box with a thin blue-grey `#354054` outline, small corner radius, and deep-blue text. |
| New dataset created in this project | Warm off-white `#FFF8ED` fill, gold `#C89600` outline, deep-blue text. Used only for `Reef Edits`, `Move / Remove / Link + CODE`, and the two `Australian Tropical Reef Features` products. The national product names use 20-unit bold text, with regular 18-unit classification subtitles. |
| Connector | Thick pale blue `#8CB6D6`, obvious arrowhead, orthogonal. |
| Overview `GBR + TS update` outline | Dotted blue-grey `#354054` rounded rectangle, about 1.5 units wide, no fill. Label in deep blue, regular weight, at least 18 units. |
| Minor logical divider, if needed | Dotted grey line. |

Gold therefore has one meaning in both figures: data created for this dataset. It is not used for group containers, outlines or headings. Intermediate datasets such as `Updated GBR + TS Features` use the input style.

Blue should dominate. Use no decorative sidebar, contour lines, gradients, shadows or stock icons. Use Arial or a compatible sans-serif font. Match the simple, editable SVG approach used by [A02-create-diagrams.py](A02-create-diagrams.py): presentation attributes, explicit geometry and text, and no CSS classes, filters, pattern fills or clip paths. Draw each connector as one polyline with a separate polygon arrowhead so that connectors and text stay editable in PowerPoint.

## Processing traceability

This table supports verification and the report methods. It is not intended to appear in the figures.

| Figure element | Figure | Implementation evidence |
|---|---|---|
| Refresh GBR mapping: GBR refresh and TS retention | Y | [01d-refresh-TS-GBR-Features.py](01d-refresh-TS-GBR-Features.py). |
| Refresh GBR mapping: standardise legacy classes using the RB crosswalk | Y | [02a-patch-TS-GBR-Features.py](02a-patch-TS-GBR-Features.py). Grouped with refresh in the figure; implemented in 02a, not 01d. Reef Edits already use the correct classification. |
| Reef Edit clipping and pier exclusions | Y | [01e-clip-TS-GBR-reef-edit.py](01e-clip-TS-GBR-reef-edit.py) and [its specification](01e-clip-TS-GBR-reef-edit-spec.md). |
| Integrate edits: replacement, controls and identifier history | Y | [02a-patch-TS-GBR-Features.py](02a-patch-TS-GBR-Features.py). |
| Accepted legacy coastline clipping | Y | [02d-clip-TS-GBR-legacy.py](02d-clip-TS-GBR-legacy.py) and [its specification](02d-clip-TS-GBR-legacy-spec.md). |
| S2 All Tide and Low Tide products | Y | [01b-download-sentinel2.py](01b-download-sentinel2.py). |
| Bathymetry downloads and historical source references | X, Y | [01a-download-input-data.py](01a-download-input-data.py). |
| Update GBR + TS mapping, as a whole | X | Steps 01d, 01e, 02a and 02d above. |
| NW attribute preparation | X | [02b-patch-NW-Aus-Features.py](02b-patch-NW-Aus-Features.py). |
| CS platform treatment and source-specific class crosswalk | X | [02c-patch-CS-Features.py](02c-patch-CS-Features.py). The crosswalk is not shown. |
| National merge and feature identifiers | X | [03-merge-TS-GBR-CS-NW.py](03-merge-TS-GBR-CS-NW.py). |
| Country and EEZ source | X | [04-add-country-attribute.py](04-add-country-attribute.py). |
| DEM statistics, tide conversion and depth categories | X | [05-add-depth.py](05-add-depth.py) and [reef_utils.py](reef_utils.py). |
| Classification-table location and validation | X, Y | [crosswalk_utils.py](crosswalk_utils.py). |
| External classifications and full classification product | X | [06-crosswalk.py](06-crosswalk.py). |
| L2 dissolution, depth recalculation and membership output | X | [08-make-RB_Type_L2.py](08-make-RB_Type_L2.py) and [its specification](08-make-RB_Type_L2-spec.md). |

The extent and focus of the remapping, the use of Queensland Globe imagery for digitising, and the identification of the two regional DEMs within the composite are author-supplied provenance. The code confirms that the current pipeline uses the composite, with the older direct regional downloads commented out. It does not independently establish the completeness of manual remapping or every surface used during interpretation.

Retain the author's requested `GBR DEM 2020, 30 m` display label. The historical download comments mix a 2017 citation with a 2020 download filename. Check the original metadata before assigning a formal bibliographic citation in the report; do not silently substitute 2017 for the requested 2020 label.

## Deliberate simplifications

The figures describe the production path, not the development-only merge bypass. Quality checks, review layers and iterative corrections are part of the processing but do not require individual decision diamonds or feedback arrows.

The overview collapses the GBR + TS processing into one step and omits the Reef Boundary Type crosswalk for all regional branches. The NW and CS branches show their preparation for this compilation, not how those datasets were originally mapped. CS platform subtraction separates mapped reef and cay footprints from the remaining platform sediment areas; it is not a remapping programme.

In the GBR + TS figure, pier exclusions, cay exemptions, fragment thresholds, identifier allocation thresholds, coastline tolerances, coordinate transformations and field-length adjustments are omitted. Inshore masks used for metadata assignment are not a separate source. These details belong in the methods and implementation documentation.

The simplified classification product remains downstream of the completed full classification dataset. Joining touching parts does not mean merging reefs separated by water, applying a minimum reef size or counting named reefs.

## Acceptance checks for implementation

Before delivery, verify the processing graph of each figure against the traceability table.

In the overview, all three regional branches must reach the national merge. Expand NW and CS in the source labels. `GBR + TS Features` and `Reef Edits` must both feed `Update GBR + TS mapping`, and the dotted `GBR + TS update` outline must enclose exactly these three boxes. Sovereignty, bathymetry and tides must feed their stages from the left. The single bathymetry and tides box must feed the depth stage from its top and the dissolve stage from its bottom. The simplified classification product must follow the full classification product. Both gold product names must be bold, with regular-weight subtitles. No Reef Boundary Type crosswalk box may appear.

In the GBR + TS figure, the two legacy mapping inputs must sit side by side and flow down into the refresh, which must retain TS mapping and receive the RB crosswalk. The refresh must connect directly down to integration. Edits must be clipped before integration, while legacy clipping must follow it. Every listed interpretation source must be visible in the separate Imagery and Bathymetry boxes, and the regional DEMs must read as constituents of the composite. Both evidence boxes must feed digitising. Digitising must produce both `Reef Edits` and `Move / Remove / Link + CODE`. Only `Reef Edits` passes through coastline clipping. Correction controls must feed integration, but the classification crosswalk must not. The chain must end at `Updated GBR + TS Features`. Scope annotations about inshore and partial remapping must not appear in the figure.

For both figures, check that the generated XML is valid, labels fit their standard boxes, text does not overlap, connectors avoid unrelated boxes and each other, and nothing extends outside the canvas. Check that boxes with the same role share a width. Only the four new datasets use the gold style. Inspect the rendered figures at their intended report size, not only zoomed in. Confirm that the identifier diagrams remain unchanged.

[tests/test_workflow_diagram.py](tests/test_workflow_diagram.py) checks both figures. Each figure exposes its own nodes and edges so that the tests can check the processing graph, XML validity, visible word count, minimum font size, standard box widths, gold-style usage, connector routing and deterministic generation. Layout checks cover left-side inputs, top and bottom bathymetry ports, bold product names, separate evidence sources and the direct legacy flow. Rendered text fitting and report-scale inspection complement these structural checks.
