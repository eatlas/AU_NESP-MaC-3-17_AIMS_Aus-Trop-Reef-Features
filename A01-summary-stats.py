"""Summarise mapped feature counts and areas for the national reef mapping report.

The analysis produces source feature counts and summed Area_km2 values by L3
and L2 classification. It also cleans geometries with buffer(0), dissolves
features within each L2 class and splits multipart geometries into singlepart
polygons. Counts and areas are then summarised for these polygons, with areas
recalculated in GDA94 / Australian Albers (EPSG:3577), an equal-area projection.
Dissolved counts represent polygons, not named reefs.

Run from the repository root after 06-crosswalk.py. The dataset version comes
from config.ini. Input is the full-classification shapefile in
data/{version}/out/full-classes/. Outputs are saved to data/{version}/out/stats/:
a Markdown report with captioned tables and data provenance, an unrounded CSV
for each table, and the dissolved L2 shapefile in the input CRS. These outputs
support checking the figures used in the technical report.
"""

import configparser
from pathlib import Path

import geopandas as gpd


SCRIPT_NAME = Path(__file__).name


def summarise_features(gdf, classification):
    return (
        gdf.groupby(classification)
        .agg(
            Feature_Count=(classification, "count"),
            Total_Area_km2=("Area_km2", "sum"),
        )
        .reset_index()
        .sort_values("Total_Area_km2", ascending=False)
    )


def markdown_table(summary):
    """Render the summary without requiring the optional tabulate package."""
    lines = [
        f"| {summary.columns[0]} | Feature_Count | Total_Area_km2 |",
        "| --- | ---: | ---: |",
    ]
    for classification, count, area in summary.itertuples(index=False, name=None):
        label = str(classification).replace("|", r"\|").replace("\n", " ")
        lines.append(f"| {label} | {count} | {area:.1f} |")
    return "\n".join(lines)


def main():
    config = configparser.ConfigParser()
    config.read("config.ini")
    version = config.get("general", "version")
    output_dir = Path("data") / version / "out" / "stats"
    input_shp = (
        Path("data") / version / "out" / "full-classes"
        / f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp"
    )
    output_shp = output_dir / f"Aus-Trop-Reef-Features_{version}_RB-Type-L2.shp"
    report_path = output_dir / f"A01-summary-stats_{version}.md"

    print(f"Reading shapefile: {input_shp}")
    gdf = gpd.read_file(input_shp)
    summaries = [
        (
            "Source feature count and summed source Area_km2 by L3 classification "
            "(RB_Type_L3), before dissolving. Counts refer to input feature records.",
            summarise_features(gdf, "RB_Type_L3"),
        ),
        (
            "Source feature count and summed source Area_km2 by L2 classification "
            "(RB_Type_L2), before dissolving. Counts refer to input feature records.",
            summarise_features(gdf, "RB_Type_L2"),
        ),
    ]

    print("Cleaning geometry and dissolving features by RB_Type_L2.")
    gdf["geometry"] = gdf["geometry"].buffer(0)
    dissolved = gdf.dissolve(by="RB_Type_L2", as_index=False)[["RB_Type_L2", "geometry"]]
    singleparts = dissolved.explode(index_parts=False).reset_index(drop=True)
    singleparts_proj = singleparts.to_crs(epsg=3577)
    singleparts["Area_km2"] = singleparts_proj.geometry.area / 1e6
    summaries.append(
        (
            "Singlepart polygon count and total area by L2 classification "
            "(RB_Type_L2), after buffer(0) geometry cleaning, dissolving within "
            "each class and exploding multipart geometries. Counts refer to "
            "resulting polygons, not source records or named reefs. Areas are "
            "recalculated in GDA94 / Australian Albers (EPSG:3577), an equal-area "
            "projection. Overlaps within each class are counted once; "
            "overlaps between classes are not removed.",
            summarise_features(singleparts, "RB_Type_L2"),
        )
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    singleparts.to_file(output_shp)
    report = [
        f"# National reef mapping summary statistics: {version}",
        "This analysis summarises mapped feature counts and areas by L3 and L2 "
        "classification for checking figures in the national reef mapping technical "
        "report. It compares source record counts and summed source areas with L2 "
        "polygon counts and recalculated areas after geometry cleaning and dissolving. "
        "Dissolving merges touching or overlapping features within each class, so "
        "the resulting singlepart polygon counts are not counts of named reefs. "
        "Results are provided as captioned tables, CSV files and a dissolved L2 shapefile.",
        f"Analysis script: `{SCRIPT_NAME}`. Data: {version}.",
        f"Input shapefile: `{input_shp.as_posix()}`. Input feature records: {len(gdf)}.",
        "Tables are sorted by descending total area. Areas are in square kilometres "
        "and displayed to one decimal place. CSV files retain unrounded values. "
        "Records with missing classification values are excluded from the corresponding "
        "summary. Source area sums do not remove overlaps.",
        "Area calculations use GDA94 / Australian Albers (EPSG:3577), an equal-area "
        "projection. Source Area_km2 values are calculated by 06-crosswalk.py and "
        "rounded to four decimal places per feature. Rerun that script before this "
        "analysis if the source dataset was generated using EPSG:3112, which is "
        "conformal rather than equal-area.",
        f"Dissolved L2 polygons: [{output_shp.name}]({output_shp.name}). "
        "The shapefile retains the input CRS.",
    ]
    for number, (description, summary) in enumerate(summaries, start=1):
        csv_path = output_dir / f"A01-summary-stats_{version}_table-{number}.csv"
        summary.to_csv(csv_path, index=False)
        report.extend([
            f"Table {number}. {description} Data: {version}. Analysis script: {SCRIPT_NAME}.",
            markdown_table(summary),
            f"CSV: [{csv_path.name}]({csv_path.name}).",
        ])
    report_path.write_text("\n\n".join(report) + "\n", encoding="utf-8")
    print(f"Saved Markdown report and {len(summaries)} CSV tables to {output_dir}")
    print(f"Report: {report_path}")
    print(f"Dissolved polygons: {output_shp}")


if __name__ == "__main__":
    main()