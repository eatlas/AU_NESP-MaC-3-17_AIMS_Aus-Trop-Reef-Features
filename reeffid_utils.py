"""Allocate dataset polygon identifiers without changing official reef identifiers.

An official ``ReefID`` is not necessarily unique per polygon. For example, a reef
and its associated rock or cay can share the same source identifier. ``ReefFID``
distinguishes individual features in the national dataset, while ``ReefID`` keeps
the authority's identifier unchanged. A shared allocator is needed to resolve
these legitimate duplicates and enforce non-null, unique feature identifiers
across the combined regional inputs.

``03-merge-TS-GBR-CS-NW.py`` calls ``allocate_reeffids`` after concatenating the
Torres Strait/Great Barrier Reef, Coral Sea and north/west Australian features,
before writing the merged shapefile. Stage 02a supplies inherited official IDs
or provisional ``PROV-{lat}-{lon}`` feature IDs. Stages 02b and 02c retain existing
feature IDs, leaving first allocation to stage 03.

Allocation fills missing feature IDs from official IDs and uses ``-F01``,
``-F02``, etc. to distinguish polygons sharing an ID. These suffixes belong only
to ``ReefFID``; they are not new official reef identifiers. Existing unique
feature IDs are retained where possible, and remaining collisions are resolved
across the whole input. Features without an official ID must already have a
provisional feature ID; this module does not generate provisional IDs or decide
which features inherit official IDs.

Suffix ordering uses source attributes, centroid, area and a geometry hash
rather than input row order. Reproducibility assumes unchanged attributes and
geometry; regeneration is not a verified cross-release feature match. Carry
published ``ReefFID`` values forward on updates instead of relying on allocation
to recognise edited features.

The allocator returns a copy and raises ``ValueError`` for missing identifiers,
duplicated published feature IDs within an official-ID group, or any remaining
non-unique feature IDs. It performs no file I/O.
"""

import hashlib

import pandas as pd


def _normalise_identifier(values):
    """Return identifiers with empty and textual null values replaced by None."""
    normalised = values.astype("object").copy()
    empty = normalised.isna() | normalised.astype(str).str.strip().isin(
        ["", "None", "nan", "<NA>"]
    )
    normalised.loc[empty] = None
    return normalised


def _allocation_sort_key(row):
    """Build a deterministic key for allocating suffixes within a duplicate group."""
    geometry_hash = hashlib.sha1(row.geometry.wkb).hexdigest()
    return (
        str(row.get("CODES") or ""),
        str(row.get("Dataset") or ""),
        str(row.get("RB_Type_L3") or ""),
        round(row.geometry.centroid.y, 8),
        round(row.geometry.centroid.x, 8),
        round(row.geometry.area, 12),
        geometry_hash,
    )


def allocate_reeffids(gdf):
    """Preserve published ReefFIDs and allocate deterministic missing values.

    Official ReefID groups with multiple polygons receive ``-Fnn`` variants.
    Existing unique suffixed values are preserved, so later group members receive
    the next available suffix. A first allocation where every member only carries
    the unsuffixed ReefID assigns suffixes to the whole group.
    """
    result = gdf.copy()
    if "ReefID" not in result.columns:
        result["ReefID"] = None
    if "ReefFID" not in result.columns:
        result["ReefFID"] = None

    result["ReefID"] = _normalise_identifier(result["ReefID"])
    result["ReefFID"] = _normalise_identifier(result["ReefFID"])

    used_ids = set(result["ReefFID"].dropna())
    official_groups = result[result["ReefID"].notna()].groupby("ReefID").groups
    for reef_id, group_index in sorted(official_groups.items()):
        group_indices = list(group_index)
        existing = result.loc[group_indices, "ReefFID"]
        if len(group_indices) == 1:
            if existing.isna().all():
                result.at[group_indices[0], "ReefFID"] = reef_id
                used_ids.add(reef_id)
            continue

        published_mask = existing.notna() & (existing != reef_id)
        unsuffixed_mask = existing == reef_id
        if unsuffixed_mask.sum() == 1 and existing.isna().any():
            published_mask = published_mask | unsuffixed_mask
        published_ids = existing[published_mask]
        if published_ids.duplicated().any():
            raise ValueError(f"Published ReefFID values are duplicated for ReefID {reef_id}")

        unresolved = [idx for idx in group_indices if not published_mask.loc[idx]]
        unresolved.sort(key=lambda idx: _allocation_sort_key(result.loc[idx]))
        suffix = 1
        for idx in unresolved:
            candidate = f"{reef_id}-F{suffix:02d}"
            while candidate in used_ids:
                suffix += 1
                candidate = f"{reef_id}-F{suffix:02d}"
            result.at[idx, "ReefFID"] = candidate
            used_ids.add(candidate)
            suffix += 1

    # Features without an official ReefID must already carry a provisional ReefFID.
    missing_fid = result["ReefFID"].isna()
    if missing_fid.any():
        missing_count = int(missing_fid.sum())
        raise ValueError(f"{missing_count} features have neither ReefFID nor ReefID")

    duplicate_mask = result["ReefFID"].duplicated(keep=False)
    for duplicate_value in sorted(result.loc[duplicate_mask, "ReefFID"].unique()):
        group_indices = result.index[result["ReefFID"] == duplicate_value].tolist()
        group_indices.sort(key=lambda idx: _allocation_sort_key(result.loc[idx]))
        for suffix, idx in enumerate(group_indices, start=1):
            candidate = f"{duplicate_value}-F{suffix:02d}"
            while candidate in used_ids:
                suffix += 1
                candidate = f"{duplicate_value}-F{suffix:02d}"
            result.at[idx, "ReefFID"] = candidate
            used_ids.add(candidate)

    if result["ReefFID"].duplicated().any():
        raise ValueError("ReefFID allocation did not produce unique values")

    return result