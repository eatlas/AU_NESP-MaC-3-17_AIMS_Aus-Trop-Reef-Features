"""Verify targeted stage 06 geometry cleanup and publication validation."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon, box


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publication", ROOT / "06-crosswalk.py")
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)


class PublicationGeometryTests(unittest.TestCase):
    def frame(self, geometry):
        return gpd.GeoDataFrame({
            "ReefFID": ["test-reef"], "RB_Type_L3": ["Coral Reef"],
            "Attachment": ["Oceanic"], "DepthCat": ["Shallow"],
            "EdgeAcc_m": [10], "geometry": [geometry],
        }, crs=4283)

    def spike(self):
        return Polygon([
            (150, -17), (150.001, -17), (150.001, -16.999),
            (150.0005, -16.999), (150.0005, -16.9989),
            (150.0005, -16.999), (150, -16.999), (150, -17),
        ])

    def test_valid_features_and_attributes_unchanged(self):
        source = self.frame(box(150, -17, 150.001, -16.999))
        result = publication.repair_publication_geometry(source)
        self.assertTrue(result.geometry.iloc[0].equals_exact(source.geometry.iloc[0], 0))
        pd.testing.assert_frame_equal(result, source)

    def test_spike_removed_without_loss_or_analysis_invalidity(self):
        source = self.frame(self.spike())
        self.assertFalse(source.is_valid.all())
        result = publication.repair_publication_geometry(source)
        self.assertEqual(len(result), len(source))
        self.assertTrue(result.is_valid.all())
        self.assertTrue(result.to_crs(3577).is_valid.all())
        self.assertFalse(result.geometry.iloc[0].intersects(Point(150.0005, -16.99895)))
        pd.testing.assert_frame_equal(
            result.drop(columns="geometry"), source.drop(columns="geometry")
        )
        self.assertFalse(source.is_valid.all())
        area_change = result.to_crs(3577).area.iloc[0] - source.to_crs(3577).area.iloc[0]
        self.assertLessEqual(abs(area_change), publication.MAX_REPAIR_AREA_M2)

    def test_bow_tie_is_rejected_instead_of_splitting(self):
        bow_tie = Polygon([(150, -17), (150.01, -16.99),
                           (150.01, -17), (150, -16.99), (150, -17)])
        with self.assertRaisesRegex(ValueError, "changes polygon count"):
            publication.repair_publication_geometry(self.frame(bow_tie))

    def test_excessive_area_change_is_rejected(self):
        with patch.object(publication, "MAX_REPAIR_AREA_M2", 0):
            with self.assertRaisesRegex(ValueError, "area change"):
                publication.repair_publication_geometry(self.frame(self.spike()))

    def test_missing_empty_and_wrong_type_block_publication(self):
        for geometry in (None, Polygon(), Point(150, -17)):
            with self.subTest(geometry=geometry):
                with self.assertRaises(ValueError):
                    publication.repair_publication_geometry(self.frame(geometry))

    def test_main_writes_cleaned_geometry_and_recalculated_area(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            source_path = path / "input.shp"
            output_path = path / "output.shp"
            source = self.frame(self.spike())
            source.to_file(source_path)
            crosswalk = pd.DataFrame({
                field: ["test-value"] for field in publication.CROSSWALK_FIELDS
            })
            with patch.object(publication, "INPUT_SHP", str(source_path)), \
                    patch.object(publication, "output_shp", str(output_path)), \
                    patch.object(publication, "load_crosswalk", return_value=crosswalk), \
                    patch.object(publication, "validate_features", return_value=([0], [0], [])):
                publication.main()
            output = gpd.read_file(output_path)
            self.assertTrue(output.is_valid.all())
            self.assertTrue(output.to_crs(3577).is_valid.all())
            self.assertEqual(output.ReefFID.tolist(), source.ReefFID.tolist())
            self.assertEqual(output.Area_km2.iloc[0],
                             round(output.to_crs(3577).area.iloc[0] / 1e6, 4))
            self.assertFalse(gpd.read_file(source_path).is_valid.all())


if __name__ == "__main__":
    unittest.main()
