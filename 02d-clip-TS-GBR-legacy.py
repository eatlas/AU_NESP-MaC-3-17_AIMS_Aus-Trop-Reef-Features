"""
Stage 02d: clip retained TS and GBR legacy features to the coastline.

Runs after 02a-patch-TS-GBR-Features.py. Legacy records that survived
replacement are clipped to the coastline. A trim that leaves one polygon keeps
its identifiers unchanged. Any split, complete removal, multipart record,
invalid geometry or failed geometry operation blocks publication: correct the
feature through Reef Edit (replacement or Remove point) and rerun stages 01e,
02a and 02d. Edited (Reef Edit) records were clipped in stage 01e and pass
through unchanged. See 02d-clip-TS-GBR-legacy-spec.md.

Inputs:
  working/{version}/02/TS-GBR-Features-patched.shp (EPSG:4283)
  {in_path}/Land-exclusion/Land-exclusion-piers.shp (required)
  {in_3p_path}/Coastline50k/Split/AU_NESP-MaC-3-17_AIMS_Aus-Coastline-50k_2024_V1-1_split.shp

Outputs (EPSG:4283):
  working/{version}/02/TS-GBR-Features-clipped.shp       accepted input for stage 03
  working/{version}/02/legacy-land-split-parents.shp     original parents of splits (QA)
  working/{version}/02/legacy-land-splits.shp            clipped parts of splits (QA)
  working/{version}/02/legacy-land-removed.shp           features with no marine remainder (QA)

Run from the repository root in the AusTropReef environment.
"""

import configparser
import os
import sys
import time

import geopandas as gpd
import pandas as pd
from pyproj import CRS

from reef_utils import (CLIP_CRS, LOCKED_FILE_MESSAGE, MIN_PART_AREA_M2,
                        ClipError, OutputLockedError, area_m2,
                        check_polygon_geometries, clip_polygon,
                        prepare_coastline, remove_shapefile, single_polygon,
                        write_shapefile)

REQUIRED_FIELDS = ['Dataset', 'RB_Type_L3', 'ReefID', 'ReefFID', 'PrevReefID',
                   'CODES', 'Attachment', 'EdgeAcc_m', 'RE_row', 'RE_part']
LEGACY_SOURCES = {'GBR Features', 'TS Features'}
CAY_CLASSES = {'Vegetated Cay', 'Unvegetated Cay'}

config = configparser.ConfigParser()
config.read('config.ini')
VERSION = config.get('general', 'version')

OUT_DIR = os.path.join('working', VERSION, '02')
IN_PATH = os.path.join(OUT_DIR, 'TS-GBR-Features-patched.shp')
OUT_PATH = os.path.join(OUT_DIR, 'TS-GBR-Features-clipped.shp')
PARENTS_PATH = os.path.join(OUT_DIR, 'legacy-land-split-parents.shp')
SPLITS_PATH = os.path.join(OUT_DIR, 'legacy-land-splits.shp')
REMOVED_PATH = os.path.join(OUT_DIR, 'legacy-land-removed.shp')

RERUN = "rerun stages 01e, 02a and 02d"


def fail(message):
    print(f"\nERROR: {message}")
    sys.exit(1)


def describe(row, src_row):
    return f"src_row {src_row} (ReefFID={row['ReefFID']}, ReefID={row['ReefID']}, CODES={row['CODES']})"


def main():
    start = time.time()
    in_path = config.get('general', 'in_path')
    in_3p_path = config.get('general', 'in_3p_path')
    version = config.get('general', 'version')
    edit_source = f'Aus-Trop-Reef-Features_{version}'

    exclusion_path = os.path.join(in_path, 'Land-exclusion', 'Land-exclusion-piers.shp')
    coastline_path = os.path.join(
        in_3p_path, 'Coastline50k', 'Split',
        'AU_NESP-MaC-3-17_AIMS_Aus-Coastline-50k_2024_V1-1_split.shp')
    for path in (IN_PATH, coastline_path):
        if not os.path.exists(path):
            fail(f"Input not found: {path}")

    print("Removing previous outputs of this stage")
    for path in (OUT_PATH, PARENTS_PATH, SPLITS_PATH, REMOVED_PATH):
        remove_shapefile(path)

    # ------------------------------------------------------------------
    print(f"Reading stage 02a output from {IN_PATH}")
    src = gpd.read_file(IN_PATH).reset_index(drop=True)
    print(f"  {len(src)} records")
    if src.crs is None or not CRS(src.crs).equals(CRS(CLIP_CRS)):
        fail(f"{IN_PATH} must be in {CLIP_CRS} (found {src.crs}). Rerun stage 02a.")
    missing = [f for f in REQUIRED_FIELDS if f not in src.columns]
    if missing:
        fail(f"{IN_PATH} is missing required fields: {missing}. Rerun stages 01e and 02a.")
    src_rows = list(range(1, len(src) + 1))

    labels = src['Dataset']
    unexpected = sorted(set(labels.dropna().unique()) - LEGACY_SOURCES - {edit_source})
    n_missing = int(labels.isna().sum() + (labels.astype(str).str.strip() == '').sum())
    if unexpected or n_missing:
        fail(f"Unexpected Dataset labels {unexpected} and {n_missing} missing labels in "
             f"{IN_PATH}. Expected {sorted(LEGACY_SOURCES)} or '{edit_source}'.")
    is_legacy = labels.isin(LEGACY_SOURCES).values
    print(f"  {int(is_legacy.sum())} legacy records, {int((~is_legacy).sum())} edited records")

    problems = check_polygon_geometries(src.geometry.values)
    if problems:
        print(f"\nERROR: {len(problems)} invalid, null or non-polygon records:")
        for i, problem in problems:
            print(f"  {describe(src.iloc[i], i + 1)} [{src.at[i, 'Dataset']}]: {problem}")
        fail("No automatic repair is applied. Correct legacy features through a Reef Edit "
             f"replacement or Remove point, or correct the Reef Edit source, then {RERUN}.")

    multipart = [i for i, g in enumerate(src.geometry.values) if single_polygon(g) is None]
    if multipart:
        print(f"\nERROR: {len(multipart)} records have two or more polygon components:")
        for i in multipart:
            print(f"  {describe(src.iloc[i], i + 1)} [{src.at[i, 'Dataset']}]")
        fail("Correct multipart legacy features through a Reef Edit replacement or Remove "
             f"point, and multipart editing features in the Reef Edit source, then {RERUN}.")
    src['geometry'] = [single_polygon(g) for g in src.geometry.values]

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
    print("Clipping retained legacy features to the coastline")
    attr_cols = [c for c in src.columns if c != 'geometry']
    out_geoms = list(src.geometry.values)
    split_parents, split_parts, removed = [], [], []
    n_fragments = n_trimmed = n_cays = 0
    for i in range(len(src)):
        if not is_legacy[i]:
            continue
        row = src.iloc[i]
        geom = row.geometry
        if row['RB_Type_L3'] in CAY_CLASSES:
            n_cays += 1
            continue
        try:
            parts, n_removed, changed = clip_polygon(geom, coastline, MIN_PART_AREA_M2)
        except ClipError as exc:
            fail(f"Geometry operation failed for {describe(row, i + 1)} at step "
                 f"'{exc.step}' against coastline {coastline.path}: {exc.detail}\n"
                 "  No automatic repair is applied.")
        n_fragments += n_removed
        qa = {c: row[c] for c in attr_cols}
        qa.update(SOURCE=row['Dataset'], src_row=i + 1)
        if not parts:
            removed.append({**qa, 'part_n': None, 'geometry': geom})
        elif len(parts) == 1:
            if changed:
                n_trimmed += 1
            out_geoms[i] = parts[0]
        else:
            split_parents.append({**qa, 'part_n': None, 'geometry': geom})
            areas = [area_m2(p) for p in parts]
            total = sum(areas)
            for n, (part, a) in enumerate(zip(parts, areas), start=1):
                split_parts.append({**qa, 'after_n': len(parts), 'part_n': n,
                                    'area_m2': round(a, 1), 'share': round(a / total, 4),
                                    'geometry': part})

    print(f"  {int(is_legacy.sum())} legacy records: {n_cays} exempt cays, {n_trimmed} trimmed, "
          f"{len(split_parents)} split into {len(split_parts)} parts, "
          f"{len(removed)} with no marine remainder")
    print(f"  {n_fragments} clipping fragments below {MIN_PART_AREA_M2:g} m² removed")

    def frame(records, extra):
        cols = attr_cols + ['SOURCE', 'src_row'] + list(extra) + ['geometry']
        gdf = gpd.GeoDataFrame(pd.DataFrame(records, columns=cols),
                               geometry='geometry', crs=CLIP_CRS)
        for c in attr_cols:
            gdf[c] = gdf[c].astype(src[c].dtype)
        gdf['part_n'] = gdf['part_n'].astype('Int64')
        return gdf

    if split_parents:
        print(f"Writing {len(split_parents)} split parents to {PARENTS_PATH}")
        write_shapefile(frame(split_parents, ['part_n']), PARENTS_PATH)
        print(f"Writing {len(split_parts)} split parts to {SPLITS_PATH}")
        write_shapefile(frame(split_parts, ['after_n', 'part_n', 'area_m2', 'share']),
                        SPLITS_PATH)
    if removed:
        print(f"Writing {len(removed)} removed features to {REMOVED_PATH}")
        write_shapefile(frame(removed, ['part_n']), REMOVED_PATH)

    if split_parents or removed:
        print("\n" + "!" * 78)
        print("BLOCKED: retained legacy features need correction before stage 03.")
        for title, records, layers in [
                ("split by the coastline into separate parts", split_parents,
                 [PARENTS_PATH, SPLITS_PATH]),
                (f"with no marine part of at least {MIN_PART_AREA_M2:g} m² "
                 "(land-only or below mapping resolution)", removed, [REMOVED_PATH])]:
            if not records:
                continue
            print(f"\n{len(records)} legacy features {title}:")
            for r in records:
                print(f"  src_row {r['src_row']}  {r['SOURCE']}  ReefFID={r['ReefFID']}")
            print("  Load in QGIS with the coastline: " + "\n    ".join([''] + layers))
        print("\nRequired action: for each listed feature create a corrected, fully attributed")
        print("Reef Edit replacement, or an explicit Remove point, then " + RERUN + ".")
        print("Check that intended historic links were retained using "
              "02a-PrevReefID-review-guide.md.")
        print("Do not edit the generated QA or clipped outputs.")
        print("!" * 78)
        fail(f"{len(split_parents)} splits and {len(removed)} removals block publication of "
             f"{OUT_PATH}.")

    out = src.copy()
    out['geometry'] = out_geoms
    out = out.set_crs(CLIP_CRS, allow_override=True)
    problems = check_polygon_geometries(out.geometry.values)
    bad_type = [i + 1 for i, g in enumerate(out.geometry.values) if g.geom_type != 'Polygon']
    if problems or bad_type:
        fail(f"Final output validation failed: {problems[:10]} non-singlepart src_row={bad_type[:10]}")
    print(f"Writing {len(out)} features to {OUT_PATH}")
    write_shapefile(out, OUT_PATH)
    print(f"\nDone in {time.time() - start:.1f} s.")


if __name__ == '__main__':
    try:
        main()
    except OutputLockedError as exc:
        print(f"\nERROR: Cannot delete or write {exc.path}\n  {LOCKED_FILE_MESSAGE}\n"
              f"  ({exc.detail})")
        sys.exit(1)
