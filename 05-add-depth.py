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
      - DEMSr: DEM source, followed by ';EOT20' when LAT statistics are available

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
    5. Record the source of the depth category and refresh DEM/LAT provenance
    6. Save the enhanced dataset to a new shapefile

TEST MODE (--test):
    Exercises the production LPT lookup code paths over a test region
    (Whitsundays/Mackay, -20.4 to -22.7 S, 149.18 to 151.2 E) and outputs
    three rasters at DEM native resolution:
    - working/{version}/05/test_dem_msl.tif: Raw DEM values (MSL)
    - working/{version}/05/test_lpt_looked_up.tif: LPT values retrieved via LPTLookup
    - working/{version}/05/test_dem_lat.tif: LAT-adjusted DEM (DEM - LPT)
    Verification: compare test_lpt_looked_up against original LPT (should match
    spatially), and test_dem_msl - test_dem_lat should exactly equal test_lpt_looked_up.

HANDLING SPECIAL CASES:
    - Small reefs (sub-pixel): Uses centroid sampling to get the nearest value
    - Missing data: Returns null values when no valid data exists
    - CRS mismatches: Automatically reprojects data for correct spatial alignment
    - Existing DepthCat values: Preserved for features that already have a depth category

NOTES:
    - Raster lookup and DEM percentile calculations are shared with stage 08
      through reef_utils.py. Depth category rules remain specific to stage 05.
    - Positive values represent elevation above sea level
    - Negative values represent depth below sea level
    - The 90th percentile value represents the highest/shallowest point within each reef
    - The 10th percentile represents the deepest point within each reef
    - LAT conversion: depth_LAT = depth_MSL - LPT (where LPT is negative relative to MSL)
    - The Shallow/Deep boundary (-30 m) uses MSL datum to align with satellite-derived
      depth estimates using the green channel

DATA FORMATS:
    - Raster arrays use (rows, columns), or (bands, rows, columns) when band-first.
      Floating-point arrays use NaN for missing values after nodata masking.
    - Coordinate arrays contain pixel-centre x/y values in the DEM CRS, not
      necessarily longitude/latitude. Flattened arrays retain matching pixel order.
    - Reef tables contain one row per polygon. DEM percentile columns are
      floating-point elevations in metres; missing table values may be None or NaN.
      DEMSr and DepthCatSr identify sources; DepthCat contains category text.
    - Type hints describe data for readers and static analysis, not runtime checks.
"""

import os
import argparse
import geopandas as gpd
import rasterio
import numpy as np
from numpy.typing import NDArray
from rasterio.crs import CRS
from rasterio.windows import from_bounds
from shapely.geometry import box
import configparser
import pandas as pd
from reef_utils import (
    DEM_FIELDS,
    LPTLookup,
    MULTIRES_BATHY_NODATA,
    calculate_depth_statistics,
    get_pixel_coordinates,
    prepare_depth_rasters,
)

# Read configuration for DEM dataset paths
config = configparser.ConfigParser()
config.read('config.ini')
download_path = config.get('general', 'in_3p_path')
version = config.get('general', 'version')

# Define input and output paths
INPUT_SHAPE = os.path.join("working", version, "04", "TS-GBR-CS-NW-Features-Country.shp")
OUTPUT_DIR = os.path.join("working", version, "05")
MULTIRES_VRT = os.path.join(OUTPUT_DIR, "MultiRes-Bathy-EEZ_2024.vrt")
LPT_TIF = os.path.join(download_path, "EOT20-tides", "AU_AIMS_EOT20-tide-stats_LPT_2021-01-2025-12.tif")
OUTPUT_SHAPE = os.path.join(OUTPUT_DIR, "TS-GBR-CS-NW-Features-depth.shp")

# Create output directory if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)


def determine_depth_category(
    p90_msl: float | None,
    p90_lat: float | None,
) -> str | None:
    """Determine depth category based on DEM90pLAT and DEM90pMSL values.

    Args:
        p90_msl: 90th-percentile elevation in metres relative to MSL, or None.
        p90_lat: 90th-percentile elevation in metres relative to LAT, or None.

    Returns:
        Intertidal, Very Shallow, Shallow or Deep; None if p90_msl is None.

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


def run_test_mode() -> None:
    """Test mode: exercises the production LPT lookup code path over a test region.

    Uses the same get_pixel_coordinates() and LPTLookup.get_values_for_pixels() functions
    as the main processing loop to generate verification rasters at DEM native resolution.

    Test region: Whitsundays/Mackay area (-20.4 to -22.7 S, 149.18 to 151.2 E)
    This covers a large tidal range gradient and reef areas that should become intertidal.

    Creates (all at DEM native resolution, clipped to test region):
      - working/{version}/05/test_dem_msl.tif: Raw DEM values (MSL)
      - working/{version}/05/test_lpt_looked_up.tif: LPT values retrieved via LPTLookup (production code path)
      - working/{version}/05/test_dem_lat.tif: LAT-adjusted DEM (DEM - LPT)

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
    lpt_lookup: LPTLookup = LPTLookup(LPT_TIF)

    # Open DEM and extract the test region at native resolution
    dem_path = MULTIRES_VRT
    if not os.path.exists(dem_path):
        prepare_depth_rasters(download_path, MULTIRES_VRT)

    print(f"\nOpening DEM raster: {dem_path}")
    with rasterio.open(dem_path) as dem_src:
        dem_crs: CRS | None = dem_src.crs
        dem_nodata = MULTIRES_BATHY_NODATA
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

    # Shape (rows, columns); elevation in metres relative to MSL, NaN for nodata.
    dem_msl: NDArray[np.float32] = dem_data.astype(np.float32)
    dem_msl[dem_data == dem_nodata] = np.nan

    # Now use the PRODUCTION code path to look up LPT values for each DEM pixel
    print("  Computing pixel coordinates using get_pixel_coordinates()...")
    # get_pixel_coordinates expects shape (1, nrows, ncols) for out_image
    out_image_3d: NDArray[np.float32] = dem_msl[np.newaxis, :, :]
    # Pixel-centre grids, shape (rows, columns), in the DEM CRS.
    xs: NDArray[np.float64]
    ys: NDArray[np.float64]
    xs, ys = get_pixel_coordinates(out_image_3d, dem_transform)

    print(f"  Coordinate grid shape: {xs.shape}")
    print(f"  X range: {xs.min():.4f} to {xs.max():.4f}")
    print(f"  Y range: {ys.min():.4f} to {ys.max():.4f}")

    # Flatten for LPT lookup (same as production code)
    xs_flat: NDArray[np.float64] = xs.ravel()
    ys_flat: NDArray[np.float64] = ys.ravel()

    # Use production LPTLookup.get_values_for_coords() (handles CRS reprojection internally)
    print("  Looking up LPT values using LPTLookup.get_values_for_coords()...")
    # One LPT elevation (metres relative to MSL) per DEM pixel; NaN if unavailable.
    lpt_values_flat: NDArray[np.float64] = lpt_lookup.get_values_for_coords(xs_flat, ys_flat, dem_crs)
    lpt_looked_up: NDArray[np.float64] = lpt_values_flat.reshape(dem_msl.shape)

    # Calculate LAT-adjusted DEM using production formula: DEM_LAT = DEM_MSL - LPT
    dem_lat: NDArray[np.float64] = dem_msl - lpt_looked_up

    # Report statistics
    # One-dimensional arrays of non-missing elevations for summary statistics.
    valid_msl: NDArray[np.float32] = dem_msl[~np.isnan(dem_msl)]
    valid_lpt: NDArray[np.float64] = lpt_looked_up[~np.isnan(lpt_looked_up)]
    valid_lat: NDArray[np.float64] = dem_lat[~np.isnan(dem_lat)]
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


def main() -> None:
    """Read reef polygons, add depth statistics and categories, and save a shapefile."""
    parser = argparse.ArgumentParser(description="Add depth statistics to reef polygons")
    parser.add_argument('--test', action='store_true',
                        help='Run in test mode: output verification rasters and exit')
    args = parser.parse_args()

    if args.test:
        run_test_mode()
        return

    # Load LPT lookup
    lpt_lookup: LPTLookup = LPTLookup(LPT_TIF)

    print(f"Reading shapefile from {INPUT_SHAPE}")
    # One row per reef, with Polygon/MultiPolygon geometry and classification fields.
    reefs: gpd.GeoDataFrame = gpd.read_file(INPUT_SHAPE)

    # Fallback order of (raster path, nodata sentinel, source name).
    rasters: list[tuple[str, float, str]] = prepare_depth_rasters(download_path, MULTIRES_VRT)

    print(f"Reading raster from {MULTIRES_VRT}")
    with rasterio.open(MULTIRES_VRT) as src:
        print(f"Raster CRS: {src.crs}")
        print(f"Shapefile CRS: {reefs.crs}")

        # Reproject shapefile if CRS doesn't match
        if src.crs != reefs.crs:
            print("Reprojecting shapefile to match raster CRS...")
            reefs = reefs.to_crs(src.crs)

    # Refresh the six percentile fields (metres, MSL/LAT) and their source together.
    depth_statistics: pd.DataFrame = calculate_depth_statistics(reefs, rasters, lpt_lookup)
    reefs[list(DEM_FIELDS)] = depth_statistics[list(DEM_FIELDS)]

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
            rb_type = str(row.get('RB_Type_L3', '')).strip()
            attachment = str(row.get('Attachment', '')).strip()
            orig_type = str(row.get('OrigType', '')).strip()
            est_depth_cat: str | None = determine_depth_category(row['DEM90pMSL'], row['DEM90pLAT'])

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
                reefs.at[i, 'DepthCatSr'] = row['DEMSr']

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
