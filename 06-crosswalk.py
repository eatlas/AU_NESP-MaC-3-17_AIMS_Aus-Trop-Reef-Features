"""
Script: 06-crosswalk.py

Purpose:
    This script processes a shapefile of Australian reef features,
    enriching it with additional classification attributes from a crosswalk table. The goal is
    to harmonize the dataset with multiple external classification schemes (e.g., Seamap Australia,
    Natural Values Common Language, Queensland Wetlands Info) and prepare it for publication.

Processing Steps:
    1. Reads the input shapefile containing reef features and their attributes.
    2. Reads a crosswalk CSV table that maps the internal classification scheme (RB_Type_L3, Attachment, DepthCat)
       to external classification schemes. The crosswalk allows for multiple possible values in the
       Attachment and DepthCat columns (semicolon-separated).
    3. For each feature in the shapefile:
        - Matches it to a row in the crosswalk table using:
            * RB_Type_L3 (feature) == RB_Type_L3_v0-4 (crosswalk)
            * Attachment (feature) in Attachment_v0-4 (crosswalk, supports multiple values)
            * DepthCat (feature, defaulting to 'Shallow' if missing) in DepthCat_v0-4 (crosswalk, supports multiple values)
        - If a feature cannot be matched, it is collected for review.
    4. If any features are unmatched:
        - Saves these features to a separate shapefile for manual inspection and correction.
        - Prints a summary of mismatches and aborts further processing.
    5. For matched features:
        - Adds selected external classification attributes from the crosswalk table.
        - Retains key existing attributes from the input shapefile.
        - Converts the EdgeAcc_m attribute to integer type.
        - Recalculates Area_km2 using GDA94 / Australian Albers (EPSG:3577), an equal-area projection.
        - Reprojects the final dataset to EPSG:4283 (GDA94) for publication.
        - Determines the maximum string length for each output text field and sets the output schema accordingly.
        - Saves the enriched dataset as a new shapefile.

Inputs:
    - Reef features shapefile: working/05/TS-GBR-CS-NW-Features-depth.shp
    - Crosswalk table: data/v0-4/in/RB_Type_L3_crosswalk.csv

Outputs:
    - Enriched features shapefile: data/{version}/out/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp
    - Unmatched features shapefile (if any): working/06/Feature-mismatched.shp

Notes:
    - Requires the 'fiona' engine for shapefile writing to support custom field lengths.
    - Prints status messages at each major processing step.
    - Designed for use in the AIMS NESP 3.17 project for harmonizing reef boundary mapping data.
"""

import os
import pandas as pd
import geopandas as gpd
import numpy as np
import configparser
from crosswalk_utils import load_crosswalk, validate_features

# Input/output paths
INPUT_SHP = "working/05/TS-GBR-CS-NW-Features-depth.shp"
MISMATCHED_SHP = "working/06/Feature-mismatched.shp"


config = configparser.ConfigParser()
config.read('config.ini')
version = config.get('general', 'version')

# output_shp = f"working/06/TS-GBR-CS-NW-Features_{version}.shp"
output_shp = f'data/{version}/out/full-classes/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp'

# Output fields from crosswalk to add
CROSSWALK_FIELDS = [
    'RB_Type_L2', 'RB_Type_L1', 'NvclEco', 'NvclEcoCom', 'INUNDTN', 'SMB_CMP',
    'AS_TidalZ', 'AS_Bdepth', 'AS_System', 'AS_SubSys',
    'BC_Level1', 'BC_Level2', 'BC_Level3', 'BC_Level4',
    'SO_Level1', 'SO_Level2', 'SO_Level3', 'SC_Level1'
]

# Existing fields to retain
RETAIN_FIELDS = [
    'RB_Type_L3','Attachment', 'DepthCat','DepthCatSr', 'FeatConf', 'TypeConf', 
    'EdgeSrc', 'EdgeAcc_m', 'ReefFID', 'ReefID', 'PrevReefID', 'Dataset', 'OrigType', 'Sovereign1', 'Sovereign2', 
     'Sov1_Perc', 'Sov2_Perc', 'Union', 'DEM10p', 'DEM50p', 'DEM90p', 'DEMSr'
]

def main():
    print("Reading input shapefile...")
    gdf = gpd.read_file(INPUT_SHP)
    print(f"  Loaded {len(gdf)} features.")

    print("Reading crosswalk table...")
    crosswalk = load_crosswalk()
    print(f"  Loaded {len(crosswalk)} crosswalk rows.")

    # Check for missing or empty DepthCat values before filling/replacing.
    # Previous scripts should have already set DepthCat to a value determined from bathymetry.
    # Any NULL values indicate an error in the previous steps.
    missing_depthcat = gdf['DepthCat'].isna() | (gdf['DepthCat'] == '')
    if missing_depthcat.any():
        print("ERROR: Some features have missing or empty DepthCat values!")
        print("Summary of missing DepthCat (by RB_Type_L3, Attachment):")
        print(gdf.loc[missing_depthcat].groupby(['RB_Type_L3', 'Attachment']).size())
        print("Aborting script. Please fix the input data.")
        return
    
    # Fill missing DepthCat with 'Shallow'
    # gdf['DepthCat'] = gdf['DepthCat'].fillna('Shallow')
    # gdf['DepthCat'] = gdf['DepthCat'].replace('', 'Shallow')

    # Convert EdgeAcc_m to integer (from string).
    gdf['EdgeAcc_m'] = pd.to_numeric(gdf['EdgeAcc_m'], errors='coerce').fillna(0).astype(int)

    # Prepare for matching
    print("Matching features to crosswalk...")
    match_indices, crosswalk_indices, mismatched_indices = validate_features(
        gdf, crosswalk, check_depthcat=True
    )

    print(f"  Matched {len(match_indices)} features.")
    print(f"  {len(mismatched_indices)} features could not be matched.")

    # If mismatches, save and abort
    if mismatched_indices:
        print("Saving mismatched features for review...")
        mismatched_gdf = gdf.iloc[mismatched_indices]
        os.makedirs(os.path.dirname(MISMATCHED_SHP), exist_ok=True)
        mismatched_gdf.to_file(MISMATCHED_SHP)
        print(f"  Mismatched features saved to {MISMATCHED_SHP}")
        print("Summary of mismatches (by RB_Type_L3, Attachment, DepthCat):")
        print(mismatched_gdf.groupby(['RB_Type_L3', 'Attachment', 'DepthCat']).size())
        print("Aborting further processing due to mismatches.")
        return

    # Prepare output dataframe
    print("Preparing output dataframe...")
    matched_gdf = gdf.iloc[match_indices].copy()
    crosswalk_matched = crosswalk.iloc[crosswalk_indices].reset_index(drop=True)
    matched_gdf = matched_gdf.reset_index(drop=True)

    # Add crosswalk fields
    for field in CROSSWALK_FIELDS:
        matched_gdf[field] = crosswalk_matched[field].values

    # Recalculate Area_km2
    print("Reprojecting to EPSG:3577 (GDA94 / Australian Albers) for equal-area calculation...")
    matched_gdf_3577 = matched_gdf.to_crs(epsg=3577)
    matched_gdf['Area_km2'] = matched_gdf_3577.geometry.area / 1e6
    matched_gdf['Area_km2'] = matched_gdf['Area_km2'].round(4)

    # Reproject to EPSG:4283 for output
    print("Reprojecting to EPSG:4283 for output...")
    matched_gdf = matched_gdf.to_crs(epsg=4283)

    # Determine max string lengths for schema
    print("Determining field lengths for output schema...")
    schema = matched_gdf.schema if hasattr(matched_gdf, 'schema') else None
    properties = {}
    for field in RETAIN_FIELDS + CROSSWALK_FIELDS:
        if field in matched_gdf.columns:
            if matched_gdf[field].dtype == object:
                maxlen = matched_gdf[field].astype(str).map(len).max()
                properties[field] = f'str:{maxlen}'
            elif matched_gdf[field].dtype == int or np.issubdtype(matched_gdf[field].dtype, np.integer):
                properties[field] = 'int'
            # For DEM10p, DEM50p, DEM90p
            elif matched_gdf[field].dtype == float or np.issubdtype(matched_gdf[field].dtype, np.floating):
                properties[field] = 'float:24.1'
    # Area_km2
    properties['Area_km2'] = 'float:24.4'

    # Geometry
    geometry_type = gpd.io.file.infer_schema(matched_gdf)['geometry']

    # Output columns order
    output_cols = RETAIN_FIELDS + CROSSWALK_FIELDS + ['Area_km2', 'geometry']
    output_cols = [col for col in output_cols if col in matched_gdf.columns or col == 'geometry']

    # Save output
    print(f"Saving output to {output_shp}...")
    os.makedirs(os.path.dirname(output_shp), exist_ok=True)
    # Fiona is needed for schema handling
    matched_gdf[output_cols].to_file(
        output_shp,
        driver='ESRI Shapefile',
        schema={'geometry': geometry_type, 'properties': properties},
        engine='fiona'
    )
    print(f"Done! Output saved to {output_shp}")
    print("Next step is uploading the new version to NextCloud on the eAtlas and updating the metadata record.")

if __name__ == "__main__":
    main()