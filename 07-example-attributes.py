"""
Script: 07-example-attributes.py

Purpose:
    This script selects a random subset of features from the harmonized reef features shapefile
    and saves their attributes (excluding geometry) to a CSV file. The resulting CSV provides
    example attribute values for use in documentation, allowing users to see the structure and
    content of the dataset without needing to download or inspect the full shapefile.

Details:
    - Reads the versioned shapefile produced by the crosswalk/enrichment process.
    - Randomly selects a fixed number of features (default: 10, configurable).
    - Exports all attribute columns (except geometry) to a CSV file in the working/07 directory.
    - Uses a fixed random seed for reproducibility.

Inputs:
    - working/06/TS-GBR-CS-NW-Features_{version}.shp

Outputs:
    - working/07/TS-GBR-CS-NW-Features_{version}_subset.csv

Intended Use:
    - To provide example attribute tables for documentation and user guidance.
"""
import os
import geopandas as gpd
import configparser
import numpy as np

# Constants
N_SAMPLES = 10
RANDOM_SEED = 42

# Read config for version
config = configparser.ConfigParser()
config.read('config.ini')
version = config.get('general', 'version')

# Input and output paths
input_shp = f'data/{version}/out/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp'
output_csv = f"working/07/TS-GBR-CS-NW-Features_{version}_subset.csv"

def main():
    print(f"Reading shapefile: {input_shp}")
    gdf = gpd.read_file(input_shp)
    print(f"Loaded {len(gdf)} features.")

    np.random.seed(RANDOM_SEED)
    sample_indices = np.random.choice(gdf.index, size=min(N_SAMPLES, len(gdf)), replace=False)
    sample_gdf = gdf.loc[sample_indices]

    # Drop geometry for CSV output
    sample_df = sample_gdf.drop(columns='geometry')
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    sample_df.to_csv(output_csv, index=False)
    print(f"Saved {len(sample_df)} example attributes to {output_csv}")

if __name__ == "__main__":
    main()