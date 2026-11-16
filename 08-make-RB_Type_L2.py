"""Create national singlepart L2 polygons with aggregated reef attributes.

Adapted from NW-Aus-Features 13-make-RB_Type_L2.py. Read the output of stage
06, clean and dissolve by RB_Type_L2, and retain the NW attribute priorities.
The output uses EPSG:4283; areas are calculated in EPSG:3577.
DEM percentiles are recalculated over dissolved polygons using the stage 05
processing. Aggregated DepthCat and DepthCatSr remain independent of the DEM.

National identifiers do not follow the NW suffix scheme. Each polygon retains
source identifiers, datasets and primary sovereigns as semicolon-separated
attributes. NW identifier suffixes use lossless grouped range notation.
L2FID is local to this output, not a persistent reef identifier.

These are dissolved L2 polygons, not countable reefs. A05 subsequently applies
the 100 m separation and minimum effective-width rules.
"""

import configparser
from pathlib import Path
import re

import geopandas as gpd
import pandas as pd

from reef_utils import (
    DEM_FIELDS,
    LPTLookup,
    calculate_depth_statistics,
    dissolve_to_l2_components,
    prepare_depth_rasters,
)


ROOT = Path(__file__).resolve().parent
config = configparser.ConfigParser()
config.read(ROOT / "config.ini")
VERSION = config.get("general", "version")
DATA_DIR = ROOT / "data" / VERSION
DOWNLOAD_PATH = ROOT / config.get("general", "in_3p_path")
MULTIRES_VRT = ROOT / "working" / VERSION / "05" / "MultiRes-Bathy-EEZ_2024.vrt"
LPT_TIF = (DOWNLOAD_PATH / "EOT20-tides" /
           "AU_AIMS_EOT20-tide-stats_LPT_2021-01-2025-12.tif")
INPUT_SHP = (DATA_DIR / "out" / "full-classes" /
             f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{VERSION}.shp")
OUTPUT_SHP = (DATA_DIR / "out" / "simp-classes" /
              f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_L2_{VERSION}.shp")
MULTI_ATTACHMENT_SHP = ROOT / "working" / VERSION / "08" / "multi-attachment-values.shp"
ATTACHMENTS = ["Land", "Fringing", "Oceanic", "Isolated"]
DEPTH_ORDER = ["Land", "Surface", "Intertidal", "Very Shallow", "Shallow", "Deep"]
CONFIDENCE_ORDER = ["Very Low", "Low", "Medium", "High"]
ENUMS = {"Attachment": ATTACHMENTS, "DepthCat": DEPTH_ORDER}
CONFIDENCE_FIELDS = ("FeatConf", "TypeConf")
IDENTIFIER_FIELDS = ("ReefFID", "ReefID", "PrevReefID")
SOURCE_LIST_FIELDS = (*IDENTIFIER_FIELDS, "Dataset", "Sovereign1")
NW_ID_BASE = r"R-[0-9]{4}-[0-9]{3,}"
CONFIDENCE_QA_CSV = ROOT / "working" / VERSION / "08" / "confidence-issues.csv"
OUTPUT_COLUMNS = ["L2FID", *SOURCE_LIST_FIELDS, "RB_Type_L2", "RB_L3_Agg", "Attachment", "DepthCat",
                  "DepthCatSr", *DEM_FIELDS, "FeatConf", "TypeConf", "EdgeSrc", "EdgeAcc_m",
                  "Area_km2", "geometry"]


def unique_nonempty(values):
    return sorted({str(value).strip() for value in values
                   if pd.notna(value) and str(value).strip()})


def join_semicolon(values):
    return ";".join(sorted({item.strip() for value in unique_nonempty(values)
                            for item in value.split(";") if item.strip()}))


def encode_identifier_list(values):
    """Losslessly group NW suffixes, retaining literals when grouping is longer."""
    identifiers = unique_nonempty(join_semicolon(values).split(";"))
    groups, literals = {}, []
    for identifier in identifiers:
        if "{" in identifier or "}" in identifier:
            raise ValueError(f"Source identifier contains reserved braces: {identifier!r}")
        match = re.fullmatch(rf"({NW_ID_BASE})([a-z]+)", identifier)
        if match:
            base, suffix = match.groups()
            groups.setdefault(base, []).append(suffix)
        else:
            literals.append(identifier)
    for base, suffixes in groups.items():
        suffixes.sort(key=lambda suffix: (len(suffix), suffix))
        start = end = suffixes[0]
        runs = []
        for suffix in suffixes[1:]:
            if suffix[:-1] == end[:-1] and ord(suffix[-1]) == ord(end[-1]) + 1:
                end = suffix
            else:
                runs.append(start if start == end else f"{start}-{end}")
                start = end = suffix
        runs.append(start if start == end else f"{start}-{end}")
        encoded = base + "{" + ",".join(runs) + "}"
        originals = [base + suffix for suffix in suffixes]
        if len(encoded.encode("utf-8")) < len(";".join(originals).encode("utf-8")):
            literals.append(encoded)
        else:
            literals.extend(originals)
    return ";".join(sorted(literals))


def expand_identifier_list(value):
    """Expand grouped NW identifiers to a sorted unique list; reject invalid notation."""
    identifiers = set()
    for token in unique_nonempty(value.split(";")):
        if "{" not in token and "}" not in token:
            identifiers.add(token)
            continue
        match = re.fullmatch(rf"({NW_ID_BASE})\{{([^{{}}]+)\}}", token)
        if not match:
            raise ValueError(f"Malformed identifier group: {token!r}")
        base, contents = match.groups()
        for item in contents.split(","):
            suffix = re.fullmatch(r"([a-z]+)(?:-([a-z]+))?", item)
            if not suffix:
                raise ValueError(f"Malformed identifier suffix: {item!r}")
            start, end = suffix.groups()
            if end is None:
                identifiers.add(base + start)
            else:
                # Ranges vary only the final letter, so az-ba is not a valid range.
                if start[:-1] != end[:-1] or start[-1] >= end[-1]:
                    raise ValueError(f"Invalid identifier suffix range: {item!r}")
                identifiers.update(base + start[:-1] + chr(letter)
                                   for letter in range(ord(start[-1]), ord(end[-1]) + 1))
    return sorted(identifiers)


def choose_priority(values, priority):
    present = set(unique_nonempty(values))
    return next(value for value in priority if value in present)


def prepare_features(gdf):
    """Validate national attributes and prepare singlepart source geometries."""
    required = {"RB_Type_L2", "RB_Type_L3", "DepthCatSr", "EdgeSrc", "EdgeAcc_m",
                "geometry"} | set(SOURCE_LIST_FIELDS) | set(ENUMS) | set(CONFIDENCE_FIELDS)
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
    """Aggregate attributes, including source lists, for each L2 component."""
    components = dissolve_to_l2_components(gdf)
    print(f"Aggregating attributes for {len(components)} L2 components...", flush=True)
    rows = []
    for l2fid, component in enumerate(components, start=1):
        group = gdf.loc[component["member_indices"]].drop_duplicates("SourceRow")
        rows.append({
            "L2FID": l2fid, "RB_Type_L2": component["l2_class"],
            **{field: encode_identifier_list(group[field]) for field in IDENTIFIER_FIELDS},
            "Dataset": join_semicolon(group["Dataset"]),
            "Sovereign1": join_semicolon(group["Sovereign1"]),
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
        if l2fid % 1000 == 0 or l2fid == len(components):
            print(f"  Aggregating attributes: {l2fid}/{len(components)}", flush=True)
    print("Calculating L2 polygon areas...", flush=True)
    singleparts = gpd.GeoDataFrame(rows, crs=gdf.crs)
    singleparts["Area_km2"] = (singleparts.to_crs(3577).geometry.area / 1e6).round(4)
    return singleparts


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
    issues = []
    for field in gdf.select_dtypes(include=["object", "string"]).columns:
        lengths = gdf[field].fillna("").astype(str).str.encode("utf-8").str.len()
        overflow = lengths > 254
        if overflow.any():
            details = []
            for index, row in gdf.loc[overflow].head(10).iterrows():
                identifier = (f"L2FID={row['L2FID']}" if "L2FID" in gdf.columns
                              else f"row={index}")
                l2_class = (f", RB_Type_L2={row['RB_Type_L2']!r}"
                            if "RB_Type_L2" in gdf.columns else "")
                count = (len(expand_identifier_list(str(row[field])))
                         if field in IDENTIFIER_FIELDS
                         else len(unique_nonempty(str(row[field]).split(";"))))
                details.append(f"{identifier}{l2_class}, {lengths.loc[index]} bytes, "
                               f"{count} unique values")
            issues.append(f"{field} exceeds the shapefile text limit of 254 bytes "
                          f"in {int(overflow.sum())} features; first 10: "
                          + "; ".join(details))
    if issues:
        raise ValueError("\n".join(issues))


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
    singleparts = dissolve_by_l2(features)
    validate_text_lengths(singleparts)
    rasters = prepare_depth_rasters(DOWNLOAD_PATH, MULTIRES_VRT)
    lpt_lookup = LPTLookup(LPT_TIF)
    singleparts[list(DEM_FIELDS)] = calculate_depth_statistics(
        singleparts, rasters, lpt_lookup)
    multi = singleparts[singleparts["AttSet"].str.contains(";")]
    validate_text_lengths(singleparts)
    OUTPUT_SHP.parent.mkdir(parents=True, exist_ok=True)
    singleparts[OUTPUT_COLUMNS].to_file(OUTPUT_SHP, encoding="UTF-8")
    # Always replace the QA layer, including an empty layer on a clean rerun.
    MULTI_ATTACHMENT_SHP.parent.mkdir(parents=True, exist_ok=True)
    multi[OUTPUT_COLUMNS[:-1] + ["AttSet", "geometry"]].to_file(
        MULTI_ATTACHMENT_SHP, encoding="UTF-8")
    print(f"Wrote {len(singleparts)} L2 polygons: {OUTPUT_SHP}", flush=True)
    print(f"Wrote {len(multi)} mixed-attachment QA polygons: {MULTI_ATTACHMENT_SHP}",
          flush=True)


if __name__ == "__main__":
    main()
