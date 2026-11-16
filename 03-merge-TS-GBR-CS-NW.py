#!/usr/bin/env python
"""
Merges three shapefiles (CS-Features, TS-GBR-Features, NW-Aus-Features) into one output shapefile.
All shapefiles are in EPSG:4283. The resulting shapefile has attributes corresponding to the 
superset of the attributes from the input shapefiles.

The TS-GBR input is the coastline-clipped output of 02d-clip-TS-GBR-legacy.py.
--allow-review (development only) reads the raw stage 02a output instead and
writes to working/{version}/03-review.
"""

import argparse
import configparser
import os
import sys
import geopandas as gpd
import pandas as pd
from crosswalk_utils import load_crosswalk, validate_features
from reeffid_utils import allocate_reeffids

# Wrapper applied to ReefLabel when the label comes from PrevReefID rather than
# ReefID. Set to '{ids}' to show former identifiers without any marking.
PREV_LABEL_FORMAT = '[{ids}]'

# Intermediate tracking fields added by stage 01e, never published
TRACKING_FIELDS = ['RE_row', 'RE_part']


def build_reef_label(reef_id, prev_reef_id):
    """Return the identifier to display on a map, or None where there is none."""
    if pd.notna(reef_id) and str(reef_id).strip():
        return str(reef_id).strip()
    if pd.notna(prev_reef_id) and str(prev_reef_id).strip():
        ids = [part.strip() for part in str(prev_reef_id).split(';') if part.strip()]
        if ids:
            return PREV_LABEL_FORMAT.format(ids='; '.join(ids))
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--allow-review', action='store_true',
        help='Development only: read the raw stage 02a output (bypassing the stage '
             '02d legacy coastline gate) and write to working/{version}/03-review.')
    args = parser.parse_args()

    # Define input and output paths
    config = configparser.ConfigParser()
    config.read('config.ini')
    version = config.get('general', 'version')
    working_dir = os.path.join('working', version)
    cs_features_path = os.path.join(working_dir, '02', 'CS-Features-patched.shp')
    nw_aus_features_path = os.path.join(working_dir, '02', 'NW-Aus-Features-patched.shp')
    if args.allow_review:
        ts_gbr_features_path = os.path.join(working_dir, '02', 'TS-GBR-Features-patched.shp')
        output_dir = os.path.join(working_dir, '03-review')
        print("!" * 78)
        print("WARNING: --allow-review. Legacy coastline correction (stage 02d) has been")
        print(f"bypassed. Output in {output_dir} is NOT for publication.")
        print("!" * 78)
    else:
        ts_gbr_features_path = os.path.join(working_dir, '02', 'TS-GBR-Features-clipped.shp')
        output_dir = os.path.join(working_dir, '03')

    for path in (cs_features_path, ts_gbr_features_path, nw_aus_features_path):
        if not os.path.exists(path):
            print(f"ERROR: Input not found: {path}")
            if path == ts_gbr_features_path and not args.allow_review:
                print("  Run 02d-clip-TS-GBR-legacy.py and resolve any blocking cases.")
            sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'TS-GBR-CS-NW-Features.shp')
    
    print("Reading input shapefiles...")
    # Read input shapefiles
    cs_gdf = gpd.read_file(cs_features_path)
    ts_gbr_gdf = gpd.read_file(ts_gbr_features_path)
    nw_aus_gdf = gpd.read_file(nw_aus_features_path)
    # Stage 01e tracking fields are intermediate only
    ts_gbr_gdf = ts_gbr_gdf.drop(columns=[c for c in TRACKING_FIELDS if c in ts_gbr_gdf.columns])
    
    # Print information about input datasets
    print(f"CS-Features: {len(cs_gdf)} features")
    print(f"TS-GBR-Features: {len(ts_gbr_gdf)} features")
    print(f"NW-Aus-Features: {len(nw_aus_gdf)} features")

    # Debug: Print CRS of each input
    print(f"CS-Features CRS: {cs_gdf.crs}")
    print(f"TS-GBR-Features CRS: {ts_gbr_gdf.crs}")
    print(f"NW-Aus-Features CRS: {nw_aus_gdf.crs}")
    
    # Get the superset of all columns
    all_columns = set()
    for gdf in [cs_gdf, ts_gbr_gdf, nw_aus_gdf]:
        all_columns.update(gdf.columns)
    
    # Ensure geometry column is handled properly
    all_columns.discard('geometry')
    all_columns = list(all_columns)
    
    # Make sure all GeoDataFrames have the same columns
    for name, gdf in [("CS-Features", cs_gdf), 
                     ("TS-GBR-Features", ts_gbr_gdf), 
                     ("NW-Aus-Features", nw_aus_gdf)]:
        for col in all_columns:
            if col not in gdf.columns:
                print(f"Adding missing column '{col}' to {name}")
                gdf[col] = None
    
    # Concatenate the GeoDataFrames
    print("Merging shapefiles...")
    merged_gdf = gpd.pd.concat([cs_gdf, ts_gbr_gdf, nw_aus_gdf], ignore_index=True)

    unresolved_mask = (
        merged_gdf['ReefFID'].isna()
        | merged_gdf['ReefFID'].duplicated(keep=False)
    )
    unresolved_count = int(unresolved_mask.sum())
    print(f"Allocating ReefFID values ({unresolved_count} unresolved records)...")
    merged_gdf = allocate_reeffids(merged_gdf)
    print(f"  All {len(merged_gdf)} ReefFID values are non-null and unique")

    merged_gdf['ReefLabel'] = [
        build_reef_label(reef_id, prev)
        for reef_id, prev in zip(merged_gdf['ReefID'], merged_gdf['PrevReefID'])
    ]
    labelled = merged_gdf['ReefLabel'].notna()
    from_prev = labelled & merged_gdf['ReefID'].isna()
    print(f"Building ReefLabel: {int(labelled.sum())} features labelled "
          f"({int(from_prev.sum())} from PrevReefID), "
          f"{int((~labelled).sum())} left blank")

    # Debug: Print CRS of merged_gdf before setting CRS
    print(f"Merged GeoDataFrame CRS before set_crs: {merged_gdf.crs}")

    # Ensure the output has WGS84 CRS
    merged_gdf = merged_gdf.set_crs(epsg=4283)
    
    # Print information about the merged dataset
    print(f"Merged dataset: {len(merged_gdf)} features")
    
    # Validate feature classifications against the crosswalk
    print("Validating feature classifications against crosswalk...")
    crosswalk = load_crosswalk()
    _, _, mismatched_indices = validate_features(merged_gdf, crosswalk, check_depthcat=False)

    if mismatched_indices:
        mismatched_gdf = merged_gdf.iloc[mismatched_indices]
        mismatch_output = os.path.join(output_dir, 'Feature-mismatched.shp')
        mismatched_gdf.to_file(mismatch_output)
        print(f"ERROR: {len(mismatched_indices)} features have invalid (RB_Type_L3, Attachment) combinations.")
        print(f"  Mismatched features saved to {mismatch_output}")
        print("Summary of mismatches (by RB_Type_L3, Attachment):")
        print(mismatched_gdf.groupby(['RB_Type_L3', 'Attachment']).size())
        print("Aborting. Fix the feature classifications before proceeding.")
        return
    print(f"  All {len(merged_gdf)} features have valid classifications.")

    # Save the merged shapefile
    print(f"Saving merged shapefile to: {output_path}")
    merged_gdf.to_file(output_path)
    print("Merge completed successfully.")

if __name__ == "__main__":
    main()