"""Check that A01 reports source statistics and reuses stage 08 L2 geometry."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("summary_stats", ROOT / "A01-summary-stats.py")
summary_stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary_stats)


class SummaryStatsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        previous_directory = Path.cwd()
        os.chdir(temporary.name)
        self.addCleanup(os.chdir, previous_directory)
        self.version = "test-v1"
        Path("config.ini").write_text(f"[general]\nversion = {self.version}\n", encoding="utf-8")
        self.output_dir = Path("data") / self.version / "out" / "stats"
        self.source_path = (
            self.output_dir.parent / "full-classes"
            / f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_{self.version}.shp"
        )
        self.l2_path = (
            self.output_dir.parent / "simp-classes"
            / f"AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features_L2_{self.version}.shp"
        )
        self.source_path.parent.mkdir(parents=True)
        self.l2_path.parent.mkdir(parents=True)
        self.source = gpd.GeoDataFrame({
            "RB_Type_L3": ["Coral Reef", "Coral Reef Flat", "Limestone Reef"],
            "RB_Type_L2": ["Coral Reef", "Coral Reef", "Rocky Reef"],
            "Area_km2": [0.1234, 0.2345, 0.01],
            "geometry": [box(0, 0, 100, 100), box(100, 0, 200, 100),
                         box(500, 0, 600, 100)],
        }, crs=3577)
        self.l2 = gpd.GeoDataFrame({
            "L2FID": [1, 2, 3],
            "RB_Type_L2": ["Coral Reef", "Coral Reef", "Rocky Reef"],
            "Area_km2": [999.0, 0.0, 888.0],
            "geometry": [box(0, 0, 200, 100), box(1000, 0, 1000.1, 0.1),
                         box(500, 0, 600, 100)],
        }, crs=3577)
        self.source.to_file(self.source_path)
        self.l2.to_file(self.l2_path)

    def test_reuses_l2_geometry_retains_source_tables_and_recalculates_unrounded_areas(self):
        with patch.object(gpd.GeoDataFrame, "dissolve", side_effect=AssertionError(
                "A01 must not dissolve geometry")), \
                patch.object(gpd.GeoDataFrame, "to_file", side_effect=AssertionError(
                    "A01 must not create a shapefile")):
            summary_stats.main()
        table1 = pd.read_csv(self.output_dir / f"A01-summary-stats_{self.version}_table-1.csv")
        table2 = pd.read_csv(self.output_dir / f"A01-summary-stats_{self.version}_table-2.csv")
        table3 = pd.read_csv(self.output_dir / f"A01-summary-stats_{self.version}_table-3.csv")
        source_coral = table2.loc[table2.RB_Type_L2.eq("Coral Reef")].iloc[0]
        coral = table3.loc[table3.RB_Type_L2.eq("Coral Reef")].iloc[0]
        self.assertEqual(source_coral.Feature_Count, 2)
        self.assertAlmostEqual(source_coral.Total_Area_km2, 0.3579)
        self.assertEqual(table1.Feature_Count.sum(), len(self.source))
        self.assertAlmostEqual(table1.Total_Area_km2.sum(), self.source.Area_km2.sum())
        self.assertEqual(coral.Feature_Count, 2)
        self.assertAlmostEqual(coral.Total_Area_km2, 0.02000001, places=12)
        self.assertEqual(table3.Feature_Count.sum(), 3)
        report = (self.output_dir / f"A01-summary-stats_{self.version}.md").read_text(
            encoding="utf-8")
        self.assertIn(f"../simp-classes/{self.l2_path.name}", report)
        self.assertIn("Input L2 polygons: 3", report)
        self.assertIn("08-make-RB_Type_L2.py", report)
        self.assertIn("stage 08 Area_km2 attribute is not summed", report)
        self.assertNotIn("RB-Type-L2.shp", report)
        self.assertEqual(list(self.output_dir.glob("*.shp")), [])
        restored = gpd.read_file(self.l2_path)
        self.assertTrue(restored.geometry.geom_equals(self.l2.geometry).all())
        self.assertEqual(restored.Area_km2.tolist(), [999.0, 0.0, 888.0])

    def test_missing_l2_input_requests_stage_08_instead_of_falling_back_to_dissolution(self):
        self.l2_path.unlink()
        with patch.object(gpd, "read_file") as read_file:
            with self.assertRaisesRegex(FileNotFoundError, "Run python 08-make-RB_Type_L2.py"):
                summary_stats.main()
            read_file.assert_not_called()
        self.assertFalse(self.output_dir.exists())


if __name__ == "__main__":
    unittest.main()
