"""
This script processes the v0-4+ version of the NW-Aus-Features dataset.

It trims unnecessary attributes from the input shapefile and adds attributes as needed
to align the attribute structure with other datasets. Specifically, it retains only
the core attributes required for downstream use and adds an 'OrigType' attribute as
a copy of 'RB_Type_L3'.

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
    version = config.get('general', 'version')
    in_3p_path = config['general']['in_3p_path']
    nw_aus_feat_version = config['general']['nw_aus_feat_version']
    
    # Define paths
    input_file = os.path.join(in_3p_path, f'NW-Aus-Feat_{nw_aus_feat_version}', 'out', 'full-classes',
                             f'AU_NESP-MaC-3-17_AIMS_NW-Aus-Features_L3_{nw_aus_feat_version}.shp')
    
    output_dir = os.path.join('working', version, '02')
    output_file = os.path.join(output_dir, 'NW-Aus-Features-patched.shp')
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Reading {input_file}")
    # Read the shapefile using geopandas
    gdf = gpd.read_file(input_file)

    # Preserve published feature IDs on updates; stage 03 performs first allocation.
    if 'ReefFID' not in gdf.columns:
        gdf['ReefFID'] = None

    # Retain only the specified columns (plus geometry)
    columns_to_keep = [
        'EdgeSrc', 'EdgeAcc_m', 'FeatConf', 'TypeConf',
        'DepthCat', 'DepthCatSr', 'RB_Type_L3', 'Attachment',
        'ReefFID', 'ReefID', 'PrevReefID'
    ]
    columns_to_keep_with_geom = [col for col in columns_to_keep if col in gdf.columns]
    if 'geometry' in gdf.columns:
        columns_to_keep_with_geom.append('geometry')
    gdf = gdf[columns_to_keep_with_geom]

    print(f"Retained columns: {', '.join(columns_to_keep_with_geom)}")

    # Add OrigType as a copy of RB_Type_L3
    if 'RB_Type_L3' in gdf.columns:
        gdf['OrigType'] = gdf['RB_Type_L3']
        print("Added 'OrigType' attribute as a copy of 'RB_Type_L3'")
    else:
        print("Warning: 'RB_Type_L3' column not found, 'OrigType' not added")

    # Add Dataset attribute
    gdf['Dataset'] = f'NW-Aus-Features_{nw_aus_feat_version}'
    print(f"Added 'Dataset' attribute set to 'NW-Aus-Features_{nw_aus_feat_version}'")

    # Save the modified shapefile
    print(f"Saving to {output_file}")
    gdf.to_file(output_file)
    
    print("Patching complete.")

if __name__ == "__main__":
    main(perform_clipping=True)