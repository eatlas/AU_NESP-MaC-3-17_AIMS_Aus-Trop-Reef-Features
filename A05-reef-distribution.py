"""Count and measure national reefs in three independent regionalisations.

Adapted from NW-Aus-Features A05. Run 08-make-RB_Type_L2.py first.

Writes regional CSV statistics, map layers and captioned Markdown report tables
to data/{version}/out/stats/. Each table caption records the configured dataset
version and this script's name.

Intermediate shapefiles are rebuilt by default. Use --use-cache to reuse them
only when inputs and processing rules are unchanged. With --quality-only, only
the analysis-region cache is cleared; distribution caches are left untouched.
"""

import argparse
import configparser
import csv
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

from reef_utils import cluster_countable


ROOT = Path(__file__).resolve().parent
config = configparser.ConfigParser()
config.read(ROOT / "config.ini")
VERSION = config.get("general", "version")
DATA_DIR = ROOT / "data" / VERSION
IN_3P_DIR = ROOT / config.get("general", "in_3p_path")
WORK_DIR = ROOT / "working" / VERSION / "A05"
INPUT_REEFS = (DATA_DIR / "out" / "simp-classes" /
               f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_L2_{VERSION}.shp")
INPUT_FEATURES = (DATA_DIR / "out" / "full-classes" /
                  f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{VERSION}.shp")
COUNTABLE_CACHE = WORK_DIR / "countable-reefs.shp"
OUTPUT_CSV = (DATA_DIR / "out" / "stats" /
              f"Aus-Trop-Reef-Features_Region-stats_{VERSION}.csv")
OUTPUT_MARKDOWN = OUTPUT_CSV.parent / f"A05_Report-tables_{VERSION}.md"
CHECKS_CSV = WORK_DIR / "region-stats-checks.csv"
SCRIPT_NAME = Path(__file__).name

AREA_CRS = 3577
CHECK_REGION_OVERLAPS = True
SLIVER_BUFFER_M = 5.0
OVERLAP_BUFFER_M = 2.5
NEAR_SAMPLE_M = 20.0
NO_MATCH = "No match"
REEF_TYPES = (("Coral Reef", "Coral"), ("Rocky Reef", "Rocky"))
CONFIDENCE_LEVELS = ("High", "Medium", "Low", "Very Low", "Missing")
LEGACY_DATASETS = ("GBR Features", "TS Features")
BOUNDARY_BASES = ("Regional or edited mapping", "Legacy area default")
# EdgeAcc_m is entered as rounded values, so each common value gets its own bin.
# Inner edges are geometric midpoints between neighbouring centres.
EDGE_BIN_CENTRES = (10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 100, 120, 150, 200,
                    250, 300, 400, 500, 600, 800, 1000, 1500, 2000, 3000)
EDGE_PLOT_LIMITS = (EDGE_BIN_CENTRES[0], EDGE_BIN_CENTRES[-1])
EDGE_BAR_HALF_WIDTH_DECADES = 0.025
PIECE_COLUMNS = ["CountFID", "RB_Type_L2", "TYPE", "NAME", "Near", "Sliver",
                 "Area_km2", "geometry"]
# field None marks CAPAD, identified by TYPE and NAME after dissolving its zones.
# Non-overlapping regionalisations are overlap checked and cut as cookie cutters.
REGIONALISATIONS = (
    {"name": "IMCRA v4.0 Meso-scale Bioregions (2023)", "slug": "imcra",
     "source": (IN_3P_DIR / "IMCRA-v4-0-Meso-Bioregions" /
                "IMCRA-v4-Mesoscale-Bioregions.shp"),
     "field": "MESO_NAME", "overlapping": False, "simplify_m": None, "near_m": None},
    {"name": "Analysis-regions v1", "slug": "analysis-region",
     "source": (IN_3P_DIR / "nesp-3-17-analysis-regions" /
                "analysis-regions.shp"),
     "field": "subregion", "overlapping": False, "simplify_m": None, "near_m": None},
    {"name": "CAPAD 2024 - Marine", "slug": "capad",
     "source": (IN_3P_DIR / "CAPAD-2024" /
                "Collaborative_Australian_Protected_Areas_Database_(CAPAD)_2024_-_Marine.shp"),
     "field": None, "overlapping": True, "simplify_m": 10.0, "near_m": 300.0},
)


def polygons(geometry):
    """Keep polygonal parts of an overlay result, discarding lines and points."""
    if geometry.is_empty:
        return Polygon()
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if not hasattr(geometry, "geoms"):
        return Polygon()
    parts = [part for part in geometry.geoms
             if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty]
    return unary_union(parts) if parts else Polygon()


def load_countable():
    """Cluster coral and rocky reefs once, then cache their stable CountFIDs."""
    if COUNTABLE_CACHE.exists():
        print(f"Loading countable reefs: {COUNTABLE_CACHE}", flush=True)
        return gpd.read_file(COUNTABLE_CACHE).to_crs(AREA_CRS)

    print(f"Loading reef features: {INPUT_REEFS}", flush=True)
    reefs = gpd.read_file(INPUT_REEFS)[["RB_Type_L2", "geometry"]]
    reefs = reefs[reefs["RB_Type_L2"].isin([reef_type for reef_type, _ in REEF_TYPES])]
    reefs = reefs.to_crs(AREA_CRS)
    print(f"Clustering {len(reefs)} reef features", flush=True)
    countable, stats = cluster_countable(reefs, show_progress=True)
    if stats["n_unassigned"]:
        raise ValueError(f"{stats['n_unassigned']} reefs could not be clustered")
    if countable.empty:
        raise ValueError("No countable coral or rocky reefs in the national L2 input")
    countable = countable.reset_index(drop=True)
    countable["CountFID"] = countable.index + 1
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    countable.to_file(COUNTABLE_CACHE)
    print(f"Cached {len(countable)} countable reefs: {COUNTABLE_CACHE}", flush=True)
    return countable


def cache_suffix(setting):
    """Name suffix recording the region simplification tolerance."""
    return f"-{setting['simplify_m']:g}m" if setting["simplify_m"] else ""


def read_cached(path):
    """Read a cached layer in EPSG:3577 with TYPE and NAME identity columns."""
    layer = gpd.read_file(path).to_crs(AREA_CRS)
    if "RegionName" in layer.columns:
        layer = layer.rename(columns={"RegionName": "NAME"}).assign(TYPE="")
    layer["TYPE"] = layer["TYPE"].fillna("")
    return layer


def load_regions(setting):
    """Load named non-overlapping regions in EPSG:3577."""
    source, field, slug = setting["source"], setting["field"], setting["slug"]
    cache = WORK_DIR / f"regions-{slug}.shp"
    if cache.exists():
        print(f"Loading cached {slug} regions: {cache}", flush=True)
        return read_cached(cache)[["TYPE", "NAME", "geometry"]]

    print(f"Loading {slug} regions: {source}", flush=True)
    regions = gpd.read_file(source)[[field, "geometry"]].to_crs(AREA_CRS)
    if regions[field].isna().any() or regions[field].eq(NO_MATCH).any():
        raise ValueError(f"Missing or reserved region name in {source}")
    if regions.geometry.isna().any() or not regions.geometry.is_valid.all():
        raise ValueError(f"Null or invalid region geometry in {source}")
    regions = regions.rename(columns={field: "RegionName"})
    regions = regions[["RegionName", "geometry"]].reset_index(drop=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    regions.to_file(cache)
    print(f"Cached {len(regions)} regions: {cache}", flush=True)
    return read_cached(cache)[["TYPE", "NAME", "geometry"]]


def load_capad(setting):
    """Dissolve CAPAD by TYPE and NAME, then simplify in metres."""
    source, simplify_m = setting["source"], setting["simplify_m"]
    cache = WORK_DIR / f"regions-capad{cache_suffix(setting)}.shp"
    if cache.exists():
        print(f"Loading cached CAPAD regions: {cache}", flush=True)
        return read_cached(cache)[["TYPE", "NAME", "geometry"]]

    print(f"Loading CAPAD regions: {source}", flush=True)
    regions = gpd.read_file(source)[["TYPE", "NAME", "geometry"]].to_crs(AREA_CRS)
    if (regions[["TYPE", "NAME"]].isna().any().any() or
            regions["NAME"].eq(NO_MATCH).any()):
        raise ValueError(f"Missing or reserved CAPAD identity in {source}")
    if regions.geometry.isna().any():
        raise ValueError(f"Null CAPAD geometry in {source}")
    invalid = ~regions.geometry.is_valid
    if invalid.any():
        print(f"Repairing {invalid.sum()} invalid CAPAD geometries", flush=True)
        regions.loc[invalid, "geometry"] = regions.loc[invalid, "geometry"].apply(
            lambda geometry: polygons(make_valid(geometry)))
    if regions.geometry.is_empty.any() or not regions.geometry.is_valid.all():
        raise ValueError(f"Unrepairable CAPAD geometry in {source}")
    print(f"Dissolving {len(regions)} CAPAD zones by TYPE and NAME", flush=True)
    regions = regions.dissolve(by=["TYPE", "NAME"], as_index=False)
    regions = regions[["TYPE", "NAME", "geometry"]].reset_index(drop=True)
    original = regions.geometry.copy()
    print(f"Simplifying {len(regions)} CAPAD areas to {simplify_m:g} m", flush=True)
    regions["geometry"] = regions.geometry.simplify(simplify_m, preserve_topology=True)
    invalid = regions.geometry.is_empty | ~regions.geometry.is_valid
    if invalid.any():
        print(f"Retaining original boundaries for {invalid.sum()} CAPAD areas "
              "whose simplified geometry is invalid", flush=True)
        regions.loc[invalid, "geometry"] = original.loc[invalid]
    if regions.geometry.is_empty.any() or not regions.geometry.is_valid.all():
        raise ValueError("CAPAD has empty or invalid dissolved geometry")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    regions.to_file(cache)
    print(f"Cached {len(regions)} CAPAD protected areas: {cache}", flush=True)
    return regions


def check_overlaps(regions, slug):
    """Save and reject overlaps surviving a 2.5 m inward buffer."""
    pairs = regions.sindex.query(regions.geometry, predicate="intersects")
    overlaps = []
    for first, second in zip(*pairs):
        if first >= second:
            continue
        intersection = polygons(regions.geometry.iloc[first].intersection(
            regions.geometry.iloc[second]))
        if not intersection.is_empty and not intersection.buffer(-OVERLAP_BUFFER_M).is_empty:
            overlaps.append({"RegionA": regions["NAME"].iloc[first],
                             "RegionB": regions["NAME"].iloc[second],
                             "geometry": intersection})
    if overlaps:
        path = WORK_DIR / f"debug-overlap-{slug}.shp"
        gpd.GeoDataFrame(overlaps, crs=regions.crs).to_file(path)
        raise ValueError(f"{len(overlaps)} region overlaps wider than 5 m; inspect {path}")


def nearest_cells(area, owners, regions, distance):
    """Split an area between regions by Voronoi cells of sampled region boundaries."""
    reach = area.buffer(distance)
    coords, labels = [], []
    for owner in owners:
        edge = regions.geometry.iloc[owner].boundary.intersection(reach)
        points = shapely.get_coordinates(shapely.segmentize(edge, NEAR_SAMPLE_M))
        coords.append(points)
        labels.append(np.full(len(points), owner))
    coords, labels = np.vstack(coords), np.concatenate(labels)
    # Voronoi merges coincident samples, such as those on shared boundaries.
    coords, first = np.unique(coords.round(1), axis=0, return_index=True)
    labels = labels[first]
    if len(set(labels.tolist())) < 2:
        return [(int(label), area) for label in set(labels.tolist())]
    points = shapely.points(coords)
    cells = list(shapely.voronoi_polygons(shapely.multipoints(coords),
                                          extend_to=reach).geoms)
    cell_index, point_index = shapely.STRtree(points).query(cells, predicate="contains")
    by_owner = {}
    for cell, point in zip(cell_index, point_index):
        by_owner.setdefault(int(labels[point]), []).append(cells[cell])
    return [(owner, unary_union(parts)) for owner, parts in by_owner.items()]


def build_near_regions(regions, reefs, setting):
    """Divide the band within near_m outside all regions by nearest region."""
    distance = setting["near_m"]
    cache = (WORK_DIR / f"near-regions-{setting['slug']}{cache_suffix(setting)}-"
             f"{distance:g}m.shp")
    if cache.exists():
        print(f"Loading near regions: {cache}", flush=True)
        return read_cached(cache)

    # Only regions within the near distance of a reef can own a near region with reef.
    _, nearby = regions.sindex.query(reefs.geometry, predicate="dwithin",
                                     distance=distance)
    candidates = sorted(set(nearby.tolist()))
    print(f"Building {distance:g} m near regions for {len(candidates)} regions",
          flush=True)
    bands = {}
    for index in candidates:
        buffer = regions.geometry.iloc[index].buffer(distance)
        blockers = regions.geometry.iloc[regions.sindex.query(buffer, predicate="intersects")]
        band = polygons(buffer.difference(unary_union(list(blockers))))
        if not band.is_empty:
            bands[index] = band
    owners = list(bands)
    band_layer = gpd.GeoSeries([bands[index] for index in owners], crs=AREA_CRS)
    first, second = band_layer.sindex.query(band_layer, predicate="intersects")
    overlaps = [polygons(band_layer.iloc[a].intersection(band_layer.iloc[b]))
                for a, b in zip(first, second) if a < b]
    contested = polygons(unary_union(overlaps)) if overlaps else Polygon()
    print(f"Resolving {contested.area / 1e6:.3f} km2 where near bands compete",
          flush=True)

    # Uncontested band is used directly; only contested areas need nearest-region tests.
    owned = {index: [polygons(bands[index].difference(contested))] for index in owners}
    components = list(contested.geoms) if isinstance(contested, MultiPolygon) else [contested]
    for component in components:
        if component.is_empty:
            continue
        competing = [owners[j] for j in
                     band_layer.sindex.query(component, predicate="intersects")]
        for owner, cell in nearest_cells(component, competing, regions, distance):
            owned[owner].append(polygons(cell.intersection(component)
                                         .intersection(bands[owner])))
    rows = []
    for index in owners:
        geometry = polygons(unary_union(owned[index]))
        if not geometry.is_empty:
            rows.append({"TYPE": regions["TYPE"].iloc[index],
                         "NAME": regions["NAME"].iloc[index], "geometry": geometry})
    near = gpd.GeoDataFrame(rows, columns=["TYPE", "NAME", "geometry"], crs=AREA_CRS)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    near.to_file(cache)
    print(f"Cached {len(near)} near regions: {cache}", flush=True)
    return read_cached(cache)


def reef_cache_path(setting):
    """Reef piece cache named by region simplification and near distance."""
    near = f"-near{setting['near_m']:g}m" if setting["near_m"] else ""
    return WORK_DIR / f"reefs-by-{setting['slug']}{cache_suffix(setting)}{near}.shp"


def write_pieces(pieces, path, setting):
    """Save reef pieces, using RegionName for single-field regionalisations."""
    columns = [column for column in PIECE_COLUMNS[:-1] + ["Assigned", "geometry"]
               if column in pieces.columns]
    output = pieces[columns]
    if setting["field"] is not None:
        output = output.drop(columns="TYPE").rename(columns={"NAME": "RegionName"})
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    output.to_file(path)


def slice_reefs(reefs, regions, near, setting):
    """Cut each countable reef into region, near region and No match pieces."""
    cache = reef_cache_path(setting)
    if cache.exists():
        print(f"Loading reef pieces: {cache}", flush=True)
        return read_cached(cache)[PIECE_COLUMNS]

    slug, overlapping = setting["slug"], setting["overlapping"]
    print(f"Slicing {len(reefs)} countable reefs by {slug} regions", flush=True)
    rows = []
    for position, reef in enumerate(reefs.itertuples(index=False), start=1):
        by_key = {}
        remaining = reef.geometry
        for region_index in regions.sindex.query(reef.geometry, predicate="intersects"):
            region = regions.iloc[region_index]
            # Overlapping regions each take their full intersection with the reef;
            # otherwise claimed area is removed so it cannot be claimed twice.
            source = reef.geometry if overlapping else remaining
            piece = polygons(source.intersection(region.geometry))
            if piece.is_empty:
                continue
            by_key.setdefault((region.TYPE, region.NAME, 0), []).append(piece)
            if not overlapping:
                remaining = polygons(remaining.difference(region.geometry))
                if remaining.is_empty:
                    break
        if overlapping and by_key:
            inside = unary_union([part for parts in by_key.values() for part in parts])
            remaining = polygons(reef.geometry.difference(inside))
        if near is not None and not remaining.is_empty:
            for near_index in near.sindex.query(remaining, predicate="intersects"):
                zone = near.iloc[near_index]
                piece = polygons(remaining.intersection(zone.geometry))
                if piece.is_empty:
                    continue
                by_key.setdefault((zone.TYPE, zone.NAME, 1), []).append(piece)
                remaining = polygons(remaining.difference(zone.geometry))
                if remaining.is_empty:
                    break
        if not remaining.is_empty:
            by_key[("", NO_MATCH, 0)] = [remaining]

        for (region_type, name, is_near), parts in by_key.items():
            piece = polygons(unary_union(parts))
            if piece.is_empty:
                continue
            rows.append({"CountFID": reef.CountFID, "RB_Type_L2": reef.RB_Type_L2,
                         "TYPE": region_type, "NAME": name, "Near": is_near,
                         "Sliver": int(piece.buffer(-SLIVER_BUFFER_M).is_empty),
                         "Area_km2": piece.area / 1e6, "geometry": piece})
        if position % 1000 == 0:
            print(f"  {slug}: {position}/{len(reefs)} reefs", flush=True)

    pieces = gpd.GeoDataFrame(rows, columns=PIECE_COLUMNS, crs=AREA_CRS)
    write_pieces(pieces, cache, setting)
    print(f"Cached {len(pieces)} reef pieces: {cache}", flush=True)
    return pieces


def assign_counts(pieces, reef_areas):
    """Count each reef in its largest piece and in any region holding over half of it."""
    pieces = pieces.copy()
    kept = pieces["Sliver"] == 0
    # Ties favour a region, then a near region, then No match.
    priority = np.where(pieces["NAME"].eq(NO_MATCH), 2, np.where(pieces["Near"].eq(1), 1, 0))
    ranked = (pieces.assign(_priority=priority)[kept]
              .sort_values(["CountFID", "Area_km2", "_priority"],
                           ascending=[True, False, True]))
    pieces["Winner"] = 0
    pieces.loc[ranked.drop_duplicates("CountFID").index, "Winner"] = 1
    majority = kept & (pieces["Area_km2"] > 0.5 * pieces["CountFID"].map(reef_areas))
    pieces["Assigned"] = ((pieces["Winner"] == 1) | majority).astype(int)
    return pieces


def union_area(pieces):
    """Sum, over reefs, the area of the union of each reef's pieces."""
    return sum(unary_union(list(group)).area if len(group) > 1 else group.iloc[0].area
               for _, group in pieces.geometry.groupby(pieces["CountFID"]))


def check_conservation(pieces, reefs, dataset_name):
    """Check that each reef is counted once and that reef area is fully accounted for."""
    results = []
    for reef_type, _ in REEF_TYPES:
        input_reefs = reefs[reefs["RB_Type_L2"] == reef_type]
        typed = pieces[pieces["RB_Type_L2"] == reef_type]
        kept = typed[typed["Sliver"] == 0]
        is_inside = (typed["Near"] == 0) & typed["NAME"].ne(NO_MATCH)
        inside, outside = typed[is_inside], typed[~is_inside]
        kept_inside = inside[inside["Sliver"] == 0]
        kept_union = union_area(kept_inside) if len(kept_inside) else 0.0
        raw_union = union_area(inside) if len(inside) else 0.0
        outside_kept = outside.loc[outside["Sliver"] == 0].geometry.area.sum()
        outside_sliver = outside.loc[outside["Sliver"] == 1].geometry.area.sum()
        input_area = input_reefs.geometry.area.sum()
        allocated = kept_union + outside_kept
        sliver = raw_union - kept_union + outside_sliver
        winners = kept[kept["Winner"] == 1]
        tolerance = max(1.0, input_area * 1e-8)
        passed = (len(winners) == len(input_reefs) and winners["CountFID"].is_unique and
                  abs(input_area - allocated - sliver) <= tolerance)
        results.append({
            "Region_dataset": dataset_name, "RB_Type_L2": reef_type,
            "Input_reef_count": len(input_reefs),
            "Assigned_reef_count": len(winners),
            "Overlap_extra_count": int(kept["Assigned"].sum()) - len(winners),
            "Split_reef_count": int((kept.groupby("CountFID").size() > 1).sum()),
            "Partial_count_sum": int((kept["Assigned"] == 0).sum()),
            "Near_assigned_count": int((winners["Near"] == 1).sum()),
            "No_match_assigned_count": int(winners["NAME"].eq(NO_MATCH).sum()),
            "Input_area_km2": f"{input_area / 1e6:.6f}",
            "Allocated_area_km2": f"{allocated / 1e6:.6f}",
            "Sliver_area_km2": f"{sliver / 1e6:.6f}",
            "Overlap_extra_area_km2":
                f"{(kept_inside.geometry.area.sum() - kept_union) / 1e6:.6f}",
            "Status": "Pass" if passed else "Fail"})
    return results


def write_csv(path, rows):
    """Write dictionaries to CSV in their key order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def region_label(region_type, name, near):
    """Report label of the form '{Near: }{Region_name}{ - Region_type}'."""
    label = f"Near: {name}" if near else name
    return f"{label} - {region_type}" if region_type else label


def summarise(datasets):
    """Write assigned counts, partial counts and clipped areas for each occupied region."""
    records = []
    for dataset_name, pieces in datasets:
        kept = pieces[pieces["Sliver"] == 0]
        for (region_type, name, near), group in kept.groupby(["TYPE", "NAME", "Near"]):
            record = {"Region_dataset": dataset_name, "Region_type": region_type,
                      "Region_name": name, "Near_region": "Yes" if near else "No",
                      "Label": region_label(region_type, name, near)}
            for reef_type, prefix in REEF_TYPES:
                typed = group[group["RB_Type_L2"] == reef_type]
                record[f"{prefix}_reef_count"] = int(typed["Assigned"].sum())
                record[f"{prefix}_reef_partial_count"] = int((typed["Assigned"] == 0).sum())
                record[f"{prefix}_reef_area_km2"] = f"{typed['Area_km2'].sum():.6f}"
            records.append(record)
    records.sort(key=lambda row: (row["Region_dataset"], row["Region_name"] == NO_MATCH,
                                  row["Region_type"], row["Region_name"],
                                  row["Near_region"]))
    write_csv(OUTPUT_CSV, records)
    print(f"Wrote {len(records)} region summaries: {OUTPUT_CSV}", flush=True)
    return records


def write_report_tables(records, checks):
    """Render the CSV summaries as captioned tables without optional dependencies."""
    input_path = (INPUT_REEFS.relative_to(ROOT)
                  if INPUT_REEFS.is_relative_to(ROOT) else INPUT_REEFS)
    checks_path = (CHECKS_CSV.relative_to(ROOT)
                   if CHECKS_CSV.is_relative_to(ROOT) else CHECKS_CSV)
    report = [
        f"<!-- Generated by {SCRIPT_NAME} from dataset version {VERSION}. -->",
        f"# National reef distribution: {VERSION}",
        f"Input reef dataset: `{input_path.as_posix()}`.",
        f"Regional statistics: [{OUTPUT_CSV.name}]({OUTPUT_CSV.name}). "
        "The CSV retains areas to six decimal places.",
        "Counts refer to countable coral and rocky reefs, not source polygons or "
        "named reefs. Partial counts refer to reefs that extend into a region but "
        "are counted elsewhere. Partial counts must not be summed across regions. "
        "Areas are clipped reef areas, including the parts of partial reefs, "
        "calculated in GDA94 / Australian Albers (EPSG:3577). Pieces that do not "
        f"survive a {SLIVER_BUFFER_M:g} m inward buffer are excluded. Areas are "
        "displayed to one decimal place in square kilometres; positive areas below "
        "0.1 km2 are shown as <0.1. Rounding can affect sums.",
        "Only regions and near regions containing retained reef area are listed. "
        "'No match' includes mapped reefs outside the regional coverage, including "
        "reefs beyond Australian waters. It is not an Australian outside-protection "
        "total. The three regionalisations are independent and must not be summed.",
    ]
    failures = [check for check in checks if check["Status"] != "Pass"]
    report.append(f"Conservation checks: `{checks_path.as_posix()}`.")
    if failures:
        report.append(
            "**WARNING: Conservation checks failed. These tables require review "
            "before use in the technical report.** Failed checks: " +
            "; ".join(f"{check['Region_dataset']} ({check['RB_Type_L2']})"
                      for check in failures) + ".")
    else:
        report.append(
            "All count and area conservation checks passed. CAPAD overlap extras "
            "are excluded from the conservation comparison.")

    for number, setting in enumerate(REGIONALISATIONS, start=1):
        caption = (
            f"**Table {number}.** Countable coral and rocky reefs and their mapped "
            f"area by region in {setting['name']}. Counts are assigned to the "
            "largest retained reef piece. Partial counts are reefs extending into "
            "the region but counted elsewhere. Areas include these partial reefs. ")
        if setting["overlapping"]:
            caption += (
                "A reef is also counted in any overlapping protected area holding "
                "more than half its area. Overlapping protected areas can therefore "
                "double count reefs and area; their rows must not be summed to "
                "estimate unique protected reefs or area. ")
        if setting["near_m"]:
            caption += (
                f"'Near:' rows show reef pieces outside all regions but within "
                f"{setting['near_m']:g} m of the named region. ")
        caption += (
            "'No match' reports the remaining mapped coverage, not only Australian "
            f"waters. Data: {VERSION}. Analysis script: {SCRIPT_NAME}.")
        lines = [
            "| Region | Coral reefs | Coral partial | Coral area (km2) | "
            "Rocky reefs | Rocky partial | Rocky area (km2) |",
            "|:---|---:|---:|---:|---:|---:|---:|",
        ]
        for row in records:
            if row["Region_dataset"] != setting["name"]:
                continue
            label = str(row["Label"]).replace("|", r"\|").replace("\r", " ").replace("\n", " ")
            cells = [label]
            for _, prefix in REEF_TYPES:
                area = float(row[f"{prefix}_reef_area_km2"])
                cells.extend([
                    f"{int(row[f'{prefix}_reef_count']):,}",
                    f"{int(row[f'{prefix}_reef_partial_count']):,}",
                    "<0.1" if 0 < area < 0.1 else f"{area:,.1f}",
                ])
            lines.append("| " + " | ".join(cells) + " |")
        report.extend([f"## {setting['name']}", caption, "\n".join(lines)])
        if len(lines) == 2:
            report.append("No retained reef area occurs in this regionalisation.")

    OUTPUT_MARKDOWN.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MARKDOWN.write_text("\n\n".join(report) + "\n", encoding="utf-8")
    print(f"Wrote report tables: {OUTPUT_MARKDOWN}", flush=True)


def export_region_stats(regions, near, records, setting):
    """Attach CSV totals to occupied regions and near regions for mapping."""
    stats = {(row["Region_type"], row["Region_name"], int(row["Near_region"] == "Yes")): row
             for row in records
             if row["Region_dataset"] == setting["name"] and row["Region_name"] != NO_MATCH}
    layers = [regions.assign(Near=0)]
    if near is not None:
        layers.append(near.assign(Near=1))
    combined = gpd.GeoDataFrame(pd.concat(layers, ignore_index=True), crs=AREA_CRS)
    matching = [stats.get(key) for key in
                zip(combined["TYPE"], combined["NAME"], combined["Near"])]
    mapped = combined.loc[[row is not None for row in matching]].copy()
    matching = [row for row in matching if row is not None]
    mapped["Label"] = [row["Label"] for row in matching]
    for _, prefix in REEF_TYPES:
        mapped[f"{prefix}Count"] = [row[f"{prefix}_reef_count"] for row in matching]
        mapped[f"{prefix}Part"] = [row[f"{prefix}_reef_partial_count"] for row in matching]
        mapped[f"{prefix}Km2"] = [float(row[f"{prefix}_reef_area_km2"]) for row in matching]
    if setting["field"] is not None:
        mapped = mapped.drop(columns="TYPE").rename(columns={"NAME": "RegionName"})
    mapped = mapped[[column for column in mapped.columns if column != "geometry"] +
                    ["geometry"]]
    path = (OUTPUT_CSV.parent /
            f"Aus-Trop-Reef-Features_Region-stats_{setting['slug']}_{VERSION}.shp")
    mapped.to_file(path)
    print(f"Wrote {len(mapped)} occupied {setting['slug']} regions: {path}", flush=True)


def prepare_quality_features(features, regions):
    """Allocate each full-classification reef record once, without size filtering."""
    required = {"ReefFID", "Dataset", "RB_Type_L2", "FeatConf", "TypeConf", "EdgeAcc_m"}
    missing = required - set(features.columns)
    if missing:
        raise ValueError(f"Feature quality input: missing fields {sorted(missing)}")
    frame = features.loc[features.RB_Type_L2.isin([kind for kind, _ in REEF_TYPES])].copy()
    if frame.empty:
        raise ValueError("Feature quality input: no coral or rocky reef records")
    for field in ("ReefFID", "Dataset"):
        if (frame[field].isna() | frame[field].astype(str).str.strip().eq("")).any():
            raise ValueError(f"Feature quality input: missing {field}")
    if not frame.ReefFID.is_unique:
        raise ValueError("Feature quality input: duplicate ReefFID")
    for name, layer in (("Feature quality input", frame), ("Analysis regions", regions)):
        if layer.crs is None:
            raise ValueError(f"{name}: missing CRS")
        bad = (layer.geometry.isna() | layer.geometry.is_empty | ~layer.geometry.is_valid
               | ~layer.geom_type.isin(("Polygon", "MultiPolygon")))
        if bad.any():
            raise ValueError(f"{name}: invalid geometry at rows {layer.index[bad].tolist()}")
    if (regions.NAME.isna() | regions.NAME.astype(str).str.strip().eq("")).any():
        raise ValueError("Analysis regions: missing NAME")
    projected = frame.to_crs(AREA_CRS)
    for index in projected.index[~projected.geometry.is_valid]:
        print(f"WARNING: In-memory analysis projection repair for "
              f"ReefFID={projected.at[index, 'ReefFID']}", flush=True)
        projected.at[index, "geometry"] = polygons(make_valid(projected.at[index, "geometry"]))
    if (~projected.geometry.is_valid | projected.geometry.is_empty).any():
        raise ValueError("Feature quality input: analysis projection repair failed")
    regions = (regions[["NAME", "geometry"]].to_crs(AREA_CRS)
               .dissolve(by="NAME", as_index=False).sort_values("NAME").reset_index(drop=True))
    if regions.empty or not regions.geometry.is_valid.all():
        raise ValueError("Analysis regions: empty or invalid after projection")
    labels = []
    for geometry in projected.geometry:
        candidates = regions.iloc[regions.sindex.query(geometry, predicate="intersects")].sort_values("NAME")
        if candidates.empty:
            labels.append(NO_MATCH)
            continue
        intersections = candidates.geometry.intersection(geometry)
        areas = intersections.area
        largest = areas.max()
        outside = max(0.0, geometry.area - unary_union(intersections).area)
        if largest <= 0 or outside > largest:
            labels.append(NO_MATCH)
        else:
            # Sorted names make equal-area ties reproducible.
            labels.append(candidates.loc[areas.eq(largest), "NAME"].iloc[0])
    frame["Region"] = labels
    frame["Boundary_basis"] = np.where(frame.Dataset.isin(LEGACY_DATASETS),
                                      BOUNDARY_BASES[1], BOUNDARY_BASES[0])
    return frame


def edge_bin_edges():
    """Bin edges whose bins are centred, on a log scale, on EDGE_BIN_CENTRES."""
    centres = np.asarray(EDGE_BIN_CENTRES, dtype=float)
    return np.concatenate(([centres[0]], np.sqrt(centres[:-1] * centres[1:]),
                           [centres[-1]]))


def quality_summaries(features):
    """Keep source, reef type, missing values and legacy defaults distinguishable."""
    edge = pd.to_numeric(features.EdgeAcc_m, errors="coerce")
    missing = features.EdgeAcc_m.isna() | features.EdgeAcc_m.astype(str).str.strip().eq("")
    invalid = ~missing & (~np.isfinite(edge) | edge.lt(0))
    if invalid.any():
        print(f"WARNING: Invalid EdgeAcc_m excluded from histogram: "
              f"{features.loc[invalid, 'ReefFID'].tolist()}", flush=True)
    positive = edge.gt(0) & ~invalid
    bins = edge_bin_edges()
    confidence_rows, edge_rows, histogram_rows = [], [], []
    keys = ["Region", "Dataset", "Boundary_basis", "RB_Type_L2"]
    for key, group in features.groupby(keys, sort=True):
        common = dict(zip(keys, key))
        for attribute in ("FeatConf", "TypeConf"):
            raw = group[attribute]
            normalised = raw.where(raw.notna() & raw.astype(str).str.strip().ne(""), "Missing")
            counts = normalised.value_counts()
            other = sorted(set(counts.index) - set(CONFIDENCE_LEVELS))
            if other:
                print(f"WARNING: Non-standard {attribute} values in {key}: {other}", flush=True)
            for level in (*CONFIDENCE_LEVELS, *other):
                count = int(counts.get(level, 0))
                confidence_rows.append({
                    **common, "Attribute": attribute, "Value": level,
                    "Count": count, "Total": len(group), "Percent": 100 * count / len(group),
                })
        selected = edge.loc[group.index][positive.loc[group.index]]
        edge_rows.append({
            **common, "Total": len(group), "Positive_count": len(selected),
            "Missing_count": int(missing.loc[group.index].sum()),
            "Zero_count": int(edge.loc[group.index].eq(0).sum()),
            "Invalid_count": int(invalid.loc[group.index].sum()),
            "Min_m": selected.min() if len(selected) else "",
            "Median_m": selected.median() if len(selected) else "",
            "P90_m": selected.quantile(0.9) if len(selected) else "",
            "Max_m": selected.max() if len(selected) else "",
            "At_most_50m_count": int(selected.le(50).sum()),
            "Over_1000m_count": int(selected.gt(1000).sum()),
        })
        plotted = selected[selected.between(*EDGE_PLOT_LIMITS)]
        counts, _ = np.histogram(plotted, bins=bins)
        for centre, left, right, count in zip(EDGE_BIN_CENTRES, bins[:-1], bins[1:], counts):
            histogram_rows.append({
                **common, "Bin_scope": "Plotted", "Bin_centre_m": centre,
                "Bin_lower_m": left, "Bin_upper_m": right,
                "Count": int(count), "Total": len(group),
            })
        histogram_rows.extend([
            {**common, "Bin_scope": "Below plotted range", "Bin_centre_m": "",
             "Bin_lower_m": "", "Bin_upper_m": EDGE_PLOT_LIMITS[0],
             "Count": int(selected.lt(EDGE_PLOT_LIMITS[0]).sum()), "Total": len(group)},
            {**common, "Bin_scope": "Above plotted range", "Bin_centre_m": "",
             "Bin_lower_m": EDGE_PLOT_LIMITS[1], "Bin_upper_m": "",
             "Count": int(selected.gt(EDGE_PLOT_LIMITS[1]).sum()), "Total": len(group)},
        ])
    return confidence_rows, edge_rows, histogram_rows, bins


def write_quality_summary():
    """Regenerate quality outputs from source records, never from reef caches."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from matplotlib.ticker import MaxNLocator

    setting = next(item for item in REGIONALISATIONS if item["slug"] == "analysis-region")
    regions = load_regions(setting)
    features = prepare_quality_features(gpd.read_file(INPUT_FEATURES), regions)
    confidence, edge, histogram, _ = quality_summaries(features)
    prefix = f"A05_Feature-quality_{VERSION}"
    directory = OUTPUT_CSV.parent
    paths = {name: directory / f"{prefix}-{name}.csv"
             for name in ("confidence", "edge-accuracy", "edge-histogram")}
    for name, rows in zip(paths, (confidence, edge, histogram)):
        write_csv(paths[name], rows)
    names = sorted(features.Region.unique(), key=lambda name: (name == NO_MATCH, name))
    plot_names = [name for name in names if name != "New Caledonia"]
    nrows = max(1, (len(plot_names) + 2) // 3)
    fig, axes = plt.subplots(nrows, 3, squeeze=False,
                             figsize=(14, 2.6 * nrows), sharex=True)
    histogram_frame = pd.DataFrame(histogram)
    colours = dict(zip(BOUNDARY_BASES, ("#176b85", "#a65b16")))
    # Equal-width bars on the log axis, so wider bins do not look like larger counts.
    centres = np.asarray(EDGE_BIN_CENTRES, dtype=float)
    bar_left = centres * 10 ** -EDGE_BAR_HALF_WIDTH_DECADES
    bar_width = centres * 10 ** EDGE_BAR_HALF_WIDTH_DECADES - bar_left
    for position, (axis, name) in enumerate(zip(axes.flat, plot_names)):
        bottom = np.zeros(len(centres))
        for basis in BOUNDARY_BASES:
            rows = histogram_frame[(histogram_frame.Region == name)
                                   & (histogram_frame.Boundary_basis == basis)
                                   & histogram_frame.Bin_scope.eq("Plotted")]
            counts = (rows.groupby("Bin_centre_m").Count.sum()
                      .reindex(EDGE_BIN_CENTRES, fill_value=0).to_numpy())
            if counts.any():
                axis.bar(bar_left, counts, width=bar_width, bottom=bottom, align="edge",
                         color=colours[basis], linewidth=0)
                bottom += counts
        group = features[features.Region == name]
        excluded = sum(row["Missing_count"] + row["Zero_count"] + row["Invalid_count"]
                       for row in edge if row["Region"] == name)
        outside = histogram_frame.loc[
            histogram_frame.Region.eq(name) & histogram_frame.Bin_scope.ne("Plotted"), "Count"
        ].sum()
        details = f"N = {len(group):,}"
        if outside:
            details += f"; outside = {outside:,}"
        if excluded:
            details += f"; excluded = {excluded:,}"
        axis.set_title(f"{name}\n{details}", fontsize=13)
        axis.set_xscale("log")
        axis.set_xlim(bar_left[0] / 1.05, (bar_left[-1] + bar_width[-1]) * 1.05)
        axis.set_xticks([10, 30, 100, 300, 1000, 3000],
                        labels=["10", "30", "100", "300", "1,000", "3,000"])
        axis.tick_params(labelsize=13)
        axis.tick_params(axis="x", labelbottom=position + 3 >= len(plot_names))
        axis.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
        axis.grid(axis="y", alpha=0.2)
    for axis in list(axes.flat)[len(plot_names):]:
        axis.set_visible(False)
    handles = [Patch(color=colours[basis]) for basis in BOUNDARY_BASES]
    labels = list(BOUNDARY_BASES)
    height = fig.get_figheight()
    if plot_names:
        fig.legend(handles, labels, loc="upper center",
                   bbox_to_anchor=(0.5, 1 - 0.42 / height), ncol=2, fontsize=13)
    else:
        fig.text(0.5, 0.5, "No regional panels after omitting New Caledonia.",
                 ha="center", fontsize=13)
    fig.suptitle(f"Boundary uncertainty of coral and rocky reef feature records: {VERSION}",
                 y=1 - 0.08 / height, fontsize=15.6)
    fig.supxlabel("EdgeAcc_m (m, logarithmic scale)", fontsize=13, y=0.05 / height)
    fig.supylabel("Feature records per value bin", fontsize=13, x=0.01)
    fig.subplots_adjust(top=1 - 1.3 / height, bottom=0.6 / height, left=0.075, right=0.985,
                        hspace=0.3, wspace=0.15)
    image = directory / f"{prefix}.png"
    fig.savefig(image, dpi=180, bbox_inches="tight")
    plt.close(fig)
    report = [
        f"# Reef feature quality: {VERSION}",
        f"Generated by {SCRIPT_NAME} from `{INPUT_FEATURES.name}`. "
        f"Scope: {len(features):,} full-classification coral and rocky reef records. "
        "No dissolving, clustering or minimum-size filtering is applied.",
        "Each record is assigned once to its largest Analysis-region intersection "
        "or to 'No match' when its area outside all regions is larger. Equal-area "
        "named-region ties use alphabetical order. Mapping source and broad reef "
        "type remain separate in the CSVs. Geometry repair, where required after "
        "analysis projection, is in-memory only.",
        "FeatConf and TypeConf are interpretation judgements, not calibrated "
        "probabilities or independently measured accuracy. Missing values remain "
        "explicit. Legacy FeatConf is blank; GBR TypeConf is blank, while Torres "
        "Strait TypeConf is inherited from CLASS_CONF (LowHigh becomes Low). "
        "Legacy EdgeAcc_m values are area-based defaults of 150, 200, 300, 600 "
        "or 800 m, not feature-specific estimates from imagery. Values in other "
        "mapping sources are reported as supplied, without inferring a new "
        "assessment or converting the values into measured errors.",
        "CSV outputs: " + ", ".join(f"[{path.name}]({path.name})" for path in paths.values()) + ".",
    ]
    confidence_frame = pd.DataFrame(confidence)
    for attribute in ("FeatConf", "TypeConf"):
        lines = ["| Analysis-region | High | Medium | Low | Very Low | Missing | Other |",
                 "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for name in names:
            rows = confidence_frame[(confidence_frame.Region == name)
                                    & (confidence_frame.Attribute == attribute)]
            counts = rows.groupby("Value").Count.sum()
            cells = [name, *[f"{int(counts.get(level, 0)):,}" for level in CONFIDENCE_LEVELS],
                     f"{int(counts.loc[~counts.index.isin(CONFIDENCE_LEVELS)].sum()):,}"]
            lines.append("| " + " | ".join(cells) + " |")
        report.extend([
            f"## {attribute}",
            f"**Table.** {attribute} categories of coral and rocky reef feature records. "
            "Counts include explicit missing values and inherited legacy attributes. "
            f"Source-separated counts and percentages are in the confidence CSV. "
            f"Dataset {VERSION}; analysis {SCRIPT_NAME}.",
            "\n".join(lines),
        ])
    lines = ["| Analysis-region | Boundary basis | Records | Median (m) | P90 (m) | "
             "Range (m) | At most 50 m | Above 1,000 m |",
             "| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |"]
    for name in names:
        for basis in BOUNDARY_BASES:
            group = features[(features.Region == name) & (features.Boundary_basis == basis)]
            if group.empty:
                continue
            values = pd.to_numeric(group.EdgeAcc_m, errors="coerce")
            values = values[np.isfinite(values) & values.gt(0)]
            cells = [name, basis, f"{len(group):,}"]
            cells.extend([f"{values.median():g}", f"{values.quantile(0.9):g}",
                          f"{values.min():g}-{values.max():g}",
                          f"{int(values.le(50).sum()):,}", f"{int(values.gt(1000).sum()):,}"]
                         if len(values) else ["", "", "", "0", "0"])
            lines.append("| " + " | ".join(cells) + " |")
    report.extend([
        "## Estimated boundary uncertainty",
        "**Table.** Positive EdgeAcc_m values by Analysis-region and boundary "
        "attribute provenance. Quantiles describe stored values, not measured "
        "positional errors. Missing, zero and invalid values are excluded from "
        f"numeric summaries and counted in the CSV. Dataset {VERSION}; analysis {SCRIPT_NAME}.",
        "\n".join(lines),
        f"![Regional histograms of positive EdgeAcc_m values.]({image.name})",
        "**Figure.** Stored boundary-uncertainty values of coral and rocky reef "
        f"feature records. EdgeAcc_m is mostly recorded as rounded values, so each "
        f"bar is centred on one of {len(EDGE_BIN_CENTRES)} common values from "
        f"{EDGE_PLOT_LIMITS[0]} to {EDGE_PLOT_LIMITS[1]:,} m "
        f"({', '.join(f'{centre:,}' for centre in EDGE_BIN_CENTRES)}). Other values "
        "are counted in the nearest of these on a logarithmic scale; bin edges are "
        "geometric midpoints between neighbouring values. Bars have equal width and "
        "show counts, not probability densities. Regional or edited mapping and "
        "legacy area-based defaults are stacked in separate colours. Values outside the plotted "
        "range are omitted from the figure, counted as 'outside' in panel labels "
        "and retained in separate CSV rows. Missing, zero and invalid values are "
        "shown as 'excluded' when present. N includes all regional records. "
        "New Caledonia is omitted from the figure but retained in all tables and CSVs. "
        "These values describe limitations of the mapping "
        f"evidence, not reef condition. Dataset {VERSION}; analysis {SCRIPT_NAME}.",
    ])
    report_path = directory / f"{prefix}.md"
    report_path.write_text("\n\n".join(report) + "\n", encoding="utf-8")
    print(f"Wrote reef feature quality summaries: {report_path}", flush=True)
    return features


def clear_cache(quality_only=False):
    """Remove spatial cache files and sidecars, preserving other working files."""
    patterns = (("regions-analysis-region.*",) if quality_only else
                ("countable-reefs.*", "regions-*.*", "near-regions-*.*",
                 "reefs-by-*.*"))
    for pattern in patterns:
        for path in sorted(WORK_DIR.glob(pattern)):
            if path.is_file():
                print(f"Removing cached file: {path}", flush=True)
                path.unlink()


def main(argv=None):
    """Run each regionalisation independently against the same countable reefs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality-only", action="store_true",
                        help="Regenerate source-feature quality summaries without countable reef processing")
    parser.add_argument("--use-cache", action="store_true",
                        help="Reuse spatial caches (only when inputs and processing rules are unchanged)")
    args = parser.parse_args(argv)
    if not args.use_cache:
        clear_cache(quality_only=args.quality_only)
    if args.quality_only:
        write_quality_summary()
        return
    reefs = load_countable()
    reef_areas = pd.Series(reefs.geometry.area.values / 1e6, index=reefs["CountFID"])
    datasets, checks, layers = [], [], []
    for setting in REGIONALISATIONS:
        print(f"Processing {setting['name']}", flush=True)
        if setting["field"] is None:
            regions = load_capad(setting)
        else:
            regions = load_regions(setting)
        if CHECK_REGION_OVERLAPS and not setting["overlapping"]:
            print(f"Checking {len(regions)} {setting['slug']} regions for overlaps",
                  flush=True)
            check_overlaps(regions, setting["slug"])
        near = build_near_regions(regions, reefs, setting) if setting["near_m"] else None
        pieces = assign_counts(slice_reefs(reefs, regions, near, setting), reef_areas)
        write_pieces(pieces, reef_cache_path(setting), setting)
        checks.extend(check_conservation(pieces, reefs, setting["name"]))
        datasets.append((setting["name"], pieces))
        layers.append((setting, regions, near))

    write_csv(CHECKS_CSV, checks)
    print(f"Wrote conservation checks: {CHECKS_CSV}", flush=True)
    records = summarise(datasets)
    write_report_tables(records, checks)
    for setting, regions, near in layers:
        export_region_stats(regions, near, records, setting)

    for check in checks:
        print(f"{check['Status']}: {check['Region_dataset']} {check['RB_Type_L2']}: "
              f"{check['Assigned_reef_count']}/{check['Input_reef_count']} reefs assigned, "
              f"{check['Overlap_extra_count']} overlap extras, "
              f"{check['Partial_count_sum']} partials; area "
              f"{check['Allocated_area_km2']} + slivers {check['Sliver_area_km2']} "
              f"of {check['Input_area_km2']} km2", flush=True)
    failures = [check for check in checks if check["Status"] != "Pass"]
    if failures:
        print(f"WARNING: {len(failures)} conservation checks failed; see {CHECKS_CSV}",
              flush=True)
    write_quality_summary()


if __name__ == "__main__":
    main()