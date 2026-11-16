"""Synthetic estimator, regionalisation and report checks for A06."""

import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Polygon, box


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "depthcat_dem", ROOT / "A06-depthcat-dem-comparison.py")
a06 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a06)


def sample_features():
    rows = []
    for region in ("GBR", "Coral Sea"):
        for reef_type in a06.REEF_TYPES:
            for category, depth in zip(a06.DEPTHCATS, (2, -1, -10, -35)):
                for index in range(30):
                    rows.append({
                        "Region": region, "RB_Type_L2": reef_type, "DepthCat": category,
                        "DepthCatSr": "Sentinel 2 Red",
                        "DEM90pLAT": depth + index / 20,
                        "DEM10pLAT": depth - 3, "Area_km2": index / 100,
                        "DEMSr": "AusBathyTopo-250m" if index % 2 else None,
                    })
    return pd.DataFrame(rows)


class SweepTests(unittest.TestCase):
    def test_grid_size_and_separated_plateau_midpoint(self):
        result = a06.sweep_threshold([0] * 30, [-10] * 30)
        self.assertEqual(result["Threshold_m"], -4.95)
        self.assertEqual(result["Balanced_accuracy"], 1)
        self.assertEqual(result["F1_upper"], 1)
        self.assertEqual(result["F1_lower"], 1)

    def test_longest_plateau_and_first_tie(self):
        with patch.object(a06, "SWEEP_RANGE", (-4, 4)), patch.object(a06, "SWEEP_STEP", 1):
            result = a06.sweep_threshold([0, 4], [-4, 1], min_n=2)
            self.assertEqual(result["Threshold_m"], -1.5)
            self.assertEqual(result["Balanced_accuracy"], 0.75)
            self.assertAlmostEqual(result["F1_upper"], 0.8)
            self.assertAlmostEqual(result["F1_lower"], 2 / 3)
            result = a06.sweep_threshold([-1, 4], [-4, 1], min_n=2)
            self.assertEqual(result["Threshold_m"], -2)

    def test_equality_goes_to_upper_and_extremes_not_trimmed(self):
        result = a06.sweep_threshold([0] * 30, [0] * 15 + [-100] * 15)
        self.assertEqual(result["Threshold_m"], -30)
        self.assertEqual(result["Balanced_accuracy"], 0.75)
        self.assertIsNotNone(a06.sweep_threshold([100] * 30, [-100] * 30))

    def test_no_threshold_for_small_identical_or_reversed_classes(self):
        self.assertIsNone(a06.sweep_threshold([0] * 29, [-5] * 30))
        self.assertIsNone(a06.sweep_threshold([0] * 30, [0] * 30))
        self.assertIsNone(a06.sweep_threshold([-5] * 30, [0] * 30))
        with self.assertRaisesRegex(ValueError, "finite"):
            a06.sweep_threshold([np.inf], [0], min_n=1)

    def test_matches_brute_force_with_imbalanced_noisy_classes(self):
        rng = np.random.default_rng(42)
        upper = rng.normal(-10, 12, 120)
        lower = rng.normal(-20, 15, 30)
        result = a06.sweep_threshold(upper, lower)
        grid = np.round(np.linspace(-60, 10, 701), 10)
        scores = np.array([((upper >= t).mean() + (lower < t).mean()) / 2 for t in grid])
        indices = np.flatnonzero(np.abs(scores - scores.max()) <= 1e-12)
        runs = np.split(indices, np.flatnonzero(np.diff(indices) != 1) + 1)
        run = max(runs, key=len)
        self.assertEqual(result["Threshold_m"], round((grid[run[0]] + grid[run[-1]]) / 2, 2))
        self.assertAlmostEqual(result["Balanced_accuracy"], scores.max())


class SelectionTests(unittest.TestCase):
    def test_selection_sources_types_and_nulls_without_depth_trim(self):
        frame = sample_features().iloc[:8].copy()
        frame.loc[0, "DepthCat"] = "Land"
        frame.loc[1, "DepthCatSr"] = "MultiResBathyEEZ"
        frame.loc[2, "DepthCatSr"] = "AHO chart"
        frame.loc[3, "RB_Type_L2"] = "Sediment Reef"
        frame.loc[4, "DEM90pLAT"] = np.nan
        frame.loc[5, "DEM90pLAT"] = -1000
        frame.loc[6, "DEM90pLAT"] = 1000
        geo = gpd.GeoDataFrame(frame, geometry=[box(i, 0, i + 1, 1) for i in range(8)],
                               crs=3577)
        selected, summary = a06.select_features(geo)
        self.assertEqual(len(selected), 3)
        self.assertEqual([row["Removed"] for row in summary], [0, 1, 2, 1, 1])
        self.assertEqual(selected.DEM90pLAT.iloc[:2].tolist(), [-1000, 1000])
        with self.assertRaisesRegex(ValueError, "Missing input fields"):
            a06.select_features(geo.drop(columns="RB_Type_L2"))

    def test_dissolve_projection_overlap_first_and_outside(self):
        features = gpd.GeoDataFrame(
            {"Name": ["inside", "overlap", "outside", "on boundary"]},
            geometry=[box(0, 0, 2, 2), box(4, 0, 6, 2), box(20, 0, 22, 2),
                      box(9, 0, 11, 2)], crs=3577)
        regions = gpd.GeoDataFrame(
            {"region": ["B", "A", "A"]},
            geometry=[box(4, -1, 10, 3), box(-1, -1, 3, 3), box(3, -1, 7, 3)],
            crs=3577)
        assigned, outside = a06.assign_regions(features, regions)
        self.assertEqual(assigned.Region.tolist(), ["A", "A"])
        self.assertEqual(outside, 2)
        assigned_other_crs, _ = a06.assign_regions(
            features.iloc[:2].to_crs(4283), regions.to_crs(4283))
        self.assertEqual(assigned_other_crs.Region.tolist(), ["A", "A"])
        self.assertEqual(assigned.crs.to_epsg(), 3577)

    def test_independent_filters_and_null_source(self):
        frame = sample_features()
        frame.loc[0, ["Area_km2", "DEM10pLAT"]] = np.nan
        self.assertEqual(len(a06.filter_features(frame, "Area_km2", 0)), len(frame) - 1)
        self.assertEqual(len(a06.filter_features(frame, "Relief_m", 0)), len(frame) - 1)
        excluded = a06.filter_features(frame, "AusBathyTopo", "exclude")
        self.assertTrue(excluded.DEMSr.isna().all())
        self.assertEqual(len(excluded), len(frame) // 2)
        self.assertTrue(a06.filter_features(frame, "Area_km2", 0.1).Area_km2.ge(0.1).all())
        with self.assertRaisesRegex(ValueError, "Unknown filter"):
            a06.filter_features(frame, "unknown", 0)
        search = a06.filter_search(frame)
        self.assertEqual(len(search), 15 * 3)
        neutral = search.loc[
            search.Parameter.eq("Relief_m") & search.Value.eq(0)]
        self.assertEqual(neutral.N.sum(), 2 * (len(frame) - 1))
        small = search.loc[search.Parameter.eq("Area_km2") & search.Value.eq(1)]
        self.assertTrue(small["Intertidal_IQR_m"].isna().all())
        self.assertTrue(small.Retained_pct.eq(0).all())

    def test_invalid_boundary_uses_valid_representative_point_with_warning(self):
        features = gpd.GeoDataFrame(
            geometry=[Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])], crs=3577)
        regions = gpd.GeoDataFrame(
            {"region": ["A"]}, geometry=[box(-1, -1, 3, 3)], crs=3577)
        output = io.StringIO()
        with redirect_stdout(output):
            assigned, outside = a06.assign_regions(features, regions)
        self.assertIn("1 invalid feature boundaries", output.getvalue())
        self.assertEqual(assigned.Region.tolist(), ["A"])
        self.assertEqual(outside, 0)
        with self.assertRaisesRegex(ValueError, "Invalid analysis region"):
            a06.assign_regions(features, regions.set_geometry(features.geometry))


class BootstrapAndOutputTests(unittest.TestCase):
    def test_shared_rng_exact_draw_order(self):
        frame = sample_features()
        with redirect_stdout(io.StringIO()):
            thresholds, _ = a06.analyse(frame, n_boot=8)
            repeat, _ = a06.analyse(frame.sample(frac=1, random_state=5).sort_index(), n_boot=8)
        pd.testing.assert_frame_equal(thresholds, repeat)
        rng = np.random.default_rng(a06.RANDOM_SEED)
        first = frame.loc[frame.Region.eq("Coral Sea")]
        upper = first.loc[first.DepthCat.eq("Intertidal"), "DEM90pLAT"].to_numpy()
        lower = first.loc[first.DepthCat.eq("Very Shallow"), "DEM90pLAT"].to_numpy()
        boot = []
        for _ in range(8):
            u = rng.choice(upper, len(upper), replace=True)
            l = rng.choice(lower, len(lower), replace=True)
            boot.append(a06.sweep_threshold(u, l)["Threshold_m"])
        expected = np.percentile(boot, [2.5, 97.5], method="linear")
        np.testing.assert_array_equal(
            thresholds.loc[0, ["CI_low_m", "CI_high_m"]].to_numpy(dtype=float), expected)
        self.assertEqual(thresholds.columns.tolist(), a06.THRESHOLD_COLUMNS)
        self.assertEqual(len(thresholds), 2 * 4 * 3)
        self.assertEqual(thresholds.Region.iloc[0], "Coral Sea")

    def test_unidentified_bootstrap_resamples_excluded(self):
        frame = sample_features()
        identified = {"Threshold_m": -1, "Balanced_accuracy": 0.8,
                      "F1_upper": 0.8, "F1_lower": 0.8}
        with patch.object(a06, "sweep_threshold", side_effect=[
                identified, None, {**identified, "Threshold_m": -3}, identified]):
            row = a06.estimate_boundary(
                frame, "Intertidal", "Very Shallow", 0,
                np.random.default_rng(1), n_boot=3)
        self.assertAlmostEqual(row["CI_low_m"], -2.95)
        self.assertAlmostEqual(row["CI_high_m"], -1.05)

    def test_linear_quantiles_and_no_bootstrap_for_unidentified_boundary(self):
        frame = sample_features().iloc[:4].copy()
        frame["DEM90pLAT"] = [0, 1, 2, 10]
        with redirect_stdout(io.StringIO()):
            thresholds, descriptive = a06.analyse(frame, n_boot=2)
        row = descriptive.iloc[0]
        self.assertEqual(row.Median_m, 1.5)
        self.assertEqual(row.Q25_m, 0.75)
        self.assertEqual(row.Q75_m, 4)
        self.assertTrue(thresholds.Threshold_m.isna().all())
        rng = Mock()
        a06.estimate_boundary(frame, "Intertidal", "Very Shallow", 0, rng, n_boot=2)
        rng.choice.assert_not_called()

    def test_report_and_all_plot_surfaces(self):
        frame = sample_features()
        with redirect_stdout(io.StringIO()):
            thresholds, descriptive = a06.analyse(frame, n_boot=2)
        search = a06.filter_search(frame)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            report = directory / "report.md"
            a06.write_report(report, "test-version",
                             [{"Step": "Outside analysis regions", "Removed": 1,
                               "Remaining": len(frame)}], thresholds, descriptive)
            text = report.read_text(encoding="utf-8")
            self.assertEqual(text.count("Dataset test-version; script"), 10)
            self.assertIn("reference -2.5 m LAT", text)
            self.assertNotIn("Filter search\n", text)
            a06.plot_regions(frame, thresholds, directory)
            a06.plot_overview(thresholds, directory / "overview.png")
            a06.plot_filter_search(search, directory / "search.png")
            files = list(directory.glob("*.png"))
            self.assertEqual(len(files), 4)
            for path in files:
                self.assertGreater(path.stat().st_size, 10000)

    def test_empty_estimates_still_plot_and_report_counts(self):
        frame = sample_features().iloc[:10]
        with redirect_stdout(io.StringIO()):
            thresholds, descriptive = a06.analyse(frame, n_boot=2)
        self.assertTrue(thresholds.Threshold_m.isna().all())
        self.assertTrue(thresholds.CI_low_m.isna().all())
        self.assertEqual(descriptive.N.sum(), 20)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            a06.plot_overview(thresholds, directory / "empty.png")
            a06.plot_regions(frame, thresholds, directory)
            self.assertTrue((directory / "empty.png").exists())

    def test_overview_single_panel_colours_intervals_and_missing_estimates(self):
        with redirect_stdout(io.StringIO()):
            thresholds, _ = a06.analyse(sample_features(), n_boot=2)
        mask = (thresholds.Region.eq("Coral Sea") & thresholds.RB_Type_L2.eq("All")
                & thresholds.Boundary.eq("Intertidal / Very Shallow"))
        thresholds.loc[mask, "Threshold_m"] = np.nan
        with patch.object(a06, "save_figure") as save:
            a06.plot_overview(thresholds, Path("unused.png"))
        fig = save.call_args.args[0]
        try:
            self.assertEqual(len(fig.axes), 1)
            self.assertLess(fig.get_size_inches()[1], 5)
            ax = fig.axes[0]
            self.assertEqual(ax.get_xlim()[0], -45)
            self.assertEqual([tick.get_text() for tick in ax.get_yticklabels()],
                             ["Coral Sea", "GBR"])
            points = [line for line in ax.lines if line.get_marker() == "o"]
            references = [line for line in ax.lines if line.get_linestyle() == "--"]
            estimates = thresholds.loc[
                thresholds.RB_Type_L2.eq("All") & thresholds.Threshold_m.notna()]
            self.assertEqual(len(points), len(estimates))
            self.assertEqual(len(references), 3)
            for index, (_, _, reference) in enumerate(a06.BOUNDARIES):
                colour = references[index].get_color()
                np.testing.assert_allclose(references[index].get_xdata(), [reference] * 2)
                boundary = " / ".join(a06.BOUNDARIES[index][:2])
                rows = estimates.loc[estimates.Boundary.eq(boundary)]
                boundary_points = [point for point in points if point.get_color() == colour]
                np.testing.assert_allclose(
                    [point.get_xdata()[0] for point in boundary_points], rows.Threshold_m)
                for point, row in zip(boundary_points, rows.itertuples()):
                    region_y = 0 if row.Region == "Coral Sea" else 1
                    self.assertAlmostEqual(point.get_ydata()[0],
                                           region_y + (index - 1) * 0.18)
            self.assertEqual(len({line.get_color() for line in references}), 3)
            for point, interval in zip(points, ax.collections):
                np.testing.assert_allclose(interval.get_colors()[0],
                                           a06.matplotlib.colors.to_rgba(point.get_color()))
                low, high = interval.get_segments()[0][:, 0]
                self.assertLessEqual(ax.get_xlim()[0], low)
                self.assertGreaterEqual(ax.get_xlim()[1], high)
            self.assertEqual(len(fig.legends[0].get_texts()), 3)
            self.assertIn("dashed lines: Coral Sea clear-water threshold",
                          fig.legends[0].get_title().get_text())
        finally:
            a06.plt.close(fig)

    def test_filter_plot_absolute_thresholds_references_log_axes_and_layout(self):
        search = a06.filter_search(sample_features())
        column = "Very Shallow / Shallow_Threshold_m"
        region_rows = search.Region.eq("Coral Sea") & search.Parameter.eq("Area_km2")
        search.loc[region_rows, column] = np.arange(region_rows.sum()) - 20.0
        search.loc[search.index[region_rows][0], column] = np.nan
        with patch.object(a06, "save_figure") as save:
            a06.plot_filter_search(search, Path("unused.png"))
        fig = save.call_args.args[0]
        try:
            axes = np.array(fig.axes).reshape(4, 3)
            np.testing.assert_allclose(
                axes[2, 0].lines[0].get_ydata(),
                search.loc[region_rows, column], equal_nan=True)
            for row, (_, _, reference) in enumerate(a06.BOUNDARIES, 1):
                for col in range(3):
                    np.testing.assert_allclose(
                        axes[row, col].lines[-1].get_ydata(), [reference, reference])
                    self.assertEqual(axes[row, col].get_ylim(), axes[row, 0].get_ylim())
                self.assertIn("threshold (m LAT)", axes[row, 0].get_ylabel())
            for col, values in enumerate((a06.SEARCH_AREA_KM2, a06.SEARCH_RELIEF_M)):
                self.assertEqual(axes[-1, col].get_xscale(), "symlog")
                np.testing.assert_allclose(axes[-1, col].get_xticks(), values)
                transformed = axes[-1, col].xaxis.get_transform().transform(values)
                self.assertTrue(np.isfinite(transformed).all())
                self.assertTrue((np.diff(transformed) > 0).all())
                limits = axes[-1, col].xaxis.get_transform().transform(
                    axes[-1, col].get_xlim())
                self.assertLess(-limits[0] / (limits[1] - limits[0]), 0.1)
                if col == 1:
                    np.testing.assert_allclose(np.diff(transformed), 1)
                else:
                    transformed_decades = axes[-1, col].xaxis.get_transform().transform(
                        [0, 0.01, 0.1, 1])
                    np.testing.assert_allclose(np.diff(transformed_decades),
                                               np.diff(transformed_decades)[0])
            self.assertLessEqual(fig.get_size_inches()[1], 9)
            legend = fig.legends[0]
            self.assertIn("Clear-water threshold (Coral Sea)",
                          [text.get_text() for text in legend.get_texts()])
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            legend_top = legend.get_window_extent(renderer).y1
            label_bottom = min(ax.get_tightbbox(renderer).y0 for ax in axes[-1])
            gap_inches = (label_bottom - legend_top) / fig.dpi
            self.assertGreater(gap_inches, 0)
            self.assertLess(gap_inches, 0.35)
        finally:
            a06.plt.close(fig)


if __name__ == "__main__":
    unittest.main()
