"""Create national singlepart L2 polygons with aggregated reef attributes.

Adapted from NW-Aus-Features 13-make-RB_Type_L2.py. Read the output of stage
06, clean and dissolve by RB_Type_L2, and retain the NW attribute priorities.
The output uses EPSG:4283; areas are calculated in EPSG:3577.

National identifiers do not follow the NW suffix scheme. Each polygon receives
an L2FID, linked to unchanged source ReefID and ReefFID values in a membership
CSV. L2FID is local to this output, not a persistent reef identifier.

These are dissolved L2 polygons, not countable reefs. A05 subsequently applies
the 100 m separation and minimum effective-width rules.
"""

import configparser
from pathlib import Path

import geopandas as gpd
import pandas as pd

from reef_utils import dissolve_to_l2_components


ROOT = Path(__file__).resolve().parent
config = configparser.ConfigParser()
config.read(ROOT / "config.ini")
VERSION = config.get("general", "version")
DATA_DIR = ROOT / "data" / VERSION
INPUT_SHP = (DATA_DIR / "out" / "full-classes" /
             f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{VERSION}.shp")
OUTPUT_SHP = (DATA_DIR / "out" / "simp-classes" /
              f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_L2_{VERSION}.shp")
MEMBERS_CSV = OUTPUT_SHP.with_name(f"{OUTPUT_SHP.stem}_members.csv")
MULTI_ATTACHMENT_SHP = ROOT / "working" / VERSION / "08" / "multi-attachment-values.shp"
ATTACHMENTS = ["Land", "Fringing", "Oceanic", "Isolated"]
DEPTH_ORDER = ["Land", "Surface", "Intertidal", "Very Shallow", "Shallow", "Deep"]
CONFIDENCE_ORDER = ["Very Low", "Low", "Medium", "High"]
ENUMS = {"Attachment": ATTACHMENTS, "DepthCat": DEPTH_ORDER}
CONFIDENCE_FIELDS = ("FeatConf", "TypeConf")
CONFIDENCE_QA_CSV = ROOT / "working" / VERSION / "08" / "confidence-issues.csv"
OUTPUT_COLUMNS = ["L2FID", "RB_Type_L2", "RB_L3_Agg", "Attachment", "DepthCat",
                  "DepthCatSr", "FeatConf", "TypeConf", "EdgeSrc", "EdgeAcc_m",
                  "Area_km2", "geometry"]


def unique_nonempty(values):
    return sorted({str(value).strip() for value in values
                   if pd.notna(value) and str(value).strip()})


def join_semicolon(values):
    return ";".join(unique_nonempty(values))


def choose_priority(values, priority):
    present = set(unique_nonempty(values))
    return next(value for value in priority if value in present)


def prepare_features(gdf):
    """Validate national attributes and prepare singlepart source geometries."""
    required = {"RB_Type_L2", "RB_Type_L3", "DepthCatSr", "EdgeSrc", "EdgeAcc_m",
                "ReefID", "ReefFID", "geometry"} | set(ENUMS) | set(CONFIDENCE_FIELDS)
    missing = required - set(gdf.columns)
    if missing:
        raise ValueError(f"Missing input fields: {sorted(missing)}")
    if gdf.empty or gdf.crs is None:
        raise ValueError("Input must contain reef features with a defined CRS")
    for field in ("RB_Type_L2", "RB_Type_L3"):
        if gdf[field].isna().any() or gdf[field].astype(str).str.strip().eq("").any():
            raise ValueError(f"Null or empty {field}")
    for field, allowed in ENUMS.items():
        invalid = ~gdf[field].isin(allowed)
        if invalid.any():
            raise ValueError(f"Unexpected {field}: {gdf.loc[invalid, field].unique().tolist()}")
    accuracy = pd.to_numeric(gdf["EdgeAcc_m"], errors="raise")
    if (accuracy.isna().any() or not accuracy.between(0, 2**31 - 1).all()
            or (accuracy % 1 != 0).any()):
        raise ValueError("EdgeAcc_m must contain non-negative 32-bit integers")
    if (gdf.geometry.isna().any() or gdf.geometry.is_empty.any()
            or not gdf.geom_type.isin(["Polygon", "MultiPolygon"]).all()):
        raise ValueError("Input must contain non-empty polygon geometries")
    gdf = gdf.to_crs(4283).reset_index(drop=True)
    gdf["SourceRow"] = gdf.index + 1
    gdf["EdgeAcc_m"] = accuracy.to_numpy(dtype=int)
    gdf["geometry"] = gdf.geometry.buffer(0)
    if gdf.geometry.is_empty.any() or not gdf.geometry.is_valid.all():
        raise ValueError("Geometry cleaning produced empty or invalid polygons")
    return gdf.explode(index_parts=False).reset_index(drop=True)


def dissolve_by_l2(gdf):
    """Aggregate attributes and retain every source-to-component membership."""
    components = dissolve_to_l2_components(gdf)
    rows, members = [], []
    for l2fid, component in enumerate(components, start=1):
        group = gdf.loc[component["member_indices"]].drop_duplicates("SourceRow")
        rows.append({
            "L2FID": l2fid, "RB_Type_L2": component["l2_class"],
            "RB_L3_Agg": join_semicolon(group["RB_Type_L3"]),
            "Attachment": choose_priority(group["Attachment"], ATTACHMENTS),
            "AttSet": join_semicolon(group["Attachment"]),
            "DepthCat": choose_priority(group["DepthCat"], DEPTH_ORDER),
            "DepthCatSr": join_semicolon(group["DepthCatSr"]),
            "FeatConf": aggregate_confidence(group["FeatConf"]),
            "TypeConf": aggregate_confidence(group["TypeConf"]),
            "EdgeSrc": join_semicolon(group["EdgeSrc"]),
            "EdgeAcc_m": int(group["EdgeAcc_m"].max()),
            "geometry": component["geometry"],
        })
        for source in group.itertuples(index=False):
            members.append({"L2FID": l2fid, "SourceRow": source.SourceRow,
                            "ReefID": source.ReefID, "ReefFID": source.ReefFID,
                            "FeatConf": source.FeatConf, "TypeConf": source.TypeConf})
    singleparts = gpd.GeoDataFrame(rows, crs=gdf.crs)
    singleparts["Area_km2"] = (singleparts.to_crs(3577).geometry.area / 1e6).round(4)
    return singleparts, pd.DataFrame(members)


def aggregate_confidence(values):
    """Unknown or missing confidence prevents a known confidence for the whole reef."""
    if not values.isin(CONFIDENCE_ORDER).all():
        return None
    return choose_priority(values, CONFIDENCE_ORDER)


def confidence_issues(features):
    """Flag non-standard values for source cleanup without ranking or rewriting them."""
    rows = []
    for source in features.drop_duplicates("SourceRow").itertuples(index=False):
        for field in CONFIDENCE_FIELDS:
            value = getattr(source, field)
            if pd.notna(value) and str(value).strip() and value not in CONFIDENCE_ORDER:
                rows.append({"SourceRow": source.SourceRow, "ReefID": source.ReefID,
                             "ReefFID": source.ReefFID, "Field": field, "Value": value})
    return pd.DataFrame(rows, columns=["SourceRow", "ReefID", "ReefFID", "Field", "Value"])


def validate_text_lengths(gdf):
    """Reject text overflow rather than silently truncating aggregated attributes."""
    for field in gdf.select_dtypes(include=["object", "string"]).columns:
        lengths = gdf[field].fillna("").astype(str).str.encode("utf-8").str.len()
        if (lengths > 254).any():
            raise ValueError(f"{field} exceeds the shapefile text limit of 254 bytes")


def main():
    print(f"Reading national features: {INPUT_SHP}", flush=True)
    features = prepare_features(gpd.read_file(INPUT_SHP))
    issues = confidence_issues(features)
    CONFIDENCE_QA_CSV.parent.mkdir(parents=True, exist_ok=True)
    issues.to_csv(CONFIDENCE_QA_CSV, index=False)
    if not issues.empty:
        print(f"WARNING: {len(issues)} non-standard confidence values require source "
              f"cleanup; see {CONFIDENCE_QA_CSV}. Affected L2 confidence is blank.",
              flush=True)
    print(f"Dissolving {len(features)} source parts by RB_Type_L2", flush=True)
    singleparts, members = dissolve_by_l2(features)
    multi = singleparts[singleparts["AttSet"].str.contains(";")]
    validate_text_lengths(singleparts)
    OUTPUT_SHP.parent.mkdir(parents=True, exist_ok=True)
    singleparts[OUTPUT_COLUMNS].to_file(OUTPUT_SHP, encoding="UTF-8")
    members.to_csv(MEMBERS_CSV, index=False)
    # Always replace the QA layer, including an empty layer on a clean rerun.
    MULTI_ATTACHMENT_SHP.parent.mkdir(parents=True, exist_ok=True)
    multi[OUTPUT_COLUMNS[:-1] + ["AttSet", "geometry"]].to_file(
        MULTI_ATTACHMENT_SHP, encoding="UTF-8")
    print(f"Wrote {len(singleparts)} L2 polygons: {OUTPUT_SHP}", flush=True)
    print(f"Wrote source memberships: {MEMBERS_CSV}", flush=True)
    print(f"Wrote {len(multi)} mixed-attachment QA polygons: {MULTI_ATTACHMENT_SHP}",
          flush=True)


if __name__ == "__main__":
    main()
