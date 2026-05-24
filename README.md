# Australian Tropical Reef Features
This dataset is a compilation and standarisation of multiple reef mapping datasets to produce a national scale dataset that covers rocky and coral reefs for tropical Australia. It combines mapping from:
1. GBRMPA GBR Features extracted from Lawrey and Stewart, 2016, and improved through manual edits, mostly on the inshore areas.
2. Torres Strait Features (Lawrey and Stewart, 2016)
3. Coral Sea Features (Lawrey and Bycroft, 2025a)
4. North and West Australian Features (Lawrey and Bycroft, 2025b)

All features were standardised to the Reef Boundary Type v0-4 classification. Where depth categories were not previously assigned (Torres Strait, GBR) the depth of the features was estimated using two datasets. For reefs inside the EEZ the Multi-resolution bathymetry composite surface for Australian waters (EEZ) (Flukes, 2024) was used. For reefs outside the EEZ the AusBathyTopo (Australia) 250m 2024 (Geoscience Australia, 2024) bathymetry was used.

Each of the features were assigned their sovereignty using Flanders Marine Institute, 2024, to allow easy filtering of reefs to those inside the Australian EEZ.

After depth category estimation the `RB_Type_L3`, `Attachment` and `DepthCat` are used to crosswalk to the Natural Values Common Language and the Seamap Australia Classification scheme. 

## Dataset metadata
To download and find out more information see the metadata record for this dataset:
Lawrey, E., Bycroft, R. (2025). Australian Tropical Reef Features - Boundaries of coral and rocky reefs (NESP MaC 3.17, AIMS) (Version v0-9) [Data set]. eAtlas. https://doi.org/10.26274/4RRW-RR88

## Environment Setup
The following is the setup needed to reproduce or extend this dataset. All input files are available for download and the output files are a direct result of running the processing scripts. All modifications to the TS-GBR-Features datasets are recorded as modification shapefiles allowing full reproducibility. 

Setting up the working environment is only needed if you want to reproduce this work, or extend it to make improvements. This is not needed if all you want to do is use the final dataset.

## Tools used:
- Python - Run scripts that download all source data, then adjust and normalise the input data to allow them to be merged into the final dataset. This is setup using Conda.
- QGIS - This is used for adjusting the manual clean up and override shapefiles that are applied to the TS-GBR mapping. This is also useful for checking the output files.
- FFMpeg and [QGIS Animated Atlas plugin](https://github.com/open-AIMS/qgis-animated-atlas) for animated preview map.

## Python setup
There are many ways to setup Python. In this project we use conda to create an environment that contains all the libraries needed for the analysis. The version of Python and the libraries is described in the `environment.yml` file. This includes the specific versions of the libraries used. We specify the version of the libraries to ensure reproducibility of the analysis, but also to speed up the setup of the Python environment as conda resolves dependencies faster when it knows the versions of the libraries it should use.

Conda is a package manager that allows a specific version Python and associated libraries to be installed into an environment that is separate from other Python installations on your machine. [Miniconda](https://www.anaconda.com/docs/getting-started/miniconda/main) is a minature installation of the Anaconda Distribution and is the smallest footprint version of using conda.

To install miniconda follow its [installation guide](https://www.anaconda.com/docs/getting-started/miniconda/install). 

To setup the environment for this dataset run:
```bash
cd {path to the AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features dataset} 
conda env create -f environment.yml
```
2. Activate the environment
```bash
conda activate AusTropReef
```

You are now ready to run the scripts that generate the dataset. 

# Reproducing this dataset:
This section details how to reproduce this dataset from scratch starting with just the source code.
1. Clone this dataset to your local machine. For this you will need Git installed, or you will need to download the zipped version of the source from GitHub.
2. Edit the `config.ini` to specify where you want to store the downloaded input datasets. The total space needed for the input data is 274 GB. Much of this storage is needed for the bathymetry and satellite imagery datasets. 
3. Setup your Python environment to run the scripts for the dataset (see the Python setup section)
4. Run `python 01a-download-input-data.py` to download the input source datasets. This downloads the third party datasets, such as the source reef boundary datasets and bathymetry data, and the manual correction datasets that were created for this dataset. These are stored in `data/{version}` where {version} is the current version of the dataset. Note the version number is specified in `config.ini`. This script will take a long time to run as it involves downloading a lot of data. The script is restartable, in that it will not redownload a file that it has already downloaded previously. This means if one of the downloads fail for some reason, rerunning the script will mean it doesn't need to start from scratch. It does not, however, resume mid-download of a single dataset.
5. Download the satellite imagery by running `python 01b-download-sentinel2.py`. Setup virtual rasters for the satellite imagery by running:
```bash
python 01c-create-virtual-rasters.py --base-dir data/{version}/in-3p/S2
```
6. Run `02a-patch-TS-GBR-Features.py`, `02b-patch-NW-Aus-Features.py` `02c-patch-CS-Features.py` to prepare each of the regional reef mapping datasets. These scripts standarise the outputs, ensuring that the attributes are ready for merging into a single dataset. 
7. Run `03-merge-TS-GBR-CS-NW.py`. This script merges all the normalised reef datasets into a single national dataset. This does not have the depth attributes, the country information or the crosswalks to the NVCL set.
8. In preparation to assigning each reef to a country download the Union of the ESRI Country shapefile and the Exclusive Economic Zones dataset. This is needed to assign the Country attribute to the reefs. This dataset is not automatically downloadable by script and so must be downloaded manually.

    Flanders Marine Institute (2024). Union of the ESRI Country shapefile and the Exclusive Economic Zones (version 4). Available online at https://www.marineregions.org/. https://doi.org/10.14284/698

    The shapefile should be downloaded and unzipped to config.ini `{in_3p_path}\EEZ-land-union_2024\`. This is the same folder where all the other downloaded data is stored.

    Make sure that the shape file is at the path: `{in_3p_path}\EEZ-land-union_2024\EEZ_land_union_v4_202410.shp`

9. Run `04-add-country-attribute.py` uses the world EEZ dataset to add sovereignty information to each reef. 
10. Run `05-add-depth.py`. This assigns a depth classification to each reef that has not already been assigned a depth category. Some of the source datasets (such as CS Features and many of the NW-Aus-Features) already have the `DepthCat` already set and so these are not overridden by this process. The depth is estimated using bathymetry converted to Lowest Astronomical Tide (LAT) using the EOT20 tidal model. The 90th percentile depth (shallowest portion) of each feature is used for classification because the spatial resolution of available bathymetry introduces significant errors when estimating peak heights.
11. Run `06-crosswalk.py`. This script performs the crosswalk to the Natural Values Common Language, Seamap Australia and Queensland Wetlands classifications. It also determines the minimum length string field needed to store each attribute to create a more compact final output shapefile.

## Preview maps
1. Use QGIS to recreate the preview images. Load: `data/{version}/ATR1-working.qgz`. Correct any path issues.
2. Use the Layout manager to open and export each preview map.
3. Install the [QGIS Animated Atlas plugin](https://github.com/open-AIMS/qgis-animated-atlas).
4. Export `ATRF1-Overview-animation` atlas. Save to a location not on OneDrive, such as `C:\temp\ATR1-animation`. This Atlas is controlled by the layers in the `Overview-animation` layer group. Export at 1920x1024 resolution. This export takes about 1 hour.
5. Use FFMpeg to convert the frames into a video:
```bash
ffmpeg -framerate 30 -i C:/temp/ATR1-animation/frame_%06d.png -c:v libx264 -crf 24 -pix_fmt yuv420p data/v0-9/previews/ATRF1-Overview-animation.mp4
```


## Moving the 3rd party data download out of One Drive using a Symbolic link (Windows)

The development of this dataset and the production of the preview maps relies on a bunch of third party datasets. These are large files as a result you may wish for them to be downloaded to a separate location to the default used in this repository. For example you may want to work on this dataset in Teams or on One Drive, but not have the third party data saved in these locations. 

To prevent the QGIS links and code files from breaking we used a fixed location for the third party data, `data\{version}\in-3p\`. By default the data download will save all third party data to this folder and all other files will expect to find the datasets with that root path. To move the data outside this location use a directory symbolic link.

For this we use a symbolic link, rather than a junction because using a junction will cause OneDrive to sync the linked content.

1. Open a command prompt with administrator privledges.
Click Start, type `cmd`, select Run as administrator. You’ll get the UAC prompt.
2. Using a windows command prompt make sure up are in the data folder of the project
```batch
cd <path to project>\AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features\data\{version}
```
3. Create the symbolic link to work the data is stored. You probably need to ensure this folder exists first (untested)
```batch
mklink /D "in-3p" "C:\data-3p\AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features\in-3p"
```

If you can't setup a symbolic link and still want to store the data in a separate folder then you can simple editing the paths in scripts and the paths in the QGIS preview-maps.qgz.

### Removing the link

Deleting the link does **not** delete the data: `rmdir in-3p`. Only the symbolic link is removed.

### Updating config.ini
If you change the path to the `in-3p` files then the default then you should update the `config.ini` file to match. The scripts read this to know where these files are.

## Standardisation of datasets
### Stage 1 - Map to RB_Type_L3 (Scripts 02x and 03)
The first stage of integrating the datasets is normalising the datasets to a common set of Reef Boundary Type classification attributes: `EdgeSrc`, `EdgeAcc_m`, `FeatConf`, `TypeConf`, `DepthCat`, `DepthCatSr`, `RB_Type_L3`, `Attachment`. In addition to these core attributes we retain any existing `ReefID`, and record `OrigType` so we can see any type modifications. We also ensure that we have an assigned `Dataset`. Where a dataset does not provide an existing attribute suitable for this mapping then the value is left blank, provided this will not cause a problem later in the processing.

The dataset source is recorded in the `Dataset` attribute. This will correspond to: 
- `TS Features`: Torres Strait Features [(Lawrey and Stewart, 2016)](https://doi.org/10.26274/vhj5-gr60)
- `CS Features`: Coral Sea Features [(Lawrey and Bycroft, 2025a)](https://doi.org/10.26274/PGJP-8462)
- `GBR Features`: Great Barrier Reef Features extracted from [(Lawrey and Stewart, 2016)](https://doi.org/10.26274/vhj5-gr60). This corresponds to the 2008 version of the GBR Features from GBRMPA.
- `Aus-Trop-Reef-Features_{version}`: Any new or remapped features added as part of the improvements to the GBR and Torres Strait mapping. These features are new as part of this dataset.
- `NW-Aus-Features_{nw_version}`:  North and West Australian Features [(Lawrey and Bycroft, 2025b)](https://doi.org/10.26274/xj4v-2739)

The version numbers in the `Dataset` values are determined from `config.ini` at processing time.

### Stage 2 - Add feature sovereignty (Script 04)
Some of the mapped features are outside the Australian EEZ and so to assist in preparing summary statistics each feature is assigned to its matching country. This ends up getting complicated when a feature is split over the EEZ boundary. To resolve this we calculate the percentage of the feature area that occurs in each territory (`Sov1_Perc`, `Sov2_Perc`), recording the largest two sovereignties (`Sovereign1`, `Sovereign2`). Details of any shared territory are recorded in the `Union` attribute. All the assignment to sovereignties and unions come from the `Union of the ESRI Country shapefile and the Exclusive Economic Zones` dataset (Flanders Marine Institute, 2024). The attribution is supplied for research convenience and is not an official statement of maritime boundaries.

### Stage 3 - Fill in missing depth values (Script 05)
In many cases the datasets will be missing any suitable `DepthCat` classification. This classification is needed to assign a suitable NVCL classification. The script uses two bathymetry sources: the Multi-resolution bathymetry composite (Flukes, 2024) for reefs inside the EEZ, and AusBathyTopo 250m (Geoscience Australia, 2024) as a fallback for reefs outside the EEZ.

The script samples the DEM within each reef boundary and stores 10th, 50th and 90th percentile depths referenced to both Mean Sea Level (MSL) and Lowest Astronomical Tide (LAT). The LAT adjustment is performed using the EOT20 Lowest Predicted Tide (LPT) raster (Lawrey, 2025), which is subtracted from each DEM pixel to convert from MSL to LAT. The resulting attributes are `DEM10pMSL`, `DEM50pMSL`, `DEM90pMSL`, `DEM10pLAT`, `DEM50pLAT`, `DEM90pLAT` and the DEM source is recorded in `DEMSr`.

Where a polygon is smaller than a raster pixel, the centroid value is used. If the source layer already provides `DepthCat`, that value is preserved. Rule-based overrides are applied based on `RB_Type_L3`, `Attachment` and `OrigType` to handle emergent features (e.g. cays are set to Land, Oceanic Platforms with false intertidal readings are corrected). The depth category thresholds (applied to the LAT-adjusted 90th percentile) are: Intertidal (>= 0 m LAT), Very Shallow (< 0 and >= -2.5 m), Shallow (< -2.5 m and MSL 90th >= -30 m), Deep (< -30 m MSL). The logic that sets the final class is captured in `DepthCatSr`.

### Stage 4 - Crosswalk to fill in RB Type Level 1 & 2, and NVCL (Script 06)
Using a crosswalk table (loaded from `{in_3p_path}/NW-Aus-Feat_{nw_version}/in/RB_Type_L3_crosswalk.csv` as specified in config.ini) the script translates each feature into Natural Values Common Language, Seamap Australia, and Queensland Wetlands ecosystems. The crosswalk matches on `RB_Type_L3`, `Attachment` and `DepthCat` (supports semicolon-separated multiple values in the table). Features that fail to match are flagged for review. This script also recalculates `Area_km2` using an equal-area projection (EPSG:3112) and truncates text fields to the minimum required length to save space.

### GBR and Torres Strait corrections (Script 02a)
The TS-GBR-Features dataset was improved prior to its integration into the national scale dataset. This improvement focused on removing false reefs, adding previously unmapped reefs, remapping reef boundaries, and assigning the full Reef Boundary Type classification attributes.

The improvements are controlled with two shapefiles stored in `data/{version}/in/`:
- `Reef-edit/AIMS_GBR-TS-Features_Edit_{version}.shp`: Polygon shapefile containing remapped or new reef features with the full set of RB Type attributes (`FeatConf`, `TypeConf`, `DepthCat`, `DepthCatSr`, `RB_Type_L3`, `Attachment`, `EdgeSrc`, `EdgeAcc_m`). Where a feature has a `CODE` attribute set, it indicates a deliberate replacement of an existing feature (e.g. for moved reefs that no longer overlap their original position).
- `Reef-remove-move/AIMS_GBR-TS-Features_remove-move_{version}.shp`: Point shapefile marking features to be removed or moved. For moves, the corresponding replacement polygon in the Reef Edit file carries the original CODE.

The patching script (`02a-patch-TS-GBR-Features.py`) processes operations in the following order:
1. Moves: Reef Edit features with a CODE matching a remove-move Move point replace the original feature.
2. Removals: Features intersecting a Remove point are deleted.
3. Overlap replacements: Remaining Reef Edit features replace any old features they overlap (using a minimum IoU threshold of 0.1 to inherit the original CODE/ReefID).
4. Retained features: All original features not affected by the above operations are kept with attributes normalised to the common schema.

New features that do not overlap any existing feature are assigned a provisional ID (`PROV-{lat}-{lon}`).

## References

Flanders Marine Institute (2024). Union of the ESRI Country shapefile and the Exclusive Economic Zones (version 4). Available online at https://www.marineregions.org/. https://doi.org/10.14284/698

Flukes, E., (2024). Multi-resolution bathymetry composite surface for Australian waters (EEZ).  Institute for Marine and Antarctic Studies (IMAS). Data accessed from https://metadata.imas.utas.edu.au/geonetwork/srv/eng/catalog.search#/metadata/69e9ac91-babe-47ed-8c37-0ef08f29338a on 31 July 2025

Geoscience Australia. (2024). AusBathyTopo (Australia) 250m 2024 - A national-scale depth model (20240011C). https://doi.org/10.26186/150050

Lawrey, E. (2025). Tidal Statistics for Australia (Tidal range, LAT, HAT, MLWS, MHWS) derived from the EOT20 tidal model (NESP MaC 3.17, AIMS) (v1-1) [Data set]. eAtlas. https://doi.org/10.26274/Z8B6-ZX94

Lawrey, E. P., Stewart M. (2016) Complete Great Barrier Reef (GBR) Reef and Island Feature boundaries including Torres Strait (NESP TWQ 3.13, AIMS, TSRA, GBRMPA) [Dataset]. eAtlas. https://doi.org/10.26274/vhj5-gr60

Lawrey, E., & Bycroft, R., (2025a). Coral Sea Features - Dataset collection - Coral reefs, Cays, Oceanic reef atoll platforms, and Depth contours (AIMS) (Version 1-2) [Data set]. eAtlas. https://doi.org/10.26274/PGJP-8462

Lawrey, E., Bycroft, R., (2025b). North and West Australian Tropical Reef Features - Boundaries of coral reefs, rocky reefs and sand banks (NESP-MaC 3.17, AIMS, Aerial Architecture) (Version 1-1) [Data set]. eAtlas. https://doi.org/10.26274/xj4v-2739


