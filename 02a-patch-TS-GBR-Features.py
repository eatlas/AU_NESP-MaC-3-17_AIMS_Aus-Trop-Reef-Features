"""
Australian Tropical Reef Feature Patching Script
===============================================

This script applies spatial and attribute corrections to the Torres Strait and 
Great Barrier Reef Features dataset (TS-GBR-Features). It processes three input files:

1. TS-GBR-Features: Contains the original feature geometries and attributes
2. Override Points: Point shapefile specifying which features to modify and how
3. Extra Features: Replacement and additional geometries to be added to the dataset

The original TS-GBR-Features dataset as a CODE attributes that is 'mostly' a unique
identifier for each feature. 

The 'Complete-GBR-FeatType-Override' contains points that indicate overrides of the
original types (Bank, Rock)and instructions for modifications (Move, Remove, Reshape, Merge).
These points are linked with the input TS-GBR-Features dataset via a spatial join, i.e. 
the points are matched with the features they intersect. 

The 'Complete-GBR-ExtraFeatures' contains additional features that correspond to modifications
or additional features. Where there is a Move, Reshape, or Merge override, the original feature 
is removed and replaced with the ExtraFeature. The attributes of the original features are
matched to the ExtraFeatures based on the CODE attribute. Where an ExtraFeature corresponds to
a new feature (i.e. a new reef), then the CODE attribute is NULL as there is no original feature
to match to.

Processing steps:
----------------
1. Copy attributes from TS-GBR-Features to ExtraFeatures based on matching CODE
2. Find spatial matches between Override points and TS-GBR-Features
   - Apply 'Bank' and 'Rock' overrides (change feature type)
3. Remove features that have 'Merge', 'Move', 'Remove', or 'Reshape' overrides
4. Merge the ExtraFeatures with the updated TS-GBR-Features
   - Set Dataset='Aus-Trop-Reef-Features_v0-1' for all ExtraFeatures
5. Rename attributes and apply classification mapping

Override actions:
----------------
- Bank/Rock: Updates FEAT_NAME of existing feature to specified value
- Remove: Removes feature with no replacement
- Move/Reshape: Removes feature, replaced by ExtraFeature with same CODE
- Merge: Removes multiple features, replaced by one ExtraFeature

Notes:
-----
- Duplicate CODEs in TS-GBR-Features are allowed (multi-part features)
- Multiple overrides with the same action on the same CODE are allowed
- Different override actions on the same CODE will cause an error
- A limitation of this approach is that the reef allocation does not
 consider depth in the RB_Type_L3 classification.

Output: working/02/TS-GBR-Features-patched.shp

Part of: NESP Marine and Coastal Hub Project 3.17
"""

import geopandas as gpd
import pandas as pd
import os
import sys
import configparser
from shapely.geometry import Point
from shapely.ops import unary_union

# Define version
VERSION = "v0-1"

# Read configuration from config.ini
config = configparser.ConfigParser()
config.read('config.ini')
download_path = config.get('general', 'in_3p_path')

# Define paths
base_path = f"data/{VERSION}"
ts_gbr_path = os.path.join(download_path, "TS-GBR-Feat", "TS_AIMS_NESP_Torres_Strait_Features_V1b_with_GBR_Features.shp")
override_path = os.path.join(base_path, "in", "Complete-GBR-FeatType-Override.shp")
extra_features_path = os.path.join(base_path, "in", "Complete-GBR-ExtraFeatures.shp")
# rb_type_lut_path = os.path.join(base_path, "in", "RB_Type_L3_Classification.csv")
rb_type_lut_path = os.path.join(download_path, "NW-Aus-Feat_v0-4", "in", "RB_Type_L3_crosswalk.csv")
output_dir = "working/02"
output_path = os.path.join(output_dir, "TS-GBR-Features-patched.shp")

def load_classification_lookup(csv_path):
    """
    Load the classification lookup table from CSV and create a mapping dictionary
    from all aliases (GBR_Features_FEAT_NAME and TS_Features_LEVEL_3) to their corresponding RB_Type_L3_v0-4 values.
    Output attribute remains 'RB_Type_L3'.
    """
    print(f"Loading classification lookup table from {csv_path}")
    try:
        df = pd.read_csv(csv_path)
        mapping = {}

        # For each row, combine aliases from GBR_Features_FEAT_NAME and TS_Features_LEVEL_3
        for _, row in df.iterrows():
            rb_type = row['RB_Type_L3_v0-4']
            # GBR_Features_FEAT_NAME (may be semicolon separated)
            if pd.notna(row.get('GBR_Features_FEAT_NAME')):
                for alias in str(row['GBR_Features_FEAT_NAME']).split(';'):
                    alias = alias.strip()
                    if alias:
                        mapping[alias.lower()] = rb_type
            # TS_Features_LEVEL_3 (may be semicolon separated)
            if pd.notna(row.get('TS_Features_LEVEL_3')):
                for ts_alias in str(row['TS_Features_LEVEL_3']).split(';'):
                    ts_alias = ts_alias.strip()
                    if ts_alias:
                        mapping[ts_alias.lower()] = rb_type
            # Also map RB_Type_L3_v0-4 itself for direct matching
            if pd.notna(rb_type):
                mapping[str(rb_type).lower()] = rb_type

        print(f"Loaded {len(mapping)} classification aliases (including direct RB_Type_L3 matches)")
        return mapping
    except Exception as e:
        print(f"Error loading classification lookup table: {e}")
        sys.exit(1)

def map_feature_classification(classification_mapping, feat_name, level_3=None):
    """
    Map feature classifications using the lookup table.
    First tries LEVEL_3 if available, then falls back to FEAT_NAME.
    Handles both direct RB_Type_L3 matches and alias matches.
    """
    # Determine the best classification to use
    classification = None
    source = None
    
    if pd.notna(level_3) and level_3.strip():
        classification = level_3.strip()
        source = "LEVEL_3"
    elif pd.notna(feat_name) and feat_name.strip():
        classification = feat_name.strip()
        source = "FEAT_NAME"
    else:
        return None, "No valid classification found"
    
    # Look up the classification in the mapping
    rb_type = classification_mapping.get(classification.lower())
    
    if rb_type is None:
        return None, f"No mapping found for '{classification}' from {source}"
    
    return rb_type, source

def main():
    print(f"Starting patching process for {VERSION}")
    print(f"Using TS-GBR features from: {ts_gbr_path}")
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Load the datasets
    print("Loading datasets...")
    try:
        ts_gbr_features = gpd.read_file(ts_gbr_path)
        override_points = gpd.read_file(override_path)
        extra_features = gpd.read_file(extra_features_path)
        classification_mapping = load_classification_lookup(rb_type_lut_path)
        # Ensure CRS is set (GDA94 EPSG:4283 if missing). GeoPandas
        # seems to not reliably set CRS automatically.
        if ts_gbr_features.crs is None:
            print("  Setting CRS to EPSG:4283 (GDA94) for input features...")
            ts_gbr_features.set_crs(epsg=4283, inplace=True)
        if extra_features.crs is None:
            extra_features.set_crs(epsg=4283, inplace=True)
        if override_points.crs is None:
            override_points.set_crs(epsg=4283, inplace=True)
    except Exception as e:
        print(f"Error loading datasets: {e}")
        sys.exit(1)
    
    print(f"Loaded {len(ts_gbr_features)} TS-GBR features")
    print(f"Loaded {len(override_points)} override points")
    print(f"Loaded {len(extra_features)} extra features")
    
    # --- Save a copy of island/mainland features for later attachment calculation ---
    print("\nSaving island/mainland features for later attachment calculation...")
    island_mainland_mask = ts_gbr_features['FEAT_NAME'].isin(['Island', 'Mainland'])
    islands_mainland = ts_gbr_features[island_mainland_mask].copy()
    
    # Remove features with FEAT_NAME='Island', 'Mainland', 'Other' early in the process
    print("\nRemoving features with FEAT_NAME='Island', 'Mainland', or 'Other'...")
    original_count = len(ts_gbr_features)
    ts_gbr_features = ts_gbr_features[~ts_gbr_features['FEAT_NAME'].isin(['Island', 'Mainland', 'Other'])]
    removed_count = original_count - len(ts_gbr_features)
    print(f"  Removed {removed_count} features with FEAT_NAME='Island', 'Mainland', or 'Other'")
    
    # Check for duplicate CODEs in TS-GBR-Features - but only warn, don't exit
    print("\nChecking for duplicate CODEs in TS-GBR-Features...")
    code_counts = ts_gbr_features['CODE'].value_counts()
    duplicate_codes = code_counts[code_counts > 1]
    if not duplicate_codes.empty:
        print(f"WARNING: Found duplicate CODEs in TS-GBR-Features: {duplicate_codes.index.tolist()}")
        print(f"These are likely multi-part features that have been split. Using first instance for each.")
    
    # Step 1: Copy attributes from TS-GBR-Features to ExtraFeatures based on CODE
    print("\nStep 1: Copying attributes from TS-GBR-Features to ExtraFeatures...")
    # Create a dictionary of CODE to attributes from ts_gbr_features
    # For duplicates, this will use the first occurrence of each CODE
    ts_gbr_dict = {}
    for _, row in ts_gbr_features.iterrows():
        if pd.notna(row['CODE']) and row['CODE'] not in ts_gbr_dict:
            ts_gbr_dict[row['CODE']] = row
    
    # Create a copy of extra_features to hold the updated data
    extra_features_with_attrs = extra_features.copy()
    
    # List to store extra features with no matching CODE
    no_match_codes = []
    
    # Copy attributes from ts_gbr_features to extra_features_with_attrs
    for idx, row in extra_features_with_attrs.iterrows():
        code = row['CODE']
        if pd.notna(code) and code in ts_gbr_dict:
            print(f"  Copying attributes for ExtraFeature with CODE {code}")
            # Copy all attributes except geometry and FEAT_NAME
            for col in ts_gbr_features.columns:
                if col not in ['geometry', 'FEAT_NAME']:
                    extra_features_with_attrs.at[idx, col] = ts_gbr_dict[code][col]
        elif pd.notna(code):  # Only report if CODE is not empty/null
            no_match_codes.append(code)
            print(f"  No matching CODE {code} found in TS-GBR-Features")
    
    if no_match_codes:
        print(f"WARNING: {len(no_match_codes)} ExtraFeature records with no matching CODE in TS-GBR-Features")
    
    # Step 2: Determine spatial matches between Override points and TS-GBR-Features
    print("\nStep 2: Finding spatial matches between Override points and TS-GBR-Features...")
    # Dictionary to track which features are affected by overrides
    affected_features = {}
    
    # Create a spatial index for ts_gbr_features to speed up spatial queries
    ts_gbr_sindex = ts_gbr_features.sindex
    
    # Identify features that intersect with override points
    for idx, override_point in override_points.iterrows():
        point_geom = override_point.geometry
        
        # Use spatial index to find potential matches
        possible_matches_idx = list(ts_gbr_sindex.intersection(point_geom.bounds))
        possible_matches = ts_gbr_features.iloc[possible_matches_idx]
        
        # Refine to exact matches
        matches = possible_matches[possible_matches.contains(point_geom)]
        
        if len(matches) == 0:
            print(f"WARNING: Override point {idx} (type: {override_point['FEAT_NAME']}) does not intersect any feature")
            continue
        
        if len(matches) > 1:
            print(f"WARNING: Override point {idx} intersects multiple features. Using the first match.")
        
        # Get the first (or only) match
        match_idx = matches.index[0]
        match_code = matches.at[match_idx, 'CODE']
        
        # Check if this feature has already been affected by an override
        if match_code in affected_features:
            # Allow multiple overrides with the same action on the same CODE
            # (This happens when a feature is split into multiple parts with the same CODE)
            if affected_features[match_code] == override_point['FEAT_NAME']:
                print(f"Note: Multiple {override_point['FEAT_NAME']} overrides affecting feature with CODE {match_code}")
            else:
                # Still an error if different actions are trying to affect the same CODE
                print(f"ERROR: Feature with CODE {match_code} is affected by conflicting overrides: "
                      f"{affected_features[match_code]} and {override_point['FEAT_NAME']}")
                sys.exit(1)
        
        # Record this override
        affected_features[match_code] = override_point['FEAT_NAME']
        
        # For 'Bank' and 'Rock' overrides, update the FEAT_NAME
        if override_point['FEAT_NAME'] in ['Bank', 'Rock']:
            print(f"  Updating FEAT_NAME to {override_point['FEAT_NAME']} for feature with CODE {match_code}")
            ts_gbr_features.loc[match_idx, 'FEAT_NAME'] = override_point['FEAT_NAME']
    
    # Step 3: Remove features that match with 'Merge', 'Move', 'Remove', 'Reshape' overrides
    print("\nStep 3: Removing features as specified by the overrides...")
    removal_codes = [code for code, action in affected_features.items() 
                    if action in ['Merge', 'Move', 'Remove', 'Reshape']]
    
    if removal_codes:
        print(f"  Removing {len(removal_codes)} features with actions: Merge, Move, Remove, Reshape")
        for code in removal_codes:
            print(f"  - Removing feature with CODE {code} (action: {affected_features[code]})")
        
        # Create a copy before filtering to report correct counts
        original_count = len(ts_gbr_features)
        ts_gbr_features = ts_gbr_features[~ts_gbr_features['CODE'].isin(removal_codes)]
        print(f"  Removed {original_count - len(ts_gbr_features)} features")
    else:
        print("  No features to remove")
    
    # Step 4: Merge the ExtraFeatures-with-attributes dataset with the updated TS-GBR-Features
    print("\nStep 4: Merging ExtraFeatures with updated TS-GBR-Features...")
    valid_extra_features = extra_features_with_attrs[pd.notna(extra_features_with_attrs['FEAT_NAME'])].copy()
    print(f"  Adding {len(valid_extra_features)} features from ExtraFeatures")
    # Ensure both dataframes use 'Dataset' and not 'DATASET'
    if 'DATASET' in valid_extra_features.columns:
        valid_extra_features = valid_extra_features.rename(columns={'DATASET': 'Dataset'})
    if 'DATASET' in ts_gbr_features.columns:
        ts_gbr_features = ts_gbr_features.rename(columns={'DATASET': 'Dataset'})
    # Set Dataset for added features
    valid_extra_features['Dataset'] = 'Aus-Trop-Reef-Features_v0-1'
    merged_features = gpd.GeoDataFrame(pd.concat([ts_gbr_features, valid_extra_features], ignore_index=True))

    # Add FeatConf and TypeConf: 'High' if override or extra feature, else None
    print("\nAssigning 'FeatConf' and 'TypeConf' attributes based on override or extra feature status...")
    # Get set of override CODEs
    override_codes = set(affected_features.keys())
    # Indices of extra features (those after the original ts_gbr_features)
    extra_feature_indices = set(merged_features.index[merged_features.index >= len(ts_gbr_features)])
    # Indices of features with override (by CODE)
    override_indices = set(idx for idx, row in merged_features.iterrows() if pd.notna(row.get('CODE')) and row.get('CODE') in override_codes)
    # Union of all indices to set as 'High'
    high_conf_indices = override_indices | extra_feature_indices

    # Set FeatConf and TypeConf
    merged_features['FeatConf'] = None
    merged_features['TypeConf'] = merged_features.get('TypeConf', None)
    for idx in high_conf_indices:
        merged_features.at[idx, 'FeatConf'] = 'High'
        merged_features.at[idx, 'TypeConf'] = 'High'

    # --- Attachment assignment step (after merging) ---
    print("\nAssigning 'Attachment' attribute (Fringing/Isolated) to merged features...")
    # Project to EPSG:3577 for buffering
    orig_crs = merged_features.crs
    if orig_crs is None or orig_crs.to_string() != "EPSG:3577":
        print("  Reprojecting merged features and islands/mainland to EPSG:3577 for buffering...")
        merged_features_3577 = merged_features.to_crs(epsg=3577)
        islands_mainland_3577 = islands_mainland.to_crs(epsg=3577)
    else:
        merged_features_3577 = merged_features
        islands_mainland_3577 = islands_mainland

    # Buffer islands/mainland by 200m
    print("  Buffering island/mainland features by 200m...")
    from shapely.ops import unary_union
    buffer_union = unary_union(islands_mainland_3577.buffer(200))

    # Assign Attachment
    print("  Assigning 'Attachment' values...")
    def attachment_func(geom, idx):
        if geom is None:
            print(f"ERROR: Feature at index {idx} has geometry=None.")
            print("Use QGIS Attribute Table > Select by Expression > is_empty($geometry) OR $geometry IS NULL")
            raise ValueError(f"Feature at index {idx} has geometry=None")
        return 'Fringing' if geom.intersects(buffer_union) else 'Isolated'
    # Use enumerate to provide index for debugging
    merged_features_3577['Attachment'] = [
        attachment_func(geom, idx) for idx, geom in enumerate(merged_features_3577.geometry)
    ]

    # Restore CRS if needed
    if orig_crs is None or orig_crs.to_string() != "EPSG:3577":
        merged_features = merged_features_3577.to_crs(orig_crs)
    else:
        merged_features = merged_features_3577

    # --- EdgeAcc_m assignment step ---
    print("\nAssigning 'EdgeAcc_m' attribute based on feature area and source...")

    # Calculate area in km^2 for each feature (project to EPSG:3577 for area calculation)
    merged_features_area = merged_features.to_crs(epsg=3577).geometry.area / 1e6  # m^2 to km^2

    # Identify features added from ExtraFeatures (those after the original ts_gbr_features)
    extra_feature_mask = merged_features.index >= len(ts_gbr_features)
    edge_acc_values = []

    for idx, area_km2 in enumerate(merged_features_area):
        is_extra = extra_feature_mask[idx]
        if is_extra:
            # FeatType-Override/ExtraFeatures table
            if area_km2 > 1:
                edge_acc = 150
            elif area_km2 > 0.1:
                edge_acc = 80
            else:
                edge_acc = 50
        else:
            # All other features table
            if area_km2 > 30:
                edge_acc = 800
            elif area_km2 > 10:
                edge_acc = 600
            elif area_km2 > 1:
                edge_acc = 300
            elif area_km2 > 0.1:
                edge_acc = 200
            else:
                edge_acc = 150
        edge_acc_values.append(edge_acc)

    merged_features['EdgeAcc_m'] = edge_acc_values

    # Step 5: Rename attributes and apply classification mapping
    print("\nStep 5: Renaming attributes and applying classification mapping...")
    
    # Rename attributes in merged features
    print("  Renaming attributes...")
    merged_features = merged_features.rename(columns={
        'IMG_SRC': 'EdgeSrc',
        'QLD_NAME': 'Name',
        'TRAD_NAME': 'OtherNames',
        'LABEL_ID': 'ReefID'
    })
    
    # Set TypeConf from CLASS_CONF where CLASS_CONF is not null
    if 'CLASS_CONF' in merged_features.columns:
        merged_features.loc[merged_features['CLASS_CONF'].notnull(), 'TypeConf'] = merged_features['CLASS_CONF']
        merged_features = merged_features.drop(columns=['CLASS_CONF'])
    
    # Set EdgeSrc for features from ExtraFeatures to 'S2 All Tide'
    print("  Setting EdgeSrc for added features...")
    # Identify rows from extra_features by checking their indices against the original dataframe
    extra_feature_indices = merged_features.index[merged_features.index >= len(ts_gbr_features)]
    merged_features.loc[extra_feature_indices, 'EdgeSrc'] = 'S2 All Tide'
    
    # Add OrigType attribute to preserve the most detailed original type
    print("  Adding OrigType attribute...")
    merged_features['OrigType'] = None
    
    for idx, row in merged_features.iterrows():
        if pd.notna(row.get('LEVEL_3')) and row.get('LEVEL_3').strip():
            merged_features.at[idx, 'OrigType'] = row['LEVEL_3'].strip()
        elif pd.notna(row.get('FEAT_NAME')) and row.get('FEAT_NAME').strip():
            merged_features.at[idx, 'OrigType'] = row['FEAT_NAME'].strip()
    
    # Apply classification mapping
    print("  Applying classification mapping...")
    # Add RB_Type_L3 column if it doesn't exist
    if 'RB_Type_L3' not in merged_features.columns:
        merged_features['RB_Type_L3'] = None
    
    # Track unmapped classifications for reporting
    unmapped = {}
    
    # Apply mapping to each feature
    for idx, row in merged_features.iterrows():
        rb_type, source = map_feature_classification(
            classification_mapping, 
            row.get('FEAT_NAME'), 
            row.get('LEVEL_3')
        )
        
        if rb_type is not None:
            merged_features.at[idx, 'RB_Type_L3'] = rb_type
        else:
            # Track unmapped classifications for reporting
            if source not in unmapped:
                unmapped[source] = set()
            
            if "No valid classification" in source:
                unmapped[source].add("Empty or NULL value")
            else:
                classification = row.get('LEVEL_3') if "LEVEL_3" in source else row.get('FEAT_NAME')
                unmapped[source].add(classification)
    
    # Report unmapped classifications
    if unmapped:
        print("\nWARNING: Could not map some classifications:")
        for source, values in unmapped.items():
            print(f"  From {source}: {', '.join(str(v) for v in values)}")
        print("Please update the classification lookup table to include these values.")
        # Generate error if mapping failed
        sys.exit(1)
    
    # Remove unnecessary attributes
    print("\nRemoving unnecessary attributes...")
    columns_to_remove = [
        'TARGET_FID', 'LOC_NAME_S', 'GBR_NAME', 'CHART_NAME', 'TRAD_NAME', 
        'UN_FEATURE', 'SORT_GBR_I', 'FEAT_NAME', 'LEVEL_1', 'LEVEL_2', 'LEVEL_3',
        'CLASS_SRC', 'POLY_ORIG', 'SUB_NO', 'CODE', 'FEATURE_C', 'X_LABEL', 
        'GBR_ID', 'LOC_NAME_L', 'X_COORD', 'Y_COORD', 'SHAPE_AREA', 'SHAPE_LEN',
        'Checked', 'RegionID', 'LatitudeID', 'GroupID', 'UNIQUE_ID','PriorityLb','OtherNames',
        'Name','Country'
    ]
    # Do not remove 'Attachment' or 'Dataset'
    columns_to_remove = [col for col in columns_to_remove if col in merged_features.columns and col not in ['Dataset', 'Attachment']]
    if columns_to_remove:
        print(f"  Removing {len(columns_to_remove)} unnecessary attributes")
        merged_features = merged_features.drop(columns=columns_to_remove)


    # Save the result
    print(f"\nSaving {len(merged_features)} features to {output_path}")
    merged_features.to_file(output_path)
    
    print("Patching process completed successfully")

if __name__ == "__main__":
    main()