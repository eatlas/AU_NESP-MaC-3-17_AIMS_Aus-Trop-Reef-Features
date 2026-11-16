"""
Refresh the GBR portion of the integrated Torres Strait and GBR Features layer.

The Torres Strait records are retained from the 2016 integrated layer. The
GBR Features records are replaced with the latest GBRMPA source, excluding the
99-* records that overlap the remapped Torres Strait coverage. Both 99-000
mainland-associated records are retained.

Output: working/{version}/01/TS-GBR-Features-latest.shp
"""

import configparser
import os
import sys

import geopandas as gpd
import pandas as pd
from shapely import make_valid


config = configparser.ConfigParser()
config.read("config.ini")
in_3p_path = config.get("general", "in_3p_path")
version = config.get("general", "version")

integrated_path = os.path.join(
    in_3p_path,
    "TS-GBR-Feat",
    "TS_AIMS_NESP_Torres_Strait_Features_V1b_with_GBR_Features.shp",
)
latest_gbr_path = os.path.join(
    "data",
    version,
    "in-3p-mirror",
    "GBRMPA-GBR-Features",
    "Great_Barrier_Reef_Features.shp",
)
output_dir = os.path.join("working", version, "01")
output_path = os.path.join(output_dir, "TS-GBR-Features-latest.shp")


CLASSIFICATION = {
    "Reef": ("Reef", None, None),
    "Rock": ("Reef", None, None),
    "Island": ("Island", None, None),
    "Cay": ("Island", "Reef Island", None),
    "Sand": ("Bank", "Sand Bank", "Sand Bank"),
    "Mainland": ("Mainland", None, None),
}

# Retain source attributes useful for identification and subsequent processing.
# Deliberately omit fields generated while producing the 2016 composite.
OUTPUT_COLUMNS = [
    "DATASET", "LOC_NAME_S", "GBR_NAME", "CHART_NAME", "TRAD_NAME",
    "UN_FEATURE", "LABEL_ID", "SORT_GBR_I", "FEAT_NAME", "LEVEL_1",
    "LEVEL_2", "LEVEL_3", "CLASS_CONF", "CLASS_SRC", "POLY_ORIG",
    "IMG_SRC", "SUB_NO", "CODE", "FEATURE_C", "QLD_NAME", "X_LABEL",
    "GBR_ID", "LOC_NAME_L", "X_COORD", "Y_COORD", "GlobalID", "geometry",
]


def align_columns(gdf):
    """Return a copy with the intermediate output schema."""
    aligned = gdf.copy()
    for column in OUTPUT_COLUMNS:
        if column not in aligned.columns:
            aligned[column] = None
    return aligned[OUTPUT_COLUMNS]


def main():
    print(f"Reading integrated Torres Strait and GBR Features: {integrated_path}")
    integrated = gpd.read_file(integrated_path)
    print(f"  {len(integrated)} features loaded")

    print(f"Reading latest GBRMPA GBR Features: {latest_gbr_path}")
    latest_gbr = gpd.read_file(latest_gbr_path)
    print(f"  {len(latest_gbr)} features loaded ({latest_gbr.crs})")

    torres_strait = integrated[integrated["DATASET"] == "TS Features"].copy()
    removed_old_gbr = len(integrated) - len(torres_strait)
    print(f"Retained {len(torres_strait)} TS Features")
    print(f"Removed {removed_old_gbr} stale GBR Features")

    label_ids = latest_gbr["LABEL_ID"].astype("string")
    torres_strait_mask = label_ids.str.startswith("99-", na=False) & (label_ids != "99-000")
    excluded_latest = latest_gbr[torres_strait_mask].copy()
    latest_gbr = latest_gbr[~torres_strait_mask].copy()
    print(f"Excluded {len(excluded_latest)} latest GBRMPA 99-* features")
    print(f"Retained {(latest_gbr['LABEL_ID'] == '99-000').sum()} features with LABEL_ID 99-000")

    invalid_mask = ~latest_gbr.geometry.is_valid
    if invalid_mask.any():
        print(f"Repairing {invalid_mask.sum()} invalid latest GBRMPA geometries")
        latest_gbr.loc[invalid_mask, "geometry"] = latest_gbr.loc[
            invalid_mask, "geometry"
        ].apply(make_valid)
    if (~latest_gbr.geometry.is_valid).any() or latest_gbr.geometry.is_empty.any():
        print("ERROR: Latest GBRMPA geometries remain invalid or empty after repair")
        sys.exit(1)

    unexpected_types = sorted(set(latest_gbr["FEAT_NAME"].dropna()) - set(CLASSIFICATION))
    if unexpected_types:
        print(f"ERROR: Unexpected FEAT_NAME values in latest GBR Features: {unexpected_types}")
        sys.exit(1)

    latest_gbr["DATASET"] = "GBR Features"
    classifications = latest_gbr["FEAT_NAME"].map(CLASSIFICATION)
    latest_gbr["LEVEL_1"] = classifications.str[0]
    latest_gbr["LEVEL_2"] = classifications.str[1]
    latest_gbr["LEVEL_3"] = classifications.str[2]
    latest_gbr["CLASS_CONF"] = None
    latest_gbr["CLASS_SRC"] = None
    latest_gbr["IMG_SRC"] = None

    if integrated.crs is None:
        integrated = integrated.set_crs(epsg=4283)
        torres_strait = torres_strait.set_crs(epsg=4283)
    latest_gbr = latest_gbr.to_crs(integrated.crs)

    torres_strait = align_columns(torres_strait)
    latest_gbr = align_columns(latest_gbr)
    refreshed = gpd.GeoDataFrame(
        pd.concat([torres_strait, latest_gbr], ignore_index=True),
        geometry="geometry",
        crs=integrated.crs,
    )

    os.makedirs(output_dir, exist_ok=True)
    print(f"Saving {len(refreshed)} refreshed features to {output_path}")
    refreshed.to_file(output_path)
    written = gpd.read_file(output_path)
    if (~written.geometry.is_valid).any() or written.geometry.is_empty.any():
        print("ERROR: Refreshed output contains invalid or empty geometries")
        sys.exit(1)
    print("Done.")


if __name__ == "__main__":
    main()