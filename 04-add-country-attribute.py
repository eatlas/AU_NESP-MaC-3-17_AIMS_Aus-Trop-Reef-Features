"""
Country Attribution Script for Australian Tropical Reef Features

Purpose:
    This script analyzes reef boundary polygons to determine which countries they're 
    associated with, including cases where reefs cross Exclusive Economic Zone (EEZ)
    boundaries. It assigns sovereign country attributes to each reef feature based on
    spatial intersection with country EEZ boundaries.

Key Algorithms:
    1. Spatial Overlay Analysis: Intersects reef boundary polygons with country EEZ polygons
    2. Area-Based Attribution: For each reef feature, calculates the area of intersection
       with each country's EEZ and determines primary/secondary countries based on the
       proportion of area that falls within each EEZ
    3. Cross-Boundary Handling: Where reefs cross multiple EEZs, the script:
       - Assigns the country with the greatest overlap area as Sovereign1
       - Assigns the country with the second greatest overlap as SOVEREIGN2
       - Records the percentage of the reef in each country as SOV1_PCT and SOV2_PCT
       - Concatenates the UNION attributes from both countries with a semicolon
    4. Edge Case Handling:
       - Reefs with no country intersection are marked as "International Waters"
       - For features crossing 3+ countries, if there are duplicate sovereign countries,
         their percentages are combined to fit the data into the two-country model
       - All distinct UNION values are preserved in the UNION field with semicolons

Output Attributes:
    - Sovereign1: Primary country with the most reef area
    - SOVEREIGN2: Secondary country with the lesser reef area (if applicable)
    - SOV1_PCT: Percentage of reef area in the primary country
    - SOV2_PCT: Percentage of reef area in the secondary country (if applicable)
    - UNION: Country or treaty designation, concatenated with semicolons for cross-boundary reefs
"""

import geopandas as gpd
import os
import sys
import configparser
from pathlib import Path
from shapely.ops import unary_union
from shapely.geometry import box  # Import box from shapely.geometry
import numpy as np
from tqdm import tqdm
import time

print("Starting script to add country attributes to reef features...")

# Load configuration
config = configparser.ConfigParser()
config.read('config.ini')
in_3p_path = config['general']['in_3p_path']

# Define paths
reef_features_path = "working/03/TS-GBR-CS-NW-Features.shp"
country_eez_dir = os.path.join(in_3p_path, "EEZ-land-union_2024")
country_eez_path = os.path.join(country_eez_dir, "EEZ_land_union_v4_202410.shp")

# Check if the CountryEEZ dataset exists
if not os.path.exists(country_eez_path):
    print(f"ERROR: The CountryEEZ dataset was not found at: {country_eez_path}")
    print("This dataset must be downloaded manually.")
    print("Please refer to the repo README.md for instructions on downloading this dataset.")
    sys.exit(1)

print("Loading datasets...")

# Load reef features shapefile
try:
    reef_features = gpd.read_file(reef_features_path)
    print(f"Loaded {len(reef_features)} reef features.")
except Exception as e:
    print(f"Error loading reef features shapefile: {e}")
    sys.exit(1)

# Load CountryEEZ shapefile
try:
    country_eez = gpd.read_file(country_eez_path)
    print(f"Loaded {len(country_eez)} EEZ features.")
except Exception as e:
    print(f"Error loading CountryEEZ shapefile: {e}")
    sys.exit(1)

# Ensure both datasets are in EPSG:4326
if reef_features.crs != "EPSG:4326":
    reef_features = reef_features.to_crs("EPSG:4326")
    print("Reprojected reef features to EPSG:4326")
    
if country_eez.crs != "EPSG:4326":
    country_eez = country_eez.to_crs("EPSG:4326")
    print("Reprojected CountryEEZ to EPSG:4326")

# Clip the CountryEEZ to the reef boundaries extent for performance
print("Clipping CountryEEZ to reef boundaries extent...")
reef_bbox = reef_features.total_bounds
country_eez_clipped = country_eez[country_eez.geometry.intersects(
    gpd.GeoSeries([box(*reef_bbox)], crs=reef_features.crs).geometry[0]
)]
print(f"Clipped CountryEEZ from {len(country_eez)} to {len(country_eez_clipped)} features.")

# Add new columns to reef features
reef_features['Sovereign1'] = None
reef_features['Sovereign2'] = None
reef_features['Sov1_Perc'] = 0
reef_features['Sov2_Perc'] = 0
reef_features['Union'] = None

# Add a check for invalid geometries before processing
print("Checking for invalid or null geometries...")
null_geom_count = reef_features[reef_features.geometry.isna()].shape[0]
if null_geom_count > 0:
    print(f"WARNING: Found {null_geom_count} features with null geometries.")
    null_geom_indices = reef_features[reef_features.geometry.isna()].index.tolist()
    print(f"Indices with null geometries: {null_geom_indices}")
    
    # Optional: Remove features with null geometries
    reef_features = reef_features[~reef_features.geometry.isna()].copy()
    print(f"Removed {null_geom_count} features. Continuing with {len(reef_features)} valid features.")

# Debug: Print the attribute names of the country_eez_clipped
print(f"CountryEEZ attributes: {list(country_eez_clipped.columns)}")

# Process each reef feature
print(f"Processing {len(reef_features)} reef features...")
start_time = time.time()

for i, reef in tqdm(reef_features.iterrows(), total=len(reef_features)):
    # Add safety check for None geometry
    if reef.geometry is None:
        print(f"WARNING: Feature at index {i} has None geometry. Skipping...")
        reef_features.at[i, 'Sovereign1'] = 'Unknown (Invalid Geometry)'
        reef_features.at[i, 'Sov1_Perc'] = 0
        reef_features.at[i, 'Union'] = 'Unknown (Invalid Geometry)'
        continue
    
    # Find intersections with CountryEEZ
    intersections = []
    total_area = reef.geometry.area

    
    
    for j, eez in country_eez_clipped.iterrows():
        if reef.geometry.intersects(eez.geometry):
            intersection = reef.geometry.intersection(eez.geometry)
            if not intersection.is_empty:
                area = intersection.area
                percentage = round((area / total_area) * 100)  # Round to integer
                intersections.append({
                    'Union': eez['UNION'],
                    'Sovereign1': eez['SOVEREIGN1'],
                    'area': area,
                    'percentage': percentage
                })

    # Sort by area descending
    intersections = sorted(intersections, key=lambda x: x['area'], reverse=True)
    
    if len(intersections) == 0:
        # No intersections found (reef might be outside of all EEZs)
        reef_features.at[i, 'Sovereign1'] = 'International Waters'
        reef_features.at[i, 'Sov1_Perc'] = 100
        reef_features.at[i, 'Union'] = 'International Waters'

    elif len(intersections) == 1:
        # Single country
        reef_features.at[i, 'Sovereign1'] = intersections[0]['Sovereign1']
        reef_features.at[i, 'Sov1_Perc'] = 100
        reef_features.at[i, 'Union'] = intersections[0]['Union']

    elif len(intersections) == 2:
        # Two countries
        reef_features.at[i, 'Sovereign1'] = intersections[0]['Sovereign1']
        reef_features.at[i, 'Sovereign2'] = intersections[1]['Sovereign1']
        reef_features.at[i, 'Sov1_Perc'] = intersections[0]['percentage'] 
        reef_features.at[i, 'Sov2_Perc'] = intersections[1]['percentage']
        reef_features.at[i, 'Union'] = f"{intersections[0]['Union']};{intersections[1]['Union']}"

    else:
        # More than two countries - check for duplicate sovereigns to consolidate
        print(f"Feature {i} intersects with {len(intersections)} country regions:")
        for idx, item in enumerate(intersections):
            print(f"  {idx+1}. {item['Sovereign1']} ({item['percentage']}%) - {item['Union']}")
        
        # Consolidate intersections with the same sovereign country
        sovereign_dict = {}
        union_values = set()
        
        for item in intersections:
            sovereign = item['Sovereign1']
            union_values.add(item['Union'])
            
            if sovereign in sovereign_dict:
                # Add to existing sovereign entry
                sovereign_dict[sovereign]['area'] += item['area']
                sovereign_dict[sovereign]['percentage'] += item['percentage']
            else:
                # Create new sovereign entry
                sovereign_dict[sovereign] = {
                    'Sovereign1': sovereign,
                    'area': item['area'],
                    'percentage': item['percentage']
                }
        
        # Convert back to a list and sort by area
        consolidated = list(sovereign_dict.values())
        consolidated = sorted(consolidated, key=lambda x: x['area'], reverse=True)
        
        if len(consolidated) <= 2:
            print(f"  After consolidating duplicate sovereigns: {len(consolidated)} unique countries")
            # We can use our standard two-country approach with the consolidated data
            reef_features.at[i, 'Sovereign1'] = consolidated[0]['Sovereign1']
            reef_features.at[i, 'Sov1_Perc'] = round(consolidated[0]['percentage'])
            
            if len(consolidated) == 2:
                reef_features.at[i, 'Sovereign2'] = consolidated[1]['Sovereign1']
                reef_features.at[i, 'Sov2_Perc'] = round(consolidated[1]['percentage'])
            
            # Still preserve all UNION values
            reef_features.at[i, 'Union'] = ";".join(union_values)
        else:
            print(f"  Warning: Feature {i} still has {len(consolidated)} unique countries after consolidation")
            # Take the top two countries by area
            reef_features.at[i, 'Sovereign1'] = consolidated[0]['Sovereign1']
            reef_features.at[i, 'Sovereign2'] = consolidated[1]['Sovereign1']
            reef_features.at[i, 'Sov1_Perc'] = round(consolidated[0]['percentage'])
            reef_features.at[i, 'Sov2_Perc'] = round(consolidated[1]['percentage'])
            reef_features.at[i, 'Union'] = ";".join(union_values)

# Save the updated shapefile
output_path = "working/04/TS-GBR-CS-NW-Features-Country.shp"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
reef_features.to_file(output_path)

elapsed_time = time.time() - start_time
print(f"Processing completed in {elapsed_time:.2f} seconds.")
print(f"Updated reef features saved to: {output_path}")

# Print summary statistics
Sovereign1_counts = reef_features['Sovereign1'].value_counts()
print("\nSummary of primary sovereign countries:")
for country, count in Sovereign1_counts.items():
    print(f"  {country}: {count} features")

print("\nFeatures with secondary sovereign countries:")
secondary_count = reef_features['Sovereign2'].notna().sum()
print(f"  {secondary_count} features ({secondary_count/len(reef_features)*100:.2f}%)")
