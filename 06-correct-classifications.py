"""
Classification Correction Script
-------------------------------

PURPOSE:
    This script corrects the RB_Type_L3 classification based on depth information.
    For features belonging to specified datasets, it changes 'Platform Coral Reef'
    to 'Deep Platform Coral Reef' when the DepthCat is 'Deep'.
    
    Then, it handles alias mapping for RB_Type_L3 values by converting any values 
    that match an alias in the LUT to their proper classification.
    
    Finally, using the LUT table, it populates additional classification fields
    (RB_Type_L1, RB_Type_L2, NvclEco, NvclEcoCom, and Position) for features
    where these values are currently NULL.

INPUTS:
    - Shapefile output from 05-add-depth.py with depth categories
    - Classification LUT table at data/v0-1/in/RB_Type_L3_Classification.csv

OUTPUTS:
    - Shapefile with corrected RB_Type_L3 classifications and populated additional fields

ALGORITHM:
    1. Load the shapefile from the previous processing step
    2. For each feature in the specified datasets ('GBR Features', 'TS Features', 'Aus Trop Reef Features'):
       a. Check if RB_Type_L3 is 'Platform Coral Reef' and DepthCat is 'Deep'
       b. If both conditions are met, update RB_Type_L3 to 'Deep Platform Coral Reef'
    3. Load the classification LUT table
    4. Create alias mapping from the LUT's 'Aliases' column
    5. Update any RB_Type_L3 values that match an alias to their correct classification
    6. For each feature, if it has a valid RB_Type_L3 value but NULL values for related fields:
       a. Look up the corresponding values in the LUT
       b. Populate the NULL fields with the looked-up values
    7. Save the updated dataset to a new shapefile
"""

import os
import geopandas as gpd
import pandas as pd
import numpy as np

# Define input and output paths
INPUT_SHAPE = "working/05/TS-GBR-CS-NW-Features-depth.shp"
OUTPUT_DIR = "working/06"
OUTPUT_SHAPE = os.path.join(OUTPUT_DIR, "TS-GBR-CS-NW-Features-corrected.shp")
LUT_PATH = "data/v0-1/in/RB_Type_L3_Classification.csv"

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

def main():
    print(f"Reading shapefile from {INPUT_SHAPE}")
    features = gpd.read_file(INPUT_SHAPE)
    
    # Count features before modification
    original_platform_reefs = len(features[features['RB_Type_L3'] == 'Platform Coral Reef'])
    
    # Target datasets
    target_datasets = ['GBR Features', 'TS Features', 'Aus Trop Reef Features']
    
    # Initialize counters
    changes_made = 0
    total_checked = 0
    
    print("Correcting classifications...")
    # Iterate through features and make corrections
    for idx, feature in features.iterrows():
        # Check if feature belongs to one of the target datasets
        if feature.get('DATASET') in target_datasets:
            # Check if it's a platform reef that needs to be reclassified
            if feature.get('RB_Type_L3') == 'Platform Coral Reef' and feature.get('DepthCat') == 'Deep':
                # Update the classification
                features.at[idx, 'RB_Type_L3'] = 'Deep Platform Coral Reef'
                changes_made += 1
            
            # Count the feature as checked
            if feature.get('RB_Type_L3') == 'Platform Coral Reef':
                total_checked += 1
    
    # Count features after modification
    updated_platform_reefs = len(features[features['RB_Type_L3'] == 'Platform Coral Reef'])
    deep_platform_reefs = len(features[features['RB_Type_L3'] == 'Deep Platform Coral Reef'])
    
    # Load the LUT table
    print(f"Loading classification LUT from {LUT_PATH}")
    try:
        lut = pd.read_csv(LUT_PATH)
        print(f"Loaded LUT with {len(lut)} classifications")
        
        # Build alias mapping dictionary
        alias_mapping = {}
        print("Building alias mapping from LUT...")
        for _, row in lut.iterrows():
            rb_type_l3 = row['RB_Type_L3']
            aliases = row.get('Aliases', '')
            
            if not pd.isna(aliases) and aliases.strip():
                # Split the aliases by semicolon and trim whitespace
                alias_list = [alias.strip() for alias in aliases.split(';') if alias.strip()]
                
                # Add each alias to the mapping dictionary
                for alias in alias_list:
                    alias_mapping[alias] = rb_type_l3
        
        # Count how many aliases were found
        print(f"Found {len(alias_mapping)} unique aliases in the LUT")
        
        # Initialize counter for alias corrections
        alias_corrections = 0
        
        # First pass: correct RB_Type_L3 values based on aliases
        print("Correcting RB_Type_L3 values based on aliases...")
        for idx, feature in features.iterrows():
            rb_type_l3 = feature.get('RB_Type_L3')
            
            # Skip if NULL
            if not rb_type_l3 or pd.isna(rb_type_l3):
                continue
            
            # Check if the RB_Type_L3 value matches an alias
            if rb_type_l3 in alias_mapping:
                # Update to the correct RB_Type_L3 value
                correct_type = alias_mapping[rb_type_l3]
                features.at[idx, 'RB_Type_L3'] = correct_type
                alias_corrections += 1
        
        # Report on alias corrections
        if alias_corrections > 0:
            print(f"Corrected {alias_corrections} features with mapped aliases")
        
        # Convert LUT to dictionary for easy lookup
        # Use RB_Type_L3 as the key
        lut_dict = {}
        for _, row in lut.iterrows():
            lut_dict[row['RB_Type_L3']] = {
                'RB_Type_L1': row['RB_Type_L1'],
                'RB_Type_L2': row['RB_Type_L2'],
                'NvclEco': row['NvclEco'],
                'NvclEcoCom': row['NvclEcoCom'],
                'Position': row['Position']
            }
        
        # Initialize counters for LUT updates
        lut_fields = ['RB_Type_L1', 'RB_Type_L2', 'NvclEco', 'NvclEcoCom', 'Position']
        field_update_counts = {field: 0 for field in lut_fields}
        total_features_updated = 0
        
        print("Populating additional classification fields from LUT...")
        # Update NULL fields using the LUT
        for idx, feature in features.iterrows():
            rb_type_l3 = feature.get('RB_Type_L3')
            
            # Skip if RB_Type_L3 is not in the LUT
            if not rb_type_l3 or rb_type_l3 not in lut_dict:
                continue
            
            # Flag to track if this feature was updated
            feature_updated = False
            
            # Check each field and update if NULL
            for field in lut_fields:
                # Check if field is NULL (None, NaN, or empty string)
                is_null = (pd.isna(feature.get(field)) or 
                           feature.get(field) is None or 
                           feature.get(field) == '')
                
                if is_null and rb_type_l3 in lut_dict:
                    # Update the field with the LUT value
                    features.at[idx, field] = lut_dict[rb_type_l3][field]
                    field_update_counts[field] += 1
                    feature_updated = True
            
            # Increment the total features updated counter if any field was updated
            if feature_updated:
                total_features_updated += 1
        
    except Exception as e:
        print(f"Warning: Could not load or apply LUT: {e}")
    
    # Save the updated shapefile
    print(f"Saving output shapefile to {OUTPUT_SHAPE}")
    features.to_file(OUTPUT_SHAPE)
    
    # Print summary
    print(f"\nClassification correction summary:")
    print(f"Total features processed: {len(features)}")
    print(f"Platform Coral Reef features checked: {total_checked}")
    print(f"Features changed to 'Deep Platform Coral Reef': {changes_made}")
    print(f"Final count of 'Platform Coral Reef': {updated_platform_reefs}")
    print(f"Final count of 'Deep Platform Coral Reef': {deep_platform_reefs}")
    
    # Print alias correction summary
    if 'alias_corrections' in locals():
        print(f"Features with RB_Type_L3 corrected via aliases: {alias_corrections}")
    
    # Print LUT update summary
    print(f"\nLUT classification field update summary:")
    print(f"Total features updated with LUT values: {total_features_updated}")
    for field, count in field_update_counts.items():
        print(f"  {field}: {count} features updated")
    
    print("Done!")

if __name__ == "__main__":
    main()
