"""Verify regional summaries of source-feature uncertainty and legacy defaults."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("feature_quality", ROOT / "A05-reef-distribution.py")
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


class FeatureQualityTests(unittest.TestCase):
    def features(self):
        return gpd.GeoDataFrame({
            "ReefFID": ["reef-a", "reef-b", "reef-c", "sediment"],
            "Dataset": ["CS Features", "GBR Features", "TS Features", "CS Features"],
            "RB_Type_L2": ["Coral Reef", "Coral Reef", "Rocky Reef", "Sediment"],
            "FeatConf": ["High", None, None, "Low"],
            "TypeConf": ["Medium", None, "Low", "Low"],
            "EdgeAcc_m": [20, 300, 150, 5000],
            "geometry": [box(0, 0, 30, 10), box(5, 0, 10, 10),
                         box(25, 0, 29, 10), box(0, 0, 10, 10)],
        }, crs=3577)

    def regions(self):
        return gpd.GeoDataFrame({
            "NAME": ["West", "East"],
            "geometry": [box(0, -10, 10, 20), box(10, -10, 30, 20)],
        }, crs=3577)

    def with_new_caledonia(self):
        features = self.features()
        features.at[2, "geometry"] = box(100, 0, 110, 10)
        regions = pd.concat([
            self.regions(),
            gpd.GeoDataFrame({"NAME": ["New Caledonia"],
                              "geometry": [box(90, -10, 120, 20)]}, crs=3577),
        ], ignore_index=True)
        return features, regions

    def test_scope_largest_area_and_source_provenance(self):
        source = self.features()
        result = quality.prepare_quality_features(source, self.regions())
        self.assertEqual(result.ReefFID.tolist(), ["reef-a", "reef-b", "reef-c"])
        self.assertEqual(result.Region.tolist(), ["East", "West", "East"])
        self.assertEqual(result.Boundary_basis.tolist(), [
            "Regional or edited mapping", "Legacy area default", "Legacy area default",
        ])
        self.assertNotIn("Region", source.columns)
        self.assertTrue(result.geometry.equals(source.geometry.iloc[:3]))

    def test_outside_area_and_equal_area_ties(self):
        source = self.features().iloc[:2].copy()
        source.geometry = [box(-100, 0, 5, 10), box(5, 0, 15, 10)]
        result = quality.prepare_quality_features(source, self.regions())
        self.assertEqual(result.Region.tolist(), ["No match", "East"])

    def test_confidence_missing_values_and_count_conservation(self):
        features = quality.prepare_quality_features(self.features(), self.regions())
        confidence, edge, histogram, bins = quality.quality_summaries(features)
        frame = pd.DataFrame(confidence)
        for attribute in ("FeatConf", "TypeConf"):
            self.assertEqual(frame.loc[frame.Attribute.eq(attribute), "Count"].sum(), 3)
        self.assertEqual(frame.loc[frame.Attribute.eq("FeatConf") &
                                   frame.Value.eq("Missing"), "Count"].sum(), 2)
        self.assertEqual(frame.loc[frame.Attribute.eq("TypeConf") &
                                   frame.Value.eq("Missing"), "Count"].sum(), 1)
        self.assertEqual(sum(row["Total"] for row in edge), 3)
        self.assertEqual(sum(row["Count"] for row in histogram), 3)
        self.assertEqual(len(bins) - 1, len(quality.EDGE_BIN_CENTRES))
        centres = np.asarray(quality.EDGE_BIN_CENTRES, dtype=float)
        self.assertTrue(np.allclose(bins[1:-1], np.sqrt(centres[:-1] * centres[1:])))
        self.assertTrue(np.all((bins[:-1] <= centres) & (centres <= bins[1:])))
        for _, group in frame.groupby(["Region", "Dataset", "RB_Type_L2", "Attribute"]):
            self.assertAlmostEqual(group.Percent.sum(), 100)

    def test_log_histogram_extremes_and_exclusions(self):
        source = pd.concat([self.features().iloc[:1]] * 8, ignore_index=True)
        source.ReefFID = [f"reef-{index}" for index in range(8)]
        source.EdgeAcc_m = [5, 10, 50, 5000, None, 0, -1, "bad"]
        features = quality.prepare_quality_features(source, self.regions())
        _, edge, histogram, bins = quality.quality_summaries(features)
        self.assertEqual(edge[0]["Total"], 8)
        self.assertEqual(edge[0]["Positive_count"], 4)
        self.assertEqual(edge[0]["Missing_count"], 1)
        self.assertEqual(edge[0]["Zero_count"], 1)
        self.assertEqual(edge[0]["Invalid_count"], 2)
        self.assertEqual(edge[0]["Median_m"], 30)
        self.assertEqual(edge[0]["At_most_50m_count"], 3)
        self.assertEqual(edge[0]["Over_1000m_count"], 1)
        self.assertEqual(sum(row["Count"] for row in histogram), 4)
        self.assertEqual(bins[0], 10)
        self.assertEqual(bins[-1], 3000)
        self.assertEqual(sum(row["Count"] for row in histogram
                             if row["Bin_scope"] == "Plotted"), 2)
        self.assertEqual(sum(row["Count"] for row in histogram
                             if row["Bin_scope"] == "Below plotted range"), 1)
        self.assertEqual(sum(row["Count"] for row in histogram
                             if row["Bin_scope"] == "Above plotted range"), 1)

    def test_common_rounded_values_have_their_own_bins(self):
        values = list(quality.EDGE_BIN_CENTRES) + [11, 22, 23, 90, 2700]
        source = pd.concat([self.features().iloc[:1]] * len(values), ignore_index=True)
        source.ReefFID = [f"reef-{index}" for index in range(len(values))]
        source.EdgeAcc_m = values
        features = quality.prepare_quality_features(source, self.regions())
        _, _, histogram, _ = quality.quality_summaries(features)
        counts = {row["Bin_centre_m"]: row["Count"] for row in histogram
                  if row["Bin_scope"] == "Plotted"}
        expected = {centre: 1 for centre in quality.EDGE_BIN_CENTRES}
        for centre in (10, 20, 25, 100, 3000):
            expected[centre] += 1
        self.assertEqual(counts, expected)

    def test_plot_limits_are_inclusive_without_clipping_tail_values(self):
        source = pd.concat([self.features().iloc[:1]] * 4, ignore_index=True)
        source.ReefFID = [f"reef-{index}" for index in range(4)]
        source.EdgeAcc_m = [9, 10, 3000, 3001]
        features = quality.prepare_quality_features(source, self.regions())
        _, edge, histogram, _ = quality.quality_summaries(features)
        plotted = [row for row in histogram if row["Bin_scope"] == "Plotted"]
        self.assertEqual(plotted[0]["Count"], 1)
        self.assertEqual(plotted[-1]["Count"], 1)
        self.assertEqual(sum(row["Count"] for row in histogram), 4)
        self.assertEqual(edge[0]["Min_m"], 9)
        self.assertEqual(edge[0]["Max_m"], 3001)

    def test_nonstandard_confidence_preserved_and_blank_reported(self):
        source = self.features().iloc[:1].copy()
        source.FeatConf = "LowHigh"
        source.TypeConf = ""
        result = quality.prepare_quality_features(source, self.regions())
        rows, _, _, _ = quality.quality_summaries(result)
        values = {(row["Attribute"], row["Value"]): row["Count"] for row in rows}
        self.assertEqual(values["FeatConf", "LowHigh"], 1)
        self.assertEqual(values["TypeConf", "Missing"], 1)

    def test_missing_fields_and_duplicate_identifiers_rejected(self):
        source = self.features()
        with self.assertRaisesRegex(ValueError, "missing fields"):
            quality.prepare_quality_features(source.drop(columns="EdgeAcc_m"), self.regions())
        source.at[1, "ReefFID"] = source.at[0, "ReefFID"]
        with self.assertRaisesRegex(ValueError, "duplicate ReefFID"):
            quality.prepare_quality_features(source, self.regions())

    def test_quality_only_writes_outputs_without_countable_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "features.shp"
            features, regions = self.with_new_caledonia()
            features.to_file(source)
            with patch.multiple(quality, INPUT_FEATURES=source,
                                OUTPUT_CSV=directory / "region-stats.csv",
                                WORK_DIR=directory / "work"), \
                    patch.object(quality, "load_regions", return_value=regions), \
                    patch.object(quality, "load_countable",
                                 side_effect=AssertionError("Must not use countable cache")):
                quality.main(["--quality-only"])
                prefix = f"A05_Feature-quality_{quality.VERSION}"
                for suffix in ("-confidence.csv", "-edge-accuracy.csv",
                               "-edge-histogram.csv", ".md", ".png"):
                    path = directory / f"{prefix}{suffix}"
                    self.assertTrue(path.exists())
                    self.assertGreater(path.stat().st_size, 0)
                report = (directory / f"{prefix}.md").read_text(encoding="utf-8")
                self.assertIn("3 full-classification coral and rocky reef records", report)
                self.assertIn("Legacy area default", report)
                self.assertIn("Missing", report)
                self.assertIn("not measured", report)
                self.assertFalse((directory / "region-stats.csv").exists())
                first = pd.read_csv(directory / f"{prefix}-confidence.csv")
                self.assertIn("New Caledonia", first.Region.tolist())
                quality.main(["--quality-only"])
                pd.testing.assert_frame_equal(
                    first, pd.read_csv(directory / f"{prefix}-confidence.csv")
                )

    def test_histogram_header_and_panel_titles_do_not_overlap(self):
        import matplotlib.pyplot as plt

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "features.shp"
            features, regions = self.with_new_caledonia()
            features.to_file(source)
            figures = []
            close = plt.close
            def retain(figure):
                if hasattr(figure, "canvas"):
                    figures.append(figure)
            with patch.multiple(quality, INPUT_FEATURES=source,
                                OUTPUT_CSV=directory / "region-stats.csv"), \
                    patch.object(quality, "load_regions", return_value=regions), \
                    patch.object(plt, "close", side_effect=retain):
                quality.write_quality_summary()
            try:
                figure = figures[-1]
                figure.canvas.draw()
                renderer = figure.canvas.get_renderer()
                legend = figure.legends[0].get_window_extent(renderer)
                self.assertFalse(legend.overlaps(figure._suptitle.get_window_extent(renderer)))
                self.assertEqual(figure._suptitle.get_fontsize(), 15.6)
                self.assertEqual(figure._supxlabel.get_fontsize(), 13)
                self.assertEqual(figure._supylabel.get_fontsize(), 13)
                self.assertEqual(figure.subplotpars.hspace, 0.3)
                self.assertEqual(figure.subplotpars.wspace, 0.15)
                xlabel = figure._supxlabel.get_window_extent(renderer)
                self.assertFalse(any("New Caledonia" in axis.title.get_text()
                                     for axis in figure.axes if axis.get_visible()))
                for axis in figure.axes:
                    if axis.get_visible():
                        self.assertFalse(legend.overlaps(axis.title.get_window_extent(renderer)))
                        self.assertTrue(any(label.get_visible() for label in axis.get_xticklabels()))
                        self.assertFalse(any(xlabel.overlaps(label.get_window_extent(renderer))
                                             for label in axis.get_xticklabels() if label.get_visible()))
                        low, high = axis.get_xlim()
                        self.assertTrue(low < 10 and high > 3000)
                        self.assertEqual(axis.title.get_fontsize(), 13)
                        self.assertTrue(all(label.get_fontsize() == 13
                                            for label in axis.get_yticklabels()))
                        self.assertEqual(axis.get_xlabel(), "")
                        self.assertEqual(axis.get_ylabel(), "")
            finally:
                for figure in figures:
                    close(figure)


if __name__ == "__main__":
    unittest.main()
