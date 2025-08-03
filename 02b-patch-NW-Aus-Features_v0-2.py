"""
NW Australia Features Attribute Normalization for v0-2

Later versions of the input dataset don't need the same level of normalisation
because corrections were applied in the source dataset.

This script normalizes the attribute names in the NW Australia Reef Features shapefile.
It reads the input shapefile from the configured third-party data directory,
renames specified attributes to conform to standardized naming conventions,
and saves the result to the working directory.

Attribute Renaming:
- 'ImgSrc' → 'EdgeSrc' 
- 'Edg_acc' → 'EdgeAcc_m'
- 'Type' → 'RB_Type_L3'
- 'TypeConf' remains unchanged

Additional processing:
- Clips reef features against the coastline to remove overlapping land areas

Input: {in_3p_path}/NW-Aus-Feat/Reef-boundaries-v0-2/Reef Boundaries Review RB.shp
Coastline: {in_3p_path}/Coastline50k/Split/AU_NESP-MaC-3-17_AIMS_Aus-Coastline-50k_2024_V1-1_split.shp
Output: working/02/NW-Aus-Features-patched.shp
"""

import os
import configparser
import geopandas as gpd
from pathlib import Path
import pandas as pd
import time
from tqdm import tqdm  # For progress tracking
from shapely.validation import make_valid  # Import make_valid function

def apply_coastline_clipping(gdf, coastline_file):
    """
    Applies coastline clipping to remove overlapping land areas from reef features.
    
    Args:
        gdf: GeoDataFrame containing reef features
        coastline_file: Path to the coastline shapefile
        
    Returns:
        GeoDataFrame with clipped geometries
    """
    start_time = time.time()
    
    # Read the coastline data
    print(f"Reading coastline shapefile from: {coastline_file}")
    coastline_gdf = gpd.read_file(coastline_file)
    print(f"Coastline CRS: {coastline_gdf.crs}")
    print(f"Loaded {len(coastline_gdf)} coastline features in {time.time() - start_time:.2f} seconds")
    
    # Ensure coastline is in EPSG:4326
    if coastline_gdf.crs and coastline_gdf.crs != "EPSG:4326":
        print(f"Converting coastline from {coastline_gdf.crs} to EPSG:4326")
        coastline_gdf = coastline_gdf.to_crs(epsg=4326)
    
    # Validate coastline geometries
    print("Validating coastline geometries...")
    invalid_coast_count = 0
    for i, geom in enumerate(coastline_gdf.geometry):
        if not geom.is_valid:
            coastline_gdf.loc[i, 'geometry'] = make_valid(geom)
            invalid_coast_count += 1
    print(f"Fixed {invalid_coast_count} invalid coastline geometries")
    
    # Clip the reef features against the coastline
    print(f"Clipping {len(gdf)} reef features against the coastline...")
    
    # Create a unified coastline geometry
    print("Creating coastline union for clipping (this may take a while)...")
    coast_start_time = time.time()
    coastline_union = coastline_gdf.unary_union
    print(f"Coastline union created in {time.time() - coast_start_time:.2f} seconds")
    
    # Function to clip a geometry against the coastline
    def clip_geometry(geom):
        if geom is None:
            return None
        try:
            # Make sure the geometry is valid before clipping
            if not geom.is_valid:
                geom = make_valid(geom)
                
            # Perform the difference operation (remove land areas)
            clipped = geom.difference(coastline_union)
            
            # Validate the resulting geometry
            if not clipped.is_empty and not clipped.is_valid:
                clipped = make_valid(clipped)
                
            # Return None if the result is empty
            if clipped.is_empty:
                return None
            return clipped
        except Exception as e:
            print(f"Error in clipping: {e}")
            # Try to recover using make_valid rather than returning the original
            try:
                valid_geom = make_valid(geom)
                return valid_geom.difference(coastline_union)
            except Exception:
                return geom
    
    # Perform the clipping with progress bar
    print("Clipping features (removing land areas)...")
    clip_start_time = time.time()
    tqdm.pandas(desc="Clipping features")
    gdf['geometry'] = gdf.geometry.progress_apply(clip_geometry)
    print(f"Clipping completed in {time.time() - clip_start_time:.2f} seconds")
    
    # Remove any features that became empty after clipping
    original_count = len(gdf)
    gdf = gdf[~gdf.geometry.isna() & ~gdf.geometry.is_empty]
    removed_count = original_count - len(gdf)
    print(f"Removed {removed_count} features that were completely on land")
    
    return gdf

def main(perform_clipping=True):
    """
    Main function to process reef feature geometries.
    
    Args:
        perform_clipping: Boolean flag to enable/disable coastline clipping (default: True)
    """
    start_time = time.time()
    # Read configuration
    config = configparser.ConfigParser()
    config.read('config.ini')
    in_3p_path = config['general']['in_3p_path']
    
    # Define paths
    input_file = os.path.join(in_3p_path, 'NW-Aus-Feat', 'Reef-boundaries-v0-2', 
                             'Reef Boundaries Review RB.shp')
    coastline_file = os.path.join(in_3p_path, 'Coastline50k', 'Split', 
                             'AU_NESP-MaC-3-17_AIMS_Aus-Coastline-50k_2024_V1-1_split.shp')
    output_dir = 'working/02'
    output_file = os.path.join(output_dir, 'NW-Aus-Features-patched.shp')
    
    print(f"Reading shapefile from: {input_file}")
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Read shapefile
    gdf = gpd.read_file(input_file)
    
    # Check the original CRS
    print(f"Original CRS: {gdf.crs}")
    
    # Reproject from EPSG:3857 to EPSG:4326
    if gdf.crs and gdf.crs.to_epsg() == 3857:
        print("Reprojecting from EPSG:3857 (Web Mercator) to EPSG:4326 (WGS84)...")
    else:
        print(f"Warning: Input data is not in EPSG:3857 as expected. Current CRS: {gdf.crs}")
        print("Proceeding with reprojection to EPSG:4326...")
    
    gdf = gdf.to_crs(epsg=4326)
    
    # Validate geometries after reprojection
    print("Validating geometries after reprojection...")
    invalid_count = 0
    invalid_geometries = []
    
    # Identify invalid geometries before fixing them
    for i, geom in enumerate(gdf.geometry):
        if not geom.is_valid:
            # Instead of using validation_reason (which doesn't exist), use explain_validity()
            # This function checks the validity of the geometry and returns a string explanation
            try:
                from shapely.validation import explain_validity
                invalid_reason = explain_validity(geom)
            except (ImportError, AttributeError):
                # Fallback if the function is not available
                invalid_reason = "Invalid geometry (reason unknown)"
            
            # Store the invalid geometry with its index and attributes
            invalid_row = gdf.iloc[i].copy()
            invalid_row['original_index'] = i  # Store the original index for reference
            invalid_row['invalid_reason'] = invalid_reason
            invalid_geometries.append(invalid_row)
            
            # Fix the geometry in the original dataframe
            gdf.loc[i, 'geometry'] = make_valid(geom)
            invalid_count += 1
    
    print(f"Fixed {invalid_count} invalid geometries after reprojection")
    
    # If any invalid geometries were found, save them to a shapefile
    if invalid_geometries:
        invalid_gdf = gpd.GeoDataFrame(invalid_geometries, crs=gdf.crs)
        invalid_output_file = os.path.join(output_dir, 'invalid_geometries_after_reprojection.shp')
        invalid_gdf.to_file(invalid_output_file)
        print(f"Saved {len(invalid_geometries)} invalid geometries to: {invalid_output_file}")
    
    # Confirm new CRS
    print(f"New CRS: {gdf.crs}")
    
    # Show original column names
    print(f"Original columns: {gdf.columns.tolist()}")
    
    # Rename columns
    column_mapping = {
        'ImgSrc': 'EdgeSrc',
        'Edg_acc': 'EdgeAcc_m',
        'Type': 'RB_Type_L3'
        # TypeConf stays the same
    }
    
    # Apply renaming
    gdf = gdf.rename(columns=column_mapping)
    
    # Show renamed column names
    print(f"Renamed columns: {gdf.columns.tolist()}")
    
    # Convert EdgeAcc_m from string to integer, replacing 'NA' with None/NULL
    print(f"Converting 'EdgeAcc_m' from string to integer, handling NA values...")
    # Check the current data type
    print(f"Original EdgeAcc_m data type: {gdf['EdgeAcc_m'].dtype}")
    print(f"Sample values before conversion: {gdf['EdgeAcc_m'].head()}")
    
    # Debug: Find problematic values that can't be directly converted to integers
    problematic_values = set()
    for value in gdf['EdgeAcc_m'].dropna().unique():
        if value == 'NA':
            continue
        try:
            int(value)
        except ValueError:
            problematic_values.add(value)
    
    if problematic_values:
        print(f"Found problematic values that can't be converted directly to integers: {problematic_values}")
    
    # Enhanced conversion strategy to handle specific edge cases
    def safe_convert(x):
        if pd.isna(x) or x == 'NA':
            return None
            
        try:
            return int(x)  # Try direct integer conversion first
        except ValueError:
            # Handle specific cases
            if isinstance(x, str):
                if x.endswith('.'):  # Handle decimal strings like '20.'
                    try:
                        return int(float(x))
                    except ValueError:
                        pass
                
                if '+' in x:  # Handle values like '10+'
                    try:
                        return int(x.replace('+', ''))
                    except ValueError:
                        pass
            
            # If we get here, we couldn't convert the value
            print(f"Unable to convert value: {x}")
            return None
    
    # Track conversion statistics
    conversion_stats = {"success": 0, "null": 0, "failed": 0}
    
    # Apply the enhanced conversion
    def track_convert(x):
        if pd.isna(x) or x == 'NA':
            conversion_stats["null"] += 1
            return None
            
        result = safe_convert(x)
        if result is not None:
            conversion_stats["success"] += 1
        else:
            conversion_stats["failed"] += 1
        return result
    
    # Apply conversion with tracking
    gdf['EdgeAcc_m'] = gdf['EdgeAcc_m'].apply(track_convert).astype('Int64')
    
    # Report conversion statistics
    print(f"Conversion statistics:")
    print(f"  - Successfully converted: {conversion_stats['success']} values")
    print(f"  - Null/NA values: {conversion_stats['null']} values")
    print(f"  - Failed to convert: {conversion_stats['failed']} values")
    
    # Verify the conversion
    print(f"New EdgeAcc_m data type: {gdf['EdgeAcc_m'].dtype}")
    print(f"Sample values after conversion: {gdf['EdgeAcc_m'].head()}")
    
    # Add new DATASET attribute
    gdf['DATASET'] = "NW Aus Features"
    print(f"Added 'DATASET' attribute with value 'NW Aus Features'")
    
    # Show new column names
    print(f"Final columns: {gdf.columns.tolist()}")
    
    # Conditionally apply coastline clipping
    if perform_clipping:
        gdf = apply_coastline_clipping(gdf, coastline_file)
    else:
        print("SKIPPING coastline clipping as requested. Features may overlap with land areas.")
    
    # Save to new shapefile
    output_suffix = "" if perform_clipping else "-no-clip"
    final_output = output_file.replace(".shp", f"{output_suffix}.shp")
    gdf.to_file(final_output)
    print(f"Normalized shapefile saved to: {final_output}")
    print(f"Total processing time: {time.time() - start_time:.2f} seconds")

if __name__ == "__main__":
    # Set to False to skip coastline clipping for testing
    main(perform_clipping=True)
    #main(perform_clipping=False)  # Uncomment this line and comment the above to skip clipping