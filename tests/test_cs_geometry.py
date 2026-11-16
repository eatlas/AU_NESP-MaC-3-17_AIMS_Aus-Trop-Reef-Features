"""Verify metric sliver cleanup without changing reef and cay geometry."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Point, Polygon, box


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("coral_sea_geometry", ROOT / "02c-patch-CS-Features.py")
coral_sea = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coral_sea)


class CoralSeaGeometryTests(unittest.TestCase):
    def frame(self, geometry):
        return gpd.GeoDataFrame({
            "ReefFID": ["platform-1"], "RB_Type_L3": ["Atoll Platform"],
            "geometry": [geometry],
        }, crs=3577)

    def test_zero_width_spike_removed_and_attributes_retained(self):
        spike = Polygon([
            (0, 0), (100, 0), (100, 100), (50, 100),
            (50, 120), (50, 100), (0, 100), (0, 0),
        ])
        self.assertFalse(spike.is_valid)
        source = self.frame(spike)
        result = coral_sea.clean_platform_slivers(source)
        self.assertTrue(result.geometry.is_valid.all())
        self.assertFalse(result.geometry.iloc[0].intersects(Point(50, 110)))
        self.assertLessEqual(result.total_bounds[3], 100)
        self.assertLess(abs(result.area.iloc[0] - 10000), 0.02)
        pd.testing.assert_frame_equal(
            result.drop(columns="geometry"), source.drop(columns="geometry")
        )
        self.assertEqual(result.crs, source.crs)
        self.assertFalse(source.geometry.iloc[0].is_valid)

    def test_metric_width_threshold_and_geographic_round_trip(self):
        # Position the test in the Coral Sea in Australian Albers coordinates.
        centre = gpd.GeoSeries([Point(150, -17)], crs=4283).to_crs(3577).iloc[0]
        x, y = centre.x, centre.y
        geometry = MultiPolygon([
            box(x, y, x + 100, y + 100),
            box(x + 110, y, x + 110.15, y + 10),
            box(x + 120, y, x + 120.3, y + 10),
        ])
        for crs in (3577, 4283):
            with self.subTest(crs=crs):
                source = self.frame(geometry).to_crs(crs)
                result = coral_sea.clean_platform_slivers(source)
                metric = result.to_crs(3577).geometry.iloc[0]
                self.assertTrue(result.geometry.is_valid.all())
                self.assertEqual(result.crs, source.crs)
                self.assertEqual(len(metric.geoms), 2)
                self.assertFalse(metric.intersects(Point(x + 110.075, y + 5)))
                self.assertTrue(metric.contains(Point(x + 120.15, y + 5)))

    def test_whole_platform_loss_blocks_output(self):
        with self.assertRaisesRegex(ValueError, "Platform buffer cleanup"):
            coral_sea.clean_platform_slivers(self.frame(box(0, 0, 0.15, 10)))

    def test_validation_rejects_missing_empty_and_non_polygon_geometry(self):
        for geometry in (None, Polygon(), Point(0, 0)):
            with self.subTest(geometry=geometry):
                with self.assertRaisesRegex(ValueError, "invalid, empty or non-polygon"):
                    coral_sea.validate_polygons(self.frame(geometry), "Test output")

    def test_main_subtracts_reefs_and_writes_valid_platforms(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            reefs_path = directory / "reefs.shp"
            platforms_path = directory / "platforms.shp"
            crosswalk_path = directory / "crosswalk.csv"
            output_path = directory / "out" / "patched.shp"
            centre = gpd.GeoSeries([Point(150, -17)], crs=4283).to_crs(3577).iloc[0]
            x, y = centre.x, centre.y
            reef = box(x + 40, y + 40, x + 60, y + 60)
            platform = box(x, y, x + 100, y + 100)
            for path, geometry, kind in (
                (reefs_path, reef, "Coral Reef"),
                (platforms_path, platform, "Atoll Platform"),
            ):
                frame = self.frame(geometry)
                frame["RB_Type_L3"] = kind
                frame["ReefFID"] = kind
                frame.to_crs(4283).to_file(path)
            pd.DataFrame({
                "CS_RB_Type_L3_v0-3": ["Coral Reef", "Atoll Platform"],
                "RB_Type_L3_v0-4": ["Coral Reef", "Oceanic Platform"],
            }).to_csv(crosswalk_path, index=False)
            original_reef = gpd.read_file(reefs_path).geometry.iloc[0]
            original_platform = gpd.read_file(platforms_path).geometry.iloc[0]
            with patch.object(coral_sea, "get_filepaths", return_value=(
                str(reefs_path), str(platforms_path), str(crosswalk_path), str(output_path)
            )):
                coral_sea.main()
            output = gpd.read_file(output_path)
            self.assertEqual(len(output), 2)
            self.assertTrue(output.geometry.is_valid.all())
            self.assertEqual(output.crs.to_epsg(), 4283)
            self.assertTrue(output.geometry.iloc[0].equals_exact(original_reef, 0))
            metric = output.to_crs(3577)
            # Geographic round trips introduce microscopic boundary differences.
            self.assertLess(metric.geometry.iloc[1].intersection(metric.geometry.iloc[0]).area, 1e-4)
            self.assertTrue(
                gpd.read_file(platforms_path).geometry.iloc[0].equals_exact(original_platform, 0)
            )


if __name__ == "__main__":
    unittest.main()
