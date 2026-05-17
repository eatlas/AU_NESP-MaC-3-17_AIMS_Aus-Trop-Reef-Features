"""
Australian Tropical Reef Feature Patching Script (v0-9+)
========================================================

This script integrates newly mapped reef features (Reef Edit) with the existing
GBR-TS features dataset. It replaces, removes and retains features as appropriate.

See 02a-patch-TS-GBR-Features_design.md for full rationale and design.

Three integration scenarios are handled:
  1. Overlap replacement — a new feature spatially overlaps old features and
     replaces them.
  2. Move — a new feature corresponds to an old feature that was mapped in the
     wrong position; linked via CODE.
  3. Removal — an old feature is a false positive, flagged by a point in the
     remove-move shapefile.

Processing order: moves, then removals, then overlap replacements.

Inputs:
  - GBR-TS features (third-party)
  - Reef Edit polygons with full RB_Type_L3 attributes
  - Remove-Move points
  - RB_Type_L3 crosswalk CSV (for retained old features)

Output: working/02/TS-GBR-Features-patched.shp

Part of: NESP Marine and Coastal Hub Project 3.17
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import os
import sys
import configparser
from shapely.ops import unary_union

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
IOU_THRESHOLD = 0.1  # Minimum IoU for inheriting CODE/ReefID from old feature

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
config = configparser.ConfigParser()
config.read('config.ini')
in_3p_path = config.get('general', 'in_3p_path')
in_path = config.get('general', 'in_path')
VERSION = config.get('general', 'version')

# Input paths
gbr_path = os.path.join(in_3p_path, "TS-GBR-Feat",
                        "TS_AIMS_NESP_Torres_Strait_Features_V1b_with_GBR_Features.shp")
reef_edit_path = os.path.join(in_path, "Reef-edit",
                              f"AIMS_GBR-TS-Features_Edit_{VERSION}.shp")
remove_move_path = os.path.join(in_path, "Reef-remove-move",
                                f"AIMS_GBR-TS-Features_remove-move_{VERSION}.shp")
crosswalk_path = os.path.join(in_3p_path, "NW-Aus-Feat_v1-0", "in",
                              "RB_Type_L3_crosswalk.csv")

# Output
output_dir = "working/02"
output_path = os.path.join(output_dir, "TS-GBR-Features-patched.shp")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def load_classification_lookup(csv_path):
    """Build a mapping from FEAT_NAME / LEVEL_3 aliases to RB_Type_L3."""
    print(f"  Loading crosswalk from {csv_path}")
    df = pd.read_csv(csv_path)
    mapping = {}
    for _, row in df.iterrows():
        rb_type = row['RB_Type_L3_v0-4']
        for col in ('GBR_Features_FEAT_NAME', 'TS_Features_LEVEL_3'):
            if pd.notna(row.get(col)):
                for alias in str(row[col]).split(';'):
                    alias = alias.strip()
                    if alias:
                        mapping[alias.lower()] = rb_type
        if pd.notna(rb_type):
            mapping[str(rb_type).lower()] = rb_type
    print(f"  Loaded {len(mapping)} classification aliases")
    return mapping


def map_classification(classification_mapping, feat_name, level_3=None):
    """Return (rb_type, source_field) using LEVEL_3 preferentially."""
    for value, source in [(level_3, 'LEVEL_3'), (feat_name, 'FEAT_NAME')]:
        if pd.notna(value) and str(value).strip():
            rb_type = classification_mapping.get(str(value).strip().lower())
            if rb_type is not None:
                return rb_type, source
    return None, None


def compute_edge_acc(area_km2):
    """Area-based EdgeAcc_m assignment."""
    if area_km2 > 30:
        return 800
    elif area_km2 > 10:
        return 600
    elif area_km2 > 1:
        return 300
    elif area_km2 > 0.1:
        return 200
    else:
        return 150


def make_provisional_id(centroid, used_ids):
    """Generate a PROV-{lat}-{lon} identifier, appending a letter on collision."""
    lat = int(round(abs(centroid.y) * 100))
    lon = int(round(abs(centroid.x) * 100))
    base = f"PROV-{lat}-{lon}"
    candidate = base
    suffix = 0
    while candidate in used_ids:
        candidate = f"{base}{chr(ord('a') + suffix)}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def compute_iou(geom_a, geom_b):
    """Intersection-over-union of two geometries."""
    if geom_a is None or geom_b is None:
        return 0.0
    intersection = geom_a.intersection(geom_b).area
    if intersection == 0:
        return 0.0
    union = geom_a.union(geom_b).area
    if union == 0:
        return 0.0
    return intersection / union


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1: Load and prepare inputs
    # ------------------------------------------------------------------
    print("Step 1: Loading and preparing inputs")

    print(f"  Reading GBR features from {gbr_path}")
    gbr = gpd.read_file(gbr_path)
    if gbr.crs is None:
        gbr = gbr.set_crs(epsg=4283)
    print(f"  {len(gbr)} GBR features loaded")

    print(f"  Reading Reef Edit from {reef_edit_path}")
    reef_edit = gpd.read_file(reef_edit_path)
    reef_edit = reef_edit.to_crs(epsg=4283)
    print(f"  {len(reef_edit)} Reef Edit features loaded")

    print(f"  Reading Remove-Move from {remove_move_path}")
    remove_move = gpd.read_file(remove_move_path)
    if remove_move.crs is None:
        remove_move = remove_move.set_crs(epsg=4283)
    print(f"  {len(remove_move)} Remove-Move points loaded")

    classification_mapping = load_classification_lookup(crosswalk_path)

    # Validate no null geometries
    for name, gdf in [('GBR', gbr), ('Reef Edit', reef_edit),
                       ('Remove-Move', remove_move)]:
        null_count = gdf.geometry.isna().sum()
        if null_count > 0:
            print(f"ERROR: {null_count} null geometries in {name}")
            sys.exit(1)

    # Normalise CODE columns: treat empty strings as null
    for gdf in [gbr, reef_edit]:
        gdf.loc[gdf['CODE'].astype(str).str.strip() == '', 'CODE'] = None

    # ------------------------------------------------------------------
    # Step 2: Process move operations (against unfiltered GBR)
    # ------------------------------------------------------------------
    print("\nStep 2: Processing move operations")

    # Identify Reef Edit features with CODE set (move operations)
    move_mask = reef_edit['CODE'].notna()
    move_edits = reef_edit[move_mask].copy()
    overlap_edits = reef_edit[~move_mask].copy()
    print(f"  {len(move_edits)} Reef Edit features with CODE (moves)")
    print(f"  {len(overlap_edits)} Reef Edit features without CODE (overlaps/new)")

    # Build CODE lookup on the full (unfiltered) GBR — move/remove points
    # can target island/cay features that would otherwise be filtered out.
    gbr_code_to_idx = {}
    for idx, row in gbr.iterrows():
        if pd.notna(row['CODE']):
            gbr_code_to_idx.setdefault(row['CODE'], []).append(idx)

    # Validate move points match Reef Edit CODEs
    move_points = remove_move[remove_move['ACTION'] == 'Move'].copy()
    print(f"  {len(move_points)} Move points in Remove-Move file")

    # Spatially join Move points to unfiltered GBR to find which CODEs they hit
    move_point_codes = set()
    unmatched_move_points = []
    gbr_sindex = gbr.sindex
    for pt_idx, pt_row in move_points.iterrows():
        pt_geom = pt_row.geometry
        candidates = list(gbr_sindex.intersection(pt_geom.bounds))
        matches = gbr.iloc[candidates]
        matches = matches[matches.contains(pt_geom)]
        if len(matches) == 0:
            print(f"  WARNING: Move point {pt_idx} does not intersect any GBR feature")
            unmatched_move_points.append(pt_idx)
        else:
            for _, m in matches.iterrows():
                move_point_codes.add(m['CODE'])

    if unmatched_move_points:
        debug_path = os.path.join(output_dir, "debug-unmatched-move-points.shp")
        move_points.loc[unmatched_move_points].to_file(debug_path)
        print(f"ERROR: {len(unmatched_move_points)} Move points do not intersect "
              f"any GBR feature. Saved to {debug_path}")
        sys.exit(1)

    reef_edit_codes = set(move_edits['CODE'].dropna().unique())

    # Validate one-to-one correspondence
    only_in_points = move_point_codes - reef_edit_codes
    only_in_edits = reef_edit_codes - move_point_codes
    if only_in_points:
        print(f"ERROR: Move point CODEs not found in Reef Edit: {only_in_points}")
        sys.exit(1)
    if only_in_edits:
        # CODEs in Reef Edit but not in Move points are disambiguation codes,
        # not errors. The design says the check is that every Move point has a
        # corresponding Reef Edit CODE. Extra Reef Edit CODEs (disambiguation)
        # are allowed.
        print(f"  Note: {len(only_in_edits)} Reef Edit CODEs have no corresponding "
              f"Move point (disambiguation CODEs)")

    # Record LABEL_IDs and mark GBR features for deletion
    move_label_ids = {}   # Reef Edit index -> LABEL_ID
    move_codes_map = {}   # Reef Edit index -> CODE
    gbr_delete_move = set()
    for edit_idx, edit_row in move_edits.iterrows():
        code = edit_row['CODE']
        if code in gbr_code_to_idx:
            gbr_indices = gbr_code_to_idx[code]
            label_id = gbr.at[gbr_indices[0], 'LABEL_ID']
            move_label_ids[edit_idx] = label_id
            move_codes_map[edit_idx] = code
            gbr_delete_move.update(gbr_indices)
        else:
            print(f"WARNING: CODE {code} from Reef Edit not found in GBR features")

    print(f"  Marking {len(gbr_delete_move)} GBR features for deletion (move)")

    # ------------------------------------------------------------------
    # Step 3: Process removals (against unfiltered GBR)
    # ------------------------------------------------------------------
    print("\nStep 3: Processing removals")
    remove_points = remove_move[remove_move['ACTION'] == 'Remove'].copy()
    print(f"  {len(remove_points)} Remove points")

    gbr_delete_remove = set()
    unmatched_remove_points = []
    for pt_idx, pt_row in remove_points.iterrows():
        pt_geom = pt_row.geometry
        candidates = list(gbr_sindex.intersection(pt_geom.bounds))
        matches = gbr.iloc[candidates]
        matches = matches[matches.contains(pt_geom)]
        if len(matches) == 0:
            print(f"  WARNING: Remove point {pt_idx} does not intersect any GBR feature")
            unmatched_remove_points.append(pt_idx)
        else:
            gbr_delete_remove.update(matches.index.tolist())

    if unmatched_remove_points:
        debug_path = os.path.join(output_dir, "debug-unmatched-remove-points.shp")
        remove_points.loc[unmatched_remove_points].to_file(debug_path)
        print(f"ERROR: {len(unmatched_remove_points)} Remove points do not intersect "
              f"any GBR feature. Saved to {debug_path}")
        sys.exit(1)

    print(f"  Marking {len(gbr_delete_remove)} GBR features for deletion (removal)")

    # ------------------------------------------------------------------
    # Apply move/remove deletions and Island/Mainland/Other filter together
    # ------------------------------------------------------------------
    print("\n  Applying deletions and filtering Island/Mainland/Other")
    all_delete = gbr_delete_move | gbr_delete_remove

    # Save island/mainland for attachment calculation before filtering
    islands_mainland = gbr[gbr['LEVEL_1'].isin(['Island', 'Mainland'])].copy()

    # Remove: move/remove targets + Island/Mainland/Other
    filter_mask = gbr['LEVEL_1'].isin(['Island', 'Mainland', 'Other'])
    drop_indices = set(gbr.index[filter_mask]) | all_delete
    original_count = len(gbr)
    gbr = gbr.drop(index=drop_indices).reset_index(drop=True)
    print(f"  Removed {original_count - len(gbr)} features "
          f"({len(all_delete)} move/remove, rest Island/Mainland/Other), "
          f"{len(gbr)} remaining")

    # Rebuild spatial index after deletions
    gbr_sindex = gbr.sindex

    # ------------------------------------------------------------------
    # Step 4: Process overlap replacements
    # ------------------------------------------------------------------
    print("\nStep 4: Processing overlap replacements")

    # For IoU computation we need an equal-area projection
    gbr_3577 = gbr.to_crs(epsg=3577)
    overlap_edits_3577 = overlap_edits.to_crs(epsg=3577)

    # Track per-edit: which GBR features overlap, their CODEs/LABEL_IDs
    overlap_info = {}       # edit_idx -> {'codes': [...], 'label_ids': [...]}
    gbr_delete_overlap = set()

    for edit_idx, edit_row in overlap_edits_3577.iterrows():
        edit_geom = edit_row.geometry
        # Use the 4283 geometry for spatial index query (index is on gbr, not gbr_3577)
        edit_geom_4283 = overlap_edits.loc[edit_idx, 'geometry']
        candidates = list(gbr_sindex.intersection(edit_geom_4283.bounds))
        if not candidates:
            overlap_info[edit_idx] = {'codes': [], 'label_ids': []}
            continue

        codes = []
        label_ids = []
        for gbr_local_idx in candidates:
            gbr_geom_3577 = gbr_3577.iloc[gbr_local_idx].geometry
            # Check any intersection first
            if not edit_geom.intersects(gbr_geom_3577):
                continue
            # Any intersection -> mark for deletion
            gbr_real_idx = gbr.index[gbr_local_idx]
            gbr_delete_overlap.add(gbr_real_idx)
            # Check IoU for CODE/LABEL_ID inheritance
            iou = compute_iou(edit_geom, gbr_geom_3577)
            if iou >= IOU_THRESHOLD:
                code = gbr.at[gbr_real_idx, 'CODE']
                label_id = gbr.at[gbr_real_idx, 'LABEL_ID']
                if pd.notna(code):
                    codes.append(code)
                if pd.notna(label_id):
                    label_ids.append(label_id)
        overlap_info[edit_idx] = {'codes': codes, 'label_ids': label_ids}

    print(f"  {len(gbr_delete_overlap)} GBR features to delete (overlapped by new features)")
    overlap_with_codes = sum(1 for v in overlap_info.values() if v['codes'])
    overlap_new = sum(1 for v in overlap_info.values() if not v['codes'])
    print(f"  {overlap_with_codes} new features inherit CODEs, "
          f"{overlap_new} are genuinely new or have no significant overlap")

    gbr = gbr.drop(index=gbr_delete_overlap).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Step 5: Assign ReefID and CODES for new features
    # ------------------------------------------------------------------
    print("\nStep 5: Assigning ReefID and CODES for new features")

    used_prov_ids = set()
    reef_edit_reefid = {}
    reef_edit_codes_attr = {}
    reef_edit_idaliases = {}

    # 5a. Move features
    for edit_idx in move_edits.index:
        label_id = move_label_ids.get(edit_idx)
        code = move_codes_map.get(edit_idx)
        reef_edit_reefid[edit_idx] = label_id
        reef_edit_codes_attr[edit_idx] = code
        reef_edit_idaliases[edit_idx] = None

    # 5b. Overlap features — first pass: determine which LABEL_IDs map 1:1
    # Count how many new features claim each LABEL_ID
    label_id_claimants = {}  # label_id -> list of edit_idx
    for edit_idx in overlap_edits.index:
        info = overlap_info.get(edit_idx, {'codes': [], 'label_ids': []})
        unique_labels = list(dict.fromkeys(info['label_ids']))  # deduplicate, preserve order
        if len(unique_labels) == 1:
            lid = unique_labels[0]
            label_id_claimants.setdefault(lid, []).append(edit_idx)

    for edit_idx in overlap_edits.index:
        info = overlap_info.get(edit_idx, {'codes': [], 'label_ids': []})
        codes = info['codes']
        label_ids = info['label_ids']
        unique_labels = list(dict.fromkeys(label_ids))

        # CODES attribute
        if codes:
            reef_edit_codes_attr[edit_idx] = ';'.join(dict.fromkeys(codes))
        else:
            reef_edit_codes_attr[edit_idx] = None

        # ReefID and IDAliases
        if len(unique_labels) == 1:
            lid = unique_labels[0]
            if len(label_id_claimants.get(lid, [])) == 1:
                # Exactly one new feature claims this LABEL_ID -> use it
                reef_edit_reefid[edit_idx] = lid
                reef_edit_idaliases[edit_idx] = None
            else:
                # Multiple new features claim the same LABEL_ID
                centroid = overlap_edits.at[edit_idx, 'geometry'].centroid
                reef_edit_reefid[edit_idx] = make_provisional_id(centroid, used_prov_ids)
                reef_edit_idaliases[edit_idx] = lid
        elif len(unique_labels) > 1:
            # Multiple old LABEL_IDs merged
            centroid = overlap_edits.at[edit_idx, 'geometry'].centroid
            reef_edit_reefid[edit_idx] = make_provisional_id(centroid, used_prov_ids)
            reef_edit_idaliases[edit_idx] = ';'.join(unique_labels)
        else:
            # Genuinely new (no overlap above threshold)
            centroid = overlap_edits.at[edit_idx, 'geometry'].centroid
            reef_edit_reefid[edit_idx] = make_provisional_id(centroid, used_prov_ids)
            reef_edit_idaliases[edit_idx] = None

    prov_count = sum(1 for v in reef_edit_reefid.values()
                     if v is not None and str(v).startswith('PROV-'))
    print(f"  {prov_count} provisional IDs assigned")
    print(f"  {len(reef_edit_reefid) - prov_count} LABEL_IDs carried forward")

    # ------------------------------------------------------------------
    # Step 6: Prepare retained old features
    # ------------------------------------------------------------------
    print("\nStep 6: Preparing retained old features")
    print(f"  {len(gbr)} GBR features retained")

    # 6.1 Crosswalk
    print("  Applying classification crosswalk")
    unmapped = []
    rbtype_values = []
    origtype_values = []
    for idx, row in gbr.iterrows():
        rb_type, source = map_classification(
            classification_mapping, row.get('FEAT_NAME'), row.get('LEVEL_3'))
        if rb_type is None:
            unmapped.append((idx, row.get('FEAT_NAME'), row.get('LEVEL_3')))
        rbtype_values.append(rb_type)
        # OrigType
        level_3 = row.get('LEVEL_3')
        feat_name = row.get('FEAT_NAME')
        if pd.notna(level_3) and str(level_3).strip():
            origtype_values.append(str(level_3).strip())
        elif pd.notna(feat_name) and str(feat_name).strip():
            origtype_values.append(str(feat_name).strip())
        else:
            origtype_values.append(None)

    if unmapped:
        print(f"ERROR: {len(unmapped)} features could not be mapped to RB_Type_L3:")
        for idx, fn, l3 in unmapped[:10]:
            print(f"  Index {idx}: FEAT_NAME={fn}, LEVEL_3={l3}")
        sys.exit(1)

    gbr['RB_Type_L3'] = rbtype_values
    gbr['OrigType'] = origtype_values

    # 6.2 Attachment
    print("  Computing Attachment (island/mainland buffer)")
    gbr_3577 = gbr.to_crs(epsg=3577)
    islands_mainland_3577 = islands_mainland.to_crs(epsg=3577)
    buffer_union = unary_union(islands_mainland_3577.buffer(200))

    attachment_values = []
    for geom in gbr_3577.geometry:
        if geom.intersects(buffer_union):
            attachment_values.append('Fringing')
        else:
            attachment_values.append('Isolated')
    gbr['Attachment'] = attachment_values

    # Override for Unvegetated Cay
    cay_mask = gbr['RB_Type_L3'] == 'Unvegetated Cay'
    gbr.loc[cay_mask, 'Attachment'] = 'Land'

    # 6.3 EdgeAcc_m
    print("  Computing EdgeAcc_m from area")
    areas_km2 = gbr_3577.geometry.area / 1e6
    gbr['EdgeAcc_m'] = [compute_edge_acc(a) for a in areas_km2]

    # 6.4 Other defaults
    gbr['FeatConf'] = None
    gbr['TypeConf'] = gbr.get('CLASS_CONF', pd.Series(dtype='object'))
    gbr['DepthCat'] = None
    gbr['DepthCatSr'] = None

    # 6.5 Rename
    rename_map = {'IMG_SRC': 'EdgeSrc', 'LABEL_ID': 'ReefID'}
    gbr = gbr.rename(columns={k: v for k, v in rename_map.items() if k in gbr.columns})

    # 6.6 Dataset — retain original
    if 'DATASET' in gbr.columns:
        gbr = gbr.rename(columns={'DATASET': 'Dataset'})

    # 6.7 CODES and IDAliases
    gbr['CODES'] = gbr['CODE'] if 'CODE' in gbr.columns else None
    gbr['IDAliases'] = None

    # ------------------------------------------------------------------
    # Step 7: Prepare new features (Reef Edit)
    # ------------------------------------------------------------------
    print("\nStep 7: Preparing Reef Edit features")

    # Recombine move_edits and overlap_edits
    new_features = pd.concat([move_edits, overlap_edits], ignore_index=False)
    new_features = new_features.copy()

    # Assign computed attributes
    new_features['ReefID'] = new_features.index.map(reef_edit_reefid)
    new_features['CODES'] = new_features.index.map(reef_edit_codes_attr)
    new_features['IDAliases'] = new_features.index.map(reef_edit_idaliases)
    new_features['OrigType'] = new_features['RB_Type_L3']
    new_features['Dataset'] = f'Aus-Trop-Reef-Features_{VERSION}'

    # EdgeAcc_m — fill nulls with area-based values
    needs_edge_acc = new_features['EdgeAcc_m'].isna()
    if needs_edge_acc.any():
        print(f"  Filling {needs_edge_acc.sum()} null EdgeAcc_m values from area")
        new_3577 = new_features[needs_edge_acc].to_crs(epsg=3577)
        areas_km2 = new_3577.geometry.area / 1e6
        for i, (orig_idx, area) in enumerate(zip(new_3577.index, areas_km2)):
            new_features.at[orig_idx, 'EdgeAcc_m'] = compute_edge_acc(area)

    # Drop Note and FEAT_NAME
    drop_cols = [c for c in ['Note', 'FEAT_NAME'] if c in new_features.columns]
    if drop_cols:
        new_features = new_features.drop(columns=drop_cols)

    # Drop the original CODE column (now recorded in CODES)
    if 'CODE' in new_features.columns:
        new_features = new_features.drop(columns=['CODE'])

    print(f"  {len(new_features)} new features prepared")

    # ------------------------------------------------------------------
    # Step 8: Merge and output
    # ------------------------------------------------------------------
    print("\nStep 8: Merging and saving output")

    # Trim old features to output schema
    output_columns = [
        'RB_Type_L3', 'Attachment', 'DepthCat', 'DepthCatSr',
        'FeatConf', 'TypeConf', 'EdgeSrc', 'EdgeAcc_m',
        'OrigType', 'Dataset', 'ReefID', 'CODES', 'IDAliases', 'geometry'
    ]

    # Keep only output columns that exist (others are discarded)
    gbr_out = gbr[[c for c in output_columns if c in gbr.columns]].copy()
    new_out = new_features[[c for c in output_columns if c in new_features.columns]].copy()

    # Align schemas
    all_cols = list(dict.fromkeys(list(gbr_out.columns) + list(new_out.columns)))
    for col in all_cols:
        if col not in gbr_out.columns:
            gbr_out[col] = None
        if col not in new_out.columns:
            new_out[col] = None

    merged = gpd.GeoDataFrame(pd.concat([gbr_out, new_out], ignore_index=True))
    merged = merged.set_crs(epsg=4283)

    print(f"  Saving {len(merged)} features to {output_path}")
    merged.to_file(output_path)

    # Summary
    print(f"\nDone. Output: {output_path}")
    print(f"  Old features retained: {len(gbr_out)}")
    print(f"  New features added: {len(new_out)}")
    print(f"  Total: {len(merged)}")


if __name__ == "__main__":
    main()
