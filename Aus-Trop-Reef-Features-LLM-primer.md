# Primer - Australian Tropical Reef Features dataset

This primer provides context for writing analysis code against the Australian Tropical Reef Features dataset. It describes the current build, output products, attributes and main limitations. Consult the [repository README](README.md) for reproduction instructions and the [Reef Boundary Type primer](Reef-boundary-type-scheme-LLM-primer.md) for classification definitions.

## Primer version 0.13

Updated for preparation of national release `v1-0`. The [configuration](config.ini) selects national version `v1-0`, North and West Australian Features `v1-2`, and Coral Sea Features `v1-2`. Configuration and local outputs do not confirm that a release has been published. Check the [metadata record](https://doi.org/10.26274/4RRW-RR88) and [download directory](https://nextcloud.eatlas.org.au/apps/sharealias/a/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features) for availability and the citation for the version used.

The [v1-0 A01 summary](data/v1-0/out/stats/A01-summary-stats_v1-0.md) records **25,257 source feature polygons**. At L2, these include 16,738 Coral Reef and 6,043 Rocky Reef records. A01 reuses stage 08's dissolved L2 polygons: 15,290 Coral Reef polygons and 5,845 Rocky Reef polygons. Neither source nor dissolved polygon counts are counts of named reefs or A05 countable reefs. The historical `v0-1` layer contained 21,832 polygons.

## What this dataset is

The dataset is a national scale compilation and standardisation of tropical reef features across Australia. It combines mapping of coral reefs, rocky reefs and sedimentary banks across the Indian Ocean, Timor Sea, Gulf of Carpentaria, Torres Strait, Great Barrier Reef and Coral Sea. It supports national environmental accounting, marine habitat mapping, marine park planning, Traditional Owner sea country mapping and environmental impact assessment.

The mapping targets reefs shallower than about 30 m on the continental shelf and about 60 m in oceanic waters. Associated features, including deeper oceanic platforms, may also be present. Features outside the Australian EEZ are included where relevant. Sovereignty attributes support filtering, but the polygons are not clipped to the EEZ.

## Provenance and source versions

The current national build combines the following sources:

| Source | Treatment in the national build |
| --- | --- |
| GBRMPA Great Barrier Reef Features | Stage 01d replaces the stale GBR portion of the 2016 integrated layer with the mirrored current GBRMPA source. Stages 01e, 02a and 02d apply manual corrections, identifier attribution and coastline trimming. |
| Torres Strait Features, Lawrey and Stewart (2016) | Stage 01d retains the Torres Strait records from the integrated source. They then pass through the same correction and clipping workflow as the GBR records. |
| Coral Sea Features, Lawrey and Bycroft (2025a), configured `v1-2` | Stage 02c standardises Reefs and Cays and Atoll Platforms using the Coral Sea-specific crosswalk column. Source `Very high` and `High` confidence values become `High`. |
| North and West Australian Features, Lawrey and Bycroft (2025b), configured `v1-2` | Stage 02b standardises source attributes and carries identifiers into the national schema. |
| Australian Coastline 50K 2024, V1-1 split layer | Used to trim edited and retained legacy TS-GBR features. Manually mapped pier exclusions remove elevated pier footprints from the working landmask. |
| Flanders Marine Institute (2024), EEZ land union v4 | Stage 04 assigns sovereignty and area shares. |
| Flukes (2024), Multi-resolution bathymetry composite; Geoscience Australia (2024), AusBathyTopo 250 m | Stage 05 derives elevation statistics and missing depth classes. |
| Lawrey (2025), EOT20 tidal statistics | Lowest Predicted Tide (LPT) provides the MSL-to-LAT adjustment for bathymetry. |

GBRMPA refresh retains both mainland-associated `99-000` records but excludes other `99-*` records that overlap Torres Strait coverage. The refreshed source is transformed to GDA94. Current GBRMPA names and identifiers do not imply that all source boundaries have been remapped recently.

Manual corrections are stored in versioned Reef Edit polygons and Reef Remove-Move points, not the historical `Complete-GBR-ExtraFeatures` and point-override workflow. Stage 02a handles Move, Remove and Link instructions, overlap replacements and retained source features. See the [patching design](02a-patch-TS-GBR-Features_design.md) and [identifier review guide](02a-PrevReefID-review-guide.md). The older [v0-1 patching script](02a-patch-TS-GBR-Features_v0-1.py) is historical reference only.

## Spatial scale and expected accuracy

The regional source mapping was generally prepared for use at about 1:250,000. Earlier assessments described typical 90th percentile boundary errors near 100 m for Coral Sea, Torres Strait and north and west Australian mapping. Retained legacy GBR boundaries can be hundreds of metres from their true position, with some errors exceeding 1 km. Manual remapping improves many inshore areas but does not establish uniform accuracy across the GBR.

Use the per-feature `EdgeAcc_m`, `EdgeSrc`, `FeatConf` and `TypeConf` attributes rather than assigning one accuracy to the whole dataset. Depth classes are indicative. DEM resolution and incomplete coverage limit their accuracy, particularly for small features. A single class cannot describe internal depth variation within a large polygon.

## Conceptual model and classification

Polygons represent reef features at the scale of geomorphic units, not individual coral colonies, named places or uniform habitat patches. A single reef structure may be split into active coral reef and sand-dominated reef flat polygons. For a broader geomorphic footprint, combine the relevant L3 subtypes using `RB_Type_L2`. Do not equate source polygon counts with counts of separate reefs.

The Reef Boundary Type v0-4 classification is hierarchical. `RB_Type_L3` is the detailed geological and ecological class. `RB_Type_L2` groups coral reef subtypes, rocky reef subtypes and other broad classes. `RB_Type_L1` separates Reef, Sediment, Land and Other. `Attachment`, `DepthCat` and `DepthCatSr` provide related context. Definitions, including Coral Reef Bank, are in the [classification primer](Reef-boundary-type-scheme-LLM-primer.md) and `Reef-Boundary-Classification-v0-4.pdf` supplied with the dataset documentation.

Oceanic Platform represents the platform remaining outside separately mapped reefs. It maps to Sediment at L2, not Coral Reef Bank. Stage 02c uses `CS_RB_Type_L3_v0-3` in the configured crosswalk because the NW source's `Atoll Platform` has a different meaning. Oceanic Platform does not imply absence of lagoon vegetation. Use the separate Coral Sea vegetation mapping when that distinction matters.

## Output products and location

The local build writes to `data/{version}/out/`:

| Product | Relative path under `out/` | Interpretation |
| --- | --- | --- |
| Full classifications, stage 06 | `full-classes/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp` | Source polygons with the full schema described below. Use this for identifier, sovereignty and detailed classification analyses. |
| National L2 polygons, stage 08 | `simp-classes/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_L2_{version}.shp` | Cleaned, dissolved singlepart polygons grouped by L2 class. Attributes are aggregated and DEM statistics recalculated. |
| Summary tables, A01 | `stats/A01-summary-stats_{version}.md` and numbered table CSVs | Source counts and areas, plus counts and unrounded areas from stage 08 L2 geometry. A01 does not generate another L2 shapefile. |
| Regional statistics, A05 | `stats/Aus-Trop-Reef-Features_Region-stats_{version}*` | CSV summaries and occupied-region shapefiles for countable reefs. |

Both national products use EPSG:4283 (GDA94 geographic coordinates). Areas use EPSG:3577 (GDA94 / Australian Albers), an equal-area projection. Full-classification and stage 08 `Area_km2` values are rounded to four decimal places in km².

Earlier releases used EPSG:3112, a conformal projection, for stored areas. Do not mix those areas with corrected `v1-0` values. Recalculate older geometry in EPSG:3577 if comparing areas across releases.

## Full-classification schema

This table describes the stage 06 product. The L2 product has a smaller, different schema.

| Field | Type | Meaning and common values |
| --- | --- | --- |
| `RB_Type_L3` | string | Detailed Reef Boundary Type class, such as Coral Reef, Coral Reef Flat, Coral Reef Bank, Rocky Reef, Low Relief Rocky Reef, Limestone Reef, Sand Bank, Non-reef Bank or an oceanic subtype. Consult the classification primer for the full enumeration. |
| `RB_Type_L2`, `RB_Type_L1` | string | Broader classes derived from the classification crosswalk. |
| `Attachment` | string | Fringing, Isolated, Oceanic or Land. Oceanic marks features seaward of the shelf break. |
| `DepthCat` | string | Land, Surface, Intertidal, Very Shallow, Shallow or Deep. Represents the approximate depth of the shallowest portion, not the mean depth. |
| `DepthCatSr` | string | Source of the depth decision. May identify imagery, a rule or a DEM with `;EOT20` when valid LAT statistics are available. |
| `FeatConf`, `TypeConf` | string | Confidence that the feature is real and that its L3 class is correct, respectively. Standard values are Very Low, Low, Medium and High. Missing values are not High confidence. |
| `EdgeSrc` | string | Primary boundary source, such as Sentinel-2 imagery or Queensland Globe imagery. |
| `EdgeAcc_m` | integer | Estimated 90th percentile boundary error in metres. |
| `ReefFID` | string | Non-null, unique polygon identifier. Use for feature-level joins within a release. |
| `ReefID` | string | Official persistent reef identifier where assigned. May be null or shared by multiple polygons. Do not use as a unique row key. |
| `PrevReefID` | string | Previous official identifiers associated with the location, separated by semicolons. Historical association, not a current identifier assignment. |
| `Dataset` | string | Source label: TS Features, GBR Features, CS Features, `NW-Aus-Features_{nw_version}` or `Aus-Trop-Reef-Features_{version}` for edited/new TS-GBR features. |
| `OrigType` | string | Original source classification. |
| `Sovereign1`, `Sovereign2` | string | Largest two sovereignty assignments by intersected area. |
| `Sov1_Perc`, `Sov2_Perc` | numeric | Percentage of polygon area in each recorded sovereignty. |
| `Union` | string | Country or treaty designation from the EEZ land union source. |
| `DEM10pMSL`, `DEM50pMSL`, `DEM90pMSL` | float | 10th, 50th and 90th percentile elevations in metres relative to Mean Sea Level. Negative below MSL. |
| `DEM10pLAT`, `DEM50pLAT`, `DEM90pLAT` | float | Corresponding elevations relative to Lowest Astronomical Tide. Negative below LAT. These replace the old unqualified `DEM10p`, `DEM50p` and `DEM90p` schema. |
| `DEMSr` | string | DEM name, followed by `;EOT20` when LAT statistics are available. DEM name alone when LPT data are missing; null when DEM data are missing. |
| `NvclEco`, `NvclEcoCom` | string | Natural Values Common Language ecosystem and ecosystem complex. |
| `INUNDTN`, `SMB_CMP` | string | Queensland Wetlands classification attributes. |
| `AS_TidalZ`, `AS_Bdepth`, `AS_System`, `AS_SubSys` | string | Seamap Australia aquatic setting attributes. Semicolon-separated alternatives may occur. |
| `BC_Level1` to `BC_Level4`, `SO_Level1` to `SO_Level3`, `SC_Level1` | string | Seamap Australia biotic component, substrate origin and structural component classifications. |
| `Area_km2` | float | Equal-area polygon area in km², calculated in EPSG:3577 and rounded to four decimal places. |

Stage 03 creates `ReefLabel` for working map display, but stage 06 does not retain it in the published full-classification schema. Intermediate tracking fields such as `RE_row`, `RE_part` and `CODES` are also not published.

## Identifier interpretation

`ReefID` is assigned by the responsible authority: GBRMPA within the GBR and AIMS for the Torres Strait, Coral Sea and north and west Australian mapping. Stage 02a carries an existing official identifier forward only when its overlap-based inheritance criteria are satisfied. Ambiguous associations are recorded in `PrevReefID` for review rather than treated as new official assignments.

Features without an official identifier receive a provisional `ReefFID` based on `PROV-{lat}-{lon}`. Where one official `ReefID` is shared by several polygons, stage 03 resolves colliding `ReefFID` values with feature suffixes such as `15-010-F01` and `15-010-F02`. These suffixes distinguish dataset polygons; they are not part of the official identifier. Existing unique `ReefFID` values are preserved. See [identifier allocation](reeffid_utils.py) for the deterministic tie-breaking rules.

The `v1-0` allocation establishes a baseline for later updates. Carry published feature identifiers forward in future source versions where possible. Do not assume that a provisional coordinate identifier or independently regenerated allocation provides a verified cross-release match.

## Bathymetry and depth classes

Stage 05 preserves existing `DepthCat` and `DepthCatSr` values. For missing classes, it applies feature-type rules, then DEM thresholds where no rule applies. Multi-resolution bathymetry is used within its coverage, with AusBathyTopo 250 m as fallback. A centroid sample may be used for sub-pixel polygons or when no valid interior sample is available.

DEM values are elevations, not positive-down depths. The 90th percentile is the shallower end of the distribution, approximating the shallowest 10 percent by area. LAT-adjusted values are calculated per pixel as `elevation_LAT = elevation_MSL - LPT`, before the percentiles are calculated.

| DEM-derived class | Threshold |
| --- | --- |
| Intertidal | `DEM90pLAT >= 0` |
| Very Shallow | `-2.5 <= DEM90pLAT < 0` |
| Shallow | `DEM90pLAT < -2.5` and `DEM90pMSL >= -30` |
| Deep | `DEM90pMSL < -30`, subject to the preceding rules |

The Shallow/Deep boundary uses MSL, not LAT. Rule-derived and source-assigned classes need not match these DEM thresholds. Missing DEM or LPT coverage must not be interpreted as zero depth.

`DEMSr` is recalculated with the statistics. Examples are `MultiResBathyEEZ_2024;EOT20` and `AusBathyTopo-250m_2024;EOT20`. DEM-derived `DepthCatSr` uses the same combined label. Existing source classifications and rule-based provenance are preserved.

## L2 polygons and countable reefs

Stage 08 dissolves source geometry by `RB_Type_L2` and splits the result into singlepart polygons. It retains `L2FID`, `ReefFID`, `ReefID`, `PrevReefID`, `Dataset`, `Sovereign1`, `RB_Type_L2`, `RB_L3_Agg`, `Attachment`, `DepthCat`, `DepthCatSr`, the six DEM percentile fields, `DEMSr`, confidence fields, `EdgeSrc`, `EdgeAcc_m` and `Area_km2`.

Attachment follows Land, Fringing, Oceanic, then Isolated priority. Depth category follows Land, Surface, Intertidal, Very Shallow, Shallow, then Deep priority. Confidence takes the lowest constituent value; any missing or non-standard constituent makes the aggregated confidence blank. Edge accuracy takes the maximum. `RB_L3_Agg`, `DepthCatSr` and `EdgeSrc` retain sorted unique values.

The DEM statistics are recalculated over each dissolved polygon using the shared stage 05 sampling method. They are not averages of source percentiles and do not replace the independently aggregated depth class. Non-standard confidence values are recorded in `working/{version}/08/confidence-issues.csv`, and mixed attachments in `working/{version}/08/multi-attachment-values.shp`.

`L2FID` is local to the generated L2 output, not a persistent reef identifier. `ReefFID`, `ReefID`, `PrevReefID`, `Dataset` and `Sovereign1` contain sorted unique non-empty source values separated by semicolons. Existing lists are split and trimmed before deduplication. The three identifier fields use lossless NW suffix shorthand when shorter: `R-8137-034{a-c,f}` represents the exact suffixes a, b, c and f. Different bases form separate groups; unsuffixed and unrecognised identifiers remain literal. Consult [Compact identifier notation](08-make-RB_Type_L2-spec.md#compact-identifier-notation) before interpreting these attributes. These are independent sets, not positionally aligned source records. `Sovereign1` is aggregated from source attributes without spatial recalculation. No membership CSV is generated. Lists exceeding 254 UTF-8 bytes after compression cause an explicit error before depth processing. Sovereignty percentages, secondary sovereigns, original confidence values and detailed external crosswalk fields remain in the full-classification product.

A05 uses the stage 08 output to cluster coral and rocky reefs less than 100 m apart, separately by reef type. It removes clusters below 100 m effective width. These countable reefs differ from both source polygons and dissolved L2 polygons. Regional counts go to the largest regional piece; areas are split at boundaries. Partial counts record reefs extending into a region but counted elsewhere.

Regionalisations are IMCRA v4.0 Meso-scale Bioregions, NESP 3.17 Analysis-regions and CAPAD 2024 Marine. CAPAD has an additional 300 m near-region analysis. Overlapping protected areas can receive additional counts and overlapping areas. Review `working/{version}/A05/region-stats-checks.csv` before interpreting totals. No sovereignty filter is applied; reefs outside a regionalisation are reported as `No match`.

## Downloading the dataset programmatically

Use the [metadata record](https://doi.org/10.26274/4RRW-RR88) to select a published version. The download share ID is `dQeoxzja6tCYSko`. The directory URL pattern is:

```text
https://nextcloud.eatlas.org.au/s/dQeoxzja6tCYSko/download?path={URL-escaped directory}
```

For the current product layout, the full-classification directory is `/{version}/out/full-classes`, and the L2 directory is `/{version}/out/simp-classes`. Directory downloads return ZIP files. Keep all associated shapefile files together, including `.shp`, `.shx`, `.dbf` and `.prj`; preserve `.cpg` where supplied. Downloading only the `.shp` file is insufficient.

The following example targets `v1-0` after it has been published with this layout. A missing directory is a publication or version-selection issue, not a reason to silently substitute an older release.

```python
from pathlib import Path
from urllib.parse import quote

from data_downloader import DataDownloader

version = "v1-0"
download_root = Path("data") / "in-3p"
download_root.mkdir(parents=True, exist_ok=True)
directory = quote(f"/{version}/out/full-classes", safe="")
url = (
    "https://nextcloud.eatlas.org.au/s/dQeoxzja6tCYSko/download"
    f"?path={directory}"
)
downloader = DataDownloader(download_path=str(download_root))
downloader.download_and_unzip(
    url, f"Aus-Trop-Reef-Features_{version}", flatten_directory=True
)
```

The repository [Conda environment](environment.yml) specifies DataDownloader `v1.2.0`. Older releases may have a different directory layout, including the shapefile directly under `out/`. Consult that release rather than applying the current paths to historical downloads.

## Typical analysis patterns

Use `ReefFID` for polygon-level joins. Use L2 or L1 for broad grouping, `Attachment` for fringing versus isolated versus oceanic features, and `DepthCat` for depth groups. Do not infer area from geographic coordinates.

```python
from pathlib import Path

import geopandas as gpd

version = "v1-0"
path = (
    Path("data") / version / "out" / "full-classes"
    / f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp"
)
gdf = gpd.read_file(path)

# Select whole polygons with at least half their area assigned to Australia.
aus = gdf[gdf["Sovereign1"].eq("Australia") & gdf["Sov1_Perc"].ge(50)]
coral = aus[aus["RB_Type_L2"].eq("Coral Reef")]
shallow_classes = {"Intertidal", "Very Shallow", "Shallow"}
shallow_coral = coral[coral["DepthCat"].isin(shallow_classes)]
oceanic = coral[coral["Attachment"].eq("Oceanic")]
summary = (
    coral.groupby("RB_Type_L3")["Area_km2"].sum()
    .reset_index()
    .sort_values("Area_km2", ascending=False)
)
```

This sovereignty filter selects whole features. Their stored areas include any parts outside the EEZ. For area strictly inside the Australian EEZ, intersect geometry with the boundary and recalculate area in EPSG:3577. Sovereignty attribution is supplied for research convenience, not as an official maritime boundary statement.

## Reproducibility and review

Run commands from the repository root with the `AusTropReef` Conda environment active. Stages 01a to 01c download inputs and prepare imagery. The EEZ union requires manual download. The dataset's [Nextcloud download directory](https://nextcloud.eatlas.org.au/apps/sharealias/a/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features) supplies an `in-3p-mirror` folder containing the GBRMPA source. Download and extract that folder to `data/{version}/in-3p-mirror/` so that stage 01d can read `GBRMPA-GBR-Features/Great_Barrier_Reef_Features.shp` and its associated files. Stage 01a does not download the mirror or overwrite an existing `in_path`; check incomplete local input folders explicitly.

The original GBRMPA source was downloaded manually because GBRMPA GeoHub does not allow programmatic download. This records how the mirrored data were acquired, not an additional download required for reproduction. Obtain a fresh GeoHub shapefile only when updating the source for a new build, retaining the complete shapefile set, source metadata and download date. See the [README reproduction instructions](README.md#reproducing-this-dataset).

The TS-GBR sequence is `01d -> 01e -> 02a -> 02d`. Stages 02b and 02c independently prepare NW and Coral Sea inputs. Stage 03 merges the accepted regional outputs and resolves feature identifiers. Stage 04 assigns sovereignty, stage 05 adds depth statistics and missing classes, and stage 06 applies crosswalks, computes equal-area areas and writes the full-classification product.

Stage 01e clips Reef Edit before identifier allocation. Splits produce warnings and review layers; multipart sources, invalid geometry and features with no retained marine remainder stop processing. Stage 02d clips retained legacy features after patching. Legacy splits or complete removals block the production output until corrected through Reef Edit or explicit removal. Both stages require `{in_path}/Land-exclusion/Land-exclusion-piers.shp`. They discard changed marine fragments below 100 m², measured in EPSG:3577. Unchanged features and mapped cays are exempt from fragment filtering, and mapped cays are exempt from land subtraction.

Stage 03 normally requires stage 02d's accepted output. Its development-only `--allow-review` option bypasses that gate and writes to `working/{version}/03-review/`. These outputs are not for publication. Review stage 02a's `working/{version}/02/debug-reefid-review.gpkg` separately; identifier uncertainty is not necessarily a blocking error.

Stage 07 writes sample attributes, stage 08 generates the L2 product, A01 generates report summaries, A02 generates identifier diagrams, A03 generates workflow diagrams and A05 generates regional statistics. Both A01 and A05 require stage 08. A01 reads stage 06 for source statistics and stage 08 for L2 geometry without repeating dissolution. L2 areas are recalculated without rounding in EPSG:3577. The former A01 `stats/Aus-Trop-Reef-Features_{version}_RB-Type-L2.shp` is obsolete. Working files and QA layers use `working/{version}/{stage}/`; stages 05 and 08 share the DEM mosaic in `working/{version}/05/`. Changing the version isolates working files but does not move older unversioned caches.

A05 reuses cached intermediate shapefiles. After input or method changes, remove affected caches and all their associated files before rebuilding. Regenerating stage 08 does not invalidate A05 caches. Check console messages and output timestamps as well as shell exit status: stage 06 can stop on validation errors without returning a nonzero status.

The [README reproduction instructions](README.md#reproducing-this-dataset), [clipping specifications](01e-clip-TS-GBR-reef-edit-spec.md), [legacy clipping specification](02d-clip-TS-GBR-legacy-spec.md), [L2 specification](08-make-RB_Type_L2-spec.md) and [regional analysis specification](A05-reef-distribution-spec.md) give the operational details. Synthetic tests do not establish that release inputs have passed manual review.

## Known limitations that affect analysis

Retained legacy GBR boundaries remain locally coarse despite the source refresh and extensive manual corrections. Sediment and seagrass classes do not form a complete national habitat inventory. Torres Strait Fringing Terrestrial Reef mapping is crosswalked to Intertidal Sediment, but some legacy polygons include shallow subtidal sediment. Do not interpret that class as a precise national intertidal extent.

Land and cay mapping is not a complete national island inventory. Stage 02a filters legacy Island, Mainland and Other records, while mapped cays from retained inputs or edits can still occur and are exempt from coastline subtraction. Their presence does not establish consistent coverage or accuracy.

Historical `v0-1` caveats included incomplete or draft depth classes in the north and west, possible coral-versus-limestone misclassification in the Pilbara, and Kimberley depth-class issues. The configured NW source has since changed. Do not apply old percentages to `v1-0` without checking the current regional source documentation. More generally, source and rule-derived depth classes remain approximate.

Oceanic platforms and associated vegetation require care when calculating coral reef area. High Intertidal Coral Reef is specific to macrotidal settings and is not interchangeable with all intertidal coral habitat. Consult the classification definitions and regional source metadata before combining classes.

## Citation, licence and references

Cite the version used with the year and version stated in the metadata record:

Lawrey, E., Bycroft, R. Australian Tropical Reef Features - Boundaries of coral and rocky reefs (NESP MaC 3.17, AIMS) [Data set]. eAtlas. https://doi.org/10.26274/4RRW-RR88

The dataset is available under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).

Flanders Marine Institute (2024). Union of the ESRI Country shapefile and the Exclusive Economic Zones (version 4). https://doi.org/10.14284/698

Flukes, E. (2024). Multi-resolution bathymetry composite surface for Australian waters (EEZ). Institute for Marine and Antarctic Studies. [Metadata record](https://metadata.imas.utas.edu.au/geonetwork/srv/eng/catalog.search#/metadata/69e9ac91-babe-47ed-8c37-0ef08f29338a).

Geoscience Australia (2024). AusBathyTopo (Australia) 250m 2024 - A national-scale depth model (20240011C). https://doi.org/10.26186/150050

Hammerton, M., Lawrey, E. (2024). Australian Coastline 50K 2024 (NESP MaC 3.17, AIMS) (2nd Ed.). eAtlas. https://doi.org/10.26274/qfy8-hj59

Lawrey, E. (2025). Tidal Statistics for Australia (Tidal range, LAT, HAT, MLWS, MHWS) derived from the EOT20 tidal model (NESP MaC 3.17, AIMS) (v1-1). eAtlas. https://doi.org/10.26274/Z8B6-ZX94

Lawrey, E. P., Stewart, M. (2016). Complete Great Barrier Reef (GBR) Reef and Island Feature boundaries including Torres Strait (NESP TWQ 3.13, AIMS, TSRA, GBRMPA). eAtlas. https://doi.org/10.26274/vhj5-gr60

Lawrey, E., Bycroft, R. (2025a). Coral Sea Features - Dataset collection - Coral reefs, Cays, Oceanic reef atoll platforms, and Depth contours (AIMS). Configured source `v1-2`. eAtlas. https://doi.org/10.26274/PGJP-8462

Lawrey, E., Bycroft, R. (2025b). North and West Australian Tropical Reef Features - Boundaries of coral reefs, rocky reefs and sand banks (NESP-MaC 3.17, AIMS, Aerial Architecture). Configured source `v1-2`. eAtlas. https://doi.org/10.26274/xj4v-2739

GBRMPA. Great Barrier Reef Features. [Reef GeoHub source](https://reef-geohub-ext-geohubgbrmpa.hub.arcgis.com/datasets/816f4d747cd94d84acfd924b27f581d8_64/about). The local mirror records a download on 3 September 2026.
