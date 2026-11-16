"""Check A07 lineage, regional allocation, removal counts and Markdown output."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import geopandas as gpd
from shapely.geometry import MultiPolygon, Point, Polygon, box


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("remap_stats", ROOT / "A07-gbr-ts-remap-stats.py")
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


def polygons(geometries, **fields):
    return gpd.GeoDataFrame({**fields, "geometry": geometries}, crs=3577)


class RemapStatsTests(unittest.TestCase):
    def setUp(self):
        self.regions = polygons(
            [box(0, 0, 100, 100), box(100, 0, 200, 100), box(200, 0, 300, 100)],
            subregion=["GBR", "Torres Strait", "Other"],
        )
        self.inshore = polygons([box(0, 0, 50, 100)])
        self.final = polygons(
            [box(10, 10, 20, 20), box(60, 10, 70, 20), box(110, 10, 120, 20),
             box(30, 10, 40, 20), box(130, 10, 140, 20), box(210, 10, 220, 20)],
            Dataset=["Aus-Trop-Reef-Features_test"] * 4 + ["TS Features",
                                                           "Aus-Trop-Reef-Features_test"],
            ReefID=["old-1", None, "old-2", " ", "old-3", None],
            PrevReefID=[None, "old-4;old-5", "old-6", None, None, None],
            RB_Type_L2=["Coral Reef", "Rocky Reef", "Sediment",
                        "Coral Reef", "Coral Reef", "Coral Reef"],
        )
        self.edits = polygons([
            MultiPolygon([box(10, 10, 20, 20), box(30, 10, 40, 20)]),
            box(60, 10, 70, 20), box(110, 10, 120, 20), box(210, 10, 220, 20),
        ])
        self.legacy = polygons([box(5, 30, 20, 50), box(10, 30, 25, 50),
                                box(110, 30, 120, 50)])
        self.controls = gpd.GeoDataFrame({
            "ACTION": ["Remove", "Remove", "Remove", "Move", "Link"],
            "geometry": [Point(15, 40), Point(15, 40), Point(115, 40),
                         Point(65, 40), Point(115, 60)],
        }, crs=3577)

    def analyse(self, **overrides):
        inputs = dict(final=self.final, edits=self.edits, controls=self.controls,
                      legacy=self.legacy, regions=self.regions,
                      inshore=self.inshore, version="test")
        inputs.update(overrides)
        return stats.analyse(**inputs)

    def test_lineage_provenance_source_comparison_and_distinct_removals(self):
        tables, excluded, repairs = self.analyse()
        self.assertEqual(repairs, [])
        one, two, three = tables
        total = one.iloc[4]
        self.assertEqual(total["Original Reef Edit polygons"], 3)
        self.assertEqual(total["Final editing features"], 4)
        self.assertEqual(total["Difference (final - source)"], 1)
        self.assertEqual(total.Updated, 3)
        self.assertEqual(total["Newly mapped"], 1)
        self.assertEqual(total["Retained source features"], 1)
        self.assertEqual(total["Retained source (%)"], 20.0)
        self.assertEqual(two.iloc[4][["ReefID only", "PrevReefID only",
                                     "Both identifiers"]].tolist(), [1, 1, 1])
        self.assertEqual(two.iloc[4]["Updated coral/rocky reef features"], 2)
        self.assertEqual(two.iloc[4]["Newly mapped coral/rocky reef features"], 1)
        self.assertEqual(two.iloc[4]["Retained coral/rocky reef features"], 1)
        self.assertEqual(two.iloc[4]["Total coral/rocky reef features"], 4)
        self.assertEqual(two.iloc[4]["Retained coral/rocky reef (%)"], 25.0)
        self.assertEqual(three.iloc[4]["Remove points"], 3)
        self.assertEqual(three.iloc[4]["Distinct removed legacy features"], 3)
        self.assertEqual(three.iloc[0]["Distinct removed legacy features"], 2)
        self.assertEqual(excluded["Final features"], 1)
        paragraph = stats.results_paragraph(one, three)
        self.assertIn("1 recorded positional correction", paragraph)
        self.assertIn("did not overlap the revised outlines", paragraph)
        self.assertIn("50.0% of mapped features", paragraph)
        self.assertNotIn("recorded legacy identifiers", paragraph)
        self.assertNotIn("Reef Edit layer", paragraph)
        self.assertNotIn("Link instruction", paragraph)

    def test_allocation_safeguards_and_different_crs(self):
        allocator = stats.SpatialAllocation(self.regions, self.inshore)
        cases = polygons([box(40, 10, 60, 20), box(41, 10, 61, 20),
                          box(90, 10, 120, 20), box(-80, 10, 10, 20),
                          box(210, 10, 220, 20)])
        self.assertEqual(allocator.assign(cases).tolist(),
                         ["GBR inshore", "GBR outside inshore", "Torres Strait", None, None])
        points = gpd.GeoDataFrame(geometry=[Point(100, 40), Point(50, 40)], crs=3577)
        self.assertEqual(allocator.assign(points).tolist(),
                         ["GBR outside inshore", "GBR inshore"])
        tables, _, _ = self.analyse(edits=self.edits.to_crs(epsg=4283),
                                controls=self.controls.to_crs(epsg=4326))
        self.assertEqual(tables[0].iloc[4]["Original Reef Edit polygons"], 3)
        self.assertEqual(tables[2].iloc[4]["Distinct removed legacy features"], 3)

    def test_empty_editing_and_controls_and_invalid_inputs(self):
        tables, _, _ = self.analyse(final=self.final.iloc[0:0], edits=self.edits.iloc[0:0],
                                controls=self.controls.iloc[0:0])
        self.assertEqual(tables[0].iloc[4]["Final editing features"], 0)
        self.assertTrue(tables[0]["Retained source (%)"].isna().all())
        self.assertIn("Not applicable", stats.markdown_table(tables[0]))
        self.assertIn("No processed editing features", stats.results_paragraph(tables[0], tables[2]))
        bad = self.controls.copy()
        bad.loc[0, "ACTION"] = "Unexpected"
        with self.assertRaisesRegex(ValueError, "unsupported ACTION"):
            self.analyse(controls=bad)
        bad.loc[0, "ACTION"] = None
        with self.assertRaisesRegex(ValueError, "missing or blank ACTION"):
            self.analyse(controls=bad)
        with self.assertRaisesRegex(ValueError, "missing fields"):
            self.analyse(final=self.final.drop(columns="ReefID"))
        bad = self.edits.copy()
        bad.loc[0, "geometry"] = None
        with self.assertRaisesRegex(ValueError, "geometry at rows"):
            self.analyse(edits=bad)
        bad = self.controls.copy()
        bad.loc[0, "geometry"] = Point(80, 80)
        with self.assertRaisesRegex(ValueError, "no legacy target"):
            self.analyse(controls=bad)

    def test_reconciliation_rejects_incorrect_counts(self):
        tables, _, _ = self.analyse()
        tables[0].loc[0, "Updated"] += 1
        with self.assertRaisesRegex(ValueError, "do not reconcile"):
            stats.validate_totals(*tables)

    def test_main_writes_only_markdown_with_configured_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            previous = Path.cwd()
            os.chdir(temporary)
            try:
                config_path = Path("config.ini")
                config_path.write_text(
                    "[general]\nversion = test\nin_path = custom-inputs\n"
                    f"in_3p_path = {Path(temporary) / 'third-party'}\n", encoding="utf-8",
                )
                config = stats.configparser.ConfigParser()
                config.read(config_path)
                _, paths = stats.input_paths(config)
                frames = (self.final, self.edits, self.controls, self.legacy,
                          self.regions, self.inshore)
                for path, frame in zip(paths.values(), frames):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    frame.to_file(path)
                with patch.object(gpd.GeoDataFrame, "to_file",
                                  side_effect=AssertionError("Must not modify inputs")):
                    stats.main()
                output_dir = Path("data") / "test" / "out" / "stats"
                output = output_dir / "A07-gbr-ts-remap-stats_test.md"
                text = output.read_text(encoding="utf-8")
                self.assertEqual(list(output_dir.iterdir()), [output])
                self.assertIn("Table 3.", text)
                self.assertIn("Checks passed", text)
                self.assertIn("3 previously mapped features", text)
                self.assertIn("custom-inputs/Reef-edit", text)
                self.assertIn("third-party/nesp-3-17-analysis-regions", text)
                self.assertIn("Final features: 1 records excluded", text)
                self.assertNotIn("Geometry checks for publication", text)
                self.assertNotIn(Path(temporary).as_posix(), text)
                controls = self.controls.copy()
                controls.loc[0, "ACTION"] = "Bad"
                controls.to_file(paths["Control points"])
                with self.assertRaisesRegex(ValueError, "unsupported ACTION"):
                    stats.main()
                self.assertEqual(output.read_text(encoding="utf-8"), text)
            finally:
                os.chdir(previous)

    def test_invalid_polygons_are_repaired_in_memory_and_disclosed(self):
        final = self.final.copy()
        final.loc[0, "geometry"] = Polygon([(10, 10), (20, 20), (10, 20),
                                            (20, 10), (10, 10)])
        original = final.geometry.to_wkb().tolist()
        tables, _, repairs = self.analyse(final=final)
        self.assertEqual(tables[0].iloc[4].Updated, 3)
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["Source row"], 1)
        self.assertEqual(repairs[0]["Repaired type"], "MultiPolygon")
        self.assertIn("Self-intersection", repairs[0]["Reason"])
        self.assertEqual(final.geometry.to_wkb().tolist(), original)
        self.assertFalse(final.geometry.iloc[0].is_valid)
        final.loc[0, "geometry"] = Polygon([(10, 10), (20, 10), (30, 10), (10, 10)])
        with self.assertRaisesRegex(ValueError, "no valid polygon"):
            self.analyse(final=final)

    def test_provenance_uses_logical_repository_paths_and_hides_external_directories(self):
        local = Path.cwd() / "data" / "test" / "input.shp"
        self.assertEqual(stats.provenance_path(local), "`data/test/input.shp`")
        self.assertEqual(stats.provenance_path(Path("data") / "test" / "input.shp"),
                         "`data/test/input.shp`")
        external = Path.cwd().parent / "external-data" / "input.shp"
        label = stats.provenance_path(external)
        self.assertEqual(label, "`input.shp` (external input; location configured in local config.ini)")
        self.assertNotIn("external-data", label)
        self.assertEqual(stats.provenance_path(Path("..") / "external-data" / "input.shp"),
                         label)

    def test_geometry_issues_shapefile_preserves_locations_and_removes_stale_output(self):
        final = self.final.copy()
        final.loc[0, "geometry"] = Polygon([(10, 10), (20, 20), (10, 20),
                                            (20, 10), (10, 10)])
        _, _, repairs = self.analyse(final=final)
        with tempfile.TemporaryDirectory() as temporary:
            previous = Path.cwd()
            os.chdir(temporary)
            try:
                stats.write_geometry_issues(repairs, "test")
                path = Path("working") / "test" / "A07" / "invalid-polygons.shp"
                layer = gpd.read_file(path)
                self.assertEqual(len(layer), 1)
                self.assertEqual(layer.crs.to_epsg(), 4283)
                self.assertEqual(layer.Source_row.tolist(), [1])
                self.assertEqual(layer.Check_at.tolist(), ["Source CRS"])
                self.assertIn("Self-intersection", layer.Reason.iloc[0])
                self.assertTrue(layer.geometry.iloc[0].equals(
                    gpd.GeoSeries([final.geometry.iloc[0]], crs=3577).to_crs(4283).iloc[0]
                ))
                unrelated = path.parent / "keep.txt"
                unrelated.write_text("keep", encoding="utf-8")
                stats.write_geometry_issues([], "test")
                self.assertFalse(path.exists())
                self.assertEqual(list(path.parent.iterdir()), [unrelated])
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
