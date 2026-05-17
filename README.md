# Australian Tropical Reef Features
This dataset is a compilation and standarisation of multiple reef mapping datasets to produce a national scale dataset that covers rocky and coral reefs for tropical Australia. It combines mapping from:
1. GBRMPA GBR Features extracted from Lawrey and Stewart, 2016, and improved through 990 manual edits.
2. Torres Strait Features (Lawrey and Stewart, 2016)
3. Coral Sea Features (Lawrey and Bycroft, 2025a)
4. North and West Australian Features (Lawrey and Bycroft, 2025b)

All features were standardised to the Reef Boundary Type v0-4 classification. Where depth categories were not previously assigned (Torres Strait, GBR and ~30% of the North and West Features) the depth of the features was estimated using two datasets. For reefs inside the EEZ the Multi-resolution bathymetry composite surface for Australian waters (EEZ) (Flukes, 2024) was used. For reefs outside the EEZ the AusBathyTopo (Australia) 250m 2024 (Geoscience Australia, 2024) bathymetry was used.

Each of the features were assigned their sovereignty using Flanders Marine Institute, 2024, to allow easy filtering of reefs to those inside the Australian EEZ.

After the depth category estimation the `RB_Type_L3`, `Attachment` and `DepthCat` were used to crosswalk to the Natural Values Common Language and the Seamap Australia Classification scheme. 

## Dataset metadata
To download and find out more information see the metadata record for this dataset:
Lawrey, E., Bycroft, R. (2025). Australian Tropical Reef Features - Boundaries of coral and rocky reefs (NESP MaC 3.17, AIMS) (Version v0-1) [Data set]. eAtlas. https://doi.org/10.26274/4RRW-RR88

## Environment Setup
The following is the setup needed to reproduce or extend this dataset. All input files are available for download and the output files are a direct result of running the processing scripts. All modifications to the TS-GBR-Features datasets are recorded as modification shapefiles allowing full reproducibility. 

Setting up the working environment is only needed if you want to reproduce this work, or extend it to make improvements. This is not needed if all you want to do is use the final dataset.

## Tools used:
- Python - Run scripts that download all source data, then adjust and normalise the input data to allow them to be merged into the final dataset.
- QGIS - This is used for adjusting the manual clean up and override shapefiles that are applied to the TS-GBR mapping. This is also useful for checking the output files.

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
2. Edit the `config.ini` to specify where you want to store the downloaded input datasets. In my case I am saving them to temporary folder. The total space needed for the input data is 74 GB. Much of this storage is needed for the bathymetry datasets. You may also want the Sentinel 2 imagery, which is an additional 
3. Setup your Python environment to run the scripts for the dataset (see the Python setup section)
4. Run `python 01a-download-input-data.py` to download the input source datasets. This downloads the third party datasets, such as the source reef boundary datasets and bathymetry data, but also the manual correction datasets that were created for this dataset. These are stored in `data/v0-1/in` where v0-1 corresponds to the current version. Note the version number is specified in `config.ini`. This script will take a long time to run as it involves downloading a lot of data (74 GB). The script is restartable, in that it will not redownload a file that it has already downloaded previously. This means if one of the downloads fail for some reason, rerunning the script will mean it doesn't need to start from scratch. It does not, however, resume mid-download of a single dataset.
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

09. Run `04-add-country-attribute.py` uses the world EEZ dataset to add sovereignty information to each reef. 
10. Run `05-add-depth.py`. This assigns a depth classification to each reef that has not already been assigned a depth category. Some of the source datasets (such as CS Features and many of the NW-Aus-Features) already have the `DepthCat` already set and so these are not overridden by this process. This is to ensure that we retain any source depth classification that are likely to be more accurate than that determined from the bathymetry dataset. This is because for most reefs there is no sufficiently high resolution bathymetry to accurately determine the peak height (shallowest portion) of the reef. When trying to determine the highest peak of the lagoonal reefs in the Coral Sea we found that for small reefs (~100 m) across the error in the peak height from 30 m resolution bathyemtry was 7 - 9 m and for 100 m bathymetry the error can be as much as 30 - 40 m. For this reason we have shifted the `DepthCat` classification to be based on the 90th height. 
11. Run `06-cross-walk.py`. This script performs the crosswalk to the Natural Values Common Language, adding attributes `NvclEco` and `NcvlEcoCom`. This script also determines the minimum length string field needed to store each attribute to create a more compact final output shapefile. 

## Moving the 3rd party data download out of One Drive using a Symbolic link (Windows)

The development of this dataset and the production of the preview maps relies on a bunch of third party datasets. These are large files as a result you may wish for them to be downloaded to a separate location to the default used in this repository. For example you may want to work on this dataset in Teams or on One Drive, but not have the third party data saved in these locations. 

To prevent the QGIS links and code files from breaking we used a fixed location for the third party data, `data\{version}\in-3p\`. By default the data download will save all third party data to this folder and all other files will expect to find the datasets with that root path. To move the data outside this location use a directory symbolic link.

For this we use a symbolic link, rather than a junction because using a junction will cause OneDrive to sync the linked content.

1. Open a command prompt with administrator privledges.
Click Start, type `cmd`, select Run as administrator. You’ll get the UAC prompt.
2. Using a windows command prompt make sure up are in the data folder of the project
```batch
cd <path to project>\AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features\data\v1-0
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

## Standardistion of datasets
### Stage 1 - Map to RB_Type_L3 (Scripts 02x and 03)
The first stage of integrating the datasets is normalising the datasets to a common set of Reef Boundary Type classification attributes: `EdgeSrc`, `EdgeAcc_m`, `FeatConf`,`TypeConf`,`DepthCat`, `DepthCatSr`, `RB_Type_L3`, `Attachment`. In addition to these core attributes we should retain any existing `ReefID`, and record `OrigType` so we can see any type modifications. We also ensure that we have an assigned `Dataset`. Where a dataset does not provide an existing attribute suitable for this mapping then the value should be left blank, provided this will not cause a problem later in the processing.
In addition to this the dataset source should be recorded in the `Dataset` attribute. This will correspond to: 
- `TS Features`: Torres Strait Features [(Lawrey and Stewart, 2016)](https://doi.org/10.26274/vhj5-gr60)
- `CS Features`: Coral Sea Features [(Lawrey and Bycroft, 2025a)](https://doi.org/10.26274/PGJP-8462)
- `GBR Features`: Great Barrier Reef Features extracted from [(Lawrey and Stewart, 2016)](https://doi.org/10.26274/vhj5-gr60). This corresponds to the 2008 version of the GBR Features from GBRMPA.
- `Aus-Trop-Features_v0-1`: Any new features added as part of the improvements to the GBR mapping. These features are new as part of this dataset.
- `NW-Aus-Features_v0-4`:  North and West Australian Features [(Lawrey and Bycroft, 2025b)](https://doi.org/10.26274/xj4v-2739)

### Stage 2 - Add feature soverignty (Scripts 04)
Some of the mapped features are outside the Australian EEZ and so to assist in preparing summary statistics each features is assigned to its matching 'country'. This ends up getting complicated when a feature is split over the EEZ boundary. To resolve this we calculate the percentage of the feature areas that occurs in each territory (`Sov1_Perc`, `Sov2_Perc`), recording the largest two sovereignties (`Sovereign1`, `Sovereign2`). Details of any shared territory are recorded in the `Union` attribute. All the assignment to sovereignties and unions come from the `Union of the ESRI Country shapefile and the Exclusive Economic Zones` dataset (Flanders Marine Institute, 2024). The attribution is supplied for research convenience and is not an official statement of maritime boundaries.

### Stage 3 - Fill in missing depth values (Scripts 05)
In many cases the datasets will be missing any suitable `DepthCat` classification. This classification is needed to assign a suitable NVCL classification. We therefore use the Multi-resolution bathymetry composite (Flukes, 2024) dataset to estimate an approximate depth category for features that have not existing assigned class. The script samples the appropriate DEM within each reef boundary, stores the 10th, 50th and 90th percentile depths (DEM10p, DEM50p, DEM90p) and records the DEM source in DEMSr. Where a polygon is smaller than a raster pixel, the centroid value is used. If the source layer already provides DepthCat, that value is preserved. In some cases rule-based overrides are used based on RB_Type_L3, Attachment and OrigType to ensure emergent features are handled correctly. The logic that set the final class is captured in DepthCatSr.

### Stage 4 - Crosswalk to fill in RB Type Level 1 & 2, and NVCL
Using a crosswalk table (based on config.ini > general > in_3p_path `NW-Aus-Feat_v0-4/in/RB_Type_L3_crosswalk.csv`) the script translates each feature into Natural Values Common Language and Seamap Australia ecosystems. Features that fail to match this table are flagged for review. This script also recalculates the Area_km2 using an equal-area projection (EPSG 3112) and truncates the text fields to the minimum required length so save space. 

### Complete GBR (TS Features + GBR Features) corrections
The TS-GBR-Features dataset was slightly improved prior its integration into the national scale dataset. This improvement focused on removing false reefs, adding deeper previously unmapped reefs, making some boundary corrections and adding classifications needed to map the features reliably to the Natural Values Common Language. 
| Improvement                      | Percentage complete |
|-----------------------------------|--------------------|
| Classification adjustments        | 95                 |
| Removing false reefs              | 90                 |
| Adding previously unmapped reefs  | 70                 |
| Correcting boundary position errors | 2                |

Only minimal corrections were made to the existing boundaries, except for a small number of features. The boundary errors for most existing features is quite high, several hundred metres to over one kilometre. 

The improvements to the dataset were controlled with two shapefiles:
- `Complete-GBR-FeatType-Override.shp`: Point shapefile with instructions for the modification to apply, including changing the classification, or to remove, move, or reshape the feature.
- `Complete-GBR-ExtraFeatures.shp`: Updated boundary for an existing feature (matched by the `CODE` attribute), or the boundary of a new feature. 

The features were reclassified based on a manual review of Sentinel composite imagery (Lawrey and Hammerton, 2024). The features were only reclassified to a simplified scheme, with the main aim to indicate separate coral reefs from sand banks and rocky reefs. These classifications align with the RB_Type_L2 and Natural Values Common Language. This simplified classification was used to facilitate rapid corrections to be made, and they align closed with what is needed to mostly describe the diversity of feature in the GBR and Torres Strait.

In the northern parts of the GBR there are many reef features that are significantly off position. To correct these we marked the features to be moved were marked as 'Moved' in the FeatType-Override, then a new digitised version, or a copy from the original in the correct location was saved in the `Complete-GBR-ExtraFeatures.shp`. To ensure the moved feature retains the original feature details we record the CODE of the moved feature in the ExtraFeatures dataset. Where this is filled in the feature will obtain the details of the original feature.

Edits were kept to a minimum and only when the GBR feature reef position was so far off that it didn't overlap with the actual reef.

The `Complete-GBR-FeatType-Override` contains points that indicate overrides of the original types (Bank, Rock) and instructions for modifications (Move, Remove, Reshape, Merge). These points are linked with the input TS-GBR-Features dataset via a spatial join, i.e. the points are matched with the features they intersect. 

The `Complete-GBR-ExtraFeatures` contains additional features that correspond to modifications or additional features. Where there is a Move, Reshape, or Merge override, the original feature is removed and replaced with the ExtraFeature. The CODE attribute corresponds to the ID of the reef that the ExtraFeature is replacing. The CODE is used to look up which features should be deleted and replaced with the polygons from the ExtraFeatures. Where an ExtraFeature corresponds to a new feature (i.e. a new reef), then the CODE attribute is left as NULL as there is no original feature to match to.


Scenarios
- **Situation**: An existing reef feature is larger than it should be, but there is only a single true reef, i.e. a one-to-one relationship to the true reef.
Approach: Replace the exisiting existing reef with a new boundary. Add an ExtraFeature with the CODE of the feature being replaced. 

- **Situation**: An existing reef is much too large and it needs to be remapped as multiple smaller reefs.
Approach: Draw each of the smaller reef features as ExtraFeatures, record the CODE of the existing reef they are replace in each of the features. This effectively indicates that these finer mapped reefs were previously known by a common ID. In v0.1 of the dataset we did not use this approach, but instead only assigned the CODE to the reef that is most likely to retain the ID in the future, i.e. we were making a call on how the IDs will be allocated. This is problematic because the reefs we added that were not allocated a CODE provided no tracibility to theory origin. In v1-0 by assigning the ID on each replacement reef we remove the need to also tag in the override dataset and we retain a trace of 'this reef was previously known as CODE X'.
- **Situation**: Multiple smaller existing features are replaced with a single larger reef.
Approach: This occurs in areas where with better imagery we can see that multiple neighbouring reefs are actually a single larger reef. We add the new boundary to the ExtraFeatures.



#### Override and ExtraFeatures

The following is a tracking of the improvements applied to the TS-GBR-Features dataset. The override time is the total editing time in QGIS.

| Override Time | Extra Features | Overrides |
|---------------|---------------|-----------|
| 4 hours       | 476           | 334       |
| 4 hr 20 min   | 505           | 335       |
| 4 hr 45 min   | 519           | 358       |
| 6 hr 10 min   | 698           | 393       |
| 7 hr 10 min   | 798           | 412       |
| 8 hr 30 min   | 877           | 445       |
| 9 hr 20 min   | 927           | 480       |
| 9 hr 40 min   | 990           | 492       |
This covers up to v0-1

## References

Flanders Marine Institute (2024). Union of the ESRI Country shapefile and the Exclusive Economic Zones (version 4). Available online at https://www.marineregions.org/. https://doi.org/10.14284/698

Flukes, E., (2024). Multi-resolution bathymetry composite surface for Australian waters (EEZ).  Institute for Marine and Antarctic Studies (IMAS). Data accessed from https://metadata.imas.utas.edu.au/geonetwork/srv/eng/catalog.search#/metadata/69e9ac91-babe-47ed-8c37-0ef08f29338a on 31 July 2025

Geoscience Australia. (2024). AusBathyTopo (Australia) 250m 2024 - A national-scale depth model (20240011C). https://doi.org/10.26186/150050

Lawrey, E. P., Stewart M. (2016) Complete Great Barrier Reef (GBR) Reef and Island Feature boundaries including Torres Strait (NESP TWQ 3.13, AIMS, TSRA, GBRMPA) [Dataset]. eAtlas. https://doi.org/10.26274/vhj5-gr60

Lawrey, E., & Bycroft, R., (2025a). Coral Sea Features - Dataset collection - Coral reefs, Cays, Oceanic reef atoll platforms, and Depth contours (AIMS) (Version 1-1) [Data set]. eAtlas. https://doi.org/10.26274/PGJP-8462

Lawrey, E., Bycroft, R., (2025b). North and West Australian Tropical Reef Features - Boundaries of coral reefs, rocky reefs and sand banks (NESP-MaC 3.17, AIMS, Aerial Architecture). [Data set]. eAtlas. https://doi.org/10.26274/xj4v-2739

## Errata v0-1
These are issues that were identified during the use of the dataset that should be resolve prior to the next version
1. EdgeAcc_m of most of the Torres Strait features is excessively high. The EdgeAcc_m of many of the small reefs is 150 m for small reefs. This is probably 3 - 5 x too large.






