"""Sum GBR Features source Reef, Rock and Sand areas within the GBR Analysis-region,
and count GBR Features reefs under A05's countable-reef rules.

Run from the repository root in AusTropReef. Configuration comes from config.ini.
Writes data/{version}/out/stats/A08-gbr-features-reef-area_{version}.md. Invalid
source geometries are repaired in memory with make_valid; source files are not
changed. See A08-gbr-features-reef-area-spec.md.
"""

import configparser
from datetime import datetime
import math
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import make_valid
from shapely.validation import explain_validity
from reef_utils import cluster_countable


SCRIPT_NAME = Path(__file__).name
AREA_CRS = 3577
PORTAL_RECORDS = 5362
HOPLEY_GIS_KM2 = 24081
SLIVER_BUFFER_M = 5.0
MIN_WIDTH_M = 100.0
COUNT_TYPES = (("Reef", "Coral Reef"), ("Rock", "Rocky Reef"))
COUNT_STAGES = ("Source records", "Size only", "Separation only", "Countable reefs (A05 rules)")
REFERENCE_COUNTS = (
    ("Hopley et al. (2007) Gazetteer", "2,904", "20,055", "", ""),
    ("Hopley et al. (2007) GIS", "3,703", "24,081", "", ""),
)
SELECTIONS = (
    ("Reef", ("Reef",)),
    ("Reef + Rock", ("Reef", "Rock")),
    ("Reef + Rock + Sand", ("Reef", "Rock", "Sand")),
)
CLASSES = SELECTIONS[-1][1]
POLYGONAL = ("Polygon", "MultiPolygon")
PROVENANCE = (
    ("Dataset / provider", "Great Barrier Reef Features / Great Barrier Reef Marine Park Authority (GBRMPA)"),
    ("Source", "https://reef-geohub-ext-geohubgbrmpa.hub.arcgis.com/datasets/"
               "816f4d747cd94d84acfd924b27f581d8_64/about"),
    ("Downloaded", "3 September 2026"),
    ("Data Updated", "18 June 2025, 07:45:47 GMT+10"),
    ("Info Updated", "10 November 2025, 13:20:49 GMT+10"),
    ("Published Date", "23 May 2025, 02:53:31 GMT+10"),
    ("Portal record count", f"{PORTAL_RECORDS:,}"),
    ("Licence", "CC BY 4.0"),
)


def input_paths(config):
    version = config.get("general", "version")
    third_party = Path(config.get("general", "in_3p_path"))
    return version, {
        "GBR Features": Path("data") / version / "in-3p-mirror" / "GBRMPA-GBR-Features"
        / "Great_Barrier_Reef_Features.shp",
        "Analysis regions": third_party / "nesp-3-17-analysis-regions" / "analysis-regions.shp",
    }


def provenance_path(path):
    try:
        relative = Path(os.path.abspath(path)).relative_to(Path.cwd())
    except ValueError:
        return f"`{path.name}` (external input; location configured in local config.ini)"
    return f"`{relative.as_posix()}`"


def check_polygons(geometry, name):
    bad = geometry.isna() | geometry.is_empty | ~geometry.geom_type.isin(POLYGONAL)
    if bad.any():
        raise ValueError(f"{name}: null, empty or non-polygon geometry at rows "
                         f"{geometry.index[bad].tolist()}")


def region_geometries(regions):
    if regions.crs is None:
        raise ValueError("Analysis regions: missing CRS")
    if "subregion" not in regions.columns:
        raise ValueError("Analysis regions: missing subregion field")
    if not regions.subregion.eq("GBR").any():
        raise ValueError("Analysis regions: no GBR subregion")
    projected = regions.to_crs(AREA_CRS)
    check_polygons(projected.geometry, "Analysis regions")
    if not projected.geometry.is_valid.all():
        raise ValueError("Analysis regions: invalid geometry after projection at rows "
                         f"{projected.index[~projected.geometry.is_valid].tolist()}")
    gbr_mask = projected.subregion.eq("GBR")
    ts_mask = projected.subregion.eq("Torres Strait")
    gbr = projected.geometry[gbr_mask].union_all()
    if gbr.is_empty or not gbr.is_valid or gbr.area <= 0:
        raise ValueError("Analysis regions: dissolved GBR region is empty or invalid")
    return {
        "GBR": gbr,
        "Torres Strait": projected.geometry[ts_mask].union_all(),
        "Other regions": projected.geometry[~gbr_mask & ~ts_mask].union_all(),
        "All regions": projected.geometry.union_all(),
        "By name": projected.dissolve(by="subregion").geometry.sort_index(),
    }


def repair(series, name):
    """Return polygonal make_valid repairs, stopping rather than discarding parts."""
    repaired = series.copy()
    invalid = ~series.is_valid
    repaired[invalid] = [make_valid(geometry) for geometry in series[invalid]]
    bad = repaired.is_empty | ~repaired.geom_type.isin(POLYGONAL)
    if bad.any():
        raise ValueError(f"{name}: make_valid produced empty or non-polygonal geometry at rows "
                         f"{repaired.index[bad].tolist()}")
    return repaired, invalid


def prepare_records(source):
    """Return selected source records projected to AREA_CRS with repair diagnostics."""
    if source.crs is None:
        raise ValueError("GBR Features: missing CRS")
    if "FEAT_NAME" not in source.columns:
        raise ValueError("GBR Features: missing FEAT_NAME field")
    selected = source[source.FEAT_NAME.isin(CLASSES)].copy()
    if not selected.FEAT_NAME.eq("Reef").any():
        raise ValueError("GBR Features: no Reef records")
    check_polygons(selected.geometry, "GBR Features selected records")
    selected["reason"] = [
        explain_validity(geometry).split("[")[0].strip() if not geometry.is_valid else ""
        for geometry in selected.geometry
    ]
    selected["raw_km2"] = selected.geometry.to_crs(AREA_CRS).area / 1e6
    repaired, invalid = repair(selected.geometry, "GBR Features source CRS")
    selected["repaired"] = invalid
    projected = gpd.GeoSeries(repaired, crs=source.crs).to_crs(AREA_CRS)
    projected, projection_invalid = repair(projected, "GBR Features after projection")
    for index in projected.index[projection_invalid]:
        print(f"WARNING: projection repair for source row {index}", flush=True)
    records = gpd.GeoDataFrame(selected.drop(columns="geometry"), geometry=projected, crs=AREA_CRS)
    records["projection_repaired"] = projection_invalid
    records["area_km2"] = records.area / 1e6
    bad = ~records.area_km2.map(math.isfinite) | (records.area_km2 <= 0)
    if bad.any():
        raise ValueError("GBR Features: non-finite or non-positive area at rows "
                         f"{records.index[bad].tolist()}")
    return records


def assigned_regions(geometries, by_name):
    """Name the region holding each unit's largest non-sliver piece, as in A05."""
    names = []
    for geometry in geometries:
        candidates = []
        for position in by_name.sindex.query(geometry, predicate="intersects"):
            piece = geometry.intersection(by_name.iloc[position])
            if piece.is_empty or piece.area <= 0:
                continue
            sliver = piece.buffer(-SLIVER_BUFFER_M).is_empty
            candidates.append((sliver, -piece.area, by_name.index[position]))
        names.append(min(candidates)[2] if candidates else None)
    return pd.Series(names, index=geometries.index)


def count_stages(records, areas):
    """Return GBR counts and areas by reef type at each countable-reef stage."""
    rows = []
    for feat_name, reef_type in COUNT_TYPES:
        chosen = records.loc[records.FEAT_NAME.eq(feat_name), ["geometry"]].copy()
        if chosen.empty:
            units = {stage: gpd.GeoSeries([], crs=AREA_CRS) for stage in COUNT_STAGES}
        else:
            chosen["RB_Type_L2"] = reef_type
            groups, stats = cluster_countable(chosen, min_width_m=MIN_WIDTH_M, drop_small=False)
            if stats["n_unassigned"]:
                raise ValueError(f"{feat_name}: {stats['n_unassigned']} records could not be clustered")
            width = 2 * (chosen.area / math.pi) ** 0.5
            units = {
                COUNT_STAGES[0]: chosen.geometry,
                COUNT_STAGES[1]: chosen.geometry[width >= MIN_WIDTH_M],
                COUNT_STAGES[2]: groups.geometry,
                COUNT_STAGES[3]: groups.geometry[groups.EffWidth_m >= MIN_WIDTH_M],
            }
        for stage in COUNT_STAGES:
            geometries = units[stage].reset_index(drop=True)
            regions = assigned_regions(geometries, areas["By name"])
            rows.append({"Type": reef_type, "Stage": stage,
                         "GBR count": int(regions.eq("GBR").sum()),
                         "GBR area (km2)": geometries.intersection(areas["GBR"]).area.sum() / 1e6})
    return pd.DataFrame(rows)


def analyse(source, regions):
    """Return results, repair diagnostics, excluded Reef area and countable-reef tables."""
    areas = region_geometries(regions)
    records = prepare_records(source)
    records["gbr_km2"] = records.geometry.intersection(areas["GBR"]).area / 1e6
    if not records.gbr_km2.map(math.isfinite).all():
        raise ValueError("GBR Features: non-finite clipped area")

    results, repairs = [], []
    for label, classes in SELECTIONS:
        chosen = records[records.FEAT_NAME.isin(classes)]
        area = chosen.gbr_km2.sum()
        results.append({
            "Selection": label,
            "Source records": int((chosen.gbr_km2 > 0).sum()),
            "Area (km2)": area,
            "Difference from 24,081 km2": area - HOPLEY_GIS_KM2,
            "Difference (%)": 100 * (area - HOPLEY_GIS_KM2) / HOPLEY_GIS_KM2,
        })
        fixed = chosen[chosen.repaired]
        for reason, group in fixed.groupby("reason", sort=True):
            repairs.append({"Selection": label, "Reason": reason, "Records": len(group),
                            "Before repair (km2)": group.raw_km2.sum(),
                            "After repair (km2)": group.area_km2.sum()})
        repairs.append({"Selection": label, "Reason": "Total", "Records": len(fixed),
                        "Before repair (km2)": fixed.raw_km2.sum(),
                        "After repair (km2)": fixed.area_km2.sum()})
        projection = int(chosen.projection_repaired.sum())
        if projection:
            repairs.append({"Selection": label, "Reason": "Projection repair", "Records": projection,
                            "Before repair (km2)": math.nan, "After repair (km2)": math.nan})

    reef = records[records.FEAT_NAME.eq("Reef")].geometry
    excluded = [
        {"Location": "Torres Strait region",
         "Area (km2)": reef.intersection(areas["Torres Strait"]).area.sum() / 1e6},
        {"Location": "Other Analysis-regions",
         "Area (km2)": reef.intersection(areas["Other regions"]).area.sum() / 1e6},
        {"Location": "Outside all Analysis-regions",
         "Area (km2)": reef.difference(areas["All regions"]).area.sum() / 1e6},
    ]
    return (pd.DataFrame(results), pd.DataFrame(repairs), pd.DataFrame(excluded),
            count_stages(records, areas))


def markdown_table(frame, formats):
    lines = ["| " + " | ".join(frame.columns) + " |",
             "| " + " | ".join("---:" if column in formats else "---" for column in frame.columns) + " |"]
    for row in frame.itertuples(index=False):
        values = []
        for column, value in zip(frame.columns, row):
            if column in formats:
                values.append("" if pd.isna(value) else format(value, formats[column]))
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def stage_table(counts):
    """Pivot stage counts so coral and rocky figures sit side by side."""
    rows = []
    for stage in COUNT_STAGES:
        row = {"Stage": stage}
        for reef_type, label in (("Coral Reef", "Coral reef"), ("Rocky Reef", "Rocky reef")):
            match = counts[counts.Stage.eq(stage) & counts.Type.eq(reef_type)].iloc[0]
            row[f"{label} count"] = match["GBR count"]
            row[f"{label} area (km2)"] = match["GBR area (km2)"]
        rows.append(row)
    frame = pd.DataFrame(rows)
    return markdown_table(frame, {column: (",d" if column.endswith("count") else ",.1f")
                                  for column in frame.columns[1:]})


def read_a05_reference(path):
    summary = pd.read_csv(path)
    selected = summary[
        summary.Region_dataset.eq("Analysis-regions v1")
        & summary.Region_name.eq("GBR")
        & summary.Near_region.eq("No")
    ]
    if len(selected) != 1:
        raise ValueError(f"{path}: expected exactly one GBR Analysis-region row")
    row = selected.iloc[0]
    values = []
    for reef_type in ("Coral", "Rocky"):
        count = float(row[f"{reef_type}_reef_count"])
        area = float(row[f"{reef_type}_reef_area_km2"])
        if (not math.isfinite(count) or count < 0 or not count.is_integer()
                or not math.isfinite(area) or area < 0):
            raise ValueError(f"{path}: invalid GBR {reef_type} reef count or area")
        values.extend((f"{int(count):,}", f"{area:,.1f}"))
    return ("A05 national dataset countable reefs (Table B.2)", *values)


def build_report(results, repairs, excluded, counts, version, paths, source, regions,
                 a05_reference):
    provenance = "\n".join(
        ["| Item | Value |", "| --- | --- |"] + [f"| {item} | {value} |" for item, value in PROVENANCE])
    return "\n\n".join([
        f"# GBR Features source reef area: {version}",
        f"Analysis script: `{SCRIPT_NAME}`. National dataset version: {version}. "
        f"Generated: {datetime.now().astimezone().isoformat()}.",
        "## Results",
        f"Table 1. Summed GBR Features source-record areas within the GBR Analysis-region, "
        f"with differences from the Hopley et al. (2007) GIS reef area of {HOPLEY_GIS_KM2:,} km2. "
        f"Differences use unrounded totals. Data: {version}. Analysis script: {SCRIPT_NAME}.",
        markdown_table(results, {"Source records": ",d", "Area (km2)": ",.6f",
                                 "Difference from 24,081 km2": "+,.1f", "Difference (%)": "+.2f"}),
        "## Source dataset provenance",
        "Author-supplied download and portal metadata. No numbered source release has been "
        "supplied. These source dates are separate from the national dataset version and "
        "report generation time.",
        provenance,
        f"GBR Features: {provenance_path(paths['GBR Features'])}. Observed input records: "
        f"{len(source):,}. Source CRS: {source.crs}.",
        f"Analysis regions: {provenance_path(paths['Analysis regions'])}. Records: "
        f"{len(regions):,}. CRS: {regions.crs}.",
        f"Calculation CRS: EPSG:{AREA_CRS} (GDA94 / Australian Albers).",
        "## Calculation rules",
        "Selections use exact FEAT_NAME values and are cumulative: Reef; Reef and Rock; "
        "Reef, Rock and Sand. An absent class contributes zero. Invalid selected geometries "
        "are repaired with shapely make_valid in the source CRS, reprojected to EPSG:3577 "
        "and repaired again if projection makes them invalid. Each record is clipped to the "
        "dissolved Analysis-region polygons with subregion GBR. Areas are calculated from "
        "the clipped geometry and summed without intermediate rounding.",
        "Source records are counted when their clipped area is positive. A MultiPolygon is one "
        "record, and a record crossing the region boundary counts once and contributes only "
        "its area inside the region. Records are not dissolved, exploded or buffered, overlaps "
        "are not subtracted, stored area attributes are not used, and A05 size and counting "
        "rules are not applied. These are summed record areas, not unique spatial footprints.",
        "LABEL_ID is not used for regional selection. The 99-* labels include Torres Strait "
        "features, but the Analysis-region clip defines the GBR scope.",
        "## Geometry repair",
        "Many source Reef records store rings in reverse: the reef outline as an interior "
        "ring and the enclosed island as the exterior ring, or island outlines as extra "
        "exterior rings nested inside the reef outline. make_valid restores the reef outline "
        "and cuts the islands out as holes, so reef area excludes enclosed island and cay "
        "areas. Reading the shapefile with GDAL OGR_ORGANIZE_POLYGONS=DEFAULT gives the same "
        "total. buffer(0) would delete reefs stored with reversed rings.",
        f"Table 2. Repaired records by validity reason. Areas are unclipped EPSG:{AREA_CRS} "
        "totals for the repaired records. Before-repair areas use the raw geometry and can "
        f"be negative. Data: {version}. Analysis script: {SCRIPT_NAME}.",
        markdown_table(repairs, {"Records": ",d", "Before repair (km2)": ",.1f",
                                 "After repair (km2)": ",.1f"}),
        "## Area excluded by the clip",
        "Table 3. Repaired Reef area outside the GBR Analysis-region. Context only; not "
        f"included in Table 1. Data: {version}. Analysis script: {SCRIPT_NAME}.",
        markdown_table(excluded, {"Area (km2)": ",.1f"}),
        "## Countable-reef comparison",
        "A05's countable-reef rules applied to the repaired GBR Features source. Reef is "
        "treated as Coral Reef and Rock as Rocky Reef; Sand is excluded. Records of the same "
        f"type are grouped when their 50 m buffers join (`cluster_countable` in reef_utils.py), "
        f"and units with an effective width (equal-area circle diameter) below {MIN_WIDTH_M:.0f} m "
        "are excluded. The whole source is clustered before regional assignment. Each unit is "
        "counted once, in the Analysis-region holding its largest piece that survives a "
        f"-{SLIVER_BUFFER_M:.0f} m buffer. GBR area is the clipped area of every unit "
        "intersecting the GBR region, including units counted in a neighbouring region. The "
        "source-record count uses this largest-piece rule, so it can differ from Table 1.",
        "Table 4. GBR count and area of GBR Features units at each countable-reef stage. Size "
        "only and Separation only apply one criterion each; Countable reefs apply both, as A05 "
        f"does. Data: {version}. Analysis script: {SCRIPT_NAME}.",
        stage_table(counts),
        "Table 5. Reference GBR counts and areas. Hopley figures are as published and have no "
        "coral or rocky classification; A05 reef figures are Coral Reef, from the national "
        "dataset (Appendix B, Table B.2).",
        "| Source | Reef count | Reef area (km2) | Rocky reef count | "
        "Rocky reef area (km2) |\n| --- | ---: | ---: | ---: | ---: |\n"
        + "\n".join("| " + " | ".join(row) + " |"
                    for row in (*REFERENCE_COUNTS, a05_reference)),
        f"A05 reference figures: {provenance_path(paths['A05 statistics'])}. "
        "Regenerate A05 from the same national build before running A08.",
        "## Historical interpretation",
        "| Hopley et al. (2007) source | Discrete reef features | Reef area (km2) |\n"
        "| --- | ---: | ---: |\n| Gazetteer | 2,904 | 20,055 |\n| GIS | 3,703 | 24,081 |",
        "The historical dataset and calculation method are unavailable. Numerical agreement "
        "does not establish which classes Hopley included or reproduce the historical method. "
        "The 2,904 Gazetteer figure has no documented inclusion criteria, although it became "
        "the de facto GBR reef count. The 3,703 GIS figure is a feature count with no size or "
        "separation criteria. Source-record counts are not Hopley's discrete-reef counts or "
        "A05's countable-reef counts.",
        f"A05 reports {a05_reference[1]} countable coral reefs and "
        f"{a05_reference[2]} km2 of countable coral "
        "reef area in the GBR, from the national dataset after remapping and reclassification. "
        "A05 counts each countable reef in the region holding its largest piece and clips its "
        "area among regions, as Table 4 does, and its area excludes groups narrower than "
        f"{MIN_WIDTH_M:.0f} m effective width. The difference between the A05 figures and the "
        "Table 4 countable-reef figures estimates the combined effect of the remapping under "
        "identical counting rules. This calculation alone cannot split that effect into reef "
        "additions, false-reef removals, sand-bank corrections or rocky-reef reclassification.",
        "Reference: Hopley, D., Smithers, S. G., & Parnell, K. (2007). *The geomorphology of "
        "the Great Barrier Reef: Development, diversity and change*. Cambridge University "
        "Press. https://researchonline.jcu.edu.au/1554/",
    ]) + "\n"


def main():
    config = configparser.ConfigParser()
    if not config.read("config.ini"):
        raise FileNotFoundError("Missing config.ini; run from the repository root")
    version, paths = input_paths(config)
    paths["A05 statistics"] = (Path("data") / version / "out" / "stats"
                              / f"Aus-Trop-Reef-Features_Region-stats_{version}.csv")
    a05_reference = read_a05_reference(paths["A05 statistics"])
    frames = {}
    for name, path in paths.items():
        if name == "A05 statistics":
            continue
        if not path.is_file():
            raise FileNotFoundError(f"Missing {name}: {path}")
        print(f"Reading {name}: {path}")
        frames[name] = gpd.read_file(path)
    source, regions = frames["GBR Features"], frames["Analysis regions"]
    if len(source) != PORTAL_RECORDS:
        print(f"WARNING: {len(source):,} source records; portal reports {PORTAL_RECORDS:,}",
              flush=True)
    results, repairs, excluded, counts = analyse(source, regions)
    report = build_report(results, repairs, excluded, counts, version, paths, source, regions,
                          a05_reference)
    output_dir = Path("data") / version / "out" / "stats"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"A08-gbr-features-reef-area_{version}.md"
    output.write_text(report, encoding="utf-8")
    print(results.to_string(index=False, formatters={
        "Area (km2)": "{:,.6f}".format, "Difference from 24,081 km2": "{:+,.1f}".format,
        "Difference (%)": "{:+.2f}".format}))
    print(f"Saved report: {output}")
    print(counts.to_string(index=False, formatters={"GBR area (km2)": "{:,.1f}".format}))


if __name__ == "__main__":
    main()
