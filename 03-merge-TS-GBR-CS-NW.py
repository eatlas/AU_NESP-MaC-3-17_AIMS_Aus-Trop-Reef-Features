#!/usr/bin/env python
"""
Merges three shapefiles (CS-Features, TS-GBR-Features, NW-Aus-Features) into one output shapefile.
All shapefiles are in EPSG:4283. The resulting shapefile has attributes corresponding to the 
superset of the attributes from the input shapefiles.
"""

import os
import geopandas as gpd
from crosswalk_utils import load_crosswalk, validate_features

def main():

    
    # Define input and output paths
    cs_features_path = 'working/02/CS-Features-patched.shp'
    ts_gbr_features_path = 'working/02/TS-GBR-Features-patched.shp'
    nw_aus_features_path = 'working/02/NW-Aus-Features-patched.shp'
    
    # Create output directory if it doesn't exist
    output_dir = 'working/03'
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'TS-GBR-CS-NW-Features.shp')
    
    print("Reading input shapefiles...")
    # Read input shapefiles
    cs_gdf = gpd.read_file(cs_features_path)
    ts_gbr_gdf = gpd.read_file(ts_gbr_features_path)
    nw_aus_gdf = gpd.read_file(nw_aus_features_path)
    
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