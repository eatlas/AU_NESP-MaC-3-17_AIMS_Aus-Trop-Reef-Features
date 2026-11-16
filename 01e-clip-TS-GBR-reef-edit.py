"""
Stage 01e: clip TS and GBR Reef Edit features to the coastline.

Removes land overhangs from the manually digitised Reef Edit polygons before
02a-patch-TS-GBR-Features.py assigns identifiers, so that disconnected marine
parts enter stage 02a as separate records. See
01e-clip-TS-GBR-reef-edit-spec.md for the full rationale.

Inputs:
  {in_path}/Reef-edit/AIMS_GBR-TS-Features_Edit_{version}.shp
  {in_path}/Land-exclusion/Land-exclusion-piers.shp (required)
  {in_3p_path}/Coastline50k/Split/AU_NESP-MaC-3-17_AIMS_Aus-Coastline-50k_2024_V1-1_split.shp

Outputs (EPSG:4283):
  working/{version}/01/Reef-Edit-clipped.shp             clipped input for stage 02a
  working/{version}/01/reef-edit-land-split-parents.shp  original parents of splits (QA)
  working/{version}/01/reef-edit-land-splits.shp         surviving parts of splits (QA)
  working/{version}/01/reef-edit-land-removed.shp        features with no marine remainder (QA)

Splits produce a WARNING. Multipart sources, complete removals, invalid
geometry and failed geometry operations stop with a nonzero exit status.

Run from the repository root in the AusTropReef environment.
"""

import configparser
import os
import sys
import time

import geopandas as gpd
import pandas as pd

from reef_utils import (CLIP_CRS, LOCKED_FILE_MESSAGE, MIN_PART_AREA_M2,
                        ClipError, OutputLockedError, area_m2,
                        check_polygon_geometries, clip_polygon,
                        prepare_coastline, remove_shapefile, single_polygon,
                        write_shapefile)

REQUIRED_FIELDS = ['CODE', 'EdgeSrc', 'FeatConf', 'EdgeAcc_m', 'DepthCat',
                   'DepthCatSr', 'RB_Type_L3', 'Attachment', 'TypeConf', 'Note']
CAY_CLASSES = {'Vegetated Cay', 'Unvegetated Cay'}

config = configparser.ConfigParser()
config.read('config.ini')
VERSION = config.get('general', 'version')

OUT_DIR = os.path.join('working', VERSION, '01')
OUT_PATH = os.path.join(OUT_DIR, 'Reef-Edit-clipped.shp')
PARENTS_PATH = os.path.join(OUT_DIR, 'reef-edit-land-split-parents.shp')
SPLITS_PATH = os.path.join(OUT_DIR, 'reef-edit-land-splits.shp')
REMOVED_PATH = os.path.join(OUT_DIR, 'reef-edit-land-removed.shp')


def fail(message):
    print(f"\nERROR: {message}")
    sys.exit(1)


def format_rows(rows):
    return ', '.join(str(r) for r in rows)


def main():
    start = time.time()
    in_path = config.get('general', 'in_path')
    in_3p_path = config.get('general', 'in_3p_path')
    version = config.get('general', 'version')

    reef_edit_path = os.path.join(in_path, 'Reef-edit',
                                  f'AIMS_GBR-TS-Features_Edit_{version}.shp')
    exclusion_path = os.path.join(in_path, 'Land-exclusion', 'Land-exclusion-piers.shp')
    coastline_path = os.path.join(
        in_3p_path, 'Coastline50k', 'Split',
        'AU_NESP-MaC-3-17_AIMS_Aus-Coastline-50k_2024_V1-1_split.shp')

    for path in (reef_edit_path, coastline_path):
        if not os.path.exists(path):
            fail(f"Input not found: {path}")

    os.makedirs(OUT_DIR, exist_ok=True)
    print("Removing previous outputs of this stage")
    for path in (OUT_PATH, PARENTS_PATH, SPLITS_PATH, REMOVED_PATH):
        remove_shapefile(path)

    # ------------------------------------------------------------------
    print(f"Reading Reef Edit from {reef_edit_path}")
    src = gpd.read_file(reef_edit_path, engine='pyogrio', fid_as_index=True)
    source_fids = src.index.to_numpy()
    print(f"  {len(src)} records")
    if src.crs is None:
        fail(f"{reef_edit_path} has no defined CRS. Define it in QGIS and rerun.")
    missing = [f for f in REQUIRED_FIELDS if f not in src.columns]
    if missing:
        fail(f"Reef Edit is missing required fields: {missing}")
    src = src.reset_index(drop=True)
    src['RE_row'] = range(1, len(src) + 1)
    attr_cols = [c for c in src.columns if c not in ('geometry', 'RE_row')]

    problems = check_polygon_geometries(src.geometry.values)
    if problems:
        print(f"\nERROR: {len(problems)} invalid, null or non-polygon Reef Edit records:")
        for i, problem in problems:
            print(f"  RE_row {i + 1} (CODE={src.at[i, 'CODE']}): {problem}")
        fail(f"Correct these records in {reef_edit_path} and rerun stages 01e, 02a and 02d. "
             "No automatic repair is applied.")

    multipart = [i + 1 for i, g in enumerate(src.geometry.values) if single_polygon(g) is None]
    if multipart:
        qgis_ids = format_rows(source_fids[re_row - 1] for re_row in multipart)
        fail(f"{len(multipart)} Reef Edit records have two or more polygon components "
             f"(RE_row {format_rows(multipart)}).\n"
             "  On the source Reef Edit layer in QGIS, use "
             "'Select features using an expression':\n"
             f"  $id IN ({qgis_ids})\n"
             "  Attribute-table sorting does not affect this selection.\n"
             f"  Separate them in QGIS into individually attributed records in "
             f"{reef_edit_path}, then rerun stages 01e, 02a and 02d.")
    src['geometry'] = [single_polygon(g) for g in src.geometry.values]

    # ------------------------------------------------------------------
    print(f"Transforming Reef Edit to {CLIP_CRS} and validating")
    src = src.to_crs(CLIP_CRS)
    problems = check_polygon_geometries(src.geometry.values)
    if problems:
        print(f"\nERROR: {len(problems)} Reef Edit records are invalid after "
              f"transformation to {CLIP_CRS}:")
        for i, problem in problems:
            print(f"  RE_row {i + 1}: {problem}")
        fail(f"Correct these records in {reef_edit_path} and rerun.")
    print(f"  {len(src)} records valid")

    print(f"Reading coastline from {coastline_path}, transforming to {CLIP_CRS}, "
          f"validating, subtracting pier exclusions from {exclusion_path} "
          "and building spatial index")
    try:
        coastline = prepare_coastline(coastline_path, exclusion_path)
    except ClipError as exc:
        fail(f"Coastline preparation failed at step '{exc.step}': {exc.detail}")
    print(f"  {len(coastline.geoms)} coastline polygons indexed")
    print(f"  {coastline.n_exclusions} pier exclusion polygons applied; "
          f"{coastline.n_land_changed} coastline records changed")

    # ------------------------------------------------------------------
    print("Clipping Reef Edit features to the coastline")
    out_records = []
    split_parents = []
    split_parts = []
    removed = []
    n_fragments = 0
    n_trimmed = 0
    n_cays = 0
    for i, row in src.iterrows():
        geom = row.geometry
        attrs = {c: row[c] for c in attr_cols}
        re_row = int(row['RE_row'])
        if row['RB_Type_L3'] in CAY_CLASSES:
            n_cays += 1
            out_records.append({**attrs, 'RE_row': re_row, 'RE_part': 1, 'geometry': geom})
            continue
        try:
            parts, n_removed, changed = clip_polygon(geom, coastline, MIN_PART_AREA_M2)
        except ClipError as exc:
            fail(f"Geometry operation failed for RE_row {re_row} (CODE={row['CODE']}) "
                 f"at step '{exc.step}' against coastline {coastline.path}: {exc.detail}\n"
                 "  No automatic repair is applied. Inspect the source record and the "
                 "local coastline in QGIS.")
        n_fragments += n_removed
        if changed and len(parts) == 1:
            n_trimmed += 1
        if not parts:
            removed.append({**attrs, 'RE_row': re_row, 'RE_part': None, 'geometry': geom})
            continue
        for p, part in enumerate(parts, start=1):
            out_records.append({**attrs, 'RE_row': re_row, 'RE_part': p, 'geometry': part})
        if len(parts) > 1:
            split_parents.append({**attrs, 'RE_row': re_row, 'RE_part': None, 'geometry': geom})
            areas = [area_m2(part) for part in parts]
            total = sum(areas)
            for p, (part, a) in enumerate(zip(parts, areas), start=1):
                split_parts.append({**attrs, 'RE_row': re_row, 'RE_part': p,
                                    'after_n': len(parts), 'area_m2': round(a, 1),
                                    'share': round(a / total, 4), 'geometry': part})

    print(f"  {len(src)} source records: {n_cays} exempt cays, {n_trimmed} trimmed, "
          f"{len(split_parents)} split into {len(split_parts)} parts, "
          f"{len(removed)} with no marine remainder")
    print(f"  {n_fragments} clipping fragments below {MIN_PART_AREA_M2:g} m² removed")

    def frame(records, extra=()):
        cols = attr_cols + ['RE_row', 'RE_part'] + list(extra) + ['geometry']
        gdf = gpd.GeoDataFrame(pd.DataFrame(records, columns=cols),
                               geometry='geometry', crs=CLIP_CRS)
        for c in attr_cols:
            gdf[c] = gdf[c].astype(src[c].dtype)
        gdf['RE_row'] = gdf['RE_row'].astype('int64')
        gdf['RE_part'] = gdf['RE_part'].astype('Int64')
        return gdf

    if split_parents:
        print(f"Writing {len(split_parents)} split parents to {PARENTS_PATH}")
        write_shapefile(frame(split_parents), PARENTS_PATH)
        print(f"Writing {len(split_parts)} split parts to {SPLITS_PATH}")
        write_shapefile(frame(split_parts, ('after_n', 'area_m2', 'share')), SPLITS_PATH)
    if removed:
        print(f"Writing {len(removed)} removed features to {REMOVED_PATH}")
        write_shapefile(frame(removed), REMOVED_PATH)

    split_rows = [r['RE_row'] for r in split_parents]
    if split_rows:
        print("\n" + "!" * 78)
        print(f"WARNING: {len(split_rows)} Reef Edit features were split by the coastline "
              f"into {len(split_parts)} parts.")
        print(f"  RE_row: {format_rows(split_rows)}")
        print(f"  Load in QGIS with the coastline: {PARENTS_PATH}")
        print(f"                                   {SPLITS_PATH}")
        print("  Check the geometry and per-feature attributes of each part. Copied values,")
        print("  in particular EdgeAcc_m and Attachment, were assessed for the original")
        print("  feature and may not suit each part. If the split is unintended, correct the")
        print("  source geometry; if the parts are genuinely separate features, map them as")
        print(f"  separate records in {reef_edit_path}. Do not edit the generated outputs.")
        print("  Rerun stages 01e, 02a and 02d after source changes.")
        print("!" * 78)

    if removed:
        rows = [r['RE_row'] for r in removed]
        fail(f"{len(rows)} Reef Edit features have no marine part of at least "
             f"{MIN_PART_AREA_M2:g} m² after land subtraction (land-only or below "
             f"mapping resolution).\n"
             f"  RE_row: {format_rows(rows)}\n"
             f"  Load {REMOVED_PATH} in QGIS with the coastline.\n"
             f"  Correct or delete these records in {reef_edit_path} (do not alter the "
             "coastline), then rerun stages 01e, 02a and 02d.")

    out = frame(out_records)
    problems = check_polygon_geometries(out.geometry.values)
    bad_type = [i for i, g in enumerate(out.geometry.values) if g.geom_type != 'Polygon']
    if problems or bad_type:
        fail(f"Final output validation failed: {problems[:10]} non-singlepart={bad_type[:10]}")
    print(f"Writing {len(out)} clipped features to {OUT_PATH}")
    write_shapefile(out, OUT_PATH)
    print(f"\nDone in {time.time() - start:.1f} s.")


if __name__ == '__main__':
    try:
        main()
    except OutputLockedError as exc:
        print(f"\nERROR: Cannot delete or write {exc.path}\n  {LOCKED_FILE_MESSAGE}\n"
              f"  ({exc.detail})")
        sys.exit(1)
