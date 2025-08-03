"""
This script create a virtual raster (VRT) from multiple bathymetry datasets. It stacks high resolution
regional composite bathymetry datasets over the national bathymetry AusBathyTopo 250 m dataset. Having
a virtual raster allows us to extract the estimated depths of reefs using the best available bathymetry
with having render a single raster file at the highest resolution.
"""
import os
import configparser
from osgeo import gdal, osr

# Read configuration
config = configparser.ConfigParser()
config.read('config.ini')
download_path = config.get('general', 'in_3p_path')

print(f"Creating virtual raster from bathymetry datasets in {download_path}")

# Define input raster files
# Australia 250m (bottom layer)
aus_raster = os.path.join(download_path, 'AusBathyTopo-250m_2024', 
                         'AusBathyTopo__Australia__2024_250m_MSL_cog.tif')

# Great Barrier Reef 30m (middle layer)
gbr_rasters = [
    os.path.join(download_path, 'GBR_GA_Bathymetry-30m_2017', 'Great_Barrier_Reef_A_2020_30m_MSL_cog.tif'),
    os.path.join(download_path, 'GBR_GA_Bathymetry-30m_2017', 'Great_Barrier_Reef_B_2020_30m_MSL_cog.tif'),
    os.path.join(download_path, 'GBR_GA_Bathymetry-30m_2017', 'Great_Barrier_Reef_C_2020_30m_MSL_cog.tif'),
    os.path.join(download_path, 'GBR_GA_Bathymetry-30m_2017', 'Great_Barrier_Reef_D_2020_30m_MSL_cog.tif')
]

# Torres Strait 30m (top layer)
ts_raster = os.path.join(download_path, 'TS_GA_AusBathyTopo-30m_2023',
                        'Australian_Bathymetry_Topography__Torres_Strait__2023_30m_MSL_cog.tif')

# North West Shelf 30m (top layer)
nws_raster = os.path.join(download_path, 'NWS-DEM-30m_2021',
                        'North_West_Shelf_DEM_v2_Bathymetry_2020_30m_MSL_cog.tif')
nws_raster_reprojected = os.path.join(download_path, 'NWS-DEM-30m_2021',
                        'North_West_Shelf_DEM_v2_Bathymetry_2020_30m_MSL_cog_WGS84.tif')

# Check if NWS raster exists and needs reprojection
if os.path.exists(nws_raster):
    need_reprojection = True
    
    # If the reprojected file already exists, we can skip reprojection
    if os.path.exists(nws_raster_reprojected):
        need_reprojection = False
        print(f"Using existing reprojected NWS DEM: {nws_raster_reprojected}")
    
    if need_reprojection:
        print(f"Reprojecting NWS DEM to WGS84 as a COG...")
        
        # First, perform the reprojection with appropriate options
        temp_file = nws_raster_reprojected + ".temp.tif"
        
        # Step 1: Reproject to WGS84
        warp_options = gdal.WarpOptions(
            dstSRS='EPSG:4326',
            resampleAlg='bilinear',
            multithread=True,
            warpOptions=['NUM_THREADS=ALL_CPUS'],
            warpMemoryLimit=2048,
            creationOptions=[
                'COMPRESS=DEFLATE',
                'PREDICTOR=2',
                'TILED=YES',
                'BLOCKXSIZE=512',
                'BLOCKYSIZE=512'
            ]
        )
        
        gdal.Warp(temp_file, nws_raster, options=warp_options)
        
        # Step 2: Create COG with proper structure
        # Set the environment variables for creating a COG
        gdal.SetConfigOption('GDAL_TIFF_OVR_BLOCKSIZE', '512')
        gdal.SetConfigOption('COMPRESS_OVERVIEW', 'DEFLATE')
        gdal.SetConfigOption('PREDICTOR_OVERVIEW', '2')
        
        # Open source file
        src_ds = gdal.Open(temp_file)
        
        # Create target dataset with COG optimizations
        driver = gdal.GetDriverByName('GTiff')
        dst_ds = driver.CreateCopy(
            nws_raster_reprojected, 
            src_ds, 
            options=[
                'COPY_SRC_OVERVIEWS=YES',
                'COMPRESS=DEFLATE',
                'PREDICTOR=2',
                'TILED=YES',
                'BLOCKXSIZE=512', 
                'BLOCKYSIZE=512',
                'BIGTIFF=YES'
            ]
        )
        
        # Build overviews using pure Python GDAL
        overview_list = [2, 4, 8, 16]
        dst_ds.BuildOverviews("NEAREST", overview_list)
        
        # Close datasets to flush to disk
        src_ds = None
        dst_ds = None
        
        # Clean up temporary file
        if os.path.exists(temp_file):
            os.remove(temp_file)
            
        print(f"Reprojection completed: {nws_raster_reprojected}")
    
    # Use the reprojected file in the VRT
    nws_raster = nws_raster_reprojected

# Create output directory if it doesn't exist
out_dir = 'working'
os.makedirs(out_dir, exist_ok=True)

# Output VRT file
vrt_path = os.path.join(out_dir, 'AusBathyTopo.vrt')

# Stack order matters - list files from bottom to top
# Order: Australia (250m) -> GBR (30m) -> Torres Strait (30m) -> NWS (30m)
input_files = [aus_raster] + gbr_rasters + [ts_raster] + [nws_raster]

# Verify all input files exist
for file_path in input_files:
    if not os.path.exists(file_path):
        print(f"WARNING: File not found: {file_path}")

# Create the VRT
print(f"Creating VRT from {len(input_files)} input rasters...")
vrt_options = gdal.BuildVRTOptions(resolution='highest', separate=False, addAlpha=False)
vrt = gdal.BuildVRT(vrt_path, input_files, options=vrt_options)

# This is needed to write the VRT to disk
vrt = None

print(f"Virtual raster created at {vrt_path}")