#!/usr/bin/env python

"""
Patches the Coral Sea Features shapefile by:
1. Adding an attribute called 'DATASET' with value 'CS Features'
2. Removing the attribute 'Stage'
3. Rounding AvArea_km2 to 6 decimal places
4. Creating an attribute 'OrigType' with values from 'RB_Type_L3'
5. Merging reef features with non-overlapping atoll platforms
6. Translating RB_Type_L3 from v0-3 to v0-4 using a crosswalk table after merging
"""

import os
import geopandas as gpd
import configparser
from pathlib import Path
import pandas as pd

# --- File path constants (set after config is loaded) ---
CONFIG_PATH = 'config.ini'
OUTPUT_DIR = 'working/02'
OUTPUT_FILENAME = 'CS-Features-patched.shp'

def get_filepaths():
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    in_3p_path = config.get('general', 'in_3p_path')
    cs_reefs_features_path = os.path.join(
        in_3p_path, 'Coral-Sea-Feat/Reefs-Cays/CS_AIMS_Coral-Sea-Features_2025_Reefs-cays.shp'
    )
    cs_platforms_features_path = os.path.join(
        in_3p_path, 'Coral-Sea-Feat/Atoll-Platforms/CS_AIMS_Coral-Sea-Features_2025_Atoll-platforms.shp'
    )
    rb_type_lut_path = os.path.join(
        in_3p_path, "NW-Aus-Feat_v0-4", "in", "RB_Type_L3_crosswalk.csv"
    )
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILENAME)
    return cs_reefs_features_path, cs_platforms_features_path, rb_type_lut_path, output_path

def process_features(gdf, dataset_name):
    """Process a GeoDataFrame with common cleanup steps"""
    print(f"Processing {dataset_name}...")
    print(f"Input dataset: {len(gdf)} features")
    print(f"Original columns: {list(gdf.columns)}")
    
    # Add 'DATASET' attribute
    gdf['Dataset'] = 'CS Features'
    

    print("\nRemoving unnecessary attributes...")
    columns_to_remove = [
        'Stage','AvArea_km2', 'id','Notes','LatCentre','LongCentre',
        'Name','NameSrc','OtherNames','OtherNaSrc','Stability','Position',
        'NvclEco','NvclEcoCom','Area_km2','Country','RB_Type_L2','RB_Type_L1'   # Remove derived attributes
    ]
    
    # Only drop columns that exist in the DataFrame
    columns_to_remove = [col for col in columns_to_remove if col in gdf.columns]
    if columns_to_remove:
        print(f"  Removing {len(columns_to_remove)} unnecessary attributes")
        gdf = gdf.drop(columns=columns_to_remove)
    
    # Create 'OrigType' attribute from 'RB_Type_L3' if it exists
    if 'RB_Type_L3' in gdf.columns:
        print("Creating 'OrigType' attribute from 'RB_Type_L3'...")
        gdf['OrigType'] = gdf['RB_Type_L3']
    else:
        print("Note: 'RB_Type_L3' attribute not found. 'OrigType' will be set to None.")
        gdf['OrigType'] = None
        
    return gdf

def load_rb_type_crosswalk(csv_path):
    """
    Loads the RB_Type_L3 crosswalk table and returns a mapping from v0-3 to v0-4.
    """
    print(f"Loading RB_Type_L3 crosswalk from {csv_path}")
    df = pd.read_csv(csv_path)
    lut = {}
    for _, row in df.iterrows():
        k = str(row['RB_Type_L3_v0-3']).strip()
        v = str(row['RB_Type_L3_v0-4']).strip()
        if k:
            lut[k] = v
    print(f"Loaded {len(lut)} RB_Type_L3 v0-3 to v0-4 mappings")
    return lut

def main():
    # Get file paths
    cs_reefs_features_path, cs_platforms_features_path, rb_type_lut_path, output_path = get_filepaths()

    print("Reading Coral Sea Features shapefiles...")
    # Read input shapefiles
    cs_reefs_gdf = gpd.read_file(cs_reefs_features_path)
    cs_platforms_gdf = gpd.read_file(cs_platforms_features_path)
    
    # Process both datasets
    cs_reefs_gdf = process_features(cs_reefs_gdf, "Reefs and Cays")
    cs_platforms_gdf = process_features(cs_platforms_gdf, "Atoll Platforms")
    
    # Ensure both GDFs have the same CRS
    if cs_reefs_gdf.crs != cs_platforms_gdf.crs:
        print(f"Converting atoll platforms to match CRS of reefs: {cs_reefs_gdf.crs}")
        cs_platforms_gdf = cs_platforms_gdf.to_crs(cs_reefs_gdf.crs)
    
    # Cut out reef features from atoll platforms
    print("Removing reef footprints from atoll platforms...")
    # Create a unified geometry of all reefs
    all_reefs_geometry = cs_reefs_gdf.union_all()
    
    # Remove reef areas from each atoll platform
    cs_platforms_gdf['geometry'] = cs_platforms_gdf.geometry.apply(
        lambda geom: geom.difference(all_reefs_geometry)
    )
    
    # Remove any atoll platforms that became empty after the difference operation
    original_count = len(cs_platforms_gdf)
    cs_platforms_gdf = cs_platforms_gdf[~cs_platforms_gdf.geometry.is_empty]
    if original_count != len(cs_platforms_gdf):
        print(f"Removed {original_count - len(cs_platforms_gdf)} empty geometries")
    
    # Merge the two geodataframes
    print("Merging datasets...")
    merged_gdf = gpd.GeoDataFrame(pd.concat([cs_reefs_gdf, cs_platforms_gdf], ignore_index=True))
    
    print(f"Final dataset: {len(merged_gdf)} features")
    print(f"Final columns: {list(merged_gdf.columns)}")
    
    # --- RB_Type_L3 v0-3 to v0-4 translation step ---
    rb_type_lut = load_rb_type_crosswalk(rb_type_lut_path)

    print("Translating RB_Type_L3 from v0-3 to v0-4 using crosswalk table...")
    if 'RB_Type_L3' not in merged_gdf.columns:
        raise Exception("RB_Type_L3 column not found in merged dataset.")

    # Save original RB_Type_L3 in OrigType (already done in process_features, but ensure here)
    merged_gdf['OrigType'] = merged_gdf['RB_Type_L3']

    # Map RB_Type_L3 using crosswalk, raise if not found
    def map_rb_type(val):
        key = str(val).strip()
        if key in rb_type_lut:
            return rb_type_lut[key]
        else:
            raise Exception(f"RB_Type_L3 value '{val}' not found in crosswalk table.")

    merged_gdf['RB_Type_L3'] = merged_gdf['RB_Type_L3'].apply(map_rb_type)

    # --- Add Attachment attribute ---
    def attachment_value(rb_type):
        if rb_type in ['Vegetated Cay', 'Unvegetated Cay']:
            return 'Land'
        else:
            return 'Oceanic'
    merged_gdf['Attachment'] = merged_gdf['RB_Type_L3'].apply(attachment_value)

    # Reproject to EPSG:4283 before saving
    print("Reprojecting output to EPSG:4283...")
    merged_gdf = merged_gdf.to_crs(epsg=4283)

    # Create output directory if it doesn't exist
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Save the patched shapefile
    print(f"Saving patched shapefile to: {output_path}")
    merged_gdf.to_file(output_path)
    print("Patching completed successfully.")

if __name__ == "__main__":
    main()