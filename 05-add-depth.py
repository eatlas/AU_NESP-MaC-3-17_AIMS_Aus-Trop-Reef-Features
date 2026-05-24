"""
Reef Bathymetry Statistics Calculator (v2 - with LAT adjustment)
----------------------------------------------------------------

PURPOSE:
    Calculates bathymetric statistics for reef boundary polygons by extracting
    elevation values from bathymetry/topography raster datasets. For each reef polygon,
    computes percentile-based elevation values relative to both MSL and LAT datums,
    and assigns depth category attributes using both DEM data and rule-based logic.

INPUTS:
    - Reef boundary polygons (shapefile)
    - Bathymetry/topography raster datasets (VRT and GeoTIFFs) - referenced to MSL
    - Lowest Predicted Tide (LPT) raster - used to convert MSL depths to LAT depths

OUTPUTS:
    - Copy of input shapefile with added depth attributes:
      - DEM10pMSL, DEM50pMSL, DEM90pMSL: Depth percentiles relative to Mean Sea Level
      - DEM10pLAT, DEM50pLAT, DEM90pLAT: Depth percentiles relative to Lowest Astronomical Tide
      - DepthCat: Depth category classification
      - DepthCatSr: Source of the depth category (DEM source or rule name)
      - DEMSr: DEM source used for each polygon

ALGORITHM:
    1. Load the LPT raster entirely into memory (small: 2336x1216 pixels)
    2. For each reef polygon:
       a. Extract all DEM raster values within the polygon boundary
       b. For each valid DEM pixel, look up the corresponding LPT value using
          geographic coordinates, and compute LAT-adjusted depth (DEM - LPT)
       c. Calculate 10th, 50th (median), and 90th percentile values for both
          MSL and LAT-adjusted arrays
       d. For polygons smaller than a single pixel or without valid data:
          - Use the value at the polygon's centroid as an approximation
    3. Add the calculated statistics as attributes to the polygons
    4. Assign depth category (DepthCat) using the following logic:
       - If DepthCat is already set, preserve it
       - Otherwise, apply rule-based overrides using RB_Type_L3, Attachment, and OrigType
         (e.g., certain types/attachments force 'Land', 'Intertidal', or 'Surface')
       - If no rule applies, assign category based on DEM values:
         * Intertidal: DEM90pLAT >= 0
         * Very Shallow: DEM90pLAT < 0 and >= -2.5
         * Shallow: DEM90pLAT < -2.5 and DEM90pMSL >= -30
         * Deep: DEM90pMSL < -30
    5. Record the source of the depth category and the DEM source
    6. Save the enhanced dataset to a new shapefile

TEST MODE (--test):
    Exercises the production LPT lookup code paths over a test region
    (Whitsundays/Mackay, -20.4 to -22.7 S, 149.18 to 151.2 E) and outputs
    three rasters at DEM native resolution:
    - working/05/test_dem_msl.tif: Raw DEM values (MSL)
    - working/05/test_lpt_looked_up.tif: LPT values retrieved via LPTLookup
    - working/05/test_dem_lat.tif: LAT-adjusted DEM (DEM - LPT)
    Verification: compare test_lpt_looked_up against original LPT (should match
    spatially), and test_dem_msl - test_dem_lat should exactly equal test_lpt_looked_up.

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
    - LAT conversion: depth_LAT = depth_MSL - LPT (where LPT is negative relative to MSL)
    - The Shallow/Deep boundary (-30 m) uses MSL datum to align with satellite-derived
      depth estimates using the green channel
"""

import os
import sys
import argparse
import geopandas as gpd
import rasterio
import numpy as np
from rasterio.mask import mask
from rasterio.transform import rowcol
from rasterio.windows import from_bounds
from shapely.geometry import mapping, box
from rasterio.sample import sample_gen
import configparser
import pandas as pd
import math
from osgeo import gdal

# Read configuration for DEM dataset paths
config = configparser.ConfigParser()
config.read('config.ini')
download_path = config.get('general', 'in_3p_path')

# Define input and output paths
INPUT_SHAPE = "working/04/TS-GBR-CS-NW-Features-Country.shp"
MULTIRES_VRT = "working/05/MultiRes-Bathy-EEZ_2024.vrt"
MULTIRES_TIFS = [
    os.path.join(download_path, "MultiRes-Bathy-EEZ_2024", "01_shallow_bathy.tif"),
    os.path.join(download_path, "MultiRes-Bathy-EEZ_2024", "02_mesophotic_bathy.tif"),
]
AUSBATHYTOPO_TIF = os.path.join(download_path, "AusBathyTopo-250m_2024", "AusBathyTopo__Australia__2024_250m_MSL_cog.tif")
LPT_TIF = os.path.join(download_path, "EOT20-tides", "AU_AIMS_EOT20-tide-stats_LPT_2021-01-2025-12.tif")
OUTPUT_DIR = "working/05"
OUTPUT_SHAPE = os.path.join(OUTPUT_DIR, "TS-GBR-CS-NW-Features-depth.shp")

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)


class LPTLookup:
    """Loads the LPT raster into memory and provides fast per-pixel lookups."""

    def __init__(self, lpt_path):
        print(f"Loading LPT raster into memory from {lpt_path} ...")
        with rasterio.open(lpt_path) as src:
            self.data = src.read(1)  # Single band
            self.transform = src.transform
            self.crs = src.crs
            self.nodata = src.nodata
            self.bounds = src.bounds
            self.height = src.height
            self.width = src.width
        print(f"  LPT raster loaded: {self.width}x{self.height} pixels, "
              f"bounds: {self.bounds}, nodata: {self.nodata}")
        print(f"  LPT value range: {np.nanmin(self.data[self.data != self.nodata]):.4f} to "
              f"{np.nanmax(self.data[self.data != self.nodata]):.4f}")

    def get_value(self, x, y):
        """Get LPT value at a geographic coordinate (x=lon, y=lat).
        Returns None if outside bounds or nodata."""
        # Convert geographic coordinate to pixel row/col
        col, row = ~self.transform * (x, y)
        row, col = int(round(row)), int(round(col))
        if row < 0 or row >= self.height or col < 0 or col >= self.width:
            return None
        val = self.data[row, col]
        if self.nodata is not None and val == self.nodata:
            return None
        if np.isnan(val):
            return None
        return float(val)

    def get_values_for_pixels(self, xs, ys):
        """Get LPT values for arrays of geographic coordinates in LPT's own CRS.
        Returns a numpy array with NaN where no valid LPT exists."""
        # Convert geographic coordinates to pixel row/col using the inverse transform
        inv_transform = ~self.transform
        cols, rows = inv_transform * (xs, ys)
        rows = np.round(rows).astype(int)
        cols = np.round(cols).astype(int)

        # Create output array filled with NaN
        result = np.full(len(xs), np.nan)

        # Mask for valid pixel indices
        valid = (rows >= 0) & (rows < self.height) & (cols >= 0) & (cols < self.width)
        if np.any(valid):
            vals = self.data[rows[valid], cols[valid]]
            # Mask nodata
            if self.nodata is not None:
                vals = np.where(vals == self.nodata, np.nan, vals)
            result[valid] = vals

        return result

    def get_values_for_coords(self, xs, ys, source_crs):
        """Get LPT values for coordinate arrays, reprojecting from source_crs if needed.
        This is the canonical method for looking up LPT values from any CRS.
        Returns a numpy array with NaN where no valid LPT exists."""
        import pyproj
        if source_crs is not None and self.crs is not None and source_crs != self.crs:
            transformer = pyproj.Transformer.from_crs(source_crs, self.crs, always_xy=True)
            lpt_xs, lpt_ys = transformer.transform(xs, ys)
        else:
            lpt_xs, lpt_ys = xs, ys
        return self.get_values_for_pixels(lpt_xs, lpt_ys)


def create_multires_vrt():
    """Create MultiResBathyEEZ VRT if it doesn't exist."""
    if not os.path.exists(MULTIRES_VRT):
        os.makedirs(os.path.dirname(MULTIRES_VRT), exist_ok=True)
        print(f"Creating MultiResBathyEEZ VRT at {MULTIRES_VRT} ...")
        vrt = gdal.BuildVRT(MULTIRES_VRT, MULTIRES_TIFS)
        vrt = None  # flush to disk
        print("MultiResBathyEEZ VRT created.")
    else:
        print("MultiResBathyEEZ VRT already exists.")


def get_pixel_coordinates(out_image, out_transform):
    """Given a masked raster output and its transform, return arrays of
    geographic (x, y) coordinates for all pixels in the output grid."""
    nrows, ncols = out_image.shape[1], out_image.shape[2]
    # Create grid of pixel indices
    col_indices, row_indices = np.meshgrid(np.arange(ncols), np.arange(nrows))
    # Convert pixel indices to geographic coordinates (pixel centres)
    xs = out_transform.c + (col_indices + 0.5) * out_transform.a + (row_indices + 0.5) * out_transform.b
    ys = out_transform.f + (col_indices + 0.5) * out_transform.d + (row_indices + 0.5) * out_transform.e
    return xs, ys


def get_percentiles_with_lat(geometry, raster_src, nodata_val, lpt_lookup,
                              feature_idx=None, geometry_crs=None, raster_crs=None):
    """Calculate percentiles (10, 50, 90) for both MSL and LAT-adjusted depths.

    For each valid DEM pixel within the polygon, looks up the LPT value at the same
    geographic location and computes: depth_LAT = depth_MSL - LPT

    Returns: (p10_msl, p50_msl, p90_msl, p10_lat, p50_lat, p90_lat) or all None on failure.
    """
    import pyproj
    from shapely.ops import transform as shapely_transform

    try:
        # Reproject geometry to raster CRS if needed
        if geometry_crs is not None and raster_crs is not None and geometry_crs != raster_crs:
            project = pyproj.Transformer.from_crs(geometry_crs, raster_crs, always_xy=True).transform
            geom_proj = shapely_transform(project, geometry)
        else:
            geom_proj = geometry

        geom = [mapping(geom_proj)]
        out_image, out_transform = mask(raster_src, geom, crop=True, all_touched=False, nodata=nodata_val)
        arr = out_image[0]

        # Mask nodata and NaN
        valid_mask = (arr != nodata_val) & (~np.isnan(arr))

        if not np.any(valid_mask):
            # Fallback: centroid sampling
            centroid = geometry.centroid
            # Reproject centroid to raster CRS for sampling
            if geometry_crs is not None and raster_crs is not None and geometry_crs != raster_crs:
                from shapely.geometry import Point
                centroid_proj = shapely_transform(project, centroid)
                sample_pt = (centroid_proj.x, centroid_proj.y)
            else:
                sample_pt = (centroid.x, centroid.y)

            val = list(raster_src.sample([sample_pt]))[0][0]
            if val == nodata_val or np.isnan(val):
                return None, None, None, None, None, None

            dem_msl = float(val)

            # Get LPT at centroid (in LPT's CRS, which is EPSG:4326)
            # The centroid in the original geometry CRS should be close to EPSG:4326
            # If geometry_crs differs from LPT CRS, reproject
            if geometry_crs is not None and lpt_lookup.crs is not None and geometry_crs != lpt_lookup.crs:
                project_to_lpt = pyproj.Transformer.from_crs(geometry_crs, lpt_lookup.crs, always_xy=True).transform
                centroid_lpt = shapely_transform(project_to_lpt, centroid)
                lpt_val = lpt_lookup.get_value(centroid_lpt.x, centroid_lpt.y)
            else:
                lpt_val = lpt_lookup.get_value(centroid.x, centroid.y)

            if lpt_val is None:
                # No LPT data; return MSL only
                return dem_msl, dem_msl, dem_msl, None, None, None

            dem_lat = dem_msl - lpt_val
            return dem_msl, dem_msl, dem_msl, dem_lat, dem_lat, dem_lat

        # We have valid pixels - get their geographic coordinates
        xs, ys = get_pixel_coordinates(out_image, out_transform)

        # Extract valid MSL values and their coordinates
        valid_msl = arr[valid_mask]
        valid_xs = xs[valid_mask]
        valid_ys = ys[valid_mask]

        # Get LPT values for all valid pixels (handles CRS reprojection internally)
        lpt_values = lpt_lookup.get_values_for_coords(valid_xs, valid_ys, raster_crs)

        # Calculate LAT-adjusted values: DEM_LAT = DEM_MSL - LPT
        valid_lat = valid_msl - lpt_values  # NaN propagates where LPT is missing

        # Calculate MSL percentiles
        p10_msl = float(np.nanpercentile(valid_msl, 10))
        p50_msl = float(np.nanpercentile(valid_msl, 50))
        p90_msl = float(np.nanpercentile(valid_msl, 90))

        # Calculate LAT percentiles (only from pixels with valid LPT)
        lat_valid = valid_lat[~np.isnan(valid_lat)]
        if lat_valid.size > 0:
            p10_lat = float(np.nanpercentile(lat_valid, 10))
            p50_lat = float(np.nanpercentile(lat_valid, 50))
            p90_lat = float(np.nanpercentile(lat_valid, 90))
        else:
            p10_lat, p50_lat, p90_lat = None, None, None

        return p10_msl, p50_msl, p90_msl, p10_lat, p50_lat, p90_lat

    except Exception as e:
        print(f"Error extracting percentiles for feature {feature_idx}: {e}")
        return None, None, None, None, None, None


def assign_depth_percentiles(geometry, rasters, lpt_lookup, feature_idx=None, geometry_crs=None):
    """Try each raster in order, return MSL and LAT percentiles and source name."""
    import pyproj

    for raster_path, nodata_val, src_name in rasters:
        if not os.path.exists(raster_path):
            continue
        with rasterio.open(raster_path) as src:
            raster_crs = src.crs
            result = get_percentiles_with_lat(
                geometry, src, nodata_val, lpt_lookup,
                feature_idx=feature_idx, geometry_crs=geometry_crs, raster_crs=raster_crs
            )
            p10_msl, p50_msl, p90_msl, p10_lat, p50_lat, p90_lat = result
            if all(v is not None for v in (p10_msl, p50_msl, p90_msl)):
                return p10_msl, p50_msl, p90_msl, p10_lat, p50_lat, p90_lat, src_name

    print(f"WARNING: No valid raster found for feature {feature_idx}. Geometry bounds: {geometry.bounds}")
    return None, None, None, None, None, None, None


def determine_depth_category(p90_msl, p90_lat):
    """Determine depth category based on DEM90pLAT and DEM90pMSL values.

    Logic:
      - Intertidal: DEM90pLAT >= 0
      - Very Shallow: DEM90pLAT < 0 and >= -2.5
      - Shallow: DEM90pLAT < -2.5 and DEM90pMSL >= -30
      - Deep: DEM90pMSL < -30
    """
    if p90_msl is None:
        return None

    # If LAT values available, use them for Intertidal and Very Shallow
    if p90_lat is not None:
        if p90_lat >= 0:
            return "Intertidal"
        elif p90_lat >= -2.5:
            return "Very Shallow"

    # Shallow/Deep boundary uses MSL
    if p90_msl >= -30:
        return "Shallow"
    else:
        return "Deep"


def run_test_mode():
    """Test mode: exercises the production LPT lookup code path over a test region.

    Uses the same get_pixel_coordinates() and LPTLookup.get_values_for_pixels() functions
    as the main processing loop to generate verification rasters at DEM native resolution.

    Test region: Whitsundays/Mackay area (-20.4 to -22.7 S, 149.18 to 151.2 E)
    This covers a large tidal range gradient and reef areas that should become intertidal.

    Creates (all at DEM native resolution, clipped to test region):
      - working/05/test_dem_msl.tif: Raw DEM values (MSL)
      - working/05/test_lpt_looked_up.tif: LPT values retrieved via LPTLookup (production code path)
      - working/05/test_dem_lat.tif: LAT-adjusted DEM (DEM - LPT)

    Verification in QGIS:
      1. Compare test_lpt_looked_up.tif against the original LPT raster — should match
         (resampled to DEM resolution but spatially aligned)
      2. Compute test_dem_msl - test_dem_lat — should exactly equal test_lpt_looked_up
      3. Check that intertidal areas (test_dem_lat >= 0) make sense spatially
    """
    print("=" * 60)
    print("TEST MODE: Generating verification rasters using production code paths")
    print("=" * 60)

    # Test region: Whitsundays/Mackay - large tidal gradient, intertidal reefs
    TEST_BBOX = box(149.18, -22.7, 151.2, -20.4)  # (minx, miny, maxx, maxy)
    test_minx, test_miny, test_maxx, test_maxy = TEST_BBOX.bounds
    print(f"Test region: lon {test_minx} to {test_maxx}, lat {test_miny} to {test_maxy}")

    # Load LPT lookup using the production class
    lpt_lookup = LPTLookup(LPT_TIF)

    # Open DEM and extract the test region at native resolution
    dem_path = MULTIRES_VRT
    if not os.path.exists(dem_path):
        create_multires_vrt()

    print(f"\nOpening DEM raster: {dem_path}")
    with rasterio.open(dem_path) as dem_src:
        dem_crs = dem_src.crs
        dem_nodata = 3.4e+38
        print(f"  DEM CRS: {dem_crs}")
        print(f"  DEM resolution: {dem_src.res}")

        # Reproject test bbox to DEM CRS if needed
        import pyproj
        from shapely.ops import transform as shapely_transform
        bbox_crs = rasterio.crs.CRS.from_epsg(4326)
        if dem_crs != bbox_crs:
            print(f"  Reprojecting test bbox from EPSG:4326 to {dem_crs}...")
            project = pyproj.Transformer.from_crs(bbox_crs, dem_crs, always_xy=True).transform
            test_bbox_proj = shapely_transform(project, TEST_BBOX)
            proj_minx, proj_miny, proj_maxx, proj_maxy = test_bbox_proj.bounds
        else:
            proj_minx, proj_miny, proj_maxx, proj_maxy = test_minx, test_miny, test_maxx, test_maxy

        # Get the window for our test bbox (in DEM CRS)
        window = from_bounds(proj_minx, proj_miny, proj_maxx, proj_maxy, dem_src.transform)
        # Round to integer pixel boundaries
        window = window.round_offsets().round_lengths()
        print(f"  Test region window: {window}")
        print(f"  Output size: {int(window.width)} x {int(window.height)} pixels")

        # Read the DEM for the test region
        print("  Reading DEM for test region...")
        dem_data = dem_src.read(1, window=window)
        dem_transform = dem_src.window_transform(window)

    # Mask nodata
    dem_msl = dem_data.astype(np.float32)
    dem_msl[dem_data == dem_nodata] = np.nan

    # Now use the PRODUCTION code path to look up LPT values for each DEM pixel
    print("  Computing pixel coordinates using get_pixel_coordinates()...")
    # get_pixel_coordinates expects shape (1, nrows, ncols) for out_image
    out_image_3d = dem_msl[np.newaxis, :, :]
    xs, ys = get_pixel_coordinates(out_image_3d, dem_transform)

    print(f"  Coordinate grid shape: {xs.shape}")
    print(f"  X range: {xs.min():.4f} to {xs.max():.4f}")
    print(f"  Y range: {ys.min():.4f} to {ys.max():.4f}")

    # Flatten for LPT lookup (same as production code)
    xs_flat = xs.ravel()
    ys_flat = ys.ravel()

    # Use production LPTLookup.get_values_for_coords() (handles CRS reprojection internally)
    print("  Looking up LPT values using LPTLookup.get_values_for_coords()...")
    lpt_values_flat = lpt_lookup.get_values_for_coords(xs_flat, ys_flat, dem_crs)
    lpt_looked_up = lpt_values_flat.reshape(dem_msl.shape)

    # Calculate LAT-adjusted DEM using production formula: DEM_LAT = DEM_MSL - LPT
    dem_lat = dem_msl - lpt_looked_up

    # Report statistics
    valid_msl = dem_msl[~np.isnan(dem_msl)]
    valid_lpt = lpt_looked_up[~np.isnan(lpt_looked_up)]
    valid_lat = dem_lat[~np.isnan(dem_lat)]
    print(f"\n  Statistics for test region:")
    print(f"    DEM MSL: {valid_msl.size} valid pixels, range [{valid_msl.min():.2f}, {valid_msl.max():.2f}]")
    print(f"    LPT looked up: {valid_lpt.size} valid pixels, range [{valid_lpt.min():.4f}, {valid_lpt.max():.4f}]")
    print(f"    DEM LAT: {valid_lat.size} valid pixels, range [{valid_lat.min():.2f}, {valid_lat.max():.2f}]")

    # Count pixels that would be classified as intertidal (DEM_LAT >= 0)
    intertidal_count = np.sum(valid_lat >= 0)
    print(f"    Pixels with DEM_LAT >= 0 (intertidal): {intertidal_count} ({100*intertidal_count/valid_lat.size:.1f}%)")

    # Write output rasters
    nrows, ncols = dem_msl.shape
    output_profile = {
        'driver': 'GTiff',
        'dtype': 'float32',
        'width': ncols,
        'height': nrows,
        'count': 1,
        'crs': dem_crs,
        'transform': dem_transform,
        'nodata': np.nan,
        'compress': 'lzw',
    }

    test_msl_path = os.path.join(OUTPUT_DIR, "test_dem_msl.tif")
    test_lpt_path = os.path.join(OUTPUT_DIR, "test_lpt_looked_up.tif")
    test_lat_path = os.path.join(OUTPUT_DIR, "test_dem_lat.tif")

    print(f"\n  Writing test rasters:")
    print(f"    {test_msl_path}")
    with rasterio.open(test_msl_path, 'w', **output_profile) as dst:
        dst.write(dem_msl, 1)

    print(f"    {test_lpt_path}")
    with rasterio.open(test_lpt_path, 'w', **output_profile) as dst:
        dst.write(lpt_looked_up, 1)

    print(f"    {test_lat_path}")
    with rasterio.open(test_lat_path, 'w', **output_profile) as dst:
        dst.write(dem_lat, 1)

    print(f"\nVerification in QGIS:")
    print(f"  1. Open {test_lpt_path}")
    print(f"     Compare against {LPT_TIF}")
    print(f"     They should match spatially (LPT resampled to DEM pixels via nearest neighbour)")
    print(f"  2. Raster Calculator: \"{test_msl_path}\" - \"{test_lat_path}\"")
    print(f"     Result should EXACTLY equal {test_lpt_path} (arithmetic verification)")
    print(f"  3. Check {test_lat_path} with threshold >= 0")
    print(f"     Intertidal areas should make sense (e.g., reef flats, shorelines)")
    print("=" * 60)
    print("TEST MODE COMPLETE")


def main():
    parser = argparse.ArgumentParser(description="Add depth statistics to reef polygons")
    parser.add_argument('--test', action='store_true',
                        help='Run in test mode: output verification rasters and exit')
    args = parser.parse_args()

    if args.test:
        run_test_mode()
        return

    # Load LPT lookup
    lpt_lookup = LPTLookup(LPT_TIF)

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
        (MULTIRES_VRT, 3.4e+38, "MultiResBathyEEZ_2024"),
        (AUSBATHYTOPO_TIF, 3.4e+38, "AusBathyTopo-250m_2024"),
    ]

    print(f"Reading raster from {MULTIRES_VRT}")
    with rasterio.open(MULTIRES_VRT) as src:
        print(f"Raster CRS: {src.crs}")
        print(f"Shapefile CRS: {reefs.crs}")

        # Reproject shapefile if CRS doesn't match
        if src.crs != reefs.crs:
            print("Reprojecting shapefile to match raster CRS...")
            reefs = reefs.to_crs(src.crs)
        current_crs = reefs.crs

    # Calculate statistics for each polygon
    print("Calculating depth percentiles (MSL and LAT) within each reef polygon...")
    p10_msl_values, p50_msl_values, p90_msl_values = [], [], []
    p10_lat_values, p50_lat_values, p90_lat_values = [], [], []
    src_values = []
    total = len(reefs)
    for i, geom in enumerate(reefs.geometry):
        if i % 1000 == 0:
            print(f"Processing feature {i+1}/{total}...")
        result = assign_depth_percentiles(geom, rasters, lpt_lookup,
                                          feature_idx=i, geometry_crs=current_crs)
        p10_msl, p50_msl, p90_msl, p10_lat, p50_lat, p90_lat, src_name = result
        p10_msl_values.append(p10_msl)
        p50_msl_values.append(p50_msl)
        p90_msl_values.append(p90_msl)
        p10_lat_values.append(p10_lat)
        p50_lat_values.append(p50_lat)
        p90_lat_values.append(p90_lat)
        src_values.append(src_name)

    # Add MSL values to the GeoDataFrame
    print("Adding depth percentile statistics to the shapefile...")
    reefs['DEM10pMSL'] = [round(x, 1) if x is not None else None for x in p10_msl_values]
    reefs['DEM50pMSL'] = [round(x, 1) if x is not None else None for x in p50_msl_values]
    reefs['DEM90pMSL'] = [round(x, 1) if x is not None else None for x in p90_msl_values]

    # Add LAT values
    reefs['DEM10pLAT'] = [round(x, 1) if x is not None else None for x in p10_lat_values]
    reefs['DEM50pLAT'] = [round(x, 1) if x is not None else None for x in p50_lat_values]
    reefs['DEM90pLAT'] = [round(x, 1) if x is not None else None for x in p90_lat_values]

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
            est_depth_cat = determine_depth_category(row['DEM90pMSL'], row['DEM90pLAT'])

            # Apply rules. These compensate for imperfect estimates from the DEM.
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
            # Oceanic Platform, Oceanic: If estimated is 'Intertidal', set to 'Deep'
            # (DEM positional offset and coarse resolution causes false intertidal
            # classification for platforms mapped at ~100 m depth contour)
            # This rule was added to fix the classification for two platforms that have near vertical
            # sides, combined with poor DEM data that is offset. This results in the polygon picking
            # the shallow areas, rather than the true depth. This rule should fix up platforms
            # A-9044-11 (8 km NE of Portlock Reefs) and A-9044-08 (6 km S of Eastern Fields)
            elif rb_type == 'Oceanic Platform' and attachment == 'Oceanic':
                if est_depth_cat == 'Intertidal':
                    reefs.at[i, 'DepthCat'] = 'Deep'
                    rule_applied = True
            elif orig_type in ['Pearl Pontoon', 'Channel Marker']:
                reefs.at[i, 'DepthCat'] = 'Surface'
                rule_applied = True

            if rule_applied:
                reefs.at[i, 'DepthCatSr'] = 'RB_Type_L3 rule'
            # If no rule applied, use estimated depth category
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
    valid_p10_msl = [d for d in reefs['DEM10pMSL'] if d is not None]
    valid_p50_msl = [d for d in reefs['DEM50pMSL'] if d is not None]
    valid_p90_msl = [d for d in reefs['DEM90pMSL'] if d is not None]
    valid_p90_lat = [d for d in reefs['DEM90pLAT'] if d is not None]

    print(f"\nProcessed {len(reefs)} reef polygons")
    print(f"Found MSL elevation values for {len(valid_p90_msl)} reef polygons")
    print(f"Found LAT elevation values for {len(valid_p90_lat)} reef polygons")

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

    if valid_p10_msl:
        print(f"\n10th percentile MSL depth: Min={min(valid_p10_msl):.2f}, Max={max(valid_p10_msl):.2f}, Mean={np.mean(valid_p10_msl):.2f}")
    if valid_p50_msl:
        print(f"50th percentile MSL depth: Min={min(valid_p50_msl):.2f}, Max={max(valid_p50_msl):.2f}, Mean={np.mean(valid_p50_msl):.2f}")
    if valid_p90_msl:
        print(f"90th percentile MSL depth: Min={min(valid_p90_msl):.2f}, Max={max(valid_p90_msl):.2f}, Mean={np.mean(valid_p90_msl):.2f}")
    if valid_p90_lat:
        print(f"90th percentile LAT depth: Min={min(valid_p90_lat):.2f}, Max={max(valid_p90_lat):.2f}, Mean={np.mean(valid_p90_lat):.2f}")

    print("\nDone!")


if __name__ == "__main__":
    main()
