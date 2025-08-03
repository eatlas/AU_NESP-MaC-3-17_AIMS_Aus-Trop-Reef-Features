"""
Reef Bathymetry Statistics Calculator
------------------------------------

PURPOSE:
    This script calculates bathymetric statistics for reef boundary polygons by extracting
    elevation values from a bathymetry/topography raster dataset. For each reef polygon,
    it computes percentile-based elevation values (DEM10p, DEM50p, DEM90p), then
    saves these as attributes in a new shapefile.

INPUTS:
    - Reef boundary polygons (shapefile)
    - Bathymetry/topography raster (VRT)

OUTPUTS:
    - Copy of input shapefile with added DEM10p, DEM50p, and DEM90p attributes
    - Added DepthCat (Depth Category) and DepthCatSr (Source) attributes

ALGORITHM:
    1. For each reef polygon:
       a. Extract all raster values that fall within the polygon boundary
       b. Calculate 10th, 50th (median), and 90th percentile values from these extracted pixels
       c. For polygons smaller than a single pixel or without valid data:
          - Use the value at the polygon's centroid as an approximation
    2. Add the calculated statistics as attributes to the polygons
    3. Determine depth category based on DEM90p value (90th percentile):
       - Very Shallow: >= -2.5m
       - Shallow: -30m to -2.5m
       - Deep: < -30m
    4. Identify which source DEM dataset was used for each polygon
    5. Save the enhanced dataset to a new shapefile

HANDLING SPECIAL CASES:
    - Small reefs (sub-pixel): Uses centroid sampling to get the nearest value
    - Missing data: Returns null values when no valid data exists
    - CRS mismatches: Automatically reprojects data for correct spatial alignment
    - Existing DepthCat values: Preserved for features that already have a depth category

NOTES:
    - Positive values represent elevation above sea level
    - Negative values represent depth below sea level
    - The 90th percentile value represents the highest/shallowest point within each reef
    - The 10th percentile represents the deepest point within each reef
"""

import os
import geopandas as gpd
import rasterio
import numpy as np
from rasterio.mask import mask
from shapely.geometry import mapping, box
from rasterio.sample import sample_gen
import configparser
import pandas as pd
import math

# Define input and output paths
INPUT_SHAPE = "working/04/TS-GBR-CS-NW-Features-Country.shp"
INPUT_RASTER = "working/AusBathyTopo.vrt"
OUTPUT_DIR = "working/05"
OUTPUT_SHAPE = os.path.join(OUTPUT_DIR, "TS-GBR-CS-NW-Features-depth.shp")

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Read configuration for DEM dataset paths
config = configparser.ConfigParser()
config.read('config.ini')
download_path = config.get('general', 'in_3p_path')

# Define individual DEM dataset paths and information
DEM_DATASETS = {
    'NWS': {
        'name': 'NWS_GA_DEM-compilation-30m_2020: https://doi.org/10.26186/144600',
        'path': os.path.join(download_path, 'NWS-DEM-30m_2021',
                           'North_West_Shelf_DEM_v2_Bathymetry_2020_30m_MSL_cog_WGS84.tif'),
        'priority': 4  # Highest priority (Doesn't overlap with TS)
    },
    'TS': {
        'name': 'TS_GA_AusBathyTopo-30m_2023: https://dx.doi.org/10.26186/144348',
        'path': os.path.join(download_path, 'TS_GA_AusBathyTopo-30m_2023',
                           'Australian_Bathymetry_Topography__Torres_Strait__2023_30m_MSL_cog.tif'),
        'priority': 3  # Highest priority
    },
    'GBR': {
        'name': 'GBR_GA_Bathymetry-30m_2017: http://dx.doi.org/10.4225/25/5a207b36022d2',
        'paths': [
            os.path.join(download_path, 'GBR_GA_Bathymetry-30m_2017', 'Great_Barrier_Reef_A_2020_30m_MSL_cog.tif'),
            os.path.join(download_path, 'GBR_GA_Bathymetry-30m_2017', 'Great_Barrier_Reef_B_2020_30m_MSL_cog.tif'),
            os.path.join(download_path, 'GBR_GA_Bathymetry-30m_2017', 'Great_Barrier_Reef_C_2020_30m_MSL_cog.tif'),
            os.path.join(download_path, 'GBR_GA_Bathymetry-30m_2017', 'Great_Barrier_Reef_D_2020_30m_MSL_cog.tif')
        ],
        'priority': 2  # Middle priority
    },
    'AUS': {
        'name': 'AusBathyTopo-250m_2024: https://doi.org/10.26186/150050',
        'path': os.path.join(download_path, 'AusBathyTopo-250m_2024', 
                           'AusBathyTopo__Australia__2024_250m_MSL_cog.tif'),
        'priority': 1  # Lowest priority
    }
}

def get_statistics(geometry, raster_src):
    """Calculate percentile statistics (10th, 50th, 90th) of the raster within the polygon geometry"""
    try:
        # Get raster data within the geometry
        geom = [mapping(geometry)]
        out_image, out_transform = mask(raster_src, geom, crop=True, all_touched=False, nodata=None)
        
        # Get valid data (exclude nodata values)
        out_image_masked = out_image[0]
        
        # Check if we have any valid data within the polygon
        if np.all(np.isnan(out_image_masked)) or out_image_masked.size == 0:
            # No valid pixels found, use centroid sampling instead
            centroid = geometry.centroid
            # Sample the raster at the centroid point
            sample_gen_result = list(sample_gen(raster_src, [(centroid.x, centroid.y)]))
            if sample_gen_result and sample_gen_result[0] is not None and not np.isnan(sample_gen_result[0][0]):
                value = float(sample_gen_result[0][0])
                # Return the same value for all percentiles since we only have one point
                return value, value, value
            else:
                # Still no valid data, return None
                return None, None, None
        
        # IMPORTANT: Explicitly mask the -32767 value which appears to be a NoData value
        # Create a masked array excluding both NaN and -32767 values
        valid_data = out_image_masked[out_image_masked != -32767]
        
        # Only calculate statistics if we have valid data left
        if valid_data.size == 0:
            # Try centroid method instead
            centroid = geometry.centroid
            sample_gen_result = list(sample_gen(raster_src, [(centroid.x, centroid.y)]))
            if sample_gen_result and sample_gen_result[0] is not None and not np.isnan(sample_gen_result[0][0]) and sample_gen_result[0][0] != -32767:
                value = float(sample_gen_result[0][0])
                return value, value, value
            else:
                return None, None, None
        
        # Calculate percentiles with the properly masked data
        p10 = np.nanpercentile(valid_data, 10)
        p50 = np.nanpercentile(valid_data, 50)
        p90 = np.nanpercentile(valid_data, 90)
        
        return p10, p50, p90
    except Exception as e:
        print(f"Error processing geometry: {e}")
        return None, None, None

def determine_depth_category(p90_elevation):
    """Determine depth category based on 90th percentile elevation value"""
    if p90_elevation is None:
        return None
    
    if p90_elevation >= -2.5:
        return "Very Shallow"
    elif p90_elevation >= -30:
        return "Shallow"
    else:
        return "Deep"

def get_raster_extents():
    """Load and return the extents of each DEM dataset as polygons"""
    extents = {}
    
    # Load Torres Strait extent
    try:
        if os.path.exists(DEM_DATASETS['TS']['path']):
            with rasterio.open(DEM_DATASETS['TS']['path']) as src:
                bounds = src.bounds
                extents['TS'] = box(bounds.left, bounds.bottom, bounds.right, bounds.top)
                print(f"Loaded Torres Strait dataset extent")
    except Exception as e:
        print(f"Warning: Could not load Torres Strait dataset extent: {e}")
    
    # Load GBR extents (combine all tiles)
    try:
        gbr_extents = []
        for gbr_path in DEM_DATASETS['GBR']['paths']:
            if os.path.exists(gbr_path):
                with rasterio.open(gbr_path) as src:
                    bounds = src.bounds
                    gbr_extents.append(box(bounds.left, bounds.bottom, bounds.right, bounds.top))
        
        if gbr_extents:
            from shapely.ops import unary_union
            extents['GBR'] = unary_union(gbr_extents)
            print(f"Loaded GBR dataset extent (combined {len(gbr_extents)} tiles)")
    except Exception as e:
        print(f"Warning: Could not load GBR dataset extent: {e}")
    
    # Load Australia extent
    try:
        if os.path.exists(DEM_DATASETS['AUS']['path']):
            with rasterio.open(DEM_DATASETS['AUS']['path']) as src:
                bounds = src.bounds
                extents['AUS'] = box(bounds.left, bounds.bottom, bounds.right, bounds.top)
                print(f"Loaded Australia dataset extent")
    except Exception as e:
        print(f"Warning: Could not load Australia dataset extent: {e}")
    
    return extents

def determine_dem_source(geometry, extents):
    """Determine which DEM dataset was used based on geometry and dataset extents"""
    # Check from highest to lowest priority
    if 'TS' in extents and geometry.intersects(extents['TS']):
        return DEM_DATASETS['TS']['name']
    elif 'GBR' in extents and geometry.intersects(extents['GBR']):
        return DEM_DATASETS['GBR']['name']
    elif 'AUS' in extents and geometry.intersects(extents['AUS']):
        return DEM_DATASETS['AUS']['name']
    else:
        return "Unknown"

def main():
    print(f"Reading shapefile from {INPUT_SHAPE}")
    reefs = gpd.read_file(INPUT_SHAPE)
    
    print(f"Reading raster from {INPUT_RASTER}")
    with rasterio.open(INPUT_RASTER) as src:
        # Check raster properties
        print(f"Raster CRS: {src.crs}")
        print(f"Shapefile CRS: {reefs.crs}")
        
        # Reproject shapefile if CRS doesn't match
        if src.crs != reefs.crs:
            print("Reprojecting shapefile to match raster CRS...")
            reefs = reefs.to_crs(src.crs)
        
        # Calculate statistics for each polygon
        print("Calculating depth percentiles within each reef polygon...")
        p10_values = []
        p50_values = []
        p90_values = []
        total = len(reefs)
        
        for i, geom in enumerate(reefs.geometry):
            if i % 100 == 0:
                print(f"Processing feature {i+1}/{total}...")
            p10, p50, p90 = get_statistics(geom, src)
            p10_values.append(p10)
            p50_values.append(p50)
            p90_values.append(p90)
    
    # Add values to the GeoDataFrame
    print("Adding depth percentile statistics to the shapefile...")
    reefs['DEM10p'] = [round(x, 1) if x is not None else None for x in p10_values]
    reefs['DEM50p'] = [round(x, 1) if x is not None else None for x in p50_values]
    reefs['DEM90p'] = [round(x, 1) if x is not None else None for x in p90_values]
    
    # Get DEM dataset extents for source determination
    print("Loading DEM dataset extents...")
    dem_extents = get_raster_extents()
    
    # Ensure required columns exist
    if 'DepthCat' not in reefs.columns:
        reefs['DepthCat'] = None
    if 'DepthCatSr' not in reefs.columns:
        reefs['DepthCatSr'] = None
    
    # Calculate depth categories and sources where needed
    print("Calculating depth categories and sources...")
    for i, row in reefs.iterrows():
        # Only update depth category if it's not already set
        if pd.isna(row['DepthCat']) or row['DepthCat'] is None or row['DepthCat'] == '':
            depth_cat = determine_depth_category(row['DEM90p'])
            if depth_cat:
                reefs.at[i, 'DepthCat'] = depth_cat
                
                # Set the source for the depth category
                dem_source = determine_dem_source(row.geometry, dem_extents)
                reefs.at[i, 'DepthCatSr'] = dem_source
    
    # Save the result
    print(f"Saving output shapefile to {OUTPUT_SHAPE}")
    reefs.to_file(OUTPUT_SHAPE)
    
    # Summary statistics
    valid_p10 = [d for d in reefs['DEM10p'] if d is not None]
    valid_p50 = [d for d in reefs['DEM50p'] if d is not None]
    valid_p90 = [d for d in reefs['DEM90p'] if d is not None]
    
    print(f"Processed {len(reefs)} reef polygons")
    print(f"Found elevation values for {len(valid_p90)} reef polygons")
    
    # Count depth categories
    depth_counts = reefs['DepthCat'].value_counts()
    print("\nDepth category distribution:")
    for cat, count in depth_counts.items():
        print(f"  {cat}: {count} features")
    
    # Count source distributions
    source_counts = reefs['DepthCatSr'].value_counts()
    print("\nDepth category source distribution:")
    for source, count in source_counts.items():
        print(f"  {source}: {count} features")
    
    if valid_p10:
        print(f"10th percentile depth statistics: Min={min(valid_p10):.2f}, Max={max(valid_p10):.2f}, Mean={np.mean(valid_p10):.2f}")
    if valid_p50:
        print(f"50th percentile (median) depth statistics: Min={min(valid_p50):.2f}, Max={max(valid_p50):.2f}, Mean={np.mean(valid_p50):.2f}")
    if valid_p90:
        print(f"90th percentile depth statistics: Min={min(valid_p90):.2f}, Max={max(valid_p90):.2f}, Mean={np.mean(valid_p90):.2f}")
    
    print("Done!")

if __name__ == "__main__":
    main()