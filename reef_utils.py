"""
Module: reef_utils.py

Shared utilities for reef processing scripts.

Stage 05 and stage 08 share LPT lookup, DEM fallback and depth percentile
calculations here. Depth category assignment is separate from DEM statistics.

Copied from NW-Aus-Features reef_utils.py for national L2 generation
(08-make-RB_Type_L2.py) and countable-reef clustering (A05).

The key operations are:
    - Geometry cleaning (buffer(0)) to fix invalid topologies
    - Dissolve by RB_Type_L2 class via unary_union
    - Sliver repair (buffer(+eps).buffer(-eps)) to close floating-point
      precision gaps along feature boundaries
    - Consistent spatial join to assign original features to dissolved components
    - cluster_countable(): buffer-based grouping of fused reefs into
      countable clusters
"""

import os
from contextlib import ExitStack
from functools import lru_cache
from time import perf_counter

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

# Small buffer (degrees) used to close floating-point slivers/gaps after dissolve.
# Applied as buffer(+eps).buffer(-eps): the outward pass seals sub-pixel holes along
# internal seams; the inward pass restores the outer boundary to its original extent.
# At these latitudes (~15-25S), 1e-6 degrees ~ 0.1 m.
SLIVER_EPS = 1e-6


DEM_PERCENTILE_FIELDS = (
    "DEM10pMSL", "DEM50pMSL", "DEM90pMSL",
    "DEM10pLAT", "DEM50pLAT", "DEM90pLAT",
)
DEM_FIELDS = (*DEM_PERCENTILE_FIELDS, "DEMSr")

# NoData declared by the MultiResBathyEEZ 2024 GeoTIFFs and their VRT.
# Stored as float32, 3.4e+38 is represented as 3.3999999521443642e+38.
MULTIRES_BATHY_NODATA = 3.4e+38
# NoData declared by the AusBathyTopo 250 m 2024 GeoTIFF (not an elevation).
AUS_BATHY_TOPO_NODATA = -32767.0


@lru_cache(maxsize=32)
def _depth_transformer(source_crs, target_crs):
    """Reuse the small set of CRS transformations needed for DEM sampling."""
    import pyproj

    return pyproj.Transformer.from_crs(source_crs, target_crs, always_xy=True)


class LPTLookup:
    """Load LPT values and their source label for stage 05 and L2 calculations."""

    def __init__(self, lpt_path, source_name: str = "EOT20"):
        import rasterio

        self.source_name = source_name
        print(f"Loading LPT raster into memory from {lpt_path} ...")
        with rasterio.open(lpt_path) as src:
            self.data = src.read(1)
            self.transform = src.transform
            self.crs = src.crs
            self.nodata = src.nodata
            self.bounds = src.bounds
            self.height = src.height
            self.width = src.width
        print(f"  LPT raster loaded: {self.width}x{self.height} pixels, "
              f"bounds: {self.bounds}, nodata: {self.nodata}")

    def get_value(self, x, y):
        """Return LPT at a coordinate in the LPT CRS, or None for missing data."""
        col, row = ~self.transform * (x, y)
        row, col = int(round(row)), int(round(col))
        if row < 0 or row >= self.height or col < 0 or col >= self.width:
            return None
        val = self.data[row, col]
        if self.nodata is not None and val == self.nodata:
            return None
        if np.isnan(val):
            return None
        return float(val)

    def get_values_for_pixels(self, xs, ys):
        """Return LPT for coordinate arrays in its CRS, with NaN for missing data."""
        cols, rows = ~self.transform * (xs, ys)
        rows = np.round(rows).astype(int)
        cols = np.round(cols).astype(int)
        result = np.full(len(xs), np.nan)
        valid = (rows >= 0) & (rows < self.height) & (cols >= 0) & (cols < self.width)
        if np.any(valid):
            vals = self.data[rows[valid], cols[valid]]
            if self.nodata is not None:
                vals = np.where(vals == self.nodata, np.nan, vals)
            result[valid] = vals
        return result

    def get_values_for_coords(self, xs, ys, source_crs):
        """Look up LPT, reprojecting coordinates from source_crs when needed."""
        if source_crs is not None and self.crs is not None and source_crs != self.crs:
            transformer = _depth_transformer(source_crs, self.crs)
            xs, ys = transformer.transform(xs, ys)
        return self.get_values_for_pixels(xs, ys)


def prepare_depth_rasters(download_path, vrt_path):
    """Prepare the stage 05 DEM mosaic and return the shared DEM fallback order."""
    if not os.path.exists(vrt_path):
        from osgeo import gdal

        os.makedirs(os.path.dirname(os.path.abspath(vrt_path)), exist_ok=True)
        print(f"Creating MultiResBathyEEZ VRT at {vrt_path} ...")
        tifs = [
            os.path.join(download_path, "MultiRes-Bathy-EEZ_2024", filename)
            for filename in ("01_shallow_bathy.tif", "02_mesophotic_bathy.tif")
        ]
        missing = [path for path in tifs if not os.path.exists(path)]
        if missing:
            raise FileNotFoundError(f"Missing MultiResBathyEEZ inputs: {missing}")
        vrt = gdal.BuildVRT(os.fspath(vrt_path), tifs)
        if vrt is None:
            raise RuntimeError(f"Could not create depth mosaic: {vrt_path}")
        vrt = None
        print("MultiResBathyEEZ VRT created.")
    return [
        (os.fspath(vrt_path), MULTIRES_BATHY_NODATA, "MultiResBathyEEZ_2024"),
        (os.path.join(download_path, "AusBathyTopo-250m_2024",
                      "AusBathyTopo__Australia__2024_250m_MSL_cog.tif"),
         AUS_BATHY_TOPO_NODATA, "AusBathyTopo-250m_2024"),
    ]


def get_pixel_coordinates(out_image, out_transform):
    """Return pixel-centre coordinate grids for a band-first raster array."""
    nrows, ncols = out_image.shape[1:]
    cols, rows = np.meshgrid(np.arange(ncols), np.arange(nrows))
    xs = out_transform.c + (cols + 0.5) * out_transform.a + (rows + 0.5) * out_transform.b
    ys = out_transform.f + (cols + 0.5) * out_transform.d + (rows + 0.5) * out_transform.e
    return xs, ys


def get_percentiles_with_lat(geometry, raster_src, nodata_val, lpt_lookup,
                             feature_idx=None, geometry_crs=None, raster_crs=None):
    """Return 10th, 50th and 90th percentiles for MSL and per-pixel DEM minus LPT.

    Use the original polygon's centroid when no valid pixel centres fall inside.
    Missing LPT leaves the MSL statistics intact. Non-overlapping DEMs return
    null statistics so the next DEM can be tried.
    """
    from rasterio.mask import mask
    from shapely.geometry import mapping
    from shapely.ops import transform as shapely_transform

    geom_proj = geometry
    if geometry_crs is not None and raster_crs is not None and geometry_crs != raster_crs:
        project = _depth_transformer(geometry_crs, raster_crs).transform
        geom_proj = shapely_transform(project, geometry)
    try:
        out_image, out_transform = mask(
            raster_src, [mapping(geom_proj)], crop=True, all_touched=False,
            nodata=nodata_val)
    except ValueError as exc:
        if str(exc) != "Input shapes do not overlap raster.":
            raise
        print(f"No DEM overlap for feature {feature_idx}: {exc}")
        return (None,) * 6
    arr = out_image[0]
    valid_mask = (arr != nodata_val) & (~np.isnan(arr))
    if not np.any(valid_mask):
        centroid = geometry.centroid
        if geometry_crs is not None and raster_crs is not None and geometry_crs != raster_crs:
            centroid_proj = shapely_transform(project, centroid)
        else:
            centroid_proj = centroid
        val = next(raster_src.sample([(centroid_proj.x, centroid_proj.y)]))[0]
        if val == nodata_val or np.isnan(val):
            return (None,) * 6
        dem_msl = float(val)
        if (geometry_crs is not None and lpt_lookup.crs is not None
                and geometry_crs != lpt_lookup.crs):
            project_to_lpt = _depth_transformer(geometry_crs, lpt_lookup.crs).transform
            centroid = shapely_transform(project_to_lpt, centroid)
        lpt_val = lpt_lookup.get_value(centroid.x, centroid.y)
        if lpt_val is None:
            return dem_msl, dem_msl, dem_msl, None, None, None
        dem_lat = dem_msl - lpt_val
        return dem_msl, dem_msl, dem_msl, dem_lat, dem_lat, dem_lat

    xs, ys = get_pixel_coordinates(out_image, out_transform)
    valid_msl = arr[valid_mask]
    lpt_values = lpt_lookup.get_values_for_coords(
        xs[valid_mask], ys[valid_mask], raster_crs)
    valid_lat = valid_msl - lpt_values
    lat_valid = valid_lat[~np.isnan(valid_lat)]
    msl = tuple(float(np.nanpercentile(valid_msl, percentile)) for percentile in (10, 50, 90))
    lat = (tuple(float(np.nanpercentile(lat_valid, percentile)) for percentile in (10, 50, 90))
           if lat_valid.size else (None,) * 3)
    return (*msl, *lat)


def assign_depth_percentiles(geometry, rasters, lpt_lookup, feature_idx=None, geometry_crs=None):
    """Try DEMs in fallback order; append the LPT source when LAT statistics exist."""
    for src, nodata_val, src_name in rasters:
        result = get_percentiles_with_lat(
            geometry, src, nodata_val, lpt_lookup,
            feature_idx=feature_idx, geometry_crs=geometry_crs, raster_crs=src.crs)
        if all(value is not None for value in result[:3]):
            has_lat_statistics = all(pd.notna(value) for value in result[3:])
            depth_source = f"{src_name};{lpt_lookup.source_name}" if has_lat_statistics else src_name
            return (*result, depth_source)
    print(f"WARNING: No valid raster found for feature {feature_idx}. "
          f"Geometry bounds: {geometry.bounds}")
    return (None,) * 7


def calculate_depth_statistics(reefs, rasters, lpt_lookup):
    """Calculate fresh DEM attributes, without changing geometry or depth categories.

    Return an index-aligned DataFrame containing the six percentiles rounded to
    one decimal place and DEMSr (DEM name, then semicolon-separated LPT source
    when LAT statistics exist). DEMs stay open for this serial pass and are
    closed on completion or error. Both stages use the same polygon sampling.
    """
    import rasterio

    print("Calculating depth percentiles (MSL and LAT) within each reef polygon...")
    rows = []
    with ExitStack() as stack:
        opened_rasters = []
        for raster_path, nodata_val, src_name in rasters:
            if not os.path.exists(raster_path):
                print(f"WARNING: Skipping missing depth raster: {raster_path}")
                continue
            src = stack.enter_context(rasterio.open(raster_path))
            opened_rasters.append((src, nodata_val, src_name))
        for position, (idx, geometry) in enumerate(reefs.geometry.items()):
            if position % 1000 == 0:
                print(f"Processing feature {position + 1}/{len(reefs)}...", flush=True)
            rows.append(assign_depth_percentiles(
                geometry, opened_rasters, lpt_lookup, feature_idx=idx, geometry_crs=reefs.crs))
    statistics = pd.DataFrame(rows, index=reefs.index, columns=DEM_FIELDS)
    for field in DEM_PERCENTILE_FIELDS:
        statistics[field] = [
            round(value, 1) if pd.notna(value) else None for value in statistics[field]
        ]
    return statistics


def repair_slivers(geom, show_progress=False):
    """Close seams with buffer(+eps).buffer(-eps), keeping geom if the repair changes its area.

    Buffer multipart polygons in bounded groups, unioning outward buffers
    before the inward pass so nearby parts can still join across small gaps.
    GEOS can return an empty result for valid polygons with such tiny buffers,
    for example in EPSG:3112 where coordinates are ~1e6 m.
    """
    if isinstance(geom, MultiPolygon):
        def buffer_parts(parts, distance, label):
            buffered = []
            for start in range(0, len(parts), 1000):
                group = MultiPolygon(parts[start:start + 1000])
                buffered.append(group.buffer(distance))
                if show_progress:
                    position = min(start + 1000, len(parts))
                    print(f"    {label}: {position}/{len(parts)} parts", flush=True)
            return buffered

        expanded = buffer_parts(list(geom.geoms), SLIVER_EPS, "Expanding")
        if show_progress:
            print("    Merging expanded boundaries...", flush=True)
        expanded = expanded[0] if len(expanded) == 1 else unary_union(expanded)
        contracted = buffer_parts(_polygon_parts(expanded), -SLIVER_EPS, "Contracting")
        repaired = MultiPolygon([part for group in contracted for part in _polygon_parts(group)])
    else:
        repaired = geom.buffer(SLIVER_EPS).buffer(-SLIVER_EPS)
    if repaired.is_empty or abs(repaired.area - geom.area) > 1e-6 * geom.area:
        return geom
    return repaired


def _simplify_l2_boundaries(geom):
    """Bound multipart topology work and reject cross-group overlaps."""
    if not isinstance(geom, MultiPolygon) or len(geom.geoms) <= 1000:
        return geom.simplify(SLIVER_EPS, preserve_topology=True)
    parts = list(geom.geoms)
    simplified = []
    for start in range(0, len(parts), 1000):
        group = MultiPolygon(parts[start:start + 1000])
        simplified.extend(_polygon_parts(
            group.simplify(SLIVER_EPS, preserve_topology=True)))
        print(f"    Simplifying: {min(start + 1000, len(parts))}/{len(parts)} parts",
              flush=True)
    candidate = MultiPolygon(simplified)
    print("    Validating simplified boundaries...", flush=True)
    if not candidate.is_valid:
        print("WARNING: Grouped simplification produced invalid topology; "
              "retaining unsimplified boundaries.", flush=True)
        return geom
    return candidate


def dissolve_to_l2_components(gdf):
    """
    Dissolve features by RB_Type_L2 into singlepart components.

    Applies geometry cleaning (buffer(0)) and sliver repair
    (buffer(+eps).buffer(-eps)) to ensure consistent grouping regardless
    of floating-point precision artifacts at feature boundaries.

    Parameters
    ----------
    gdf : GeoDataFrame
        Must contain 'RB_Type_L2' column and geometry.

    Returns
    -------
    list of dict
        Each dict has:
        - 'l2_class': str - the RB_Type_L2 class
        - 'geometry': shapely geometry - the dissolved singlepart polygon
        - 'member_indices': list of int - original feature indices in this component
    """
    # Clean geometries to fix invalid topologies
    print(f"  Cleaning {len(gdf)} source geometries...", flush=True)
    gdf = gdf.copy()
    gdf['geometry'] = gdf.geometry.buffer(0)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    components = []

    for l2_class, class_gdf in gdf.groupby('RB_Type_L2'):
        started = perf_counter()
        print(f"  Dissolving {len(class_gdf)} source parts: {l2_class}", flush=True)
        # Union all features of this L2 class
        print("    Unioning source boundaries...", flush=True)
        union_geom = unary_union(class_gdf.geometry)
        print(f"    Union complete ({perf_counter() - started:.1f}s elapsed). "
              "Repairing seams...", flush=True)
        # Close floating-point slivers/gaps produced by the dissolve
        union_geom = repair_slivers(union_geom, show_progress=True)
        print(f"    Seam repair complete ({perf_counter() - started:.1f}s elapsed). "
              "Simplifying boundaries...", flush=True)
        # Remove redundant micro-vertices introduced by the buffer arcs
        union_geom = _simplify_l2_boundaries(union_geom)
        print(f"    Simplification complete ({perf_counter() - started:.1f}s elapsed). "
              "Checking source coverage...", flush=True)
        # Explode into singlepart components (each = one reef)
        parts_gdf = gpd.GeoDataFrame(
            geometry=[union_geom], crs=gdf.crs
        ).explode(index_parts=False).reset_index(drop=True)
        matched, _ = parts_gdf.sindex.query(class_gdf.geometry, predicate='intersects')
        missing_positions = np.setdiff1d(np.arange(len(class_gdf)), matched)
        if len(missing_positions):
            # Aggregate area checks can hide the complete loss of a source part.
            missing = class_gdf.iloc[missing_positions]
            fields = [field for field in ('SourceRow', 'ReefID', 'ReefFID')
                      if field in missing.columns]
            details = (missing[fields].head(10).to_dict('records') if fields
                       else missing.index.tolist()[:10])
            print(f"WARNING: Restoring {len(missing)} {l2_class} source parts lost "
                  f"during seam repair/simplification; first affected parts: "
                  f"{details}", flush=True)
            union_geom = unary_union([union_geom, *missing.geometry])
            parts_gdf = gpd.GeoDataFrame(
                geometry=[union_geom], crs=gdf.crs
            ).explode(index_parts=False).reset_index(drop=True)
        parts_gdf['_part_id'] = range(len(parts_gdf))
        print(f"    Assigning {len(class_gdf)} source parts to "
              f"{len(parts_gdf)} components...", flush=True)

        # Assign each original feature to its dissolved group via representative_point.
        # representative_point() is guaranteed to lie within the feature polygon,
        # making it robust for within-polygon matching.
        feat_points = class_gdf.copy()
        feat_points['_orig_idx'] = feat_points.index
        feat_points['geometry'] = feat_points.geometry.representative_point()

        joined = gpd.sjoin(
            feat_points[['_orig_idx', 'geometry']],
            parts_gdf[['_part_id', 'geometry']],
            predicate='within',
            how='left'
        )

        # Handle features whose representative_point didn't fall within any part
        # (rare floating-point edge case): fall back to intersects with original geometry
        unassigned = joined[joined['_part_id'].isna()]
        if not unassigned.empty:
            unassigned_indices = unassigned['_orig_idx'].tolist()
            unassigned_feats = class_gdf.loc[unassigned_indices].copy()
            unassigned_feats['_orig_idx'] = unassigned_feats.index

            fallback_join = gpd.sjoin(
                unassigned_feats[['_orig_idx', 'geometry']],
                parts_gdf[['_part_id', 'geometry']],
                predicate='intersects',
                how='left'
            )
            # Drop duplicates (feature might intersect multiple parts; take first)
            fallback_join = fallback_join.drop_duplicates(subset='_orig_idx')

            # Update the main joined dataframe with fallback assignments
            for _, row in fallback_join.iterrows():
                mask = joined['_orig_idx'] == row['_orig_idx']
                joined.loc[mask, '_part_id'] = row['_part_id']

        # Still unassigned after fallback (should not happen but be safe)
        still_unassigned = joined[joined['_part_id'].isna()]
        if not still_unassigned.empty:
            raise ValueError(
                f"{len(still_unassigned)} features of class '{l2_class}' "
                "could not be assigned to any dissolved component")

        assigned_parts = joined.dropna(subset=['_part_id']).groupby('_part_id')
        component_count = assigned_parts.ngroups
        for position, (part_id, part_feats) in enumerate(assigned_parts, start=1):
            member_indices = part_feats['_orig_idx'].tolist()
            part_geom = parts_gdf.geometry.iloc[int(part_id)]

            components.append({
                'l2_class': l2_class,
                'geometry': part_geom,
                'member_indices': member_indices,
            })
            if position % 1000 == 0 or position == component_count:
                print(f"    Building components: {position}/{component_count}",
                      flush=True)
        print(f"  {l2_class} complete ({perf_counter() - started:.1f}s elapsed).",
              flush=True)

    return components


def cluster_countable(gdf, buffer_m=50.0, min_width_m=100.0, drop_small=True,
                      size_classes=None, buffer_crs=3577, show_progress=False):
    """
    Cluster fused reefs into "countable reefs".

    Grouping: each reef is buffered by buffer_m (in buffer_crs) and the
    buffers are unary-unioned per RB_Type_L2 class, so reefs within the
    buffer of each other merge into a single cluster only with reefs of
    the same type. The buffer is used ONLY to determine the grouping;
    it does not enter any measurement.

    Measurement: each cluster is mapped back to its original (unbuffered)
    member reefs, whose geometries are unioned (closely clustered reefs
    form multi-part polygons). The cluster's area and effective width are
    computed from that unbuffered union, so areas are true reef areas.
    Clusters with an effective width below min_width_m are dropped when
    drop_small is True; the survivors may be binned into size classes.

    Parameters
    ----------
    gdf : GeoDataFrame
        Fused reefs (e.g. the output of A04-reef-progression.py's
        process_version, before size classification). Must contain an
        'RB_Type_L2' column and Polygon/MultiPolygon geometries in a
        non-null CRS.
    buffer_m : float
        Buffer distance in metres (in buffer_crs), used only to decide
        the grouping.
    min_width_m : float
        Effective width (m, diameter of an equal-area circle) below
        which a cluster is not "countable".
    drop_small : bool
        If True (default), clusters with effective width below min_width_m
        are dropped; if False they are retained.
    size_classes : list of (name, lo_m, hi_m) or None
        If given, an 'SizeClass' column is added (lo inclusive, hi
        exclusive). If None, no size class is calculated.
    buffer_crs : int or pyproj.CRS
        Projected (metre) CRS in which the buffer and union are computed.
        Defaults to EPSG:3577 (Australian Albers, equal-area). The output is
        returned in the input CRS.
    show_progress : bool
        Print per-class clustering milestones and the number of clusters
        processed when True. Off by default for existing callers.

    Returns
    -------
    (GeoDataFrame, dict)
        The countable reefs (in the input CRS) with 'RB_Type_L2',
        'Area_km2', 'EffWidth_m' and (if size_classes was given)
        'SizeClass', plus a stats dict with keys 'n_fused',
        'n_clusters', 'n_dropped', 'n_countable', 'n_unassigned' and
        'n_by_class'.
    """
    if not isinstance(gdf, gpd.GeoDataFrame):
        raise TypeError(f"gdf must be a GeoDataFrame, got {type(gdf).__name__}")
    if 'RB_Type_L2' not in gdf.columns:
        raise ValueError(
            "gdf must contain an 'RB_Type_L2' column: each reef's L2 class "
            "is required for the per-class clustering. "
            f"Columns present: {list(gdf.columns)}"
        )
    if gdf.crs is None:
        raise ValueError(
            "gdf must have a non-null CRS (the output is returned in the "
            "input CRS)."
        )
    n_null_class = int(gdf['RB_Type_L2'].isna().sum())
    if n_null_class:
        raise ValueError(f"{n_null_class} features have a null RB_Type_L2")
    bad_geoms = gdf.geometry[
        ~gdf.geometry.apply(lambda g: isinstance(g, (Polygon, MultiPolygon)))
    ]
    if not bad_geoms.empty:
        kinds = sorted(bad_geoms.geom_type.unique())
        raise ValueError(
            f"gdf must contain only Polygon/MultiPolygon geometries, found "
            f"{len(bad_geoms)} of type {kinds}"
        )
    if buffer_m < 0:
        raise ValueError(f"buffer_m must be >= 0, got {buffer_m}")
    if min_width_m < 0:
        raise ValueError(f"min_width_m must be >= 0, got {min_width_m}")

    projected = gdf.to_crs(buffer_crs)

    all_rows = []
    total_clusters = 0
    total_dropped = 0
    total_unassigned = 0

    for l2_class, class_gdf in projected.groupby('RB_Type_L2'):
        if show_progress:
            print(f"  {l2_class}: buffering and grouping "
                  f"{len(class_gdf)} reefs", flush=True)

        # Grouping: buffered union per L2 class -> single-part cluster
        # boundaries. Only reefs of the same type can fall into the same
        # cluster.
        union = unary_union(class_gdf.geometry.buffer(buffer_m))
        comps = (
            gpd.GeoDataFrame(geometry=[union], crs=projected.crs)
            .explode(index_parts=False)
            .reset_index(drop=True)
        )
        comps['_comp_id'] = range(len(comps))
        n_clusters = len(comps)
        if show_progress:
            print(f"  {l2_class}: assigning reefs to {n_clusters} clusters",
                  flush=True)

        # Assign each member reef to its cluster via representative point
        # (guaranteed to lie inside the reef, hence inside one cluster),
        # with an intersects fallback for rare floating-point edge cases
        # (same approach as dissolve_to_l2_components).
        members = class_gdf.copy()
        members['_member_idx'] = members.index
        members['geometry'] = members.geometry.representative_point()
        joined = gpd.sjoin(
            members[['_member_idx', 'geometry']],
            comps[['_comp_id', 'geometry']],
            predicate='within',
            how='left',
        )
        unassigned = joined[joined['_comp_id'].isna()]
        if not unassigned.empty:
            un_feats = class_gdf.loc[
                unassigned['_member_idx'].tolist(), ['geometry']
            ].copy()
            un_feats['_member_idx'] = un_feats.index
            un_feats['geometry'] = un_feats.geometry.representative_point()
            fallback = gpd.sjoin(
                un_feats, comps[['_comp_id', 'geometry']],
                predicate='intersects', how='left',
            ).drop_duplicates(subset='_member_idx')
            for _, row in fallback.iterrows():
                joined.loc[joined['_member_idx'] == row['_member_idx'],
                           '_comp_id'] = row['_comp_id']
            still = joined[joined['_comp_id'].isna()]
            if not still.empty:
                total_unassigned += len(still)
                print(f"  WARNING: {len(still)} '{l2_class}' reefs could not "
                      f"be assigned to a cluster")

        # Build output rows per cluster
        processed_clusters = 0
        report_every = max(1, n_clusters // 20)
        for comp_id, member_reefs in joined.dropna(subset=['_comp_id']
                                                   ).groupby('_comp_id'):
            processed_clusters += 1
            member_idx = member_reefs['_member_idx'].tolist()
            geom = unary_union(class_gdf.loc[member_idx, 'geometry'])
            # Sliver repair (same as dissolve_to_l2_components) to clean
            # internal seams without changing the extent or the area.
            geom = repair_slivers(geom)
            geom = geom.simplify(SLIVER_EPS, preserve_topology=True)
            area_m2 = geom.area
            eff_width = 2.0 * np.sqrt(area_m2 / np.pi)
            if drop_small and eff_width < min_width_m:
                total_dropped += 1
            else:
                all_rows.append({
                    'RB_Type_L2': l2_class,
                    'Area_km2': area_m2 / 1e6,
                    'EffWidth_m': eff_width,
                    'geometry': geom,
                })
            if show_progress and (processed_clusters % report_every == 0 or
                                  processed_clusters == n_clusters):
                print(f"  {l2_class}: {processed_clusters}/{n_clusters} "
                      "clusters processed", flush=True)

        total_clusters += n_clusters

    out = gpd.GeoDataFrame(
        all_rows, columns=['RB_Type_L2', 'Area_km2', 'EffWidth_m', 'geometry'],
        crs=projected.crs
    ).to_crs(gdf.crs)
    if size_classes is not None:
        bins = [lo for _, lo, _ in size_classes] + [np.inf]
        labels = [name for name, _, _ in size_classes]
        out['SizeClass'] = pd.cut(
            out['EffWidth_m'], bins=bins, labels=labels, include_lowest=True
        )

    stats = {
        'n_fused': len(gdf),
        'n_clusters': total_clusters,
        'n_dropped': total_dropped,
        'n_countable': len(out),
        'n_unassigned': total_unassigned,
        'n_by_class': (out['RB_Type_L2'].value_counts().to_dict()
                       if not out.empty else {}),
    }
    return out, stats

# ---------------------------------------------------------------------------
# Coastline clipping (stages 01e and 02d)
# ---------------------------------------------------------------------------

# Processing CRS for clipping and the CRS of the stage 02a output.
CLIP_CRS = 'EPSG:4283'
# Equal-area CRS used for square-metre measurements.
AREA_CRS = 'EPSG:3577'
# Approximate mapping resolution: one 10 m x 10 m Sentinel-2 pixel.
MIN_PART_AREA_M2 = 100.0

LOCKED_FILE_MESSAGE = ("This file is probably open in QGIS or another program. "
                       "Remove the layer or close the project, then rerun.")
SHAPEFILE_SIDECARS = ('.shp', '.shx', '.dbf', '.prj', '.cpg', '.qix', '.sbn',
                      '.sbx', '.fix', '.qmd', '.shp.xml')


class ClipError(Exception):
    """A geometry operation failed or produced an invalid result.

    step names the processing step so the caller can report it with its own
    source reference. No repair is attempted.
    """

    def __init__(self, step, detail):
        super().__init__(f"{step}: {detail}")
        self.step = step
        self.detail = detail


class OutputLockedError(Exception):
    """An owned output file could not be deleted or written."""

    def __init__(self, path, detail):
        super().__init__(f"{path}: {detail}")
        self.path = path
        self.detail = detail


def remove_shapefile(path):
    """Delete a shapefile and its sidecars, raising OutputLockedError on failure."""
    import os
    base = path[:-4] if path.lower().endswith('.shp') else path
    for ext in SHAPEFILE_SIDECARS:
        candidate = base + ext
        if os.path.exists(candidate):
            try:
                os.remove(candidate)
            except OSError as exc:
                raise OutputLockedError(candidate, exc) from exc


def write_shapefile(gdf, path):
    """Write a shapefile, raising OutputLockedError if it cannot be written."""
    remove_shapefile(path)
    try:
        gdf.to_file(path)
    except Exception as exc:
        # A partial file must not be left looking like a successful output.
        try:
            remove_shapefile(path)
        except OutputLockedError:
            pass
        raise OutputLockedError(path, exc) from exc


def single_polygon(geom):
    """Return geom as a Polygon, or None if it has two or more components.

    A MultiPolygon with one component is treated as a Polygon.
    """
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon) and len(geom.geoms) == 1:
        return geom.geoms[0]
    return None


def check_polygon_geometries(geoms):
    """Return [(position, problem)] for null, empty, non-polygon or invalid geometries."""
    from shapely.validation import explain_validity
    problems = []
    for i, geom in enumerate(geoms):
        if geom is None:
            problems.append((i, 'null geometry'))
        elif geom.is_empty:
            problems.append((i, 'empty geometry'))
        elif not isinstance(geom, (Polygon, MultiPolygon)):
            problems.append((i, f'non-polygon geometry ({geom.geom_type})'))
        elif not geom.is_valid:
            problems.append((i, explain_validity(geom)))
    return problems


class Coastline:
    """Polygon landmask in CLIP_CRS with a spatial index."""

    def __init__(self, geoms, path, n_exclusions=0, n_land_changed=0):
        from shapely import STRtree
        self.geoms = geoms
        self.path = path
        self.n_exclusions = n_exclusions
        self.n_land_changed = n_land_changed
        self.tree = STRtree(geoms)


def prepare_coastline(path, exclusion_path=None):
    """Validate the landmask, transform it to CLIP_CRS and index it.

    If exclusion_path is supplied, subtract its polygons before indexing.
    Neither input is modified. Missing or invalid exclusions raise ClipError;
    no repair or reef fragment-area filter is applied to the landmask.
    """
    land = gpd.read_file(path)
    if land.crs is None:
        raise ClipError('reading coastline', f"{path} has no defined CRS")
    problems = check_polygon_geometries(land.geometry.values)
    if problems:
        detail = '; '.join(f"coastline record {i + 1}: {p}" for i, p in problems[:20])
        raise ClipError('validating coastline input',
                        f"{len(problems)} invalid records in {path}. {detail}")
    land = land.to_crs(CLIP_CRS)
    problems = check_polygon_geometries(land.geometry.values)
    if problems:
        detail = '; '.join(f"coastline record {i + 1}: {p}" for i, p in problems[:20])
        raise ClipError(f'validating coastline after transformation to {CLIP_CRS}',
                        f"{len(problems)} invalid records from {path}. {detail}")
    geoms = list(land.geometry.values)
    n_exclusions = n_land_changed = 0
    if exclusion_path is not None:
        from shapely.validation import explain_validity
        try:
            exclusions = gpd.read_file(exclusion_path)
        except Exception as exc:
            raise ClipError('reading pier exclusions', f"{exclusion_path}: {exc}") from exc
        if exclusions.crs is None:
            raise ClipError('reading pier exclusions',
                            f"{exclusion_path} has no defined CRS")
        problems = check_polygon_geometries(exclusions.geometry.values)
        if problems:
            detail = '; '.join(f"exclusion record {i + 1}: {p}" for i, p in problems)
            raise ClipError('validating pier exclusions',
                            f"{exclusion_path}: {detail}")
        try:
            exclusions = exclusions.to_crs(CLIP_CRS)
        except Exception as exc:
            raise ClipError(f'transforming pier exclusions to {CLIP_CRS}',
                            f"{exclusion_path}: {exc}") from exc
        problems = check_polygon_geometries(exclusions.geometry.values)
        if problems:
            detail = '; '.join(f"exclusion record {i + 1}: {p}" for i, p in problems)
            raise ClipError(f'validating pier exclusions after transformation to {CLIP_CRS}',
                            f"{exclusion_path}: {detail}")
        n_exclusions = len(exclusions)
        try:
            exclusion_union = unary_union(exclusions.geometry.values)
        except Exception as exc:
            raise ClipError('union of pier exclusions',
                            f"{exclusion_path}: {exc}") from exc
        if not exclusion_union.is_valid:
            raise ClipError('union of pier exclusions',
                            f"{exclusion_path}: {explain_validity(exclusion_union)}")
        try:
            intersecting = np.flatnonzero(
                land.geometry.intersects(exclusion_union).to_numpy())
        except Exception as exc:
            raise ClipError('finding coastline intersecting pier exclusions',
                            f"{path} against {exclusion_path}: {exc}") from exc
        for i in intersecting:
            detail = f"coastline record {i + 1} in {path} against {exclusion_path}"
            try:
                result = geoms[i].difference(exclusion_union)
            except Exception as exc:
                raise ClipError('subtracting pier exclusions from coastline',
                                f"{detail}: {exc}") from exc
            if not result.is_valid:
                raise ClipError('subtracting pier exclusions from coastline',
                                f"{detail}: {explain_validity(result)}")
            try:
                changed = not result.equals(geoms[i])
            except Exception as exc:
                raise ClipError('comparing coastline after pier exclusion',
                                f"{detail}: {exc}") from exc
            if changed:
                geoms[i] = result
                n_land_changed += 1
        geoms = [part for geom in geoms for part in _polygon_parts(geom)]
    return Coastline(np.asarray(geoms, dtype=object), path,
                     n_exclusions, n_land_changed)


_area_transformer = None


def area_m2(geom):
    """Area of a CLIP_CRS geometry in square metres, measured in AREA_CRS."""
    global _area_transformer
    import shapely
    from pyproj import Transformer
    if _area_transformer is None:
        _area_transformer = Transformer.from_crs(CLIP_CRS, AREA_CRS, always_xy=True)
    projected = shapely.transform(
        geom, lambda xy: np.column_stack(_area_transformer.transform(xy[:, 0], xy[:, 1])))
    return projected.area


def _polygon_parts(geom):
    """Polygon components of a valid result, discarding lines and points."""
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    if hasattr(geom, 'geoms'):
        parts = []
        for sub in geom.geoms:
            parts.extend(_polygon_parts(sub))
        return parts
    return []


def clip_polygon(geom, coastline, min_area_m2=MIN_PART_AREA_M2):
    """Subtract the coastline from one valid Polygon in CLIP_CRS.

    Returns (parts, n_fragments_removed, changed). parts is a list of valid
    Polygons; an unchanged feature is returned as [geom]. Parts of an altered
    feature below min_area_m2 (strict less-than, measured in AREA_CRS) are
    removed. Raises ClipError with the failing step; never returns the input
    as a substitute for a failed subtraction.
    """
    from shapely.validation import explain_validity
    try:
        idx = coastline.tree.query(geom, predicate='intersects')
    except Exception as exc:
        raise ClipError('querying coastline spatial index', exc) from exc
    if len(idx) == 0:
        return [geom], 0, False

    try:
        land = unary_union(coastline.geoms[idx])
    except Exception as exc:
        raise ClipError(f'union of {len(idx)} intersecting coastline polygons', exc) from exc
    if not land.is_valid:
        raise ClipError(f'union of {len(idx)} intersecting coastline polygons',
                        f"invalid result: {explain_validity(land)}")

    try:
        result = geom.difference(land)
    except Exception as exc:
        raise ClipError('subtracting coastline', exc) from exc
    if not result.is_valid:
        raise ClipError('subtracting coastline',
                        f"invalid result: {explain_validity(result)}")

    if result.equals(geom):
        return [geom], 0, False

    parts = []
    removed = 0
    for part in _polygon_parts(result):
        if area_m2(part) < min_area_m2:
            removed += 1
        else:
            parts.append(part)
    return parts, removed, True
