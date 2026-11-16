"""Report GBR and Torres Strait edits using final lineage and source edit layers.

Run from the repository root in AusTropReef after building the stage 06 output.
Configuration comes from config.ini. The Markdown report is written to
data/{version}/out/stats/. No source geometry or identifier is modified.
Invalid polygons are exported to working/{version}/A07/invalid-polygons.shp.
"""

import configparser
from datetime import datetime
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import make_valid
from shapely.ops import unary_union
from shapely.validation import explain_validity


SCRIPT_NAME = Path(__file__).name
LOCATIONS = ("GBR inshore", "GBR outside inshore", "Torres Strait")
REPORT_GROUPS = (
    (LOCATIONS[0], LOCATIONS[:1]),
    (LOCATIONS[1], LOCATIONS[1:2]),
    (LOCATIONS[2], LOCATIONS[2:]),
    ("GBR outside inshore + Torres Strait (subtotal)", LOCATIONS[1:]),
    ("GBR + Torres Strait (total)", LOCATIONS),
)


def input_paths(config):
    version = config.get("general", "version")
    inputs = Path(config.get("general", "in_path"))
    third_party = Path(config.get("general", "in_3p_path"))
    paths = {
        "Final features": Path("data") / version / "out" / "full-classes"
        / f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp",
        "Reef Edit": inputs / "Reef-edit"
        / f"AIMS_GBR-TS-Features_Edit_{version}.shp",
        "Control points": inputs / "Reef-remove-move"
        / f"AIMS_GBR-TS-Features_remove-move_{version}.shp",
        "Legacy reference": Path("working") / version / "01"
        / "TS-GBR-Features-latest.shp",
        "Analysis regions": third_party / "nesp-3-17-analysis-regions"
        / "analysis-regions.shp",
        "Inshore extent": Path("data") / version / "extras"
        / "inshore-extent" / "inshore-extent.shp",
    }
    return version, paths


def present(series):
    return series.notna() & series.astype(str).str.strip().ne("")


def provenance_path(path):
    try:
        relative = Path(os.path.abspath(path)).relative_to(Path.cwd())
    except ValueError:
        return f"`{path.name}` (external input; location configured in local config.ini)"
    return f"`{relative.as_posix()}`"


def repair_polygon_layer(frame, name, repairs, stage):
    frame = frame.reset_index(drop=True).copy()
    invalid = (
        frame.geom_type.isin(("Polygon", "MultiPolygon"))
        & ~frame.geometry.is_empty & ~frame.geometry.is_valid
    )
    for index in frame.index[invalid]:
        original = frame.at[index, "geometry"]
        repaired = make_valid(original)
        parts = [repaired]
        polygons = []
        non_polygon_parts = 0
        while parts:
            part = parts.pop()
            if part.geom_type == "Polygon":
                polygons.append(part)
            elif part.geom_type in ("MultiPolygon", "GeometryCollection"):
                parts.extend(part.geoms)
            else:
                non_polygon_parts += 1
        geometry = unary_union(polygons)
        if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in (
            "Polygon", "MultiPolygon"
        ):
            raise ValueError(f"{name}: source row {index + 1} has no valid polygon "
                             "after in-memory repair")
        frame.at[index, "geometry"] = geometry
        diagnostic = {
            "Input": name, "Source row": index + 1,
            "Dataset": frame.at[index, "Dataset"] if "Dataset" in frame else "",
            "ReefFID": frame.at[index, "ReefFID"] if "ReefFID" in frame else "",
            "Stage": stage, "Reason": explain_validity(original),
            "Repaired type": geometry.geom_type,
            "Non-polygon remnants omitted": non_polygon_parts,
            "geometry": original, "CRS": frame.crs,
        }
        repairs.append(diagnostic)
        print(f"WARNING: {name}, source row {index + 1}: in-memory repair "
              f"({diagnostic['Reason']}); {non_polygon_parts} non-polygon remnants omitted")
    return frame


def write_geometry_issues(repairs, version):
    path = Path("working") / version / "A07" / "invalid-polygons.shp"
    if not repairs:
        for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix"):
            path.with_suffix(suffix).unlink(missing_ok=True)
        print("Geometry checks: no invalid polygons; any previous diagnostic layer removed.")
        return
    rows = []
    for repair in repairs:
        geometry = gpd.GeoSeries(
            [repair["geometry"]], crs=repair["CRS"]
        ).to_crs(epsg=4283).iloc[0]
        rows.append({
            "Input": repair["Input"], "Source_row": repair["Source row"],
            "Dataset": repair["Dataset"], "ReefFID": repair["ReefFID"],
            "Check_at": repair["Stage"], "Reason": repair["Reason"],
            "Fix_type": repair["Repaired type"],
            "Remnants": repair["Non-polygon remnants omitted"], "geometry": geometry,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(rows, geometry="geometry", crs=4283).to_file(path, index=False)
    source_count = sum(repair["Stage"] == "Source CRS" for repair in repairs)
    print(f"WARNING: {source_count:,} source polygons invalid on read; "
          f"{len(repairs) - source_count:,} additional issues after projection.")
    print(f"Invalid polygon locations: {path.resolve()}")
    print("Load this layer in QGIS. Check_at distinguishes stored Source CRS failures "
          "from EPSG:3577 analysis issues. Source_row is 1-based file read order. "
          "Review stored failures before publication. Source shapefiles are unchanged.")


def validate_layer(frame, name, fields=(), points=False):
    missing = set(fields) - set(frame.columns)
    if missing:
        raise ValueError(f"{name}: missing fields {sorted(missing)}")
    if frame.crs is None:
        raise ValueError(f"{name}: missing CRS")
    allowed = ("Point",) if points else ("Polygon", "MultiPolygon")
    bad = (
        frame.geometry.isna() | frame.geometry.is_empty
        | ~frame.geometry.is_valid | ~frame.geom_type.isin(allowed)
    )
    if bad.any():
        rows = (frame.index[bad] + 1).tolist()
        raise ValueError(f"{name}: invalid, empty or wrong-type geometry at rows {rows}")
    for field in fields:
        if field not in ("ReefID", "PrevReefID") and not present(frame[field]).all():
            raise ValueError(f"{name}: missing or blank {field} values")


class SpatialAllocation:
    def __init__(self, regions, inshore):
        if not {"GBR", "Torres Strait"}.issubset(set(regions.subregion)):
            raise ValueError("Analysis regions: require GBR and Torres Strait subregion labels")
        if inshore.empty:
            raise ValueError("Inshore extent: no polygons")
        self.regions = (
            regions[["subregion", "geometry"]].to_crs(epsg=3577)
            .dissolve(by="subregion").sort_index()
        )
        self.inshore = unary_union(inshore.to_crs(epsg=3577).geometry)

    def assign(self, frame):
        projected = frame.to_crs(epsg=3577)
        locations = []
        for geometry in projected.geometry:
            positions = sorted(self.regions.sindex.query(geometry, predicate="intersects"))
            candidates = self.regions.iloc[positions]
            region = None
            if geometry.geom_type == "Point":
                if not candidates.empty:
                    region = candidates.index[0]
            elif not candidates.empty:
                areas = candidates.geometry.intersection(geometry).area
                if len(candidates) == 1:
                    covered_area = areas.iloc[0]
                else:
                    covered_area = geometry.intersection(
                        unary_union(candidates.geometry)
                    ).area
                remainder = max(0.0, geometry.area - covered_area)
                largest = areas.max()
                if largest > 0 and largest >= remainder:
                    region = areas.idxmax()
            if region == "GBR":
                inside = (
                    self.inshore.covers(geometry) if geometry.geom_type == "Point"
                    else geometry.intersection(self.inshore).area >= geometry.area / 2
                )
                locations.append(LOCATIONS[0] if inside else LOCATIONS[1])
            elif region == "Torres Strait":
                locations.append(LOCATIONS[2])
            else:
                locations.append(None)
        return pd.Series(locations, index=frame.index, dtype="object")


def removed_targets(controls, legacy):
    targets = set()
    for index, point in controls.loc[controls.ACTION.eq("Remove")].geometry.items():
        hits = legacy.sindex.query(point, predicate="intersects")
        if len(hits) == 0 and pd.notna(controls.at[index, "Location"]):
            raise ValueError(f"Control points: Remove point at source row {index + 1} "
                             "has no legacy target")
        targets.update(int(position) for position in hits)
    return legacy.iloc[sorted(targets)].copy()


def summarise(frame, metrics):
    return pd.DataFrame([
        {"Location": label, **{
            name: int((frame.Location.isin(locations) & mask).sum())
            for name, mask in metrics.items()
        }}
        for label, locations in REPORT_GROUPS
    ])


def retained_percentage(retained, total):
    return retained.div(total.where(total.ne(0))) * 100


def analyse(final, edits, controls, legacy, regions, inshore, version):
    requirements = (
        (final, "Final features", ("Dataset", "ReefID", "PrevReefID", "RB_Type_L2"), False),
        (edits, "Reef Edit", (), False),
        (controls, "Control points", ("ACTION",), True),
        (legacy, "Legacy reference", (), False),
        (regions, "Analysis regions", ("subregion",), False),
        (inshore, "Inshore extent", (), False),
    )
    prepared = {}
    repairs = []
    for frame, name, fields, points in requirements:
        if not points:
            frame = repair_polygon_layer(frame, name, repairs, "Source CRS")
        validate_layer(frame, name, fields, points)
        prepared[name] = frame
    final, edits, controls, legacy, regions, inshore = (
        prepared[name] for name in (
            "Final features", "Reef Edit", "Control points", "Legacy reference",
            "Analysis regions", "Inshore extent",
        )
    )
    unsupported = set(controls.ACTION) - {"Move", "Remove", "Link"}
    if unsupported:
        raise ValueError(f"Control points: unsupported ACTION values {sorted(unsupported)}")

    allocation = SpatialAllocation(regions, inshore)
    layers = {}
    for name, frame in (("Final features", final), ("Reef Edit", edits),
                        ("Control points", controls), ("Legacy reference", legacy)):
        layers[name] = frame.to_crs(epsg=3577).reset_index(drop=True)
        if name != "Control points":
            layers[name] = repair_polygon_layer(layers[name], name, repairs, "EPSG:3577")
        layers[name]["Location"] = allocation.assign(layers[name])
    final, edits, controls, legacy = (layers[name] for name in (
        "Final features", "Reef Edit", "Control points", "Legacy reference"
    ))
    removed = removed_targets(controls, legacy)
    editing = final.Dataset.eq(f"Aus-Trop-Reef-Features_{version}")
    reef_id, previous_id = present(final.ReefID), present(final.PrevReefID)
    updated = editing & (reef_id | previous_id)
    new = editing & ~(reef_id | previous_id)
    reef = final.RB_Type_L2.isin(("Coral Reef", "Rocky Reef"))
    all_final = pd.Series(True, index=final.index)
    source = summarise(edits, {"Original Reef Edit polygons": pd.Series(True, index=edits.index)})
    table1 = summarise(final, {
        "Final editing features": editing, "Updated": updated,
        "Newly mapped": new, "Retained source features": ~editing,
        "Total final features": all_final,
    })
    table1.insert(1, "Original Reef Edit polygons", source["Original Reef Edit polygons"])
    table1.insert(3, "Difference (final - source)",
                  table1["Final editing features"] - table1["Original Reef Edit polygons"])
    table1["Retained source (%)"] = retained_percentage(
        table1["Retained source features"], table1["Total final features"]
    )
    table2 = summarise(final, {
        "ReefID only": editing & reef_id & ~previous_id,
        "PrevReefID only": editing & ~reef_id & previous_id,
        "Both identifiers": editing & reef_id & previous_id,
        "Updated coral/rocky reef features": updated & reef,
        "Newly mapped coral/rocky reef features": new & reef,
        "Retained coral/rocky reef features": ~editing & reef,
        "Total coral/rocky reef features": reef,
    })
    table2["Retained coral/rocky reef (%)"] = retained_percentage(
        table2["Retained coral/rocky reef features"], table2["Total coral/rocky reef features"]
    )
    table3 = summarise(controls, {
        "Remove points": controls.ACTION.eq("Remove"),
        "Move points": controls.ACTION.eq("Move"),
        "Link points": controls.ACTION.eq("Link"),
    })
    removals = summarise(removed, {
        "Distinct removed legacy features": pd.Series(True, index=removed.index),
    })
    table3.insert(2, "Distinct removed legacy features",
                  removals["Distinct removed legacy features"])
    validate_totals(table1, table2, table3)
    exclusions = {
        name: int(frame.Location.isna().sum()) for name, frame in layers.items()
    }
    return (table1, table2, table3), exclusions, repairs


def validate_totals(table1, table2, table3):
    checks = (
        table1.Updated + table1["Newly mapped"] == table1["Final editing features"],
        table1["Final editing features"] + table1["Retained source features"]
        == table1["Total final features"],
        table2[["ReefID only", "PrevReefID only", "Both identifiers"]].sum(axis=1)
        == table1.Updated,
        table2["Updated coral/rocky reef features"] <= table1.Updated,
        table2["Newly mapped coral/rocky reef features"] <= table1["Newly mapped"],
        table2["Updated coral/rocky reef features"]
        + table2["Newly mapped coral/rocky reef features"]
        + table2["Retained coral/rocky reef features"]
        == table2["Total coral/rocky reef features"],
    )
    if not all(check.all() for check in checks):
        raise ValueError("Feature status or lineage totals do not reconcile")
    for table in (table1, table2, table3):
        numbers = table.drop(columns=[
            column for column in table if column == "Location" or column.endswith("(%)")
        ])
        if not (
            numbers.iloc[:3].sum().eq(numbers.iloc[4]).all()
            and numbers.iloc[1:3].sum().eq(numbers.iloc[3]).all()
        ):
            raise ValueError("Regional totals do not reconcile")
    for table, retained, total, percentage in (
        (table1, "Retained source features", "Total final features", "Retained source (%)"),
        (table2, "Retained coral/rocky reef features", "Total coral/rocky reef features",
         "Retained coral/rocky reef (%)"),
    ):
        expected = retained_percentage(table[retained], table[total])
        if not (table[percentage].eq(expected)
                | (table[percentage].isna() & expected.isna())).all():
            raise ValueError("Retained legacy percentages do not reconcile")


def counted(count, singular, plural=None):
    return f"{count:,} {singular if count == 1 else plural or singular + 's'}"


def results_paragraph(table1, table3):
    total, inshore = table1.iloc[4], table1.iloc[0]
    if total["Final editing features"] == 0:
        sentences = ["No processed editing features were present in the GBR and Torres Strait."]
    else:
        sentences = [
            "Mapping revisions in the GBR and Torres Strait updated "
            f"{counted(total.Updated, 'previously mapped feature')} and added "
            f"{counted(total['Newly mapped'], 'feature')} to the mapping.",
            "The inshore GBR contained "
            f"{counted(inshore.Updated, 'revised feature')} and "
            f"{counted(inshore['Newly mapped'], 'addition')}.",
        ]
    for position, description in (
        (0, "In the inshore GBR"), (1, "Outside the inshore GBR"), (2, "In Torres Strait"),
    ):
        row = table1.iloc[position]
        if row["Total final features"]:
            sentences.append(
                f"{description}, {counted(row['Retained source features'], 'feature')} "
                f"({row['Retained source (%)']:.1f}% of mapped features) "
                "remained based on legacy mapping without manual revision."
            )
    control = table3.iloc[4]
    sentences.append("The revisions also explicitly excluded "
                     f"{counted(control['Distinct removed legacy features'], 'legacy feature')}.")
    if control["Move points"]:
        sentences.append(
            f"In {counted(control['Move points'], 'recorded positional correction')}, "
            "the old reef outlines did not overlap the revised outlines, indicating "
            "substantial positional errors in the old mapping."
        )
    return " ".join(sentences)


def markdown_table(table):
    columns = list(table.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| --- | " + " | ".join("---:" for _ in columns[1:]) + " |",
    ]
    for row in table.itertuples(index=False, name=None):
        values = [
            ("Not applicable" if pd.isna(value) else f"{value:.1f}")
            if column.endswith("(%)") else f"{value:,}"
            for column, value in zip(columns[1:], row[1:])
        ]
        lines.append("| " + str(row[0]) + " | "
                     + " | ".join(values) + " |")
    return "\n".join(lines)


def main():
    config = configparser.ConfigParser()
    if not config.read("config.ini"):
        raise FileNotFoundError("Missing config.ini; run from the repository root")
    version, paths = input_paths(config)
    frames = {}
    for name, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing {name}: {path}")
        print(f"Reading {name}: {path}")
        frames[name] = gpd.read_file(path)
    try:
        tables, exclusions, repairs = analyse(
            frames["Final features"], frames["Reef Edit"], frames["Control points"],
            frames["Legacy reference"], frames["Analysis regions"],
            frames["Inshore extent"], version,
        )
    except ValueError as error:
        raise ValueError(f"{error}. Input paths: {paths}") from error
    report = [
        f"# GBR and Torres Strait remapping statistics: {version}",
        f"Analysis script: `{SCRIPT_NAME}`. Generated: {datetime.now().astimezone().isoformat()}.",
        "## Results paragraph",
        results_paragraph(tables[0], tables[2]),
        "## Tables",
    ]
    captions = (
        "Source polygons and processed feature records. Difference is final minus source. "
        "Updated means editing provenance with ReefID or PrevReefID; newly mapped means "
        "neither identifier is recorded. Retained source (%) is retained legacy records "
        "divided by all final records, including additions.",
        "Final feature lineage and reef-only counts. Coral/rocky reef subtotals use "
        "RB_Type_L2. Retained coral/rocky reef (%) uses all final coral/rocky reef records "
        "as its denominator; all other counts include non-reef classes.",
        "Explicit control instructions and distinct legacy source records targeted by Remove "
        "points. Point counts are not counts of unique affected reefs. Move and replacement "
        "targets are not explicit removals.",
    )
    for number, (table, caption) in enumerate(zip(tables, captions), start=1):
        report.extend([
            f"Table {number}. {caption} Data: {version}. Analysis script: {SCRIPT_NAME}.",
            markdown_table(table),
        ])
    report.extend([
        "## Methods and interpretation",
        "Analysis-Regions subregion labels GBR and Torres Strait define the reporting scope. "
        "Polygons are assigned by largest intersection area in EPSG:3577, including the "
        "unassigned remainder; points use boundary-inclusive coverage. Within GBR, at least "
        "50% of polygon area inside the remapping extent defines inshore. Exact ties use "
        "alphabetical region order, with named regions preferred over unassigned. "
        "Combined rows are subtotals, not additional records.",
        f"Editing provenance is Dataset = Aus-Trop-Reef-Features_{version}. "
        "Retained source mapping is not counted as a manual update. Counts are records, "
        "not named reefs or individual identifiers. No geometries are dissolved or exploded.",
        "Newly mapped features are additions to the recorded mapping, not physical reef "
        "formation or independently verified discoveries. The lineage threshold in stage "
        "02a is at least 10% of either polygon's area after its sliver test, with explicit "
        "overrides. Replacement can occur below that threshold. No recorded predecessor "
        "therefore does not prove that no old polygon overlapped. The legacy reference "
        "includes refreshed GBR Features and existing TS Features.",
        "Remove points are intersected with the legacy reference; targeted source rows "
        "are counted once and allocated by their own geometry. Point locations and target "
        "locations can yield different regional counts. Move instructions indicate no "
        "overlap between old and corrected reef outlines, not physical movement. They "
        "are not an independent positional-accuracy assessment. Controls are not added "
        "to editing-feature counts.",
        "Reef Edit and final editing counts are allocated independently. Coastline clipping "
        "can split or discard source polygons and alter regional assignment. These counts "
        "need not match; the difference is not a measure of reef discovery or loss.",
        "Retained legacy percentages describe the share of current mapping without manual "
        "revision, not the proportion of original polygons left unchanged or a measured "
        "error rate. Revised features can result from splits or merges. Percentages include "
        "newly mapped features in the denominator and are recalculated for combined regions, "
        "not summed. Regions with no final features are marked Not applicable. Retained "
        "mapping may still require reassessment; retention alone does not establish an error.",
        "## Provenance and validation",
        "Inputs must represent the same processing build. Version labels alone cannot "
        "establish that the final output incorporates the latest editing inputs.",
    ])
    for name, path in paths.items():
        frame = frames[name]
        report.append(f"{name}: {provenance_path(path)}. "
                      f"Source records: {len(frame):,}. CRS: {frame.crs}.")
    for name, count in exclusions.items():
        report.append(f"{name}: {count:,} records excluded from GBR + Torres Strait.")
    report.append(
        "Checks passed: updated + newly mapped = final editing features; editing + retained "
        "= total final features; lineage subdivisions = updated; regional rows reconcile "
        "with subtotals and totals; reef-only counts do not exceed all-class counts. "
        "All in-scope Remove points intersect the legacy reference."
    )
    write_geometry_issues(repairs, version)
    output_dir = Path("data") / version / "out" / "stats"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"A07-gbr-ts-remap-stats_{version}.md"
    output.write_text("\n\n".join(report) + "\n", encoding="utf-8")
    print(f"Saved report: {output}")


if __name__ == "__main__":
    main()
