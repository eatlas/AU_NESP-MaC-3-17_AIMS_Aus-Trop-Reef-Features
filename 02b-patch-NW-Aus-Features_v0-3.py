"""
This script applies any necessary corrections to the v0-3 version of the 
NW-Aus-Features dataset. 

It copies the input shapefile to the output directory, renames it to match the
output that corresponds to the v0-2 version of the dataset, and removes the
'DebugID', 'debug_stat', and 'tile_id' attributes.
"""
import os
import configparser
import shutil
import glob
import geopandas as gpd

def main(perform_clipping=False):
    # Read configuration
    config = configparser.ConfigParser()
    config.read('config.ini')
    in_3p_path = config['general']['in_3p_path']
    
    # Define paths
    input_file = os.path.join(in_3p_path, 'NW-Aus-Feat_v0-3', 'out', 
                             'NW-Aus-Features_v0-3.shp')
    output_dir = 'working/02'
    output_file = os.path.join(output_dir, 'NW-Aus-Features-patched.shp')
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Reading {input_file}")
    # Read the shapefile using geopandas
    gdf = gpd.read_file(input_file)
    
    # Remove debug attributes and attributes that are not yet consistently
    # developed for all datasets.
    columns_to_drop = ['DebugID', 'debug_stat', 'tile_id', 
                       'GeoAttach','Relief','FlowInflu','SO_L2','Paleo']
    columns_removed = []
    
    for column in columns_to_drop:
        if column in gdf.columns:
            gdf = gdf.drop(columns=[column])
            columns_removed.append(column)
    
    if columns_removed:
        print(f"Removed attributes: {', '.join(columns_removed)}")
    else:
        print("None of the specified attributes were found in the shapefile")
    
    # Filter out features where RB_Type_L3 = 'Shallow sediment'
    # We remove this feature type in this version of the dataset because
    # it is not consistently available on the GBR portion of the dataset.
    if 'RB_Type_L3' in gdf.columns:
        feature_count_before = len(gdf)
        gdf = gdf[gdf['RB_Type_L3'] != 'Shallow sediment']
        features_removed = feature_count_before - len(gdf)
        print(f"Removed {features_removed} features with RB_Type_L3 = 'Shallow sediment'")
    else:
        print("Warning: RB_Type_L3 column not found, no features were filtered")
    
    # Save the modified shapefile
    print(f"Saving to {output_file}")
    gdf.to_file(output_file)
    
    print("Patching complete.")

if __name__ == "__main__":
    main(perform_clipping=True)