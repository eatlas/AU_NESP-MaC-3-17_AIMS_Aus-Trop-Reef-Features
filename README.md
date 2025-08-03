# Australian Tropical Reef Features
This dataset is a compilation and standarisation of multiple reef mapping datasets to produce a national scale dataset that covers rocky and coral reefs for tropical Australia. It combines mapping from
1. GBRMPA GBR Features extracted from Lawrey and Stewart, 2016, and improved through 990 manual edits.
2. Torres Strait Features (Lawrey and Stewart, 2016)
3. Coral Sea Features (Lawrey and Bycroft, 2025a)
4. North and West Australian Features (Lawrey and Bycroft, 2025b)

All features were standardised to the Reef Boundary Type classification. Where depth categories were not previously assigned (Torres Strait, GBR and ~30% of the North and West Features) the depth of the features was estimated using two datasets. For reefs inside the EEZ the Multi-resolution bathymetry composite surface for Australian waters (EEZ) (Flukes, 2024) was used. For reefs outside the EEZ the AusBathyTopo (Australia) 250m 2024 (Geoscience Australia, 2024) bathmetry was used.

Each of the features were assigned their sovereignty using Flanders Marine Institute, 2024, to allow easy filtering of reefs to those inside the Australian EEZ.

After the depth category estimation the `RB_Type_L3`, `Attachment` and `DepthCat` are used to crosswalk to the Natural Values Common Language and the Seamap Australia Classification scheme. 

# Environment Setup
The following is the setup needed to reproduce or extend this dataset. This is not needed if all you want to do is use the final dataset.

## Tools used:
- Python - Run scripts that download all source data, then adjust and normalise the input data to allow them to be merged into the final dataset.
- QGIS - This is used for adjusting the manual clean up and adjustment that was applied to the GBR mapping.

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
1. Clone this dataset to your local machine.
2. Edit the `config.ini` to specify where you want to store the downloaded input datasets. In my case I am saving them to temporary folder. The total space needed for the input data is 74 GB.
3. Setup your Python environment to run the scripts for the dataset (see the Python setup section)
4. Run `python 01-download-input-data.py` to download the input source datasets. This downloads the third party datasets, such as the source reef boundary datasets and bathymetry data, but also the manual correction datasets that were created for this dataset. These are stored in `data/v0-1/in` where v0-1 corresponds to the current version. Note the version number is specified in `config.ini`. This script will take a long time to run as it involves downloading a lot of data. The script is restartable, in that it will not redownload a file that it has already downloaded previously. This means if one of the downloads fail for some reason, rerunning the script will mean it doesn't need to start from scratch. It does not resume mid-download of a single dataset.
5. Run `01b-create-bathy-virtual-raster.py` to create a virtual raster of all the bathymetry datasets that were downloaded. This virtual raster has the AusBathyTopo 250 m on the bottom of the stack, then higher resolution composite regional DEMs layed on top. These bathymetry datasets are used to estimate the depth classification of reefs that are not estimate from satellite imagery by `05-add-depth.py`.
6. Run `02a-patch-TS-GBR-Features.py`, `02b-patch-NW-Aus-Features.py` `02c-patch-CS-Features.py` to prepare each of the regional reef mapping datasets. These scripts standarise the outputs, ensuring that the attributes are ready for merging into a single dataset. The GBR processing also applies corrections (removal of false reefs, boundary cleanups, classification corrections) base on `data/{version}/in/Complete-GBR-ExtraFeatures.shp` and `data/{version}/in/Complete-GBR-FeatType-Override.shp`.
7. Run `03-merge-TS-GBR-CS-NW.py`. This script merges all the normalised reef datasets into a single national dataset.
8. In preparation to assigning each reef to a country download the Union of the ESRI Country shapefile and the Exclusive Economic Zones dataset. This is needed to assign the Country attribute to the reefs. This dataset is not downloadable by script and so must be downloaded manually.

    Flanders Marine Institute (2024). Union of the ESRI Country shapefile and the Exclusive Economic Zones (version 4). Available online at https://www.marineregions.org/. https://doi.org/10.14284/698

    The shapefile should be downloaded and unzipped to config.ini `{in_3p_path}\EEZ-land-union_2024\`

    Make sure that the shape file is at the path: `{in_3p_path}\EEZ-land-union_2024\EEZ_land_union_v4_202410.shp`

9. Run `04-add-country-attribute.py` uses the world EEZ dataset to add sovereignty information to each reef. 
10. Run `05-add-depth.py`. This assigns a depth classification to each reef based on the virtual raster bathymetry created by `01b-create-bathy-virtual-raster.py`. This only sets the depth classification for features that have not been set in the source datasets. This is to ensure that we retain any source depth classification that are likely to be more accurate than that determined from the bathymetry dataset. This is because for small reefs the bathymetry virtual raster will be too low a resolution to accurately determine the peak height (shallowest portion) of the reef. We found that for small reefs (~100 m) across the error in the peak height from 30 m resolution bathyemtry was 7 - 9 m and for 100 m bathymetry the error can be as much as 30 - 40 m. Since the base national bathymetry is 250 m error, depth estimates from only the DEM can be very significant for small reefs.
11. Run `06-correct-classifications.py`

## Standardistion of datasets
### Stage 1 - Map to RB_Type_L3
The first stage of integrating the datasets is normalising the datasets to a common set of Reef Boundary Type classification attributes: `EdgeSrc`, `EdgeAcc_m`, `FeatConf`,`TypeConf`,`DepthCat`, `DepthCatSr`, `RB_Type_L3`, `Attachment`. In addition to these core attributes we should retain any existing `ReefID`, and record `OrigType` so we can see any type modifications. We also ensure that we have an assigned `Dataset`. Where a dataset does not provide an existing attribute suitable for this mapping then the value should be left blank, provided this will not cause a problem later in the processing.
In addition to this the dataset source should be recorded in the `Dataset` attribute. This will correspond to: 
- `TS Features`: Torres Strait Features [(Lawrey and Stewart, 2016)](https://doi.org/10.26274/vhj5-gr60)
- `CS Features`: Coral Sea Features [(Lawrey and Bycroft, 2025a)](https://doi.org/10.26274/PGJP-8462)
- `GBR Features`: Great Barrier Reef Features extracted from [(Lawrey and Stewart, 2016)](https://doi.org/10.26274/vhj5-gr60). This corresponds to the 2008 version of the GBR Features from GBRMPA.
- `Aus-Trop-Features_v0-1`: Any new features added as part of the improvements to the GBR mapping. These features are new as part of this dataset.
- `NW-Aus-Features_v0-4`:  North and West Australian Features [(Lawrey and Bycroft, 2025b)](https://doi.org/10.26274/xj4v-2739)

### Stage 2 - Fill in missing depth values
In many cases the datasets will be missing any suitable `DepthCat` classification. This classification is needed to assign a suitable NVCL classification. We therefore use the Multi-resolution bathymetry composite (Flukes, 2024) dataset to estimate an approximate depth category for features that have not existing assigned class. Where this depth class is assigned the `DepthCatSr` was set to `MultiRes-Bathy-EEZ 2024`. In addition to the depth classification we record depth estimates `DEMmax` and `DEMmedian` as additional information about the features. 

### Stage 3 - Crosswalk to fill in RB Type Level 1 & 2, and NVCL
Using a crosswalk (based on config.ini > general > in_3p_path `NW-Aus-Feat_v0-4/in/RB_Type_L3_crosswalk.csv`) the attributes for `RB_Type_L2`, `RB_Type_L1` and `NvclEco` and `NvclEcoCom` will be added. 

### Stage 4 - Add feature soverignty 
Some of the mapped features are outside the Australian EEZ and so to assist in preparing summary statistics each features is assigned to its matching 'country'. This ends up getting complicated when a feature is split over the EEZ boundary. To resolve this we calculate the percentage of the feature areas that occurs in each territory (`SOV1_PCT`, `SOV2_PCT`), recording the largest two sovereignties (`Sovereign1`, `Sovereign2`). Details of any shared territory are recorded in the `Union` attribute. All the assignment to sovereignties and unions comes from the `Union of the ESRI Country shapefile and the Exclusive Economic Zones` dataset (Flanders Marine Institute, 2024).



### Complete GBR (TS Features + GBR Features)
This dataset contains both reefs, islands and the Queensland mainland. We need to remove all features other than rocky and coral reefs. We also need to correct the classification of some feature types as there are sand banks that were assigned the classification of reef.

We correct this by having an override point shapefile that will correct these features.

`data\v0-1\in\Complete-GBR-FeatType-Override.shp` Is used to record these overrides. The classification of the reefs was based on manual review of Sentinel composite imagery (Lawrey and Hammerton, 2024).

This was used to mark false positive features that should be removed and features that are originally marked as 'Reef' but are infact banks.

In the northern parts of the GBR there are many reef features that are significantly off position. To correct these we marked the features to be moved as 'Moved' in the FeatType-Override, then added a new digitised version, or a copy from the original in the correct location in the `Complete-GBR-ExtraFeatures.shp`. To ensure the moved feature retains the original feature details we record the CODE of the moved feature in the ExtraFeatures dataset. Where this is filled in the feature will obtain the details of the original feature.

Edits were kept to a minimum and only when the GBR feature reef position was so far off that it didn't overlap with the actual reef.

Keep just rocky reefs and coral reefs
"FEAT_NAME" = 'Rock'  OR "FEAT_NAME" = 'Reef'



## Override and ExtraFeatures

4 hours of corrections were applied to the TS-GBR-Features 
ExtraFeatures 476 Features - 258 KB
Override 334 Features - 28.7 KB

4 hr 20 min 
ExtraFeatures 505 features
Override 335 features

4 hr 45 min
ExtraFeatures 519 features
Override 358 features

6 hr 10 min
ExtraFeatures 698 features
Override 393 features

7 hr 10 min
ExtraFeatures 798 features - 405 KB
Override 412 features - 35 KB

8 hr 30 min
ExtraFeatures 877 features - 657 KB
Override 445 features - 38 KB

9 hr 20 min
ExtraFeatures 927 features - 657 KB
Override 480 features - 38 KB

## References

Flanders Marine Institute (2024). Union of the ESRI Country shapefile and the Exclusive Economic Zones (version 4). Available online at https://www.marineregions.org/. https://doi.org/10.14284/698

Flukes, E., (2024). Multi-resolution bathymetry composite surface for Australian waters (EEZ).  Institute for Marine and Antarctic Studies (IMAS). Data accessed from https://metadata.imas.utas.edu.au/geonetwork/srv/eng/catalog.search#/metadata/69e9ac91-babe-47ed-8c37-0ef08f29338a on 31 July 2025

Geoscience Australia. (2024). AusBathyTopo (Australia) 250m 2024 - A national-scale depth model (20240011C). 
# https://doi.org/10.26186/150050

Lawrey, E. P., Stewart M. (2016) Complete Great Barrier Reef (GBR) Reef and Island Feature boundaries including Torres Strait (NESP TWQ 3.13, AIMS, TSRA, GBRMPA) [Dataset]. eAtlas. https://doi.org/10.26274/vhj5-gr60

Lawrey, E., & Bycroft, R., (2025a). Coral Sea Features - Dataset collection - Coral reefs, Cays, Oceanic reef atoll platforms, and Depth contours (AIMS) (Version 1-1) [Data set]. eAtlas. https://doi.org/10.26274/PGJP-8462

Lawrey, E., Bycroft, R., (2025b). North and West Australian Tropical Reef Features - Boundaries of coral reefs, rocky reefs and sand banks (NESP-MaC 3.17, AIMS, Aerial Architecture). [Data set]. eAtlas. https://doi.org/10.26274/xj4v-2739






