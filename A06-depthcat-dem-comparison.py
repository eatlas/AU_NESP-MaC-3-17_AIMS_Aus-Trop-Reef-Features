"""Compare image-assigned DepthCat with DEM peak elevations by analysis region.

Run after stage 08, using the full-classification (not dissolved L2) input.
Outputs are rebuilt in data/{version}/out/stats/. See the companion specification
for the estimator, bootstrap draw order and interpretation limitations.
"""

import configparser
from pathlib import Path
import re

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MultipleLocator
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
REGION_FIELD = "region"
DEPTHCATS = ("Intertidal", "Very Shallow", "Shallow", "Deep")
DEPTHCAT_SOURCES = (
    "Sentinel 2 Infrared", "Sentinel 2 Red", "Sentinel 2 Green",
    "Sentinel 2 Blue", "Sentinel 2 Intertidal", "S2 Low tide Infrared",
    "Google Earth", "Queensland Globe",
)
REEF_TYPES = ("Coral Reef", "Rocky Reef", "Sediment")
TYPE_COLOURS = ("#e75ad6", "#b88169", "#f8ec5c")
SEARCH_AREA_KM2 = (0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0)
SEARCH_RELIEF_M = (0, 1, 2, 4, 8)
SEARCH_AUSBATHYTOPO = ("include", "exclude")
MIN_N = 30
SWEEP_RANGE = (-60, 10)
SWEEP_STEP = 0.1
N_BOOT = 500
RANDOM_SEED = 20261103
BOUNDARIES = (
    ("Intertidal", "Very Shallow", 0.0),
    ("Very Shallow", "Shallow", -2.5),
    ("Shallow", "Deep", -25.0),
)
PLOT_RANGE = (-60, 10)
SCRIPT_NAME = Path(__file__).name
THRESHOLD_COLUMNS = [
    "Region", "RB_Type_L2", "Boundary", "Upper", "Lower", "Clear_water_m",
    "N_upper", "N_lower", "Threshold_m", "CI_low_m", "CI_high_m",
    "Balanced_accuracy", "F1_upper", "F1_lower",
]


def select_features(features):
    """Apply sequential selection rules, retaining all finite DEM elevations."""
    required = [
        "DepthCat", "DepthCatSr", "RB_Type_L2", "DEM90pLAT", "DEM10pLAT",
        "DEMSr", "Area_km2", "geometry",
    ]
    missing = set(required) - set(features.columns)
    if missing:
        raise ValueError(f"Missing input fields: {sorted(missing)}; run stage 08 first")
    selected = features[required].copy()
    for column in ("DEM90pLAT", "DEM10pLAT", "Area_km2"):
        selected[column] = pd.to_numeric(selected[column], errors="raise")
        if np.isinf(selected[column].dropna()).any():
            raise ValueError(f"Non-finite values in {column}")
    summary = [{"Step": "Input", "Removed": 0, "Remaining": len(selected)}]
    rules = (
        ("DepthCat", lambda frame: frame.DepthCat.isin(DEPTHCATS)),
        ("Image-based DepthCatSr",
         lambda frame: frame.DepthCatSr.isin(DEPTHCAT_SOURCES)),
        ("RB_Type_L2", lambda frame: frame.RB_Type_L2.isin(REEF_TYPES)),
        ("DEM90pLAT not null", lambda frame: frame.DEM90pLAT.notna()),
    )
    for name, rule in rules:
        before = len(selected)
        selected = selected.loc[rule(selected)].copy()
        summary.append({"Step": name, "Removed": before - len(selected),
                        "Remaining": len(selected)})
    return selected.reset_index(drop=True), summary


def assign_regions(features, regions, field=REGION_FIELD):
    """Join projected representative points to dissolved, sorted regions."""
    if regions[field].isna().any():
        raise ValueError(f"Missing {field} in analysis regions")
    for label, frame in (("features", features), ("regions", regions)):
        if (frame.crs is None or frame.geometry.isna().any()
                or frame.geometry.is_empty.any()):
            raise ValueError(f"Missing CRS, null or empty geometry in {label}")
    if not regions.geometry.is_valid.all():
        raise ValueError("Invalid analysis region geometry")
    invalid_features = int((~features.geometry.is_valid).sum())
    if invalid_features:
        print(f"Warning: {invalid_features} invalid feature boundaries; regional "
              "assignment uses their representative points, not polygon overlays",
              flush=True)
    regions = regions[[field, "geometry"]].to_crs(3577)
    regions = regions.dissolve(by=field, as_index=False).sort_values(field)
    regions = regions.reset_index(drop=True).rename(columns={field: "Region"})
    projected = features.to_crs(3577).reset_index(drop=True)
    points = gpd.GeoDataFrame(
        geometry=projected.geometry.representative_point(), crs=3577)
    if (points.geometry.is_empty.any() or points.geometry.isna().any()
            or not points.geometry.is_valid.all()):
        raise ValueError("Could not derive valid feature representative points")
    joined = gpd.sjoin(points, regions, how="left", predicate="within")
    joined = joined.sort_values("index_right", kind="stable")
    joined = joined.loc[~joined.index.duplicated(keep="first")]
    projected["Region"] = joined["Region"].reindex(projected.index)
    outside = int(projected.Region.isna().sum())
    return projected.loc[projected.Region.notna()].copy(), outside


def sweep_threshold(upper, lower, min_n=MIN_N):
    """Select the midpoint of the first longest maximal-accuracy grid run."""
    upper, lower = np.asarray(upper, dtype=float), np.asarray(lower, dtype=float)
    if not np.isfinite(upper).all() or not np.isfinite(lower).all():
        raise ValueError("Threshold samples must contain only finite depths")
    if len(upper) < min_n or len(lower) < min_n:
        return None
    candidates = np.round(np.linspace(
        *SWEEP_RANGE, round((SWEEP_RANGE[1] - SWEEP_RANGE[0]) / SWEEP_STEP) + 1), 10)
    upper_sorted, lower_sorted = np.sort(upper), np.sort(lower)
    recall_upper = 1 - np.searchsorted(upper_sorted, candidates, side="left") / len(upper)
    recall_lower = np.searchsorted(lower_sorted, candidates, side="left") / len(lower)
    accuracy = (recall_upper + recall_lower) / 2
    maximum = accuracy.max()
    if maximum <= 0.5 + 1e-12:
        return None
    indices = np.flatnonzero(np.abs(accuracy - maximum) <= 1e-12)
    runs = np.split(indices, np.flatnonzero(np.diff(indices) != 1) + 1)
    run = max(runs, key=len)
    threshold = round(float((candidates[run[0]] + candidates[run[-1]]) / 2), 2)
    tp_upper = int(np.count_nonzero(upper >= threshold))
    tp_lower = int(np.count_nonzero(lower < threshold))
    fn_upper, fn_lower = len(upper) - tp_upper, len(lower) - tp_lower
    return {
        "Threshold_m": threshold,
        "Balanced_accuracy": (tp_upper / len(upper) + tp_lower / len(lower)) / 2,
        "F1_upper": 2 * tp_upper / (2 * tp_upper + fn_upper + fn_lower),
        "F1_lower": 2 * tp_lower / (2 * tp_lower + fn_lower + fn_upper),
    }


def estimate_boundary(frame, upper, lower, reference, rng=None, n_boot=N_BOOT):
    samples_upper = frame.loc[frame.DepthCat.eq(upper), "DEM90pLAT"].to_numpy()
    samples_lower = frame.loc[frame.DepthCat.eq(lower), "DEM90pLAT"].to_numpy()
    row = {
        "Boundary": f"{upper} / {lower}", "Upper": upper, "Lower": lower,
        "Clear_water_m": reference, "N_upper": len(samples_upper),
        "N_lower": len(samples_lower),
        **dict.fromkeys(THRESHOLD_COLUMNS[8:], np.nan),
    }
    estimate = sweep_threshold(samples_upper, samples_lower)
    if estimate is None:
        return row
    row.update(estimate)
    if rng is not None:
        boot = []
        for _ in range(n_boot):
            resampled_upper = rng.choice(samples_upper, len(samples_upper), replace=True)
            resampled_lower = rng.choice(samples_lower, len(samples_lower), replace=True)
            result = sweep_threshold(resampled_upper, resampled_lower)
            if result is not None:
                boot.append(result["Threshold_m"])
        if boot:
            row["CI_low_m"], row["CI_high_m"] = np.percentile(
                boot, [2.5, 97.5], method="linear")
        else:
            print(f"Warning: no identified bootstrap thresholds for "
                  f"{upper} / {lower}", flush=True)
    return row


def analyse(features, n_boot=N_BOOT):
    """Share one RNG across alphabetically ordered regions, types and boundaries."""
    rng = np.random.default_rng(RANDOM_SEED)
    thresholds, descriptive = [], []
    for region, frame in features.groupby("Region", sort=True):
        print(f"Estimating thresholds: {region}", flush=True)
        for reef_type in ("All", *REEF_TYPES):
            subset = frame if reef_type == "All" else frame.loc[
                frame.RB_Type_L2.eq(reef_type)]
            for category in DEPTHCATS:
                depths = subset.loc[subset.DepthCat.eq(category), "DEM90pLAT"]
                quantiles = depths.quantile([0.25, 0.5, 0.75], interpolation="linear")
                descriptive.append({
                    "Region": region, "RB_Type_L2": reef_type, "DepthCat": category,
                    "N": len(depths), "Median_m": quantiles.loc[0.5],
                    "Q25_m": quantiles.loc[0.25], "Q75_m": quantiles.loc[0.75],
                })
            for upper, lower, reference in BOUNDARIES:
                thresholds.append({
                    "Region": region, "RB_Type_L2": reef_type,
                    **estimate_boundary(subset, upper, lower, reference, rng, n_boot),
                })
    return (pd.DataFrame(thresholds, columns=THRESHOLD_COLUMNS),
            pd.DataFrame(descriptive))


def filter_features(features, parameter, value):
    if parameter == "Area_km2":
        keep = features.Area_km2.ge(value)
    elif parameter == "Relief_m":
        keep = (features.DEM90pLAT - features.DEM10pLAT).ge(value)
    elif parameter == "AusBathyTopo":
        keep = ~features.DEMSr.str.startswith("AusBathyTopo", na=False) if value == "exclude" else pd.Series(
            True, index=features.index)
    else:
        raise ValueError(f"Unknown filter parameter: {parameter}")
    return features.loc[keep]


def filter_search(features):
    """Vary filters independently; no bootstrap or filtering of main estimates."""
    rows = []
    groups = [("All regions", features), *features.groupby("Region", sort=True)]
    for parameter, values in (
            ("Area_km2", SEARCH_AREA_KM2), ("Relief_m", SEARCH_RELIEF_M),
            ("AusBathyTopo", SEARCH_AUSBATHYTOPO)):
        for value in values:
            for region, original in groups:
                filtered = filter_features(original, parameter, value)
                row = {
                    "Parameter": parameter, "Value": value, "Region": region,
                    "N": len(filtered), "Original_n": len(original),
                    "Retained_pct": 100 * len(filtered) / len(original),
                }
                for category in DEPTHCATS:
                    depths = filtered.loc[filtered.DepthCat.eq(category), "DEM90pLAT"]
                    original_n = int(original.DepthCat.eq(category).sum())
                    row[f"{category}_n"] = len(depths)
                    row[f"{category}_retained_pct"] = (
                        100 * len(depths) / original_n if original_n else np.nan)
                    row[f"{category}_IQR_m"] = (
                        depths.quantile(0.75) - depths.quantile(0.25)
                        if len(depths) >= MIN_N else np.nan)
                if region != "All regions":
                    for upper, lower, reference in BOUNDARIES:
                        estimate = estimate_boundary(filtered, upper, lower, reference)
                        for metric in ("N_upper", "N_lower", "Threshold_m", "Balanced_accuracy"):
                            row[f"{upper} / {lower}_{metric}"] = estimate[metric]
                rows.append(row)
    return pd.DataFrame(rows)


def markdown_table(headers, rows):
    def cell(value):
        return str(value).replace("|", r"\|").replace("\n", " ")
    lines = ["| " + " | ".join(map(cell, headers)) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(map(cell, row)) + " |" for row in rows)
    return "\n".join(lines)


def formatted(value, digits=2):
    return "n/a" if pd.isna(value) else f"{value:.{digits}f}"


def write_report(path, version, selection, thresholds, descriptive):
    parts = [
        "# DepthCat and DEM depth comparison",
        "DEM90pLAT is a pixel-averaged proxy for reef peak elevation, not a "
        "validated sounding. No DEM trim or quality filter is applied. "
        "Nearshore and Offshore areas are combined when REGION_FIELD is region. "
        "Thresholds are DEM-based indications, not optical depth calibrations.",
    ]
    number = 0

    def table(title, headers, rows):
        nonlocal number
        number += 1
        parts.extend([
            f"## {title}",
            f"Table {number}. {title}. Dataset {version}; script {SCRIPT_NAME}.",
            markdown_table(headers, rows),
        ])

    table("Feature selection", ["Step", "Removed", "Remaining"],
          [[row[key] for key in ("Step", "Removed", "Remaining")] for row in selection])
    overall = descriptive.loc[descriptive.RB_Type_L2.eq("All")]
    counts = overall.pivot(index="Region", columns="DepthCat", values="N").reindex(
        columns=DEPTHCATS, fill_value=0)
    table("Feature counts by region and DepthCat", ["Region", *DEPTHCATS, "All"],
          [[region, *map(int, row), int(row.sum())] for region, row in counts.iterrows()])
    for reef_type in ("All", *REEF_TYPES):
        stats = descriptive.loc[descriptive.RB_Type_L2.eq(reef_type)]
        table(f"DEM elevation statistics: {reef_type}",
              ["Region", "DepthCat", "n", "Median (m LAT)", "25th percentile",
               "75th percentile"],
              [[row.Region, row.DepthCat, row.N, formatted(row.Median_m),
                formatted(row.Q25_m), formatted(row.Q75_m)]
               for row in stats.itertuples(index=False)])
    parts.append(
        "Threshold cells show estimate [95% bootstrap interval] in m LAT; "
        "balanced accuracy (BA); and n (upper/lower). n/a means either class has "
        f"fewer than {MIN_N} features or the best balanced accuracy is no better "
        "than chance. F1 scores for each class are in the CSV. Intervals use "
        f"{N_BOOT} class-stratified bootstrap resamples; unidentified resamples "
        "are excluded. Clear-water reference depths are included in the headers.")
    headers = [
        "Region", *[f"{upper} / {lower} (reference {reference:g} m LAT)"
                    for upper, lower, reference in BOUNDARIES],
    ]
    for reef_type in ("All", *REEF_TYPES):
        rows = []
        for region, frame in thresholds.loc[
                thresholds.RB_Type_L2.eq(reef_type)].groupby("Region", sort=True):
            cells = []
            for row in frame.itertuples(index=False):
                counts_text = f"n={row.N_upper}/{row.N_lower}"
                if pd.isna(row.Threshold_m):
                    cells.append(f"n/a; {counts_text}")
                else:
                    cells.append(
                        f"{row.Threshold_m:.2f} [{formatted(row.CI_low_m)}, "
                        f"{formatted(row.CI_high_m)}]; "
                        f"BA={row.Balanced_accuracy:.3f}; {counts_text}")
            rows.append([region, *cells])
        table(f"DepthCat thresholds: {reef_type}", headers, rows)
    parts.extend([
        "## Interpretation and limitations",
        "Unresolved reef peaks pull DEM thresholds deeper. Nearshore positional "
        "offsets, smoothing and land contamination can pull them shallower. "
        "Low balanced accuracy indicates poor separation, not a calibration. "
        "Water clarity and substrate albedo vary within regions. The Shallow / "
        "Deep transition is approximately MSL-referenced, so its LAT elevation "
        "also depends on the local tidal offset.",
        "The Coral Sea is a cautionary reference: the known clear-water "
        "thresholds are 0, -2.5 and -25 m LAT, but coarse DEM coverage can give "
        "much deeper estimates. GBR bathymetry provides a secondary comparison. "
        "Torres Strait has a limited depth range and no Deep features in the "
        "specification's v1-0 selection. Manual checks of peak resolution are "
        "required before treating any estimate as a calibration.",
        "The independent area, relief and DEM-source filter search is supplied "
        "as a separate CSV and appendix figure; it is not applied to these tables.",
        "Reference: Lawrey, E., Bycroft, R., Hammerton, M. (2026). Mapping the reef "
        "and island features of the Coral Sea Marine Park. "
        "https://doi.org/10.26274/96ft-5236",
    ])
    path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")


def depth_axis(ax, horizontal=True):
    axis = ax.xaxis if horizontal else ax.yaxis
    axis.set_major_locator(MultipleLocator(5))
    axis.set_minor_locator(MultipleLocator(1))
    if horizontal:
        ax.set_xlim(PLOT_RANGE)
        ax.set_xlabel("DEM elevation (m LAT)")
    else:
        ax.set_ylim(PLOT_RANGE)
        ax.set_ylabel("DEM elevation (m LAT)")
    ax.grid(axis="x" if horizontal else "y", alpha=0.2)
    ax.set_axisbelow(True)


def save_figure(fig, path):
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_regions(features, thresholds, directory):
    bins = np.arange(PLOT_RANGE[0], PLOT_RANGE[1] + 1, 1)
    reference_edges = [PLOT_RANGE[1], *[item[2] for item in BOUNDARIES], PLOT_RANGE[0]]
    for region, frame in features.groupby("Region", sort=True):
        estimates = thresholds.loc[
            thresholds.Region.eq(region) & thresholds.RB_Type_L2.eq("All")]
        estimated_edges = [
            PLOT_RANGE[1], *estimates.Threshold_m.tolist(), PLOT_RANGE[0]]
        fig, axes = plt.subplots(4, 1, figsize=(8.3, 10.5), sharex=True)
        fig.suptitle(f"{region}: DepthCat and DEM peak elevation", fontsize=12)
        for index, (category, ax) in enumerate(zip(DEPTHCATS, axes)):
            ax.axvspan(reference_edges[index + 1], reference_edges[index],
                       facecolor="none", edgecolor="0.65", hatch="///", zorder=0)
            top, bottom = estimated_edges[index:index + 2]
            if np.isfinite(top) and np.isfinite(bottom) and bottom <= top:
                ax.axvspan(bottom, top, color="#759ac2", alpha=0.18, zorder=0)
            elif np.isfinite(top) and np.isfinite(bottom):
                ax.text(0.01, 0.92, "Estimated boundaries reversed; no band shown",
                        transform=ax.transAxes, va="top")
            for boundary_index in (index - 1, index):
                if 0 <= boundary_index < len(estimates):
                    row = estimates.iloc[boundary_index]
                    if pd.notna(row.Threshold_m):
                        ax.axvline(row.Threshold_m, color="#285886", linewidth=1)
                        if pd.notna(row.CI_low_m) and pd.notna(row.CI_high_m):
                            ax.axvspan(row.CI_low_m, row.CI_high_m,
                                       color="#285886", alpha=0.18)
                        ax.text(row.Threshold_m, 0.98, f"{row.Threshold_m:.2f}",
                                transform=ax.get_xaxis_transform(), va="top",
                                ha="center", color="#285886")
            arrays, labels = [], []
            subset = frame.loc[frame.DepthCat.eq(category)]
            for reef_type in REEF_TYPES:
                depths = subset.loc[subset.RB_Type_L2.eq(reef_type), "DEM90pLAT"]
                clipped = int(((depths < PLOT_RANGE[0]) | (depths > PLOT_RANGE[1])).sum())
                arrays.append(np.clip(depths.to_numpy(), *PLOT_RANGE))
                labels.append(f"{reef_type}: n={len(depths)}, clipped={clipped}")
            ax.hist(arrays, bins=bins, stacked=True, color=TYPE_COLOURS,
                    label=labels, edgecolor="white", linewidth=0.2)
            ax.set_title(f"{category} (n={len(subset)})", loc="left")
            ax.set_ylabel("Features")
            depth_axis(ax)
            ax.legend(loc="upper left", bbox_to_anchor=(0, 0.84), fontsize=9)
        handles = [
            Patch(facecolor="none", edgecolor="0.65", hatch="///", label="Clear-water band"),
            Patch(facecolor="#759ac2", alpha=0.3, label="Estimated regional band"),
            Patch(facecolor="#285886", alpha=0.3, label="95% bootstrap interval"),
        ]
        fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=9)
        fig.tight_layout(rect=(0, 0.035, 1, 0.97))
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(region)).strip("_")
        save_figure(fig, directory / f"A06_{slug}_by-type.png")


def plot_overview(thresholds, path):
    estimates = thresholds.loc[thresholds.RB_Type_L2.eq("All")]
    regions = sorted(estimates.loc[estimates.Threshold_m.notna(), "Region"].unique())
    fig, ax = plt.subplots(figsize=(8.3, max(3, 0.42 * len(regions) + 1.6)))
    positions = {region: index for index, region in enumerate(regions)}
    colours = ("#009E73", "#0072B2", "#D55E00")
    handles = []
    limits = [reference for _, _, reference in BOUNDARIES]
    for index, ((upper, lower, reference), colour) in enumerate(zip(BOUNDARIES, colours)):
        boundary = f"{upper} / {lower}"
        frame = estimates.loc[estimates.Boundary.eq(boundary) & estimates.Threshold_m.notna()]
        for row in frame.itertuples():
            y = positions[row.Region] + (index - 1) * 0.18
            ax.plot(row.Threshold_m, y, "o", color=colour, markersize=5, zorder=3)
            limits.append(row.Threshold_m)
            if pd.notna(row.CI_low_m) and pd.notna(row.CI_high_m):
                ax.hlines(y, row.CI_low_m, row.CI_high_m, color=colour, linewidth=1.5)
                limits.extend((row.CI_low_m, row.CI_high_m))
        ax.axvline(reference, color=colour, linestyle="--", linewidth=1, alpha=0.8)
        handles.append(Line2D([], [], color=colour, marker="o", label=boundary))
    ax.set_yticks(range(len(regions)), regions)
    ax.set_ylim(len(regions) - 0.4, -0.6)
    ax.set_title("Regional DepthCat thresholds")
    depth_axis(ax)
    ax.set_xlabel("Estimated threshold (m LAT)")
    ax.set_xlim(-45, 5 * np.ceil((max(limits) + 2) / 5))
    ax.grid(axis="x", alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)
    if not regions:
        ax.text(0.5, 0.5, "No identified thresholds", ha="center",
                transform=ax.transAxes)
    legend = fig.legend(
        handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.005),
        ncol=3, fontsize=9,
        title="Points and bars: estimates and 95% intervals; dashed lines: Coral Sea clear-water threshold",
        title_fontsize=9)
    fig.canvas.draw()
    legend_top = legend.get_window_extent().transformed(fig.transFigure.inverted()).y1
    fig.tight_layout(rect=(0, legend_top + 0.01, 1, 1))
    save_figure(fig, path)


def plot_filter_search(search, path):
    fig, axes = plt.subplots(
        4, 3, figsize=(8.3, 9), sharex="col", sharey="row",
        gridspec_kw={"width_ratios": [3, 2.4, 1.4]})
    regions = sorted(search.loc[search.Region.ne("All regions"), "Region"].unique())
    palette = plt.get_cmap("tab20" if len(regions) > 10 else "tab10")
    colours = {region: palette(index % palette.N) for index, region in enumerate(regions)}
    for col, parameter in enumerate(("Area_km2", "Relief_m", "AusBathyTopo")):
        panel = search.loc[search.Parameter.eq(parameter)]
        for region, frame in panel.groupby("Region", sort=True):
            x = np.arange(len(frame)) if parameter == "AusBathyTopo" else frame.Value.astype(float)
            colour = "black" if region == "All regions" else colours[region]
            axes[0, col].plot(x, frame.Retained_pct, ".-", color=colour,
                              label=region, linewidth=1)
            if region != "All regions":
                for index, (upper, lower, _) in enumerate(BOUNDARIES, 1):
                    values = frame[f"{upper} / {lower}_Threshold_m"]
                    axes[index, col].plot(x, values, ".-",
                                          color=colour, linewidth=1)
        axes[0, col].set_title(
            {"Area_km2": "Feature size", "Relief_m": "Bathymetric relief",
             "AusBathyTopo": "DEM resolution"}[parameter])
        axes[0, col].set_ylim(0, 105)
        for row in range(4):
            axes[row, col].grid(alpha=0.2)
            if row:
                axes[row, col].axhline(
                    BOUNDARIES[row - 1][2], color="0.4", linestyle="--",
                    linewidth=1, label="Clear-water threshold (Coral Sea)")
        axes[-1, col].set_xlabel(
            {"Area_km2": "Minimum feature area (km$^2$)",
             "Relief_m": "Minimum DEM relief (m)\n90th - 10th percentile elevation",
             "AusBathyTopo": "AusBathyTopo\n250 m DEM"}[parameter])
        if parameter == "AusBathyTopo":
            axes[-1, col].set_xticks([0, 1], ["Keep", "Drop"])
        else:
            values = SEARCH_AREA_KM2 if parameter == "Area_km2" else SEARCH_RELIEF_M
            base = 10 if parameter == "Area_km2" else 2
            # Reserve one step for zero; positive settings retain log spacing.
            axes[-1, col].set_xscale(
                "symlog", base=base, linthresh=values[1],
                linscale=1 - 1 / base)
            axes[-1, col].set_xlim(-values[1] * 0.15, values[-1] * 1.15)
            axes[-1, col].set_xticks(values, [f"{value:g}" for value in values])
            axes[-1, col].minorticks_off()
            axes[-1, col].tick_params(
                axis="x", labelrotation=45 if parameter == "Area_km2" else 0)
    axes[0, 0].set_ylabel("Retained (%)")
    for index, (upper, lower, _) in enumerate(BOUNDARIES, 1):
        axes[index, 0].set_ylabel(f"{upper} /\n{lower}\nthreshold (m LAT)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    reference_handle, reference_label = axes[1, 0].get_legend_handles_labels()
    legend = fig.legend(
        handles + reference_handle, labels + reference_label,
        loc="lower center", bbox_to_anchor=(0.5, 0.005), ncol=3, fontsize=9)
    fig.suptitle("Effect of bathymetry quality filters on DepthCat thresholds")
    fig.canvas.draw()
    legend_top = legend.get_window_extent().transformed(fig.transFigure.inverted()).y1
    fig.tight_layout(rect=(0, legend_top + 0.01, 1, 0.97))
    save_figure(fig, path)


def main():
    config = configparser.ConfigParser()
    config.read(ROOT / "config.ini")
    version = config.get("general", "version")
    data_dir = ROOT / "data" / version
    input_path = (data_dir / "out" / "full-classes" /
                  f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{version}.shp")
    region_path = (ROOT / config.get("general", "in_3p_path") /
                   "nesp-3-17-analysis-regions" / "analysis-regions.shp")
    print(f"Loading {input_path}", flush=True)
    features, selection = select_features(gpd.read_file(input_path))
    features, outside = assign_regions(features, gpd.read_file(region_path))
    selection.append({"Step": "Outside analysis regions", "Removed": outside,
                      "Remaining": len(features)})
    for row in selection:
        print(f"{row['Step']}: removed {row['Removed']}; remaining {row['Remaining']}",
              flush=True)
    if features.empty:
        raise ValueError("No selected features within analysis regions")
    slugs = [re.sub(r"[^A-Za-z0-9_-]+", "_", str(region)).strip("_")
             for region in features.Region.unique()]
    if len(set(slugs)) != len(slugs) or not all(slugs):
        raise ValueError("Region names do not produce unique nonempty plot filenames")
    thresholds, descriptive = analyse(features)
    print("Searching independent quality filters", flush=True)
    search = filter_search(features)
    output = data_dir / "out" / "stats"
    plots = output / "A06-plots"
    plots.mkdir(parents=True, exist_ok=True)
    stem = f"A06_DepthCat-DEM-comparison_{version}"
    thresholds.to_csv(output / f"{stem}.csv", index=False)
    search.to_csv(output / f"A06_filter-search_{version}.csv", index=False)
    write_report(output / f"{stem}.md", version, selection, thresholds, descriptive)
    with plt.rc_context({"font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
                         "xtick.labelsize": 9, "ytick.labelsize": 9}):
        plot_regions(features, thresholds, plots)
        plot_filter_search(search, plots / "A06_filter-search.png")
        plot_overview(thresholds, plots / "A06_thresholds-overview.png")
    print(f"Written tables, CSVs and {features.Region.nunique() + 2} plots to {output}",
          flush=True)


if __name__ == "__main__":
    main()
