"""Synthetic checks for national L2 preparation and A05 regional reporting."""

import csv
import configparser
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon, box

from reef_utils import cluster_countable


ROOT = Path(__file__).resolve().parents[1]


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


l2 = load_script("national_l2", "08-make-RB_Type_L2.py")
distribution = load_script("national_distribution", "A05-reef-distribution.py")


def source_features(geometries, types=None):
    count = len(geometries)
    return gpd.GeoDataFrame({
        "RB_Type_L2": types or ["Coral Reef"] * count,
        "RB_Type_L3": ["Coral Reef"] * count,
        "Attachment": ["Isolated"] * count, "DepthCat": ["Shallow"] * count,
        "DepthCatSr": ["DEM"] * count, "FeatConf": ["High"] * count,
        "TypeConf": ["Medium"] * count, "EdgeSrc": ["Image"] * count,
        "EdgeAcc_m": [10] * count,
        "ReefID": [f"GBR-{index}a" for index in range(count)],
        "ReefFID": [f"source-{index}" for index in range(count)],
        "geometry": geometries,
    }, crs=3577)


class NationalL2Tests(unittest.TestCase):
    def test_seam_repair_preserves_tiny_detached_source_components(self):
        source = source_features([
            box(130, -15, 130.1, -14.9),
            box(131, -15, 131 + 1e-9, -15 + 1e-9),
        ]).set_crs(4283, allow_override=True)
        prepared = l2.prepare_features(source)
        result, members = l2.dissolve_by_l2(prepared)
        self.assertEqual(len(result), 2)
        self.assertEqual(set(members.SourceRow), {1, 2})
        self.assertEqual(set(members.ReefFID), set(source.ReefFID))
        self.assertTrue(result.geometry.is_valid.all())
        self.assertTrue((result.geometry.to_crs(3577).area > 0).all())
        tiny_l2fid = members.loc[members.SourceRow.eq(2), "L2FID"].iloc[0]
        tiny_output = result.loc[result.L2FID.eq(tiny_l2fid), "geometry"].iloc[0]
        self.assertTrue(tiny_output.equals(prepared.geometry.iloc[1]))

    def test_restoring_a_source_part_does_not_depend_on_its_size(self):
        source = source_features([
            box(142, -10.6, 142.001, -10.599),
            box(142.14, -10.54, 142.141, -10.539),
        ]).set_crs(4283, allow_override=True)
        prepared = l2.prepare_features(source)
        with patch("reef_utils.repair_slivers", return_value=prepared.geometry.iloc[0]):
            result, members = l2.dissolve_by_l2(prepared)
        self.assertEqual(len(result), 2)
        self.assertEqual(set(members.SourceRow), {1, 2})
        restored_fid = members.loc[members.SourceRow.eq(2), "L2FID"].iloc[0]
        restored = result.loc[result.L2FID.eq(restored_fid), "geometry"].iloc[0]
        self.assertTrue(restored.equals(prepared.geometry.iloc[1]))
        self.assertGreater(result.loc[result.L2FID.eq(restored_fid), "Area_km2"].iloc[0],
                           0.01)

    def test_dissolve_priorities_and_original_identifiers(self):
        source = source_features([box(0, -2000000, 100, -1999900),
                                  box(100, -2000000, 200, -1999900)])
        source.loc[1, ["RB_Type_L3", "Attachment", "DepthCat", "FeatConf",
                       "TypeConf", "EdgeAcc_m", "EdgeSrc"]] = [
                           "Coral Reef Flat", "Fringing", "Intertidal",
                           "Low", "Very Low", 25, "Other"]
        result, members = l2.dissolve_by_l2(l2.prepare_features(source))
        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row.RB_L3_Agg, "Coral Reef;Coral Reef Flat")
        self.assertEqual(row.Attachment, "Fringing")
        self.assertEqual(row.AttSet, "Fringing;Isolated")
        self.assertEqual(row.DepthCat, "Intertidal")
        self.assertEqual(row.FeatConf, "Low")
        self.assertEqual(row.TypeConf, "Very Low")
        self.assertEqual(row.EdgeAcc_m, 25)
        self.assertEqual(row.EdgeSrc, "Image;Other")
        self.assertAlmostEqual(row.Area_km2, 0.02, places=4)
        self.assertEqual(members.ReefID.tolist(), source.ReefID.tolist())
        self.assertEqual(members.ReefFID.tolist(), source.ReefFID.tolist())
        self.assertEqual(members.L2FID.tolist(), [1, 1])
        self.assertEqual(result.crs.to_epsg(), 4283)

    def test_multipart_source_and_separate_classes(self):
        source = source_features([
            MultiPolygon([box(0, -2000000, 100, -1999900),
                          box(1000, -2000000, 1100, -1999900)]),
            box(100, -2000000, 200, -1999900),
        ], ["Coral Reef", "Rocky Reef"])
        result, members = l2.dissolve_by_l2(l2.prepare_features(source))
        self.assertEqual(len(result), 3)
        self.assertEqual(result.geom_type.tolist(), ["Polygon"] * 3)
        self.assertEqual(members.SourceRow.value_counts().to_dict(), {1: 2, 2: 1})
        self.assertEqual(set(result.RB_Type_L2), {"Coral Reef", "Rocky Reef"})

    def test_confidence_blanks_and_non_standard_values(self):
        source = source_features([box(0, -2000000, 100, -1999900),
                                  box(100, -2000000, 200, -1999900)])
        source.loc[0, "FeatConf"] = None
        source.loc[1, "TypeConf"] = "Very high"
        features = l2.prepare_features(source)
        issues = l2.confidence_issues(features)
        self.assertEqual(issues[["SourceRow", "Field", "Value"]].values.tolist(),
                         [[2, "TypeConf", "Very high"]])
        result, members = l2.dissolve_by_l2(features)
        self.assertTrue(pd.isna(result.FeatConf.iloc[0]))
        self.assertTrue(pd.isna(result.TypeConf.iloc[0]))
        self.assertEqual(members.TypeConf.tolist(), ["Medium", "Very high"])
        for value in ("LowHigh", "HighLow"):
            source.loc[1, "TypeConf"] = value
            features = l2.prepare_features(source)
            self.assertEqual(l2.confidence_issues(features).Value.tolist(), [value])
            self.assertIsNone(l2.aggregate_confidence(features.TypeConf))

    def test_invalid_inputs_and_text_overflow_are_explicit(self):
        source = source_features([box(0, -2000000, 100, -1999900)])
        cases = [("Attachment", "Unknown"), ("DepthCat", None),
                 ("RB_Type_L2", ""), ("EdgeAcc_m", -1), ("EdgeAcc_m", 1.5)]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                invalid = source.copy()
                invalid[field] = value
                with self.assertRaises((ValueError, TypeError)):
                    l2.prepare_features(invalid)
        with self.assertRaisesRegex(ValueError, "Missing input fields"):
            l2.prepare_features(source.drop(columns="ReefFID"))
        with self.assertRaisesRegex(ValueError, "non-empty polygon"):
            l2.prepare_features(source.set_geometry(gpd.GeoSeries([Polygon()], crs=3577)))
        with self.assertRaisesRegex(ValueError, "254 bytes"):
            l2.validate_text_lengths(pd.DataFrame({"EdgeSrc": ["x" * 255]}))


class CountableReefTests(unittest.TestCase):
    def test_separation_width_and_class_boundaries(self):
        source = source_features([
            box(0, 0, 100, 100), box(199, 0, 299, 100),
            box(400, 0, 500, 100), box(0, 0, 100, 100),
            box(1000, 0, 1010, 10),
        ], ["Coral Reef", "Coral Reef", "Coral Reef", "Rocky Reef", "Coral Reef"])
        result, stats = cluster_countable(source)
        self.assertEqual(stats["n_countable"], 3)
        self.assertEqual(stats["n_dropped"], 1)
        self.assertEqual(stats["n_unassigned"], 0)
        self.assertEqual(stats["n_by_class"], {"Coral Reef": 2, "Rocky Reef": 1})
        self.assertAlmostEqual(result.Area_km2.sum(), 0.04, places=8)
        self.assertAlmostEqual(result.geometry.area.max(), 20000, places=4)

    def test_minimum_effective_width_is_measured_from_unbuffered_area(self):
        threshold = 3.141592653589793 * 50**2
        source = source_features([box(0, 0, 100, threshold * 0.99 / 100),
                                  box(1000, 0, 1100, threshold * 1.01 / 100)])
        result, stats = cluster_countable(source)
        self.assertEqual(stats["n_dropped"], 1)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.Area_km2.iloc[0], threshold * 1.01 / 1e6)
        empty, stats = cluster_countable(source.iloc[:1])
        self.assertTrue(empty.empty)
        self.assertEqual(stats["n_countable"], 0)


class RegionDistributionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        for name, value in {
            "WORK_DIR": self.directory / "work",
            "OUTPUT_CSV": self.directory / "out" / "summary.csv",
            "CHECKS_CSV": self.directory / "work" / "checks.csv",
        }.items():
            override = patch.object(distribution, name, value)
            override.start()
            self.addCleanup(override.stop)
        self.reefs = gpd.GeoDataFrame({
            "CountFID": [1], "RB_Type_L2": ["Coral Reef"],
            "geometry": [box(0, 0, 100, 100)],
        }, crs=3577)

    def allocate(self, regions, setting, near=None):
        pieces = distribution.slice_reefs(self.reefs, regions, near, setting)
        areas = pd.Series(self.reefs.geometry.area.values / 1e6,
                          index=self.reefs.CountFID)
        return distribution.assign_counts(pieces, areas)

    def test_configured_regional_input_path_is_used(self):
        configured_path = self.directory / "shared-inputs"

        def read_config(parser, *args, **kwargs):
            parser.read_dict({"general": {"version": "test-version",
                                         "in_3p_path": str(configured_path)}})
            return []

        with patch.object(configparser.ConfigParser, "read", read_config):
            configured = load_script("configured_distribution", "A05-reef-distribution.py")
        for setting in configured.REGIONALISATIONS:
            self.assertTrue(setting["source"].is_relative_to(configured_path))
        self.assertEqual(configured.INPUT_REEFS.name,
                         "AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_L2_test-version.shp")

    def test_split_counts_partial_counts_slivers_and_cache(self):
        regions = gpd.GeoDataFrame({
            "TYPE": ["", "", ""], "NAME": ["A", "B", "Thin"],
            "geometry": [box(0, 0, 60, 100), box(60, 0, 80, 100),
                         box(98, 0, 100, 100)],
        }, crs=3577)
        setting = dict(distribution.REGIONALISATIONS[0], slug="test")
        pieces = self.allocate(regions, setting)
        self.assertEqual(pieces.loc[pieces.Assigned == 1, "NAME"].tolist(), ["A"])
        self.assertEqual(pieces.loc[pieces.Sliver == 1, "NAME"].tolist(), ["Thin"])
        records = distribution.summarise([("Test", pieces)])
        by_name = {row["Region_name"]: row for row in records}
        self.assertNotIn("Thin", by_name)
        self.assertEqual(by_name["A"]["Coral_reef_count"], 1)
        self.assertEqual(by_name["B"]["Coral_reef_partial_count"], 1)
        self.assertEqual(by_name["No match"]["Coral_reef_area_km2"], "0.001800")
        checks = distribution.check_conservation(pieces, self.reefs, "Test")
        self.assertTrue(all(row["Status"] == "Pass" for row in checks))
        self.assertEqual(checks[0]["Sliver_area_km2"], "0.000200")
        distribution.write_pieces(pieces, distribution.reef_cache_path(setting), setting)
        cached = self.allocate(regions, setting)
        self.assertEqual(cached.Assigned.tolist(), pieces.Assigned.tolist())
        self.assertEqual(set(cached.NAME), set(pieces.NAME))

    def test_capad_overlap_majority_counts_and_map_exports(self):
        regions = gpd.GeoDataFrame({
            "TYPE": ["Federal", "State"], "NAME": ["Shared", "Shared"],
            "geometry": [box(0, 0, 70, 100), box(30, 0, 100, 100)],
        }, crs=3577)
        setting = dict(distribution.REGIONALISATIONS[2], near_m=None)
        pieces = self.allocate(regions, setting)
        self.assertEqual(pieces.Assigned.sum(), 2)
        checks = distribution.check_conservation(pieces, self.reefs, setting["name"])
        self.assertEqual(checks[0]["Overlap_extra_count"], 1)
        self.assertEqual(checks[0]["Overlap_extra_area_km2"], "0.004000")
        self.assertEqual(checks[0]["Status"], "Pass")
        records = distribution.summarise([(setting["name"], pieces)])
        self.assertEqual(len(records), 2)
        distribution.export_region_stats(regions, None, records, setting)
        path = distribution.OUTPUT_CSV.parent / (
            f"Aus-Trop-Reef-Features_Region-stats_capad_{distribution.VERSION}.shp")
        mapped = gpd.read_file(path)
        self.assertEqual(set(zip(mapped.TYPE, mapped.NAME)),
                         {("Federal", "Shared"), ("State", "Shared")})
        self.assertEqual(mapped.CoralCount.tolist(), [1, 1])
        self.assertEqual(mapped.CoralPart.tolist(), [0, 0])
        self.assertEqual(mapped.crs.to_epsg(), 3577)

    def test_near_regions_partition_contested_band_outside_all_regions(self):
        regions = gpd.GeoDataFrame({
            "TYPE": ["Federal", "State"], "NAME": ["A", "B"],
            "geometry": [box(-500, -500, 0, 500), box(400, -500, 900, 500)],
        }, crs=3577)
        setting = distribution.REGIONALISATIONS[2]
        near = distribution.build_near_regions(regions, self.reefs, setting)
        self.assertEqual(len(near), 2)
        self.assertAlmostEqual(near.geometry.iloc[0].intersection(
            near.geometry.iloc[1]).area, 0, places=5)
        for geometry in near.geometry:
            self.assertAlmostEqual(geometry.intersection(regions.union_all()).area, 0)
        cached = distribution.build_near_regions(regions, self.reefs, setting)
        self.assertEqual(len(cached), 2)
        pieces = self.allocate(regions, setting, near)
        self.assertEqual(pieces.loc[pieces.Assigned == 1, "Near"].tolist(), [1])
        self.assertTrue(all(row["Status"] == "Pass" for row in
                            distribution.check_conservation(pieces, self.reefs, "Near")))

    def test_overlap_check_writes_debug_layer_and_rejects_wide_overlap(self):
        regions = gpd.GeoDataFrame({
            "TYPE": ["", ""], "NAME": ["A", "B"],
            "geometry": [box(0, 0, 70, 100), box(30, 0, 100, 100)],
        }, crs=3577)
        distribution.WORK_DIR.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "overlaps wider than 5 m"):
            distribution.check_overlaps(regions, "test")
        self.assertTrue((distribution.WORK_DIR / "debug-overlap-test.shp").exists())

    def test_complete_synthetic_l2_to_regional_pipeline_and_cached_rerun(self):
        source = source_features([
            box(0, -2000000, 100, -1999900),
            box(100, -2000000, 200, -1999900),
            box(1000, -2000000, 1100, -1999900),
        ], ["Coral Reef", "Coral Reef", "Rocky Reef"])
        source.loc[0, "FeatConf"] = None
        source.loc[1, "TypeConf"] = "LowHigh"
        source.loc[1, "Attachment"] = "Fringing"
        input_path = self.directory / "input.shp"
        output_path = self.directory / "l2.shp"
        source.to_crs(4283).to_file(input_path)
        qa_path = self.directory / "qa.shp"
        confidence_path = self.directory / "confidence.csv"
        members_path = self.directory / "members.csv"
        with patch.multiple(l2, INPUT_SHP=input_path, OUTPUT_SHP=output_path,
                            MEMBERS_CSV=members_path, MULTI_ATTACHMENT_SHP=qa_path,
                            CONFIDENCE_QA_CSV=confidence_path):
            l2.main()
            self.assertEqual(len(gpd.read_file(output_path)), 2)
            self.assertEqual(len(gpd.read_file(qa_path)), 1)
            self.assertEqual(len(pd.read_csv(members_path)), 3)
            self.assertEqual(pd.read_csv(confidence_path).Value.tolist(), ["LowHigh"])
            source["Attachment"] = "Isolated"
            source["TypeConf"] = "High"
            source.to_crs(4283).to_file(input_path)
            l2.main()
            self.assertTrue(gpd.read_file(qa_path).empty)
            self.assertTrue(pd.read_csv(confidence_path).empty)

        regionalisations = []
        for setting in distribution.REGIONALISATIONS:
            path = self.directory / f"{setting['slug']}.shp"
            if setting["field"] is None:
                regions = gpd.GeoDataFrame({
                    "TYPE": ["Federal", "Federal", "State"],
                    "NAME": ["Park", "Park", "Park"],
                    "geometry": [box(-100, -2000100, 80, -1999800),
                                 box(70, -2000100, 130, -1999800),
                                 box(0, -2000100, 150, -1999800)],
                }, crs=3577)
            else:
                regions = gpd.GeoDataFrame({
                    setting["field"]: ["West", "East", "Unoccupied"],
                    "geometry": [box(-100, -2000100, 120, -1999800),
                                 box(120, -2000100, 500, -1999800),
                                 box(5000, -2000100, 5500, -1999800)],
                }, crs=3577)
            regions.to_file(path)
            regionalisations.append(dict(setting, source=path))
        with patch.multiple(distribution, INPUT_REEFS=output_path,
                            COUNTABLE_CACHE=distribution.WORK_DIR / "countable.shp",
                            REGIONALISATIONS=tuple(regionalisations)):
            distribution.main()
            checks = pd.read_csv(distribution.CHECKS_CSV)
            self.assertEqual(len(checks), 6)
            self.assertEqual(set(checks.Status), {"Pass"})
            with distribution.OUTPUT_CSV.open(newline="", encoding="utf-8") as file:
                records = list(csv.DictReader(file))
            self.assertEqual(list(records[0]), [
                "Region_dataset", "Region_type", "Region_name", "Near_region", "Label",
                "Coral_reef_count", "Coral_reef_partial_count", "Coral_reef_area_km2",
                "Rocky_reef_count", "Rocky_reef_partial_count", "Rocky_reef_area_km2"])
            self.assertNotIn("Unoccupied", {row["Region_name"] for row in records})
            self.assertIn("No match", {row["Region_name"] for row in records})
            for setting in regionalisations:
                mapped = gpd.read_file(distribution.OUTPUT_CSV.parent / (
                    f"Aus-Trop-Reef-Features_Region-stats_{setting['slug']}_"
                    f"{distribution.VERSION}.shp"))
                expected = [row for row in records
                            if row["Region_dataset"] == setting["name"]
                            and row["Region_name"] != "No match"]
                self.assertEqual(len(mapped), len(expected))
                self.assertEqual(sum(mapped.CoralCount),
                                 sum(int(row["Coral_reef_count"]) for row in expected))
            before = distribution.OUTPUT_CSV.read_bytes()
            with patch.object(distribution, "cluster_countable",
                              side_effect=AssertionError("Must reuse countable cache")):
                distribution.main()
            self.assertEqual(distribution.OUTPUT_CSV.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
