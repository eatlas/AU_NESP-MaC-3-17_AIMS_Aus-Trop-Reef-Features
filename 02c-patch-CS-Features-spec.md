# Coral Sea feature preparation

## Purpose and inputs

[02c-patch-CS-Features.py](02c-patch-CS-Features.py) prepares Coral Sea reef, cay and atoll-platform mapping for the national merge. It reads `in_3p_path`, `cs_feat_version` and `nw_aus_feat_version` from [config.ini](config.ini). Run it from the repository root.

The reef and cay input is `CS-Feat_{cs_feat_version}/Reefs-Cays/CS_AIMS_Coral-Sea-Features_2025_Reefs-cays.shp` beneath `in_3p_path`. The platform input is `CS-Feat_{cs_feat_version}/Atoll-Platforms/CS_AIMS_Coral-Sea-Features_2025_Atoll-platforms.shp`. The classification crosswalk is `NW-Aus-Feat_{nw_aus_feat_version}/in/RB_Type_L3_crosswalk.csv`.

## Confidence standardisation

For both input layers, `Very high` and `High` map to `High` in `FeatConf` and `TypeConf`. Other values, including nulls and blanks, are unchanged. No general case conversion, trimming or ranking is applied. The script prints the number of `Very high` values replaced in each field for each layer.

This standardisation reduces the Coral Sea confidence scale to the national scale. It does not interpret ambiguous source values such as `LowHigh` or `HighLow`. Stage 08 continues to flag non-standard values reaching the national L2 input.

## Geometry and attribute processing

Both layers receive `Dataset` = `CS Features`. Source classifications are retained in `OrigType`. Unused descriptive attributes and derived area and classification fields are removed.

Atoll platforms are reprojected to the reef layer CRS when necessary. The union of reef and cay geometries is subtracted from each platform. Empty platform results are removed and their number is printed. The remaining platform features are merged with reefs and cays.

After subtraction and removal of empty results, platforms are projected to EPSG:3577 (metres) and buffered inward by 0.1 m, then outward by 0.1 m using round joins. This morphological opening removes zero-width spikes and narrow slivers that can become invalid rings during projection or shapefile writing. It also rounds corners and can remove polygon parts or connections narrower than approximately 0.2 m. It is not an exact boundary-preserving repair. The script prints the net area removed. Reef and cay geometry is not buffered, and feature attributes and identifiers are retained.

Buffered platforms are returned to the reef CRS before merging. If cleanup removes a whole retained platform or produces invalid or non-polygon geometry, the script reports the affected records and stops rather than silently dropping them. Geometry is also validated after output projection and after reading back the written shapefile. A failure prevents a successful completion message. Source data is never repaired or overwritten.

The script translates `RB_Type_L3` using the crosswalk columns `CS_RB_Type_L3_v0-3` and `RB_Type_L3_v0-4`. Blank source cells are excluded from the lookup. Missing crosswalk entries cause an error. Coral Sea Atoll Platform maps to Oceanic Platform because separately mapped reefs are excluded from its geometry.

Vegetated Cay and Unvegetated Cay receive Attachment = Land. Other translated types receive Attachment = Oceanic. Published `ReefFID` values are retained. If the field is absent, it is added with null values for first allocation in stage 03.

## Output and regeneration

The output is `working/{version}/02/CS-Features-patched.shp` in EPSG:4283, where `{version}` is `[general] version` in [config.ini](config.ini), not the Coral Sea source version. Source datasets are not rewritten. Stage 06 subsequently recalculates the national areas and classification crosswalks.

Run `python 02c-patch-CS-Features.py`, then downstream stages 03 to 06, to propagate confidence standardisation and platform cleanup into the national dataset. Run A07 again to check remaining invalid final polygons; this platform-only cleanup does not address invalid features from other datasets. Run stage 08 afterwards to rebuild the reusable L2 product. A05 caches must be invalidated separately when regenerating regional statistics from changed inputs.

## Validation

Focused tests check both input-layer names, both confidence fields, unchanged lower confidence values, nulls, blanks and non-standard values. An end-to-end synthetic stage 02c run checks that both layers are standardised in the exported shapefile while input files remain unchanged.

Geometry tests check spike removal, the 0.1 m metric tolerance, geographic CRS round trips, retained attributes, polygon validity after shapefile writing, unchanged reef geometry and failure when a whole platform would be lost.

Run `python -m unittest discover -s tests -p "test_cs_*.py" -b` in the AusTropReef environment. These tests do not download data or regenerate the national dataset.
