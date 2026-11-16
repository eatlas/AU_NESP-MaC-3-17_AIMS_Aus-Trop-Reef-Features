# GBR Features source reef area

## Purpose

Implemented on 9 November 2026 in [A08-gbr-features-reef-area.py](A08-gbr-features-reef-area.py), with tests in [tests/test_gbr_features_reef_area.py](tests/test_gbr_features_reef_area.py).

Calculate source-record counts and areas from the GBR Features dataset downloaded on 3 September 2026, within the GBR Analysis-region. Progressively include `Reef`, `Rock` and `Sand` because their inclusion in Hopley's historical area estimate is uncertain.

Also apply A05's countable-reef rules to the same source. The aim is to show what the GBR reef count would be under the criteria used for the national dataset's countable coral reefs in the GBR (Appendix B, Table B.2). This separates the effect of the counting rules from the effect of the remapping.

## Input and output

Run from the repository root in the `AusTropReef` environment. Read `version` and `in_3p_path` from [config.ini](config.ini).

| Resource | Path |
| --- | --- |
| Original GBR Features source ([processing reference](01d-refresh-TS-GBR-Features.py)) | `data/{version}/in-3p-mirror/GBRMPA-GBR-Features/Great_Barrier_Reef_Features.shp` |
| Analysis regions ([usage reference](A07-gbr-ts-remap-stats.py)) | `{in_3p_path}/nesp-3-17-analysis-regions/analysis-regions.shp` |
| Current A05 regional statistics | `data/{version}/out/stats/Aus-Trop-Reef-Features_Region-stats_{version}.csv` |
| Proposed script | `A08-gbr-features-reef-area.py` |
| Markdown results | `data/{version}/out/stats/A08-gbr-features-reef-area_{version}.md` |

Read the full original source, then clip to the Analysis-region polygons with `subregion` equal to `GBR`. Do not filter on `LABEL_ID`. The source includes Torres Strait features with `99-*` labels, but the label is not a reliable regional key. No `99-*` area falls inside the GBR region, while some non-`99-*` records fall in Torres Strait and Temperate East. Do not add Torres Strait Features or download another release. Create the output folder if it does not exist.

## Source dataset provenance

Identify the source snapshot using the following author-supplied download and portal metadata, rather than calling it the "latest" version:

| Item | Value |
| --- | --- |
| Dataset / provider | Great Barrier Reef Features / Great Barrier Reef Marine Park Authority (GBRMPA) |
| Source | https://reef-geohub-ext-geohubgbrmpa.hub.arcgis.com/datasets/816f4d747cd94d84acfd924b27f581d8_64/about |
| Downloaded | 3 September 2026 |
| Data Updated | 18 June 2025, 07:45:47 GMT+10 |
| Info Updated | 10 November 2025, 13:20:49 GMT+10 |
| Published Date | 23 May 2025, 02:53:31 GMT+10 |
| Portal record count | 5,362 |
| Licence | CC BY 4.0 |

No numbered source release has been supplied. Keep these source dates separate from the national dataset `version` and report generation time.

## Calculation

Report three cumulative selections using exact `FEAT_NAME` values:

| Selection | Included values |
| --- | --- |
| Reef | `Reef` |
| Reef + Rock | `Reef`, `Rock` |
| Reef + Rock + Sand | `Reef`, `Rock`, `Sand` |

Processing steps:

1. Check the observed source record count against the portal count. Report it, and print a warning rather than stopping if the two differ.
2. Select the records for each class. Stop if a selected geometry is null, empty or not a Polygon/MultiPolygon.
3. Repair invalid selected geometries with `shapely.make_valid` in the source CRS, as in [01d-refresh-TS-GBR-Features.py](01d-refresh-TS-GBR-Features.py).
4. Reproject to GDA94 / Australian Albers (EPSG:3577), matching A05 and A07. The source CRS is GDA2020 (EPSG:7844). Using GDA2020 Albers (EPSG:9473) instead changes the total by less than 0.001 km2.
5. Repair any geometry made invalid by projection, again with `make_valid`.
6. Dissolve the GBR Analysis-region polygons and clip each selected record to the result.
7. Calculate each clipped record's area in km2 from its geometry and sum without intermediate rounding.
8. Count source records with positive clipped area. A MultiPolygon remains one record, and a record that crosses the region boundary counts once and contributes only its area inside the region.

Repair is needed because many source `Reef` records store their rings in reverse. In 432 records the reef outline is stored as an interior ring and the enclosed island as the exterior ring. Unrepaired, these records have negative area, and `buffer(0)` deletes the reef entirely. Another 120 records nest island outlines as extra exterior rings inside the reef outline. `make_valid` restores the reef outline and cuts the islands out as holes. Reading the shapefile with GDAL `OGR_ORGANIZE_POLYGONS=DEFAULT` produces the same total. Do not use `buffer(0)` or outer rings only. Reef area therefore excludes island and cay areas enclosed by reef outlines.

For the summed-area selections, do not dissolve or explode records, buffer, subtract overlaps, use stored area attributes or apply A05's size and counting rules. Repaired `Reef` records do not overlap one another, but the results are still summed record areas, not unique spatial footprints.

Stop with an explicit diagnostic if:

- the source or Analysis regions have no CRS;
- `FEAT_NAME` or `subregion` is missing;
- there is no `GBR` subregion, or the dissolved region is invalid or empty;
- there are no `Reef` records;
- a repaired geometry is empty or contains non-polygonal parts;
- a calculated area is non-finite or a pre-clip area is non-positive.

Do not silently discard records or geometry parts. An absent `Rock` or `Sand` class contributes zero.

Repair diagnostics: for each selection, report the number of records repaired, grouped by `shapely.validation.explain_validity` reason without coordinates. Also report the total unclipped Albers area of the repaired records before and after repair. Clipping invalid geometries can raise topology errors, so the before figure is computed from the raw geometry without clipping and can be negative.

## Countable-reef comparison

Apply A05's countable-reef rules to the repaired, projected and unclipped source records, treating `Reef` as Coral Reef and `Rock` as Rocky Reef. `Sand` is not a reef class and is excluded. Cluster the whole source rather than the clipped GBR records, as A05 clustered the national dataset, so groups crossing the GBR boundary are formed in the same way.

Report the GBR count and area for each type at four stages, so the separate effects of the size and separation criteria can be seen:

| Stage | Units |
| --- | --- |
| Source records | Individual repaired records |
| Size only | Records with effective width of at least 100 m |
| Separation only | Groups of same-type records whose 50 m buffers join, with no size filter |
| Countable reefs (A05 rules) | Separation groups with effective width of at least 100 m |

Use `cluster_countable` from [reef_utils.py](reef_utils.py) with its default 50 m buffer and 100 m minimum width. Use `drop_small=False` for the separation-only stage and filter its `EffWidth_m` for the countable stage. Effective width is the diameter of a circle with the same area.

Assign counts as A05 does for Analysis-regions v1. Cut each unit by the Analysis-region polygons, dissolved by `subregion`. Treat a piece as a sliver if a −5 m buffer leaves it empty. Count each unit once, in the region holding its largest non-sliver piece. If every piece of a unit is a sliver, use its largest piece. Units outside all regions are not counted in the GBR. GBR area is the clipped area of every unit intersecting the GBR region, including units counted elsewhere, matching A05's area allocation.

The source-record stage uses this largest-piece rule, so its count can differ from Table 1, which counts every record with positive area in the GBR.

Show reference figures in a separate table: Hopley's Gazetteer count of 2,904 and GIS count of 3,703, and A05's current GBR countable coral and rocky reefs and areas from Table B.2. Read the latter from the A05 regional statistics CSV, selecting the single non-near GBR row in Analysis-regions v1. Stop if that row is missing or duplicated, or its counts and areas are invalid. Do not hard-code national reference figures. Regenerate stage 08 and A05 from the same national build before running A08, and record the CSV path in the report.

## Output

Write a short Markdown report with one row per cumulative selection and columns for source-record count, area (km2, six decimals), signed difference from 24,081 km2 (one decimal), and percentage difference (two decimals). Calculate differences from unrounded totals. Print these results and the output path to the console.

Include the source provenance above, observed total input records, script name, national dataset version, generation time, repository-relative input paths, source and calculation CRSs, the calculation rules, the repair diagnostics and the countable-reef comparison.

For context, also report the repaired `Reef` area that the clip excludes, split into the Torres Strait region, all other regions combined, and area outside all regions. Use existing Markdown conventions without new dependencies. No CSV, spatial output or intermediate files are needed.

## Historical interpretation

Include these historical reference figures:

| Hopley et al. (2007) source | Discrete reef features | Reef area (km2) |
| --- | ---: | ---: |
| Gazetteer | 2,904 | 20,055 |
| GIS | 3,703 | 24,081 |

The historical dataset and calculation method are unavailable. Numerical agreement does not establish which classes Hopley included or reproduce the historical method. The 2,904 Gazetteer figure has no documented inclusion criteria, although it became the de facto GBR reef count. The 3,703 GIS figure is a feature count with no size or separation criteria. Source-record counts are not Hopley's discrete-reef counts or A05's countable-reef counts.

A05 reports 3,759 countable coral reefs and 23,727.9 km2 of countable coral reef area in the GBR, from the national dataset after remapping and reclassification. A05 counts each countable reef in the region holding its largest piece and clips its area among regions, as the countable-reef comparison here does. A05's area excludes groups narrower than 100 m effective width. The difference between the A05 figures and the countable figures for GBR Features estimates the combined effect of the remapping under identical counting rules. This calculation alone cannot split that effect into reef additions, false-reef removals, sand-bank corrections or rocky-reef reclassification.

The [Coral Sea report, "Lessons from the Great Barrier Reef"](paper/02-structure/reference/Lawrey-et-al_2026_Coral-Sea-mapping-project-report_DRAFT.md#lessons-from-the-great-barrier-reef) provides count-history context, including the persistence of the 2,904-reef figure despite later mapping improvements. It does not resolve the historical area-class inclusion. Discussion drafting is separate from this script.

Reference: Hopley, D., Smithers, S. G., & Parnell, K. (2007). *The geomorphology of the Great Barrier Reef: Development, diversity and change*. Cambridge University Press. https://researchonline.jcu.edu.au/1554/
