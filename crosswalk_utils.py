"""
Utility module for loading and validating features against the RB_Type_L3 crosswalk table.

Used by:
    - 03-merge-TS-GBR-CS-NW.py (early validation of RB_Type_L3 + Attachment)
    - 06-crosswalk.py (full validation including DepthCat)
"""

import os
import pandas as pd
import configparser


def load_crosswalk():
    """Load and prepare the crosswalk CSV from the path specified in config.ini.
    
    Returns:
        pd.DataFrame: Crosswalk table with parsed list columns for Attachment_v0-4 and DepthCat_v0-4.
    """
    config = configparser.ConfigParser()
    config.read('config.ini')
    in_3p_path = config.get('general', 'in_3p_path')
    nw_aus_feat_version = config.get('general', 'nw_aus_feat_version')

    crosswalk_csv = os.path.join(in_3p_path, f'NW-Aus-Feat_{nw_aus_feat_version}', 'in',
                                 'RB_Type_L3_crosswalk.csv')

    crosswalk = pd.read_csv(crosswalk_csv, dtype=str).fillna('')

    # Parse semicolon-separated lists
    crosswalk['Attachment_v0-4_list'] = (
        crosswalk['Attachment_v0-4'].str.split(';')
        .apply(lambda lst: [x.strip() for x in lst if x.strip()])
    )
    crosswalk['DepthCat_v0-4_list'] = (
        crosswalk['DepthCat_v0-4'].str.split(';')
        .apply(lambda lst: [x.strip() for x in lst if x.strip()])
    )

    return crosswalk


def build_crosswalk_lookup(crosswalk):
    """Build a lookup dictionary keyed by RB_Type_L3_v0-4.
    
    Returns:
        dict: {rb_type_l3: [(crosswalk_index, attachment_list, depthcat_list), ...]}
    """
    lookup = {}
    for idx, row in crosswalk.iterrows():
        key = row['RB_Type_L3_v0-4']
        lookup.setdefault(key, []).append(
            (idx, row['Attachment_v0-4_list'], row['DepthCat_v0-4_list'])
        )
    return lookup


def validate_features(gdf, crosswalk, check_depthcat=False):
    """Validate features against the crosswalk table.
    
    Checks that each feature's (RB_Type_L3, Attachment) combination exists in the
    crosswalk. Optionally also checks DepthCat.

    Args:
        gdf: GeoDataFrame with RB_Type_L3 and Attachment columns (and DepthCat if check_depthcat=True).
        crosswalk: DataFrame returned by load_crosswalk().
        check_depthcat: If True, also validate DepthCat against crosswalk.

    Returns:
        tuple: (match_indices, crosswalk_indices, mismatched_indices)
            - match_indices: list of gdf indices that matched
            - crosswalk_indices: list of corresponding crosswalk indices
            - mismatched_indices: list of gdf indices that did not match
    """
    lookup = build_crosswalk_lookup(crosswalk)

    match_indices = []
    crosswalk_indices = []
    mismatched_indices = []

    has_depthcat_col = 'DepthCat' in gdf.columns

    for i, feat in gdf.iterrows():
        key = feat['RB_Type_L3']
        attachment = feat['Attachment']
        candidates = lookup.get(key, [])
        found = False

        # Determine whether to check DepthCat for this feature:
        # - Always check if check_depthcat is True
        # - Also check if the feature has a non-empty DepthCat value available
        depthcat = None
        if has_depthcat_col:
            val = feat['DepthCat']
            if pd.notna(val) and str(val).strip():
                depthcat = str(val).strip()

        use_depthcat = check_depthcat or depthcat is not None

        if use_depthcat and depthcat is not None:
            for idx, attachment_list, depthcat_list in candidates:
                if attachment in attachment_list and depthcat in depthcat_list:
                    match_indices.append(i)
                    crosswalk_indices.append(idx)
                    found = True
                    break
        else:
            for idx, attachment_list, depthcat_list in candidates:
                if attachment in attachment_list:
                    match_indices.append(i)
                    crosswalk_indices.append(idx)
                    found = True
                    break

        if not found:
            mismatched_indices.append(i)

    return match_indices, crosswalk_indices, mismatched_indices
