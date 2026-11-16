"""
Australian Tropical Reef Feature Patching Script (v0-9+)
========================================================

CURRENT WORKFLOW: Use this script for v0-9 onwards, including v1-0.
Run 01d-refresh-TS-GBR-Features.py first.
The similarly named 02a-patch-TS-GBR-Features_v0-1.py is retained only for
historical reference to v0-1; do not run it as part of the current workflow.
Both scripts write to the same intermediate output path.

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
    - Refreshed GBR-TS features produced by 01d-refresh-TS-GBR-Features.py
  - Reef Edit polygons with full RB_Type_L3 attributes, clipped to the
    coastline by 01e-clip-TS-GBR-reef-edit.py (working/{version}/01/Reef-Edit-clipped.shp)
  - Remove-Move points
  - RB_Type_L3 crosswalk CSV (for retained old features)

Output: working/{version}/02/TS-GBR-Features-patched.shp
        working/{version}/02/debug-reefid-review.gpkg (identifier review layers)

Part of: NESP Marine and Coastal Hub Project 3.17
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import os
import sys
import configparser
from shapely.ops import unary_union
from shapely.validation import explain_validity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Erosion distance below which an intersection is treated as a digitising sliver
SLIVER_TOLERANCE_M = 10
# The tolerance is never more than this fraction of the smaller feature's width,
# so that a feature only a few tens of metres across is not erased by the test
SLIVER_WIDTH_FRACTION = 0.25
# Minimum share of either polygon's area for a candidate lineage relationship
CANDIDATE_SHARE = 0.1
# Factor by which the best candidate must exceed the next best to inherit ReefID
DOMINANCE_RATIO = 3.0
# Area ratio above which an inherited relationship is reported for review
SIZE_CHANGE_REPORT = 5.0
# Recognised ACTION values in the Remove-Move point file
VALID_ACTIONS = {'Move', 'Remove', 'Link'}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
config = configparser.ConfigParser()
config.read('config.ini')
in_3p_path = config.get('general', 'in_3p_path')
in_path = config.get('general', 'in_path')
VERSION = config.get('general', 'version')
NW_AUS_FEAT_VERSION = config.get('general', 'nw_aus_feat_version')

# Input paths
gbr_path = os.path.join("working", VERSION, "01", "TS-GBR-Features-latest.shp")
# Reef Edit clipped to the coastline by 01e-clip-TS-GBR-reef-edit.py
reef_edit_path = os.path.join("working", VERSION, "01", "Reef-Edit-clipped.shp")
remove_move_path = os.path.join(in_path, "Reef-remove-move",
                                f"AIMS_GBR-TS-Features_remove-move_{VERSION}.shp")
crosswalk_path = os.path.join(in_3p_path, f"NW-Aus-Feat_{NW_AUS_FEAT_VERSION}", "in",
                              "RB_Type_L3_crosswalk.csv")
inshore_extent_path = os.path.join("data", VERSION, "extras", "inshore-extent",
                                   "inshore-extent.shp")

# Output
output_dir = os.path.join("working", VERSION, "02")
output_path = os.path.join(output_dir, "TS-GBR-Features-patched.shp")
review_path = os.path.join(output_dir, "debug-reefid-review.gpkg")


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


def inscribed_width(geom, limit):
    """Width of the widest part of a polygon, found by bisection on erosion.

    Returns 2 * limit for anything at least that wide, since the callers only
    care about the narrow end of the range.
    """
    if not geom.buffer(-limit).is_empty:
        return 2 * limit
    lo, hi = 0.0, limit
    for _ in range(16):
        mid = (lo + hi) / 2
        if geom.buffer(-mid).is_empty:
            hi = mid
        else:
            lo = mid
    return 2 * lo


def sliver_tolerance(old_geom, new_geom):
    """Erosion distance to use for a pair, reduced for small features.

    A fixed tolerance cannot judge a feature whose whole width is comparable to
    the tolerance itself, because eroding it leaves nothing whatever the overlap
    represents. The tolerance is therefore capped at a fraction of the width of
    the smaller of the two polygons.
    """
    smaller = old_geom if old_geom.area <= new_geom.area else new_geom
    limit = SLIVER_TOLERANCE_M / SLIVER_WIDTH_FRACTION / 2
    if not smaller.buffer(-limit).is_empty:
        return SLIVER_TOLERANCE_M
    return min(SLIVER_TOLERANCE_M,
               SLIVER_WIDTH_FRACTION * inscribed_width(smaller, limit))


def score_pair(old_geom, new_geom):
    """Score an old/new polygon pair in an equal-area projection.

    Returns None where the polygons do not intersect, otherwise a dict holding
    the intersection geometry, its area, the share of each polygon's area that
    the intersection represents, and whether the intersection survives erosion.
    Erosion distinguishes a genuine overlap from a long thin contact produced by
    coordinate precision or an eye-judged division. The erosion distance is
    SLIVER_TOLERANCE_M, reduced on small features by sliver_tolerance.
    """
    if old_geom is None or new_geom is None:
        return None
    intersection = old_geom.intersection(new_geom)
    if intersection.is_empty:
        return None
    area = intersection.area
    if area <= 0:
        return None
    old_area = old_geom.area
    new_area = new_geom.area
    # A multipart intersection survives if any part survives erosion.
    survives = not intersection.buffer(-SLIVER_TOLERANCE_M).is_empty
    tolerance = SLIVER_TOLERANCE_M
    if not survives:
        tolerance = sliver_tolerance(old_geom, new_geom)
        if tolerance < SLIVER_TOLERANCE_M:
            survives = not intersection.buffer(-tolerance).is_empty
    return {
        'geometry': intersection,
        'area': area,
        'share_old': area / old_area if old_area > 0 else 0.0,
        'share_new': area / new_area if new_area > 0 else 0.0,
        'survives': survives,
        'tolerance': tolerance,
    }


def write_review_layer(gdf, layer_name):
    """Write a review layer to the review GeoPackage, skipping empty layers."""
    if len(gdf) == 0:
        print(f"    {layer_name}: 0 records (layer not written)")
        return
    gdf.to_file(review_path, layer=layer_name, driver='GPKG')
    print(f"    {layer_name}: {len(gdf)} records")


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
    if not os.path.exists(reef_edit_path):
        print(f"ERROR: {reef_edit_path} not found. Run 01e-clip-TS-GBR-reef-edit.py first.")
        sys.exit(1)
    reef_edit = gpd.read_file(reef_edit_path)
    # Identifier maps are keyed by index, so it must be a unique row index.
    reef_edit = reef_edit.reset_index(drop=True)
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

    # Invalid edit polygons can trigger opaque GEOS errors after reprojection.
    invalid_edit_mask = ~reef_edit.geometry.is_valid
    if invalid_edit_mask.any():
        invalid_edits = reef_edit[invalid_edit_mask].copy()
        invalid_edits['geom_issue'] = invalid_edits.geometry.apply(explain_validity)
        debug_path = os.path.join(output_dir, "debug-invalid-reef-edit.shp")
        invalid_edits.to_file(debug_path)
        print(f"ERROR: {len(invalid_edits)} invalid geometries in Reef Edit:")
        for idx, row in invalid_edits.iterrows():
            print(f"  Index {idx}, CODE={row.get('CODE')}: {row['geom_issue']}")
        print(f"  Saved invalid Reef Edit features to {debug_path}")
        sys.exit(1)

    # Normalise CODE columns: treat empty strings as null
    for gdf in [gbr, reef_edit]:
        gdf.loc[gdf['CODE'].astype(str).str.strip() == '', 'CODE'] = None

    # ------------------------------------------------------------------
    # Step 2: Process move operations (against unfiltered GBR)
    # ------------------------------------------------------------------
    print("\nStep 2: Processing move operations")

    unknown_actions = set(remove_move['ACTION'].dropna().unique()) - VALID_ACTIONS
    if unknown_actions:
        print(f"ERROR: Unrecognised ACTION values in Remove-Move: "
              f"{sorted(unknown_actions)}")
        print(f"  Supported values are {sorted(VALID_ACTIONS)}")
        sys.exit(1)

    # Reef Edit features with CODE set record an explicit link to an old feature
    coded_mask = reef_edit['CODE'].notna()
    print(f"  {int(coded_mask.sum())} Reef Edit features carry a CODE")
    print(f"  {int((~coded_mask).sum())} Reef Edit features matched by overlap alone")

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
    code_to_move_points = {}  # CODE -> list of Move point indices
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
                code_to_move_points.setdefault(m['CODE'], []).append(pt_idx)

    if unmatched_move_points:
        debug_path = os.path.join(output_dir, "debug-unmatched-move-points.shp")
        move_points.loc[unmatched_move_points].to_file(debug_path)
        print(f"ERROR: {len(unmatched_move_points)} Move points do not intersect "
              f"any GBR feature. Saved to {debug_path}")
        sys.exit(1)

    reef_edit_codes = set(reef_edit.loc[coded_mask, 'CODE'].unique())

    # Validate one-to-one correspondence
    only_in_points = move_point_codes - reef_edit_codes
    only_in_edits = reef_edit_codes - move_point_codes
    if only_in_points:
        # Save the offending Move points to a shapefile to aid investigation
        bad_pt_indices = sorted({
            pt_idx
            for code in only_in_points
            for pt_idx in code_to_move_points.get(code, [])
        })
        bad_points = move_points.loc[bad_pt_indices].copy()
        bad_points['bad_CODE'] = [
            next(code for code in only_in_points
                 if pt_idx in code_to_move_points.get(code, []))
            for pt_idx in bad_pt_indices
        ]
        debug_path = os.path.join(output_dir, "debug-unmatched-move-codes.shp")
        bad_points.to_file(debug_path)
        print(f"ERROR: Move point CODEs not found in Reef Edit: {only_in_points}")
        print(f"  Saved {len(bad_points)} offending Move points to {debug_path}")
        sys.exit(1)
    if only_in_edits:
        # CODEs in Reef Edit but not in Move points are disambiguation codes,
        # not errors. The design says the check is that every Move point has a
        # corresponding Reef Edit CODE. Extra Reef Edit CODEs (disambiguation)
        # are allowed.
        print(f"  Note: {len(only_in_edits)} Reef Edit CODEs have no corresponding "
              f"Move point (disambiguation CODEs)")

    # Mark the coded GBR features for deletion. Identifier inheritance is decided
    # later by the candidate allocation, not by the presence of a CODE.
    gbr_delete_move = set()
    for code in sorted(reef_edit_codes):
        if code in gbr_code_to_idx:
            gbr_delete_move.update(gbr_code_to_idx[code])
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
    # Step 4: Score every intersecting old/new polygon pair
    # ------------------------------------------------------------------
    print("\nStep 4: Scoring old/new polygon pairs")

    # Save island/mainland for attachment calculation before filtering
    islands_mainland = gbr[gbr['LEVEL_1'].isin(['Island', 'Mainland'])].copy()
    filter_mask = gbr['LEVEL_1'].isin(['Island', 'Mainland', 'Other'])

    # Old features that could still appear in the output. Anything a new feature
    # intersects is deleted from this set, because the old boundary is superseded.
    retainable = set(gbr.index[~filter_mask]) - gbr_delete_move - gbr_delete_remove

    # Coded targets are already deleted by the move, but they still supply
    # identifiers, so they are scored as well. Remove-point targets are false
    # positives and must never contribute an identifier.
    code_targets = set()
    for code in reef_edit_codes:
        code_targets.update(gbr_code_to_idx.get(code, []))
    scoring_index = sorted((retainable | code_targets) - gbr_delete_remove)
    print(f"  {len(scoring_index)} old features scored "
          f"({len(code_targets - retainable)} of them retained only as CODE targets)")

    # Areas and intersections are computed in an equal-area projection
    gbr_3577 = gbr.to_crs(epsg=3577)
    reef_edit_3577 = reef_edit.to_crs(epsg=3577)
    gbr_areas = gbr_3577.geometry.area
    edit_areas = reef_edit_3577.geometry.area
    gbr_label = gbr['LABEL_ID']
    gbr_code = gbr['CODE']

    scoring = gbr.loc[scoring_index]
    scoring_sindex = scoring.sindex

    pairs = {}  # (old_idx, edit_idx) -> scored record
    for edit_idx, edit_geom_3577 in reef_edit_3577.geometry.items():
        bounds = reef_edit.geometry.loc[edit_idx].bounds
        for pos in scoring_sindex.intersection(bounds):
            old_idx = scoring.index[pos]
            scored = score_pair(gbr_3577.geometry.loc[old_idx], edit_geom_3577)
            if scored is None:
                continue
            scored.update({'old_idx': old_idx, 'edit_idx': edit_idx, 'forced': None})
            pairs[(old_idx, edit_idx)] = scored

    slivers = sum(1 for p in pairs.values() if not p['survives'])
    rescued = sum(1 for p in pairs.values()
                  if p['survives'] and p['tolerance'] < SLIVER_TOLERANCE_M)
    print(f"  {len(pairs)} intersecting pairs, {slivers} rejected as digitising slivers")
    print(f"  {rescued} small-feature pairs kept by a reduced sliver tolerance")

    # Any intersection with a new feature deletes the old feature
    gbr_delete_overlap = {old_idx for (old_idx, _) in pairs if old_idx in retainable}
    print(f"  {len(gbr_delete_overlap)} GBR features to delete "
          f"(overlapped by new features)")

    # --- Candidate relationships -------------------------------------------
    candidates = {}
    for key, pair in pairs.items():
        if not pair['survives']:
            continue
        if max(pair['share_old'], pair['share_new']) >= CANDIDATE_SHARE:
            candidates[key] = dict(pair)

    def force_candidate(old_idx, edit_idx, reason):
        """Add a forced candidate relationship. Returns False if already present."""
        key = (old_idx, edit_idx)
        if key in candidates:
            return False
        record = dict(pairs.get(key, {
            'geometry': None, 'area': 0.0, 'share_old': 0.0, 'share_new': 0.0,
            'survives': False, 'old_idx': old_idx, 'edit_idx': edit_idx,
        }))
        record['forced'] = reason
        candidates[key] = record
        return True

    # A repeated or displaced CODE forces a relationship regardless of geometry
    coded_no_overlap = 0
    for edit_idx, code in reef_edit.loc[coded_mask, 'CODE'].items():
        for old_idx in gbr_code_to_idx.get(code, []):
            force_candidate(old_idx, edit_idx, 'CODE')
            if (old_idx, edit_idx) not in pairs:
                coded_no_overlap += 1
    print(f"  {len(candidates)} candidate relationships "
          f"({coded_no_overlap} coded pairs with no geometric overlap)")

    # --- Link override points ----------------------------------------------
    link_points = remove_move[remove_move['ACTION'] == 'Link'].copy()
    override_problems = []   # (point index, ACTION, ReefID, reason)
    links_applied = 0
    if len(link_points) > 0:
        print(f"  {len(link_points)} Link points")
        edit_sindex = reef_edit.sindex
        for pt_idx, pt_row in link_points.iterrows():
            pt = pt_row.geometry
            old_matches = [scoring.index[pos]
                           for pos in scoring_sindex.intersection(pt.bounds)
                           if scoring.geometry.iloc[pos].contains(pt)]
            new_matches = [reef_edit.index[pos]
                           for pos in edit_sindex.intersection(pt.bounds)
                           if reef_edit.geometry.iloc[pos].contains(pt)]
            if not old_matches or not new_matches:
                override_problems.append(
                    (pt_idx, 'Link', None,
                     'Obsolete: point is not inside both an old and a new polygon'))
                continue
            old_idx, edit_idx = old_matches[0], new_matches[0]
            reef_id = gbr_label.get(old_idx)
            key = (old_idx, edit_idx)
            if key not in pairs:
                override_problems.append(
                    (pt_idx, 'Link', reef_id,
                     'Obsolete: the linked polygons no longer intersect'))
                continue
            existing = candidates.get(key)
            if existing is not None:
                reason = ('Unnecessary: the relationship already qualifies on its own'
                          if existing['forced'] is None
                          else 'Unnecessary: the relationship is already set by CODE')
                override_problems.append((pt_idx, 'Link', reef_id, reason))
                continue
            force_candidate(old_idx, edit_idx, 'Link')
            links_applied += 1
        print(f"  {links_applied} Link points applied, "
              f"{len(override_problems)} reported for review")

    # ------------------------------------------------------------------
    # Step 5: Allocate ReefID, PrevReefID and ReefFID
    # ------------------------------------------------------------------
    print("\nStep 5: Allocating identifiers")

    old_with_candidate = {record['old_idx'] for record in candidates.values()}

    # LABEL_ID is not unique in the source: a reef and its associated rock or
    # island can share one identifier across several polygons. Allocation is
    # therefore grouped by identifier rather than by polygon, so that an
    # official identifier can only ever pass to one new feature.
    candidates_by_id = {}    # ReefID -> {edit_idx: aggregated record}
    candidates_by_edit = {}  # edit_idx -> list of candidate records
    for record in candidates.values():
        candidates_by_edit.setdefault(record['edit_idx'], []).append(record)
        reef_id = gbr_label.get(record['old_idx'])
        if pd.isna(reef_id):
            continue
        group = candidates_by_id.setdefault(reef_id, {})
        aggregated = group.get(record['edit_idx'])
        if aggregated is None:
            group[record['edit_idx']] = {
                'edit_idx': record['edit_idx'],
                'area': record['area'],
                'old_idx': [record['old_idx']],
                'forced': record['forced'],
            }
        else:
            aggregated['area'] += record['area']
            aggregated['old_idx'].append(record['old_idx'])
            if record['forced'] is None:
                aggregated['forced'] = None
            elif aggregated['forced'] == 'Link' and record['forced'] == 'CODE':
                aggregated['forced'] = 'CODE'

    winners = {}          # ReefID -> edit_idx that inherits the official ReefID
    groups_clear = 0      # split groups with a dominant successor
    groups_referred = 0   # split groups referred to GBRMPA
    for reef_id, group in candidates_by_id.items():
        ranked = sorted(group.values(), key=lambda r: (-r['area'], str(r['edit_idx'])))
        best = ranked[0]
        runner_up = ranked[1]['area'] if len(ranked) > 1 else 0.0
        if best['forced'] == 'Link':
            # A Link only ever produces a previous identifier
            winner = None
        elif len(ranked) > 1 and best['area'] <= 0:
            # Several coded features, none overlapping: no basis to choose
            winner = None
        elif runner_up <= 0 or best['area'] >= DOMINANCE_RATIO * runner_up:
            winner = best['edit_idx']
        else:
            winner = None
        if winner is not None:
            winners[reef_id] = winner
        if len(ranked) > 1:
            if winner is None:
                groups_referred += 1
            else:
                groups_clear += 1

    won_by_edit = {}
    for reef_id, edit_idx in winners.items():
        won_by_edit.setdefault(edit_idx, []).append(reef_id)

    def resolve_merge(edit_idx, won):
        """Pick the identifier a merged feature keeps, or None where none dominates."""
        ranked = sorted(won, key=lambda r: -candidates_by_id[r][edit_idx]['area'])
        best = candidates_by_id[ranked[0]][edit_idx]['area']
        runner_up = candidates_by_id[ranked[1]][edit_idx]['area']
        if best > 0 and best >= DOMINANCE_RATIO * runner_up:
            return ranked[0]
        return None

    # A feature can only hold one identity, so a merge keeps the dominant
    # constituent's identifier and records the rest as previous identifiers.
    inherited_by_edit = {}
    merges_resolved = 0
    merges_referred = 0
    for edit_idx, won in won_by_edit.items():
        if len(won) == 1:
            inherited_by_edit[edit_idx] = won[0]
            continue
        reef_id = resolve_merge(edit_idx, won)
        inherited_by_edit[edit_idx] = reef_id
        if reef_id is None:
            merges_referred += 1
        else:
            merges_resolved += 1
    winners = {reef_id: edit_idx for edit_idx, reef_id in inherited_by_edit.items()
               if reef_id is not None}

    used_prov_ids = set()
    reef_edit_reeffid = {}
    reef_edit_reefid = {}
    reef_edit_codes_attr = {}
    reef_edit_prevreefid = {}

    for edit_idx in reef_edit.index:
        cand_old = [r['old_idx'] for r in candidates_by_edit.get(edit_idx, [])]
        cand_ids = [c for c in dict.fromkeys(gbr_label.get(i) for i in cand_old)
                    if pd.notna(c)]
        codes = [c for c in dict.fromkeys(gbr_code.get(i) for i in cand_old)
                 if pd.notna(c)]
        reef_edit_codes_attr[edit_idx] = ';'.join(codes) if codes else None

        reef_id = inherited_by_edit.get(edit_idx)
        if reef_id is not None:
            reef_edit_reefid[edit_idx] = reef_id
            reef_edit_reeffid[edit_idx] = reef_id
            previous = [c for c in cand_ids if c != reef_id]
        else:
            centroid = reef_edit.at[edit_idx, 'geometry'].centroid
            reef_edit_reefid[edit_idx] = None
            reef_edit_reeffid[edit_idx] = make_provisional_id(centroid, used_prov_ids)
            previous = cand_ids
        reef_edit_prevreefid[edit_idx] = ';'.join(previous) if previous else None

    inherited = sum(1 for v in reef_edit_reefid.values() if v is not None)
    with_prev = sum(1 for v in reef_edit_prevreefid.values() if v is not None)
    genuinely_new = sum(1 for idx in reef_edit.index
                        if reef_edit_reefid[idx] is None
                        and reef_edit_prevreefid[idx] is None)
    merged_features = sum(1 for idx in reef_edit.index
                          if len(won_by_edit.get(idx, [])) > 1)
    print(f"  {inherited} new features inherit an official ReefID")
    print(f"  {len(reef_edit) - inherited} receive a provisional ReefFID")
    print(f"  {with_prev} record at least one PrevReefID")
    print(f"  {genuinely_new} are genuinely new (no candidate relationship)")
    print(f"  {merged_features} features merge several old reefs: "
          f"{merges_resolved} keep the dominant identifier, "
          f"{merges_referred} referred to GBRMPA")
    print(f"  {groups_clear} split groups have a dominant successor, "
          f"{groups_referred} referred to GBRMPA")

    # ------------------------------------------------------------------
    # Step 6: Review outputs
    # ------------------------------------------------------------------
    print("\nStep 6: Writing review outputs")

    all_delete = gbr_delete_move | gbr_delete_remove | gbr_delete_overlap
    delete_reason = {}
    delete_share = {}

    # An overlap deletion is only reported once the reason the same overlap did
    # not also carry the identifier across is known, since that is what a
    # reviewer has to act on. The best pair on each old feature decides it.
    best_pair = {}
    for (old_idx, _), pair in pairs.items():
        rank = (pair['survives'], max(pair['share_old'], pair['share_new']))
        if old_idx not in best_pair or rank > best_pair[old_idx]:
            best_pair[old_idx] = rank
    for idx in gbr_delete_overlap:
        survives, share = best_pair[idx]
        delete_share[idx] = share
        delete_reason[idx] = (
            f'Overlap below threshold {CANDIDATE_SHARE:.2f}' if survives
            else 'Overlap rejected as sliver')
    for idx in gbr_delete_remove:
        delete_reason[idx] = 'Remove point'
    for idx in gbr_delete_move:
        delete_reason[idx] = 'Move'

    assigned_ids = set()
    for value in reef_edit_reefid.values():
        if value is not None:
            assigned_ids.add(value)
    for value in reef_edit_prevreefid.values():
        if value is not None:
            assigned_ids.update(value.split(';'))

    if os.path.exists(review_path):
        os.remove(review_path)

    # 6.1 Orphaned identifiers: deleted old features whose identifier is gone
    orphan_idx = [i for i in sorted(all_delete)
                  if pd.notna(gbr_label.get(i)) and gbr_label.get(i) not in assigned_ids]
    orphans = gbr.loc[orphan_idx, ['LABEL_ID', 'CODE', 'geometry']].copy()
    orphans = orphans.rename(columns={'LABEL_ID': 'ReefID'})
    orphans['area_km2'] = [gbr_areas.loc[i] / 1e6 for i in orphan_idx]
    orphans['max_share'] = [delete_share.get(i) for i in orphan_idx]
    orphans['reason'] = [delete_reason.get(i) for i in orphan_idx]
    write_review_layer(orphans, 'orphaned-identifiers')

    # 6.2 Sub-threshold overlaps: survived the sliver test but failed the share test
    sub_records = [p for key, p in pairs.items()
                   if p['survives'] and key not in candidates]
    sub_threshold = gpd.GeoDataFrame(
        {
            'ReefID': [gbr_label.get(p['old_idx']) for p in sub_records],
            'CODE': [gbr_code.get(p['old_idx']) for p in sub_records],
            'area_old_km2': [gbr_areas.loc[p['old_idx']] / 1e6 for p in sub_records],
            'area_new_km2': [edit_areas.loc[p['edit_idx']] / 1e6 for p in sub_records],
            'area_int_km2': [p['area'] / 1e6 for p in sub_records],
            'share_old': [p['share_old'] for p in sub_records],
            'share_new': [p['share_new'] for p in sub_records],
            'sole_pair': [p['old_idx'] not in old_with_candidate for p in sub_records],
        },
        geometry=[p['geometry'] for p in sub_records],
        crs='EPSG:3577',
    )
    if len(sub_threshold) > 0:
        sub_threshold = sub_threshold.to_crs(epsg=4283)
    write_review_layer(sub_threshold, 'sub-threshold-overlaps')

    # 6.3 Extreme size changes among inherited relationships
    size_records = []
    for reef_id, edit_idx in winners.items():
        old_idx = candidates_by_id[reef_id][edit_idx]['old_idx']
        old_area = sum(gbr_areas.loc[i] for i in old_idx)
        new_area = edit_areas.loc[edit_idx]
        if old_area <= 0 or new_area <= 0:
            continue
        ratio = max(old_area / new_area, new_area / old_area)
        if ratio > SIZE_CHANGE_REPORT:
            size_records.append((reef_id, edit_idx, old_area, new_area, ratio))
    size_changes = gpd.GeoDataFrame(
        {
            'ReefID': [r[0] for r in size_records],
            'area_old_km2': [r[2] / 1e6 for r in size_records],
            'area_new_km2': [r[3] / 1e6 for r in size_records],
            'area_ratio': [r[4] for r in size_records],
        },
        geometry=[reef_edit.geometry.loc[r[1]] for r in size_records],
        crs='EPSG:4283',
    )
    write_review_layer(size_changes, 'extreme-size-changes')

    # 6.4 Override points that are obsolete or no longer needed
    overrides = gpd.GeoDataFrame(
        {
            'ACTION': [p[1] for p in override_problems],
            'ReefID': [p[2] for p in override_problems],
            'reason': [p[3] for p in override_problems],
        },
        geometry=[remove_move.geometry.loc[p[0]] for p in override_problems],
        crs='EPSG:4283',
    )
    write_review_layer(overrides, 'override-problems')

    # 6.5 Old features surviving inside the comprehensively remapped inshore area
    inshore = gpd.read_file(inshore_extent_path).to_crs(epsg=4283)
    inshore_union = unary_union(inshore.geometry)
    survivors = sorted(set(gbr.index[~filter_mask]) - all_delete)
    gap_idx = [i for i in survivors
               if gbr.geometry.loc[i].intersects(inshore_union)]
    gaps = gbr.loc[gap_idx, ['LABEL_ID', 'CODE', 'FEAT_NAME', 'geometry']].copy()
    gaps = gaps.rename(columns={'LABEL_ID': 'ReefID'})
    gaps['area_km2'] = [gbr_areas.loc[i] / 1e6 for i in gap_idx]
    write_review_layer(gaps, 'inshore-gaps')

    print(f"  Review layers written to {review_path}")

    # ------------------------------------------------------------------
    # Step 7: Apply deletions and the Island/Mainland/Other filter
    # ------------------------------------------------------------------
    print("\nStep 7: Applying deletions and filtering Island/Mainland/Other")
    drop_indices = set(gbr.index[filter_mask]) | all_delete
    original_count = len(gbr)
    gbr = gbr.drop(index=drop_indices).reset_index(drop=True)
    print(f"  Removed {original_count - len(gbr)} features "
          f"({len(all_delete)} move/remove/overlap, rest Island/Mainland/Other), "
          f"{len(gbr)} remaining")

    # ------------------------------------------------------------------
    # Step 8: Prepare retained old features
    # ------------------------------------------------------------------
    print("\nStep 8: Preparing retained old features")
    print(f"  {len(gbr)} GBR features retained")

    # 8.1 Crosswalk
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

    # 8.2 Attachment
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

    # 8.3 EdgeAcc_m
    print("  Computing EdgeAcc_m from area")
    areas_km2 = gbr_3577.geometry.area / 1e6
    gbr['EdgeAcc_m'] = [compute_edge_acc(a) for a in areas_km2]

    # 8.4 Other defaults
    gbr['FeatConf'] = None
    gbr['TypeConf'] = gbr.get('CLASS_CONF', pd.Series(dtype='object')).replace(
        {'LowHigh': 'Low'})
    gbr['DepthCat'] = None
    gbr['DepthCatSr'] = None

    # 8.5 Rename
    rename_map = {'IMG_SRC': 'EdgeSrc', 'LABEL_ID': 'ReefID'}
    gbr = gbr.rename(columns={k: v for k, v in rename_map.items() if k in gbr.columns})
    gbr['ReefFID'] = gbr['ReefID']

    # 8.6 Dataset — retain original
    if 'DATASET' in gbr.columns:
        gbr = gbr.rename(columns={'DATASET': 'Dataset'})

    # 8.7 CODES and PrevReefID
    gbr['CODES'] = gbr['CODE'] if 'CODE' in gbr.columns else None
    gbr['PrevReefID'] = None

    # ------------------------------------------------------------------
    # Step 9: Prepare new features (Reef Edit)
    # ------------------------------------------------------------------
    print("\nStep 9: Preparing Reef Edit features")

    new_features = reef_edit.copy()

    # Assign computed attributes
    new_features['ReefFID'] = new_features.index.map(reef_edit_reeffid)
    new_features['ReefID'] = new_features.index.map(reef_edit_reefid)
    new_features['CODES'] = new_features.index.map(reef_edit_codes_attr)
    new_features['PrevReefID'] = new_features.index.map(reef_edit_prevreefid)
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
    # Step 10: Merge and output
    # ------------------------------------------------------------------
    print("\nStep 10: Merging and saving output")

    # Trim old features to output schema
    output_columns = [
        'RB_Type_L3', 'Attachment', 'DepthCat', 'DepthCatSr',
        'FeatConf', 'TypeConf', 'EdgeSrc', 'EdgeAcc_m',
        'OrigType', 'Dataset', 'ReefFID', 'ReefID', 'CODES', 'PrevReefID',
        # Stage 01e tracking fields (null for legacy records, dropped in stage 03)
        'RE_row', 'RE_part', 'geometry'
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

    # An official identifier should be held by one feature only. The allocation
    # rules guarantee this among the new features, but LABEL_ID is not unique in
    # the source, so a retained old polygon can still share an identifier with
    # another retained polygon or with a new feature. Stage 03 resolves these
    # with -Fnn suffixes, so they are reported rather than treated as an error.
    held = merged.loc[merged['ReefID'].notna(), 'ReefID']
    duplicated = sorted(held[held.duplicated()].unique())
    if duplicated:
        print(f"  NOTE: {len(duplicated)} official ReefID values are shared by more "
              f"than one feature (source LABEL_ID is not unique)")
        share_mask = merged['ReefID'].isin(duplicated)
        write_review_layer(merged[share_mask].sort_values('ReefID'), 'shared-reefid')

    print(f"  Saving {len(merged)} features to {output_path}")
    merged.to_file(output_path)

    # Summary
    print(f"\nDone. Output: {output_path}")
    print(f"  Old features retained: {len(gbr_out)}")
    print(f"  New features added: {len(new_out)}")
    print(f"  Total: {len(merged)}")


if __name__ == "__main__":
    main()
