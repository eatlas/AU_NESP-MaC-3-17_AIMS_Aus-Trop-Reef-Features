"""
This script downloads the input data for the project. This includes the Australian coastline as a landmask, 
the reef boundaries datasets for the GBR and Torres Strait, as well as for the Coral Sea and the North and
West Australia. It also downloads bathymetry datasets to create a national bathymetry virtual dataset to
estimate the depth of the reef features.

There is one additional dataset that is not downloaded by this script: the ESRI Country shapefile. This
must be manually downloaded because it is available for direct download. See README.md for details.
"""
from data_downloader import DataDownloader

import os
import zipfile
import csv
import time
import configparser
from urllib.parse import urlparse
from pyproj import CRS  # Add this import for the CRS class

# Read configuration from config.ini
config = configparser.ConfigParser()
config.read('config.ini')
download_path = config.get('general', 'in_3p_path')
version = config.get('general', 'version')

# Create an instance of the DataDownloader class
downloader = DataDownloader(download_path=download_path)

print(" --------------------------------------------------------")
print(f"Downloading source data files to {download_path}. This will take a while ...")

# --------------------------------------------------------
# Function to replace the .prj file with WKT2 EPSG:4283
def replace_prj_with_epsg_4283(shapefile_path):
    prj_file = os.path.splitext(shapefile_path)[0] + ".prj"
    print(f"Replacing .prj file at {prj_file} with EPSG:4283 WKT2...")
    # Generate WKT2 string for EPSG:4283 using pyproj
    wkt_content = CRS.from_epsg(4283).to_wkt("WKT2_2019")
    with open(prj_file, "w") as f:
        f.write(wkt_content)
    print(".prj file successfully replaced!")

# The dataset names in the data/in are kept short to prevent long paths causing issues in Windows.
# --------------------------------------------------------
# Australian Coastline 50K 2024 (NESP MaC 3.17, AIMS)
# https://eatlas.org.au/geonetwork/srv/eng/catalog.search#/metadata/c5438e91-20bf-4253-a006-9e9600981c5f
# Hammerton, M., & Lawrey, E. (2024). Australian Coastline 50K 2024 (NESP MaC 3.17, AIMS) (2nd Ed.) 
# [Data set]. eAtlas. https://doi.org/10.26274/qfy8-hj59

# Use this version for overview maps
direct_download_url = 'https://nextcloud.eatlas.org.au/s/DcGmpS3F5KZjgAG/download?path=%2FV1-1%2F&files=Simp'
downloader.download_and_unzip(direct_download_url, 'Coastline50k', subfolder_name='Simp', flatten_directory=True)

direct_download_url = 'https://nextcloud.eatlas.org.au/s/DcGmpS3F5KZjgAG/download?path=%2FV1-1%2F&files=Split'
downloader.download_and_unzip(direct_download_url, 'Coastline50k', subfolder_name='Split', flatten_directory=True)

# REEF DATASETS

# --------------------------------------------------------
# Lawrey, E. P., Stewart M. (2016) Complete Great Barrier Reef (GBR) Reef and Island Feature boundaries 
# including Torres Strait (NESP TWQ 3.13, AIMS, TSRA, GBRMPA) [Dataset]. Australian Institute of Marine 
# Science (AIMS), Torres Strait Regional Authority (TSRA), Great Barrier Reef Marine Park Authority [producer]. 
# eAtlas Repository [distributor]. https://eatlas.org.au/data/uuid/d2396b2c-68d4-4f4b-aab0-52f7bc4a81f5
direct_download_url = 'https://nextcloud.eatlas.org.au/s/xQ8neGxxCbgWGSd/download/TS_AIMS_NESP_Torres_Strait_Features_V1b_with_GBR_Features.zip'
downloader.download_and_unzip(direct_download_url, 'TS-GBR-Feat')

# Replace the .prj file for the GBR shapefile because it is using an older WKT format
# that fails to load correctly in stages 3.
gbr_shapefile = os.path.join(downloader.download_path, 'TS-GBR-Feat', 'TS_AIMS_NESP_Torres_Strait_Features_V1b_with_GBR_Features.shp')
replace_prj_with_epsg_4283(gbr_shapefile)

# --------------------------------------------------------
# Lawrey, E., Bycroft, R. (2025). Coral Sea Features - Dataset collection - Coral reefs, Cays, Oceanic 
# reef atoll platforms, and Depth contours (AIMS). [Data set]. eAtlas. https://doi.org/10.26274/pgjp-8462
# Reefs and Cays
direct_download_url = 'https://nextcloud.eatlas.org.au/s/DcoZ33bMzeY5JaK/download?path=%2FReefs-Cays'
downloader.download_and_unzip(direct_download_url, 'Coral-Sea-Feat', subfolder_name='Reefs-Cays', flatten_directory=True)

# Atoll Platforms
direct_download_url = 'https://nextcloud.eatlas.org.au/s/DcoZ33bMzeY5JaK/download?path=%2FAtoll-Platforms'
downloader.download_and_unzip(direct_download_url, 'Coral-Sea-Feat', subfolder_name='Atoll-Platforms', flatten_directory=True)

# --------------------------------------------------------
# Lawrey, E., Bycroft, R. (2025). North and West Australian Tropical Reef Features - Boundaries of coral reefs, 
# rocky reefs, sand banks and intertidal zone (NESP-MaC 3.17, AIMS, Aerial Architecture). [Data set]. 
# eAtlas. https://doi.org/10.26274/xj4v-2739
direct_download_url = 'https://nextcloud.eatlas.org.au/s/ZbxtYci3A6WYnHc/download?path=%2Fv0-4'
downloader.download_and_unzip(direct_download_url, 'NW-Aus-Feat_v0-4', flatten_directory=True)


# BATHYMETRY DATASETS
# These three datasets were replaced by the Multi-resolution bathymetry composite surface for Australian waters (EEZ)
# dataset. They are left here for reference only.
# --------------------------------------------------------
# Beaman, R. 2023. AusBathyTopo (Torres Strait) 30m 2023 - A High-resolution Depth Model (20230006C). 
# Geoscience Australia, Canberra. https://dx.doi.org/10.26186/144348
# direct_download_url = 'https://files.ausseabed.gov.au/survey/Australian%20Bathymetry%20Topography%20(Torres%20Strait)%202023%2030m.zip'
# downloader.download_and_unzip(direct_download_url, 'TS_GA_AusBathyTopo-30m_2023')

# --------------------------------------------------------
# Beaman, R.J. 2017. AusBathyTopo (Great Barrier Reef) 30m 2017 - A High-resolution Depth Model 
# (20170025C). Geoscience Australia, Canberra. http://dx.doi.org/10.4225/25/5a207b36022d2
# direct_download_url = 'https://files.ausseabed.gov.au/survey/Great%20Barrier%20Reef%20Bathymetry%202020%2030m.zip'
# downloader.download_and_unzip(direct_download_url, 'GBR_GA_Bathymetry-30m_2017')

# --------------------------------------------------------
# Lebrec, U., Paumard, V., O’Leary, M. J., & Lang, S. C. (2021). Towards a regional high-resolution bathymetry 
# of the North West Shelf of Australia based on Sentinel-2 satellite images, 3D seismic surveys, and historical 
# datasets. Earth System Science Data, 13(11), 5191–5212. https://doi.org/10.5194/essd-13-5191-2021
# https://ecat.ga.gov.au/geonetwork/srv/eng/catalog.search#/metadata/144600
# Data: https://doi.org/10.26186/144600
# direct_download_url = 'https://ausseabed-public-warehouse-bathymetry.s3.ap-southeast-2.amazonaws.com/L3/1d6f5de4-84ff-4177-a90d-77997ba8d688/North_West_Shelf_DEM_v2_Bathymetry_2020_30m_MSL_cog.tif'
# downloader.download_only(direct_download_url, 'NWS-DEM-30m_2021') 

# --------------------------------------------------------
# Geoscience Australia. (2024).AusBathyTopo (Australia) 250m 2024 - A national-scale depth model (20240011C). 
# https://doi.org/10.26186/150050
direct_download_url = 'https://files.ausseabed.gov.au/survey/AusBathyTopo%20(Australia)%202024%20250m.zip'
downloader.download_and_unzip(direct_download_url, 'AusBathyTopo-250m_2024')    

# --------------------------------------------------------
# Flukes, E., (2024). Multi-resolution bathymetry composite surface for Australian waters (EEZ). 
# Institute for Marine and Antarctic Studies (IMAS). Data accessed from 
# https://metadata.imas.utas.edu.au/geonetwork/srv/eng/catalog.search#/metadata/69e9ac91-babe-47ed-8c37-0ef08f29338a 
# on 31 July 2025
# These are 22GB and 37 GB files so they will take a while to download.
direct_download_url = 'https://data.imas.utas.edu.au/attachments/69e9ac91-babe-47ed-8c37-0ef08f29338a/bathymetry/01_shallow_bathy.tif'
downloader.download_only(direct_download_url, 'MultiRes-Bathy-EEZ_2024') 

# We need to mesophotic bathymetry for 30-70m depth range as a lot of deeper reefs are in this range.
direct_download_url = 'https://data.imas.utas.edu.au/attachments/69e9ac91-babe-47ed-8c37-0ef08f29338a/bathymetry/02_mesophotic_bathy.tif'
downloader.download_only(direct_download_url, 'MultiRes-Bathy-EEZ_2024') 


# --------------------------------------------------------
# Download the input data associated with this dataset. This includes all the manual edits that will
# be applied to the GBR and Torres Strait datasets.
# Switch to downloading the in data associated with this dataset.


downloader.download_path = config.get('general', 'in_path')

# There is a risk that will overwrite any existing manually edited data. The script should however
# skip if the in folder already exists.
direct_download_url = f'https://nextcloud.eatlas.org.au/s/dQeoxzja6tCYSko/download?path=%2F{version}%2Fin'
# Extract the zip contents directly to the download_path but not specifying a dataset_name
# because we expect the path to be complete from the config.ini without a subfolder.
# Even though download_and_unzip will skip if the folder already exists,
# apply an additional check here to make it explicit that we are not overwriting
# any existing manually edited data.
if not os.path.exists(downloader.download_path):
    print(f"Downloading input data to {downloader.download_path} ...")
    downloader.download_and_unzip(direct_download_url, flatten_directory=True)
else:
    print(f"Input data folder {downloader.download_path} already exists. Skipping download to avoid overwriting any existing manually edited data.")
# --------------------------------------------------------
# Remind the user that they have to manually download the dataset.
# We cannot download automatically.
print("Make sure you have downloaded the Union of the ESRI Country shapefile. See README.md for details.")