"""Synthetic checks for national L2 preparation and A05 regional reporting."""

import csv
import configparser
import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon, Polygon, box

from reef_utils import (
    DEM_FIELDS, DEM_PERCENTILE_FIELDS, SLIVER_EPS, _simplify_l2_boundaries,
    cluster_countable, repair_slivers,
)


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
        "PrevReefID": [f"previous-{index}" for index in range(count)],
        "Dataset": ["Synthetic"] * count,
        "Sovereign1": ["Australia"] * count,
        "geometry": geometries,
    }, crs=3577)


class NationalL2Tests(unittest.TestCase):
    def test_multipart_seam_repair_matches_original_buffer_operation(self):
        holed = Polygon(
            box(0, 0, 1, 1).exterior.coords,
            [box(0.25, 0.25, 0.75, 0.75).exterior.coords])
        cases = [
            MultiPolygon([box(0, 0, 1, 1), box(2, 0, 3, 1)]),
            MultiPolygon([box(0, 0, 1, 1),
                          box(1 + SLIVER_EPS / 2, 0, 2, 1)]),
            MultiPolygon([box(0, 0, 1, 1),
                          box(1 + SLIVER_EPS * 3, 0, 2, 1)]),
            MultiPolygon([holed, box(2, 0, 3, 1)]),
            MultiPolygon([box(130, -15, 130.1, -14.9),
                          box(131, -15, 131 + 1e-9, -15 + 1e-9)]),
        ]
        for geometry in cases:
            with self.subTest(wkt=geometry.wkt):
                expected = geometry.buffer(SLIVER_EPS).buffer(-SLIVER_EPS)
                if (expected.is_empty
                        or abs(expected.area - geometry.area) > 1e-6 * geometry.area):
                    expected = geometry
                result = repair_slivers(geometry)
                self.assertTrue(result.is_valid)
                self.assertLessEqual(result.symmetric_difference(expected).area, 1e-14)
                expected_parts = len(expected.geoms) if expected.geom_type == "MultiPolygon" else 1
                result_parts = len(result.geoms) if result.geom_type == "MultiPolygon" else 1
                self.assertEqual(result_parts, expected_parts)

    def test_seam_buffering_reports_progress_at_intervals_and_completion(self):
        geometry = MultiPolygon([box(index * 2, 0, index * 2 + 1, 1)
                                 for index in range(1001)])
        output = io.StringIO()
        with redirect_stdout(output):
            result = repair_slivers(geometry, show_progress=True)
        self.assertIn("Expanding: 1000/1001 parts", output.getvalue())
        self.assertIn("Expanding: 1001/1001 parts", output.getvalue())
        self.assertIn("Merging expanded boundaries", output.getvalue())
        self.assertIn("Contracting: 1001/1001 parts", output.getvalue())
        self.assertEqual(len(result.geoms), 1001)

    def test_seam_repair_still_closes_gaps_across_buffer_groups(self):
        geometry = MultiPolygon([
            *[box(100 + index * 3, 0, 101 + index * 3, 1) for index in range(999)],
            box(0, 0, 1, 1), box(1 + SLIVER_EPS / 2, 0, 2, 1),
        ])
        result = repair_slivers(geometry)
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.geoms), 1000)
        self.assertTrue(result.covers(box(0.5, 0.25, 1.5, 0.75)))

    def test_grouped_simplification_retains_valid_topology_and_reports_progress(self):
        geometry = MultiPolygon([box(index * 2, 0, index * 2 + 1, 1)
                                 for index in range(1001)])
        output = io.StringIO()
        with redirect_stdout(output):
            result = _simplify_l2_boundaries(geometry)
        self.assertIn("Simplifying: 1000/1001 parts", output.getvalue())
        self.assertIn("Simplifying: 1001/1001 parts", output.getvalue())
        self.assertTrue(result.is_valid)
        self.assertTrue(result.equals(geometry))
        with patch.object(MultiPolygon, "simplify", return_value=box(0, 0, 1, 1)):
            with redirect_stdout(output):
                result = _simplify_l2_boundaries(geometry)
        self.assertIs(result, geometry)
        self.assertIn("retaining unsimplified boundaries", output.getvalue())

    def test_dissolve_reports_geometry_and_attribute_milestones(self):
        source = source_features([box(130, -15, 130.001, -14.999)])
        source = source.set_crs(4283, allow_override=True)
        output = io.StringIO()
        with redirect_stdout(output):
            result = l2.dissolve_by_l2(l2.prepare_features(source))
        for message in (
                "Unioning source boundaries", "Union complete", "Repairing seams",
                "Seam repair complete", "Simplifying boundaries",
                "Checking source coverage", "Assigning 1 source parts",
                "Building components: 1/1", "Coral Reef complete",
                "Aggregating attributes: 1/1", "Calculating L2 polygon areas"):
            self.assertIn(message, output.getvalue())
        self.assertEqual(len(result), 1)
        self.assertEqual(result.ReefFID.tolist(), ["source-0"])

    def test_seam_repair_preserves_tiny_detached_source_components(self):
        source = source_features([
            box(130, -15, 130.1, -14.9),
            box(131, -15, 131 + 1e-9, -15 + 1e-9),
        ]).set_crs(4283, allow_override=True)
        prepared = l2.prepare_features(source)
        result = l2.dissolve_by_l2(prepared)
        self.assertEqual(len(result), 2)
        self.assertEqual(set(result.ReefFID), set(source.ReefFID))
        self.assertTrue(result.geometry.is_valid.all())
        self.assertTrue((result.geometry.to_crs(3577).area > 0).all())
        tiny_output = result.loc[result.ReefFID.eq("source-1"), "geometry"].iloc[0]
        self.assertTrue(tiny_output.equals(prepared.geometry.iloc[1]))

    def test_restoring_a_source_part_does_not_depend_on_its_size(self):
        source = source_features([
            box(142, -10.6, 142.001, -10.599),
            box(142.14, -10.54, 142.141, -10.539),
        ]).set_crs(4283, allow_override=True)
        prepared = l2.prepare_features(source)
        with patch("reef_utils.repair_slivers", return_value=prepared.geometry.iloc[0]):
            result = l2.dissolve_by_l2(prepared)
        self.assertEqual(len(result), 2)
        self.assertEqual(set(result.ReefFID), set(source.ReefFID))
        restored = result.loc[result.ReefFID.eq("source-1"), "geometry"].iloc[0]
        self.assertTrue(restored.equals(prepared.geometry.iloc[1]))
        self.assertGreater(result.loc[result.ReefFID.eq("source-1"), "Area_km2"].iloc[0],
                           0.01)

    def test_dissolve_priorities_and_original_identifiers(self):
        source = source_features([box(0, -2000000, 100, -1999900),
                                  box(100, -2000000, 200, -1999900)])
        source.loc[1, ["RB_Type_L3", "Attachment", "DepthCat", "FeatConf",
                       "TypeConf", "EdgeAcc_m", "EdgeSrc"]] = [
                           "Coral Reef Flat", "Fringing", "Intertidal",
                           "Low", "Very Low", 25, "Other"]
        result = l2.dissolve_by_l2(l2.prepare_features(source))
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
        self.assertEqual(row.ReefID, "GBR-0a;GBR-1a")
        self.assertEqual(row.ReefFID, "source-0;source-1")
        self.assertEqual(row.PrevReefID, "previous-0;previous-1")
        self.assertEqual(row.Dataset, "Synthetic")
        self.assertEqual(row.Sovereign1, "Australia")
        self.assertEqual(result.crs.to_epsg(), 4283)

    def test_multipart_source_and_separate_classes(self):
        source = source_features([
            MultiPolygon([box(0, -2000000, 100, -1999900),
                          box(1000, -2000000, 1100, -1999900)]),
            box(100, -2000000, 200, -1999900),
        ], ["Coral Reef", "Rocky Reef"])
        result = l2.dissolve_by_l2(l2.prepare_features(source))
        self.assertEqual(len(result), 3)
        self.assertEqual(result.geom_type.tolist(), ["Polygon"] * 3)
        self.assertEqual(result.ReefFID.value_counts().to_dict(), {"source-0": 2, "source-1": 1})
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
        result = l2.dissolve_by_l2(features)
        self.assertTrue(pd.isna(result.FeatConf.iloc[0]))
        self.assertTrue(pd.isna(result.TypeConf.iloc[0]))
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
        for field in l2.SOURCE_LIST_FIELDS:
            with self.subTest(missing_field=field):
                with self.assertRaisesRegex(ValueError, "Missing input fields"):
                    l2.prepare_features(source.drop(columns=field))
        with self.assertRaisesRegex(ValueError, "non-empty polygon"):
            l2.prepare_features(source.set_geometry(gpd.GeoSeries([Polygon()], crs=3577)))
        with self.assertRaisesRegex(ValueError, "254 bytes"):
            l2.validate_text_lengths(pd.DataFrame({"EdgeSrc": ["x" * 255]}))

    def test_source_lists_split_trim_deduplicate_and_ignore_empty_values(self):
        source = source_features([box(0, -2000000, 100, -1999900),
                                  box(100, -2000000, 200, -1999900),
                                  box(200, -2000000, 300, -1999900)])
        for field in l2.SOURCE_LIST_FIELDS:
            source[field] = [" B;A; ;B ", "C; A", None]
        result = l2.dissolve_by_l2(l2.prepare_features(source))
        for field in l2.SOURCE_LIST_FIELDS:
            self.assertEqual(result[field].tolist(), ["A;B;C"])
        for values in ([None, pd.NA, float("nan")], ["", " ; ", "  "]):
            self.assertEqual(l2.join_semicolon(values), "")

    def test_multipart_source_in_one_component_does_not_duplicate_identifiers(self):
        source = source_features([
            MultiPolygon([box(0, -2000000, 100, -1999900),
                          box(200, -2000000, 300, -1999900)]),
            box(100, -2000000, 200, -1999900),
        ])
        result = l2.dissolve_by_l2(l2.prepare_features(source))
        self.assertEqual(len(result), 1)
        self.assertEqual(result.ReefFID.tolist(), ["source-0;source-1"])
        self.assertEqual(result.ReefID.tolist(), ["GBR-0a;GBR-1a"])

    def test_source_list_byte_limits_include_separators_and_utf8_encoding(self):
        for field in l2.SOURCE_LIST_FIELDS:
            for value in ("x" * 254, "\u00e9" * 127):
                with self.subTest(field=field, valid_bytes=len(value.encode("utf-8"))):
                    l2.validate_text_lengths(pd.DataFrame({field: [value]}))
            value = l2.join_semicolon(["x" * 127, "y" * 127])
            for overflow in (value, "\u00e9" * 128):
                with self.subTest(field=field, overflow=overflow):
                    with self.assertRaisesRegex(ValueError, f"{field}.*254 bytes"):
                        l2.validate_text_lengths(pd.DataFrame({field: [overflow]}))

    def test_overflow_reports_all_fields_and_affected_component_details(self):
        features = pd.DataFrame({
            "L2FID": [42, 43], "RB_Type_L2": ["Coral Reef", "Rocky Reef"],
            "ReefFID": ["a" * 127 + ";" + "b" * 127, "short"],
            "PrevReefID": ["short", "c" * 256],
        })
        with self.assertRaises(ValueError) as error:
            l2.validate_text_lengths(features)
        message = str(error.exception)
        self.assertIn("ReefFID exceeds", message)
        self.assertIn("L2FID=42, RB_Type_L2='Coral Reef', 255 bytes, 2 unique values",
                      message)
        self.assertIn("PrevReefID exceeds", message)
        self.assertIn("L2FID=43, RB_Type_L2='Rocky Reef', 256 bytes, 1 unique values",
                      message)

    def test_main_rejects_attribute_overflow_before_preparing_or_sampling_depth(self):
        source = source_features([box(0, -2000000, 100, -1999900),
                                  box(100, -2000000, 200, -1999900)])
        source["ReefFID"] = ["a" * 127, "b" * 127]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(l2.gpd, "read_file", return_value=source), \
                patch.object(l2, "CONFIDENCE_QA_CSV", Path(directory) / "confidence.csv"), \
                patch.object(l2, "prepare_depth_rasters") as prepare_rasters, \
                patch.object(l2, "calculate_depth_statistics") as calculate_depth:
            with self.assertRaisesRegex(ValueError, "ReefFID.*L2FID=1"):
                l2.main()
            prepare_rasters.assert_not_called()
            calculate_depth.assert_not_called()

    def test_known_large_reef_identifier_groups_fit_and_expand_losslessly(self):
        alphabet = [chr(letter) for letter in range(ord("a"), ord("z") + 1)]
        cases = [
            ("R-8137-034", alphabet + ["a" + letter for letter in alphabet[:20]],
             "R-8137-034{a-z,aa-at}", 46),
            ("R-8342-000", alphabet + ["a" + letter for letter in alphabet[:17]],
             "R-8342-000{a-z,aa-aq}", 43),
            ("R-8238-367", alphabet + ["a" + letter for letter in alphabet]
             + ["b" + letter for letter in alphabet]
             + ["c" + letter for letter in alphabet[:14]],
             "R-8238-367{a-z,aa-az,ba-bz,ca-cn}", 92),
        ]
        for base, suffixes, expected, count in cases:
            with self.subTest(base=base):
                originals = [base + suffix for suffix in suffixes]
                encoded = l2.encode_identifier_list(originals)
                self.assertEqual(encoded, expected)
                self.assertLessEqual(len(encoded.encode("utf-8")), 254)
                self.assertEqual(l2.expand_identifier_list(encoded), sorted(originals))
                self.assertEqual(len(l2.expand_identifier_list(encoded)), count)

    def test_identifier_encoding_preserves_gaps_multiple_bases_and_literal_ids(self):
        originals = ["R-8137-034" + suffix for suffix in ("a", "b", "c", "f")]
        originals += ["R-8137-035b", "R-8137-035d", "GBR-123",
                      "R-8137-034", "R-8137-034a-F01", "R-8137-034A"]
        expected = ("GBR-123;R-8137-034;R-8137-034A;R-8137-034a-F01;"
                    "R-8137-034{a-c,f};R-8137-035{b,d}")
        self.assertEqual(l2.encode_identifier_list(originals), expected)
        self.assertEqual(l2.expand_identifier_list(expected), sorted(originals))
        for value in ("R-8137-034a", "R-8137-034aaa", "GBR-0a", "R-12-034a"):
            self.assertEqual(l2.encode_identifier_list([value]), value)
        self.assertEqual(l2.encode_identifier_list([None, pd.NA, "", " ; "]), "")
        self.assertEqual(l2.expand_identifier_list(""), [])

    def test_identifier_encoding_round_trips_suffix_subsets_and_is_deterministic(self):
        suffixes = ["a", "b", "c", "f", "z", "aa", "ab", "ba", "caa"]
        for mask in range(1 << len(suffixes)):
            originals = ["R-8137-034" + suffix for index, suffix in enumerate(suffixes)
                         if mask & (1 << index)]
            encoded = l2.encode_identifier_list(originals)
            self.assertEqual(l2.expand_identifier_list(encoded), sorted(originals))
            self.assertLessEqual(len(encoded), len(";".join(sorted(originals))))
            duplicate_list = [" ; ".join(reversed(originals)), *originals, None]
            self.assertEqual(l2.encode_identifier_list(duplicate_list), encoded)

    def test_identifier_notation_rejects_reserved_source_braces_and_invalid_ranges(self):
        with self.assertRaisesRegex(ValueError, "reserved braces"):
            l2.encode_identifier_list(["R-8137-034{a-c}"])
        for invalid in (
                "R-8137-034{}", "R-8137-034{a-c", "GBR-123{a-c}",
                "R-8137-034{c-a}", "R-8137-034{a-a}", "R-8137-034{z-aa}",
                "R-8137-034{az-ba}", "R-8137-034{1-3}", "R-8137-034{A-C}",
                "R-8137-034{a,,b}"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    l2.expand_identifier_list(invalid)

    def test_dissolve_compresses_only_identifier_fields(self):
        source = source_features([box(0, -2000000, 100, -1999900),
                                  box(100, -2000000, 200, -1999900),
                                  box(200, -2000000, 300, -1999900)])
        originals = ["R-8137-034" + suffix for suffix in ("a", "b", "c")]
        for field in l2.SOURCE_LIST_FIELDS:
            source[field] = originals
        source["PrevReefID"] = ["R-8342-000a;R-8342-000c", "R-8342-000b", None]
        result = l2.dissolve_by_l2(l2.prepare_features(source))
        row = result.iloc[0]
        self.assertEqual(row.ReefFID, "R-8137-034{a-c}")
        self.assertEqual(row.ReefID, "R-8137-034{a-c}")
        self.assertEqual(row.PrevReefID, "R-8342-000{a-c}")
        self.assertEqual(row.Dataset, ";".join(originals))
        self.assertEqual(row.Sovereign1, ";".join(originals))

    def test_identifier_overflow_counts_expanded_values_not_compressed_groups(self):
        value = ";".join(f"R-8137-{number:03d}{{a-c}}" for number in range(20))
        with self.assertRaises(ValueError) as error:
            l2.validate_text_lengths(pd.DataFrame({"L2FID": [1], "ReefFID": [value]}))
        self.assertIn("60 unique values", str(error.exception))

    def test_compressed_identifiers_round_trip_through_shapefile(self):
        alphabet = [chr(letter) for letter in range(ord("a"), ord("z") + 1)]
        originals = ["R-8238-367" + suffix
                     for suffix in alphabet + ["a" + letter for letter in alphabet]]
        source = source_features([box(0, -2000000, 100, -1999900)])
        for field in l2.IDENTIFIER_FIELDS:
            source[field] = l2.encode_identifier_list(originals)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compressed.shp"
            l2.validate_text_lengths(source)
            source.to_file(path, encoding="UTF-8")
            restored = gpd.read_file(path)
            for field in l2.IDENTIFIER_FIELDS:
                self.assertEqual(restored[field].iloc[0], source[field].iloc[0])
                self.assertEqual(l2.expand_identifier_list(restored[field].iloc[0]),
                                 sorted(originals))


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


class DistributionCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "A05"
        self.directory.mkdir()
        override = patch.object(distribution, "WORK_DIR", self.directory)
        override.start()
        self.addCleanup(override.stop)

    def test_clear_removes_all_spatial_cache_families_and_sidecars(self):
        caches = [
            "countable-reefs.shp", "countable-reefs.dbf", "countable-reefs.shp.xml",
            "regions-imcra.shp", "regions-analysis-region.prj",
            "regions-capad-10m.shx", "near-regions-capad-10m-300m.cpg",
            "reefs-by-imcra.shp", "reefs-by-analysis-region.dbf",
            "reefs-by-capad-10m-near300m.shp",
        ]
        preserved = ["region-stats-checks.csv", "debug-overlap-imcra.shp", "notes.txt"]
        for name in caches + preserved:
            (self.directory / name).write_text("existing", encoding="utf-8")
        nested = self.directory / "regions-review.shp"
        nested.mkdir()
        (nested / "keep.txt").write_text("keep", encoding="utf-8")
        distribution.clear_cache()
        for name in caches:
            self.assertFalse((self.directory / name).exists(), name)
        for name in preserved:
            self.assertEqual((self.directory / name).read_text(encoding="utf-8"),
                             "existing")
        self.assertTrue((nested / "keep.txt").exists())

    def test_quality_only_clear_preserves_distribution_caches(self):
        names = ["regions-analysis-region.shp", "regions-analysis-region.dbf",
                 "countable-reefs.shp", "reefs-by-analysis-region.shp",
                 "regions-imcra.shp", "near-regions-capad-10m-300m.shp"]
        for name in names:
            (self.directory / name).touch()
        distribution.clear_cache(quality_only=True)
        for name in names:
            self.assertEqual((self.directory / name).exists(),
                             not name.startswith("regions-analysis-region."))

    def test_missing_cache_directory_is_allowed(self):
        self.directory.rmdir()
        distribution.clear_cache()
        self.assertFalse(self.directory.exists())

    def test_cache_deletion_errors_stop_processing(self):
        (self.directory / "countable-reefs.shp").touch()
        with patch.object(Path, "unlink", side_effect=PermissionError("locked")), \
                self.assertRaisesRegex(PermissionError, "locked"):
            distribution.main([])

    def test_cli_clears_caches_by_default_and_reuses_only_when_requested(self):
        for quality_only in (False, True):
            for use_cache in (False, True):
                with self.subTest(quality_only=quality_only, use_cache=use_cache):
                    args = ["--quality-only"] if quality_only else []
                    if use_cache:
                        args.append("--use-cache")
                    with patch.object(distribution, "clear_cache") as clear, \
                            patch.object(distribution, "write_quality_summary") as quality, \
                            patch.object(distribution, "load_countable",
                                         side_effect=RuntimeError("stop after cache handling")):
                        if quality_only:
                            distribution.main(args)
                            quality.assert_called_once_with()
                        else:
                            with self.assertRaisesRegex(RuntimeError, "stop after cache handling"):
                                distribution.main(args)
                        if use_cache:
                            clear.assert_not_called()
                        else:
                            clear.assert_called_once_with(quality_only=quality_only)


class RegionDistributionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        for name, value in {
            "WORK_DIR": self.directory / "work",
            "OUTPUT_CSV": self.directory / "out" / "summary.csv",
            "OUTPUT_MARKDOWN": self.directory / "out" / "report.md",
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
        self.assertEqual(configured.OUTPUT_MARKDOWN.name,
                         "A05_Report-tables_test-version.md")

    def test_report_tables_preserve_rows_format_numbers_and_caption_provenance(self):
        records = []
        for setting in distribution.REGIONALISATIONS:
            for name, near in [("A | B\nregion", False), ("A | B\nregion", True),
                               (distribution.NO_MATCH, False)]:
                records.append({
                    "Region_dataset": setting["name"],
                    "Label": distribution.region_label("Park", name, near),
                    "Coral_reef_count": 1234, "Coral_reef_partial_count": 12,
                    "Coral_reef_area_km2": "1234.560000",
                    "Rocky_reef_count": 0, "Rocky_reef_partial_count": 1,
                    "Rocky_reef_area_km2": "0.001000" if near else "0.000000",
                })
        checks = [{"Status": "Pass"}]
        with patch.object(distribution, "VERSION", "test-version"):
            distribution.write_report_tables(records, checks)
        report = distribution.OUTPUT_MARKDOWN.read_text(encoding="utf-8")
        captions = [line for line in report.splitlines() if line.startswith("**Table ")]
        self.assertEqual(len(captions), 3)
        for caption, setting in zip(captions, distribution.REGIONALISATIONS):
            self.assertIn(setting["name"], caption)
            self.assertIn("Data: test-version.", caption)
            self.assertIn("Analysis script: A05-reef-distribution.py.", caption)
        self.assertIn("within 300 m", captions[2])
        self.assertIn("double count", captions[2])
        self.assertEqual(report.count(
            "| A \\| B region - Park | 1,234 | 12 | 1,234.6 | 0 | 1 | 0.0 |"), 3)
        self.assertEqual(report.count(
            "| Near: A \\| B region - Park | 1,234 | 12 | 1,234.6 | 0 | 1 | <0.1 |"), 3)
        for table in report.split("|:---|")[1:]:
            self.assertLess(table.index("| A \\|"), table.index("| Near:"))
            self.assertLess(table.index("| Near:"), table.index("| No match"))
        self.assertIn("All count and area conservation checks passed.", report)
        self.assertIn("EPSG:3577", report)
        self.assertIn(distribution.INPUT_REEFS.name, report)
        self.assertIn(distribution.OUTPUT_CSV.name, report)
        self.assertIn(distribution.CHECKS_CSV.name, report)

    def test_report_tables_warn_on_failed_checks_and_empty_regions(self):
        checks = [{"Status": "Fail", "Region_dataset": "CAPAD 2024 - Marine",
                   "RB_Type_L2": "Rocky Reef"}]
        distribution.write_report_tables([], checks)
        report = distribution.OUTPUT_MARKDOWN.read_text(encoding="utf-8")
        self.assertIn("CAPAD 2024 - Marine (Rocky Reef)", report)
        self.assertLess(report.index("**WARNING:"), report.index("**Table 1.**"))
        self.assertNotIn("All count and area conservation checks passed.", report)
        self.assertEqual(report.count("No retained reef area occurs"), 3)

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
        source.loc[1, "Dataset"] = "Other"
        source.loc[1, "Sovereign1"] = "Indonesia"
        source.loc[1, "PrevReefID"] = "previous-0;previous-1"
        source["DepthCat"] = "Surface"
        source["DepthCatSr"] = "Satellite imagery"
        for field in DEM_PERCENTILE_FIELDS:
            source[field] = 999.0
        source["DEMSr"] = "Stale source DEM"
        input_path = self.directory / "input.shp"
        output_path = self.directory / "l2.shp"
        source.to_crs(4283).to_file(input_path)
        qa_path = self.directory / "qa.shp"
        confidence_path = self.directory / "confidence.csv"
        members_path = output_path.with_name(f"{output_path.stem}_members.csv")
        dem_path = self.directory / "dem.tif"
        lpt_path = self.directory / "lpt.tif"
        for path, value in ((dem_path, -40.0), (lpt_path, -2.0)):
            data = np.full((12, 60), value, dtype="float32")
            if path == dem_path:
                data[:, 8:12] = -10
            with rasterio.open(
                    path, "w", driver="GTiff", count=1, width=60, height=12,
                    dtype="float32", crs=3577, transform=from_origin(-100, -1999800, 25, 25),
                    nodata=-9999) as dst:
                dst.write(data, 1)
        with patch.multiple(l2, INPUT_SHP=input_path, OUTPUT_SHP=output_path,
                            MULTI_ATTACHMENT_SHP=qa_path,
                            CONFIDENCE_QA_CSV=confidence_path, LPT_TIF=lpt_path), \
                patch.object(l2, "prepare_depth_rasters",
                             return_value=[(dem_path, -9999, "Synthetic DEM")]):
            l2.main()
            result = gpd.read_file(output_path)
            qa = gpd.read_file(qa_path)
            self.assertEqual(len(result), 2)
            self.assertEqual(len(qa), 1)
            self.assertTrue(set(DEM_FIELDS).issubset(qa.columns))
            for frame in (result, qa):
                self.assertTrue(set(l2.SOURCE_LIST_FIELDS).issubset(frame.columns))
                coral = frame.loc[frame.RB_Type_L2.eq("Coral Reef")].iloc[0]
                self.assertEqual(coral.ReefFID, "source-0;source-1")
                self.assertEqual(coral.ReefID, "GBR-0a;GBR-1a")
                self.assertEqual(coral.PrevReefID, "previous-0;previous-1")
                self.assertEqual(coral.Dataset, "Other;Synthetic")
                self.assertEqual(coral.Sovereign1, "Australia;Indonesia")
                for row in frame.itertuples(index=False):
                    expected_msl = ([-40, -25, -10] if row.RB_Type_L2 == "Coral Reef"
                                    else [-40, -40, -40])
                    np.testing.assert_allclose(
                        [getattr(row, field) for field in DEM_PERCENTILE_FIELDS[:3]],
                        expected_msl)
                    np.testing.assert_allclose(
                        [getattr(row, field) for field in DEM_PERCENTILE_FIELDS[3:]],
                        np.array(expected_msl) + 2)
                self.assertEqual(set(frame.DEMSr), {"Synthetic DEM;EOT20"})
                self.assertEqual(set(frame.DepthCat), {"Surface"})
                self.assertEqual(set(frame.DepthCatSr), {"Satellite imagery"})
                self.assertEqual(frame.crs.to_epsg(), 4283)
            self.assertFalse(members_path.exists())
            self.assertEqual(pd.read_csv(confidence_path).Value.tolist(), ["LowHigh"])
            source["Attachment"] = "Isolated"
            source["TypeConf"] = "High"
            source.to_crs(4283).to_file(input_path)
            l2.main()
            self.assertTrue(gpd.read_file(qa_path).empty)
            self.assertTrue(pd.read_csv(confidence_path).empty)
            self.assertFalse(members_path.exists())

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
        with patch.multiple(distribution, INPUT_REEFS=output_path, INPUT_FEATURES=input_path,
                            COUNTABLE_CACHE=distribution.WORK_DIR / "countable.shp",
                            REGIONALISATIONS=tuple(regionalisations)):
            distribution.main([])
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
            report = distribution.OUTPUT_MARKDOWN.read_text(encoding="utf-8")
            self.assertEqual(report.count("**Table "), 3)
            self.assertEqual(sum(line.startswith("| ") for line in report.splitlines()),
                             len(records) + 3)
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
            report_before = distribution.OUTPUT_MARKDOWN.read_bytes()
            with patch.object(distribution, "cluster_countable",
                              side_effect=AssertionError("Must reuse countable cache")):
                distribution.main([])
            self.assertEqual(distribution.OUTPUT_CSV.read_bytes(), before)
            self.assertEqual(distribution.OUTPUT_MARKDOWN.read_bytes(), report_before)


if __name__ == "__main__":
    unittest.main()
