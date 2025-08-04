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
import subprocess
from osgeo import gdal

# Read configuration for DEM dataset paths
config = configparser.ConfigParser()
config.read('config.ini')
download_path = config.get('general', 'in_3p_path')

# Define input and output paths
INPUT_SHAPE = "working/04/TS-GBR-CS-NW-Features-Country.shp"
MULTIRES_VRT = "working/05/MultiResBathyEEZ.vrt"
MULTIRES_TIFS = [
    os.path.join(download_path, "MultiRes-Bathy-EEZ_2024", "01_shallow_bathy.tif"),
    os.path.join(download_path, "MultiRes-Bathy-EEZ_2024", "02_mesophotic_bathy.tif"),
]
AUSBATHYTOPO_TIF = os.path.join(download_path, "AusBathyTopo-250m_2024", "AusBathyTopo__Australia__2024_250m_MSL_cog.tif")
OUTPUT_DIR = "working/05"
OUTPUT_SHAPE = os.path.join(OUTPUT_DIR, "TS-GBR-CS-NW-Features-depth.shp")

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)



def create_multires_vrt():
    """Create MultiResBathyEEZ VRT if it doesn't exist."""
    if not os.path.exists(MULTIRES_VRT):
        os.makedirs(os.path.dirname(MULTIRES_VRT), exist_ok=True)
        print(f"Creating MultiResBathyEEZ VRT at {MULTIRES_VRT} ...")
        # Use gdal.BuildVRT instead of subprocess
        vrt = gdal.BuildVRT(MULTIRES_VRT, MULTIRES_TIFS)
        vrt = None  # flush to disk
        print("MultiResBathyEEZ VRT created.")
    else:
        print("MultiResBathyEEZ VRT already exists.")

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

def get_percentiles_from_raster(geometry, raster_src, nodata_val, feature_idx=None, raster_path=None, target_crs=None):
    """Calculate percentiles (10, 50, 90) for a polygon from a raster, with centroid fallback. Adds debug info."""
    try:
        # Reproject geometry if needed
        if target_crs is not None and hasattr(geometry, 'crs') and geometry.crs != target_crs:
            # geometry is a GeoSeries or GeoDataFrame row
            geom_proj = geometry.to_crs(target_crs)
            geom = [mapping(geom_proj)]
        elif target_crs is not None:
            # geometry is a shapely geometry, reproject manually
            import pyproj
            from shapely.ops import transform
            project = pyproj.Transformer.from_crs("EPSG:{}".format(geometry.crs.to_epsg()) if hasattr(geometry, 'crs') and geometry.crs else "EPSG:4326", target_crs, always_xy=True).transform
            geom_proj = transform(project, geometry)
            geom = [mapping(geom_proj)]
        else:
            geom = [mapping(geometry)]
        out_image, _ = mask(raster_src, geom, crop=True, all_touched=False, nodata=nodata_val)
        arr = out_image[0]
        # Mask nodata
        valid = arr[(arr != nodata_val) & (~np.isnan(arr))]
        if valid.size == 0:
            # Fallback: centroid
            centroid = geometry.centroid
            if target_crs is not None:
                import pyproj
                from shapely.ops import transform
                project = pyproj.Transformer.from_crs("EPSG:{}".format(geometry.crs.to_epsg()) if hasattr(geometry, 'crs') and geometry.crs else "EPSG:4326", target_crs, always_xy=True).transform
                centroid_proj = transform(project, centroid)
                sample_pt = (centroid_proj.x, centroid_proj.y)
            else:
                sample_pt = (centroid.x, centroid.y)
            val = list(raster_src.sample([sample_pt]))[0][0]
            if val != nodata_val and not np.isnan(val):
                return val, val, val
            else:
                return None, None, None
        p10 = np.nanpercentile(valid, 10)
        p50 = np.nanpercentile(valid, 50)
        p90 = np.nanpercentile(valid, 90)
        return p10, p50, p90
    except Exception as e:
        print(f"Error extracting percentiles: {e}")
        if feature_idx is not None:
            print(f"  Feature index: {feature_idx}")
            print(f"  Feature geometry bounds: {geometry.bounds}")
        if raster_src is not None:
            print(f"  Raster path: {raster_path}")
            print(f"  Raster bounds: {raster_src.bounds}")
        return None, None, None

def assign_depth_percentiles(geometry, rasters, feature_idx=None, geometry_crs=None):
    """Try each raster in order, reprojecting geometry as needed, return percentiles and source name."""
    import pyproj
    from shapely.ops import transform 
    for raster_path, nodata_val, src_name in rasters:
        if not os.path.exists(raster_path):
            continue
        with rasterio.open(raster_path) as src:
            raster_crs = src.crs
            # Reproject geometry if needed
            if geometry_crs is not None and raster_crs is not None and geometry_crs != raster_crs:
                # geometry is a shapely geometry, reproject manually
                project = pyproj.Transformer.from_crs(geometry_crs, raster_crs, always_xy=True).transform
                geom_proj = transform(project, geometry)
            else:
                geom_proj = geometry
            p10, p50, p90 = get_percentiles_from_raster(
                geom_proj, src, nodata_val, feature_idx=feature_idx, raster_path=raster_path, target_crs=None
            )
            if all(v is not None for v in (p10, p50, p90)):
                return p10, p50, p90, src_name
    print(f"WARNING: No valid raster found for feature {feature_idx}. Geometry bounds: {geometry.bounds}")
    return None, None, None, None

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

def main():
    print(f"Reading shapefile from {INPUT_SHAPE}")
    reefs = gpd.read_file(INPUT_SHAPE)

    # Debug: Check bounds of all features before any reprojection
    all_bounds = np.array([geom.bounds for geom in reefs.geometry])
    minx, miny = np.min(all_bounds[:, 0]), np.min(all_bounds[:, 1])
    maxx, maxy = np.max(all_bounds[:, 2]), np.max(all_bounds[:, 3])
    print(f"Input shapefile feature bounds: minx={minx}, maxx={maxx}, miny={miny}, maxy={maxy}")
    # Flag features outside lon/lat range
    out_of_range = []
    for idx, (xmin, ymin, xmax, ymax) in enumerate(all_bounds):
        if not (-180 <= xmin <= 180 and -180 <= xmax <= 180 and -90 <= ymin <= 90 and -90 <= ymax <= 90):
            out_of_range.append(idx)
    if out_of_range:
        print(f"WARNING: {len(out_of_range)} features have bounds outside -180/180/-90/90 (indices: {out_of_range[:10]}...)")
    else:
        print("All features are within expected longitude/latitude bounds.")

    # Create VRT if needed
    create_multires_vrt()

    # Prepare raster fallback order: MultiResBathyEEZ, then AusBathyTopo
    rasters = [
        (MULTIRES_VRT, 3.4e+38, "MultiRefBathyEEZ_2024"),
        (AUSBATHYTOPO_TIF, 3.4e+38, "AusBathyTopo-250m_2024"),
    ]

    print(f"Reading raster from {MULTIRES_VRT}")
    with rasterio.open(MULTIRES_VRT) as src:
        # Check raster properties
        print(f"Raster CRS: {src.crs}")
        print(f"Shapefile CRS: {reefs.crs}")
        
        # Reproject shapefile if CRS doesn't match
        if src.crs != reefs.crs:
            print("Reprojecting shapefile to match raster CRS...")
            reefs = reefs.to_crs(src.crs)
        # Set current_crs after possible reprojection
        current_crs = reefs.crs
        
        # Calculate statistics for each polygon
        print("Calculating depth percentiles within each reef polygon...")
        p10_values, p50_values, p90_values, src_values = [], [], [], []
        total = len(reefs)
        for i, geom in enumerate(reefs.geometry):
            if i % 100 == 0:
                print(f"Processing feature {i+1}/{total}...")
            p10, p50, p90, src_name = assign_depth_percentiles(geom, rasters, feature_idx=i, geometry_crs=current_crs)
            p10_values.append(p10)
            p50_values.append(p50)
            p90_values.append(p90)
            src_values.append(src_name)

    # Add values to the GeoDataFrame
    print("Adding depth percentile statistics to the shapefile...")
    reefs['DEM10p'] = [round(x, 1) if x is not None else None for x in p10_values]
    reefs['DEM50p'] = [round(x, 1) if x is not None else None for x in p50_values]
    reefs['DEM90p'] = [round(x, 1) if x is not None else None for x in p90_values]

    # Ensure required columns exist
    if 'DepthCat' not in reefs.columns:
        reefs['DepthCat'] = None
    if 'DepthCatSr' not in reefs.columns:
        reefs['DepthCatSr'] = None

    if 'DEMSr' not in reefs.columns:
        reefs['DEMSr'] = None

    # Calculate depth categories and sources where needed
    print("Calculating depth categories and sources...")
    for i, row in reefs.iterrows():
        # Only update depth category if it's not already set
        if pd.isna(row['DepthCat']) or row['DepthCat'] is None or row['DepthCat'] == '':
            rb_type = str(row.get('RB_Type_L3', '')).strip()
            attachment = str(row.get('Attachment', '')).strip()
            orig_type = str(row.get('OrigType', '')).strip()
            est_depth_cat = determine_depth_category(row['DEM90p'])

            # Apply rules. These are to compensate for imperfect edstimates from the DEM.
            rule_applied = False
            # Coral Reef, Fringing: If estimated is 'Deep', set to 'Shallow'
            if rb_type == 'Coral Reef' and attachment == 'Fringing':
                if est_depth_cat == 'Deep':
                    reefs.at[i, 'DepthCat'] = 'Shallow'
                    rule_applied = True
            # Rocky Reef, Fringing: If estimated is 'Deep', set to 'Shallow'
            elif rb_type == 'Rocky Reef' and attachment == 'Fringing':
                if est_depth_cat == 'Deep':
                    reefs.at[i, 'DepthCat'] = 'Shallow'
                    rule_applied = True
            # Intertidal Sediment, Fringing or Isolated: Set to 'Intertidal'
            elif rb_type == 'Intertidal Sediment' and attachment in ['Fringing', 'Isolated']:
                reefs.at[i, 'DepthCat'] = 'Intertidal'
                rule_applied = True
            # Island, Fringing or Isolated: Set to 'Land'
            elif rb_type == 'Island' and attachment in ['Fringing', 'Isolated']:
                reefs.at[i, 'DepthCat'] = 'Land'
                rule_applied = True
            # Unvegetated Cay, Fringing or Isolated: Set to 'Land'
            elif rb_type == 'Unvegetated Cay' and attachment in ['Fringing', 'Isolated', 'Land']:
                reefs.at[i, 'DepthCat'] = 'Land'
                rule_applied = True
            elif orig_type in ['Pearl Pontoon', 'Channel Marker']:
                reefs.at[i, 'DepthCat'] = 'Surface'
                rule_applied = True

            if rule_applied:
                # If a rule was applied, set the DepthCatSr to the rule source
                reefs.at[i, 'DepthCatSr'] = 'RB_Type_L3 rule'
            # If no rule applied, use estimated depth category as before
            if not rule_applied and est_depth_cat:
                reefs.at[i, 'DepthCat'] = est_depth_cat
                reefs.at[i, 'DepthCatSr'] = src_values[i]
        # Set DEM source
        if pd.isna(row['DEMSr']) or row['DEMSr'] is None or row['DEMSr'] == '':
            reefs.at[i, 'DEMSr'] = src_values[i]

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