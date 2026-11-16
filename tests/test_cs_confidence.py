"""Verify Coral Sea confidence standardisation in both input layers."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("coral_sea", ROOT / "02c-patch-CS-Features.py")
coral_sea = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coral_sea)


class CoralSeaConfidenceTests(unittest.TestCase):
    def test_both_fields_and_layers_preserve_other_values(self):
        values = ["Very high", "High", "Medium", "Low", "Very Low",
                  None, "", "LowHigh", "HighLow"]
        expected = ["High", "High", "Medium", "Low", "Very Low",
                    None, "", "LowHigh", "HighLow"]
        for layer in ("Reefs and Cays", "Atoll Platforms"):
            with self.subTest(layer=layer):
                source = gpd.GeoDataFrame({
                    "FeatConf": values, "TypeConf": values[::-1],
                    "RB_Type_L3": ["Coral Reef"] * len(values),
                    "ReefFID": [f"CS-{index}" for index in range(len(values))],
                    "geometry": [box(index, 0, index + 0.5, 0.5)
                                 for index in range(len(values))],
                }, crs=4283)
                result = coral_sea.process_features(source, layer)
                self.assertEqual(result.FeatConf.tolist(), expected)
                self.assertEqual(result.TypeConf.tolist(), expected[::-1])
                self.assertEqual(result.ReefFID.tolist(), source.ReefFID.tolist())
                self.assertTrue(result.geometry.equals(source.geometry))
                self.assertTrue(result.Dataset.eq("CS Features").all())
                self.assertTrue(result.OrigType.eq("Coral Reef").all())
                repeated = coral_sea.process_features(result.copy(), layer)
                pd.testing.assert_series_equal(repeated.FeatConf, result.FeatConf)
                pd.testing.assert_series_equal(repeated.TypeConf, result.TypeConf)

    def test_main_exports_standardised_layers_without_rewriting_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            reefs_path = directory / "reefs.shp"
            platforms_path = directory / "platforms.shp"
            output_path = directory / "out" / "patched.shp"
            crosswalk_path = directory / "crosswalk.csv"
            for path, reef_type, geometry in (
                (reefs_path, "Coral Reef", box(150, -20, 150.01, -19.99)),
                (platforms_path, "Atoll Platform", box(151, -20, 151.01, -19.99)),
            ):
                gpd.GeoDataFrame({
                    "RB_Type_L3": [reef_type], "FeatConf": ["Very high"],
                    "TypeConf": ["Very high"], "ReefFID": [reef_type],
                    "geometry": [geometry],
                }, crs=4283).to_file(path)
            pd.DataFrame({
                "CS_RB_Type_L3_v0-3": ["Coral Reef", "Atoll Platform"],
                "RB_Type_L3_v0-4": ["Coral Reef", "Oceanic Platform"],
            }).to_csv(crosswalk_path, index=False)
            with patch.object(coral_sea, "get_filepaths", return_value=(
                str(reefs_path), str(platforms_path), str(crosswalk_path), str(output_path)
            )):
                coral_sea.main()
            result = gpd.read_file(output_path)
            self.assertEqual(len(result), 2)
            self.assertTrue(result.FeatConf.eq("High").all())
            self.assertTrue(result.TypeConf.eq("High").all())
            self.assertEqual(set(result.RB_Type_L3), {"Coral Reef", "Oceanic Platform"})
            for path in (reefs_path, platforms_path):
                unchanged = gpd.read_file(path)
                self.assertTrue(unchanged.FeatConf.eq("Very high").all())
                self.assertTrue(unchanged.TypeConf.eq("Very high").all())


if __name__ == "__main__":
    unittest.main()
