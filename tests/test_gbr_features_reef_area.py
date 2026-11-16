"""Check A08 repair, GBR clipping, cumulative selections and report output."""

import importlib.util
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Polygon, box


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reef_area", ROOT / "A08-gbr-features-reef-area.py")
area = importlib.util.module_from_spec(spec)
spec.loader.exec_module(area)

M = 1000  # 1 km in metres; 1 km x 1 km box = 1 km2


def km_box(x0, y0, x1, y1):
    return box(x0 * M, y0 * M, x1 * M, y1 * M)


def reversed_rings(x0, y0, x1, y1, island):
    """Reef outline stored as a hole around an island stored as the shell."""
    return Polygon(island.exterior.coords, [km_box(x0, y0, x1, y1).exterior.coords])


class ReefAreaTests(unittest.TestCase):
    def setUp(self):
        self.regions = gpd.GeoDataFrame({
            "subregion": ["GBR", "GBR", "Torres Strait", "Coral Sea"],
            "geometry": [km_box(0, 0, 50, 100), km_box(50, 0, 100, 100),
                         km_box(0, 100, 100, 200), km_box(100, 0, 200, 100)],
        }, crs=3577)
        island = km_box(12, 12, 13, 13)
        self.source = gpd.GeoDataFrame({
            "FEAT_NAME": ["Reef", "Reef", "Reef", "Reef", "Rock", "Sand", "Island", "Reef"],
            "LABEL_ID": ["10-001", "10-002", "99-001", "10-003", "10-004", "10-005",
                         "10-006", "10-007"],
            "geometry": [
                km_box(0, 0, 2, 2),                       # 4 km2 inside GBR
                reversed_rings(10, 10, 15, 15, island),   # 25 - 1 = 24 km2 after repair
                km_box(10, 150, 13, 153),                 # 9 km2 Torres Strait
                km_box(99, 0, 101, 1),                    # crosses into Coral Sea: 1 km2 GBR
                km_box(20, 20, 21, 22),                   # Rock 2 km2
                km_box(30, 30, 30.5, 31),                 # Sand 0.5 km2
                km_box(40, 40, 41, 41),                   # Island not selected
                km_box(0, 300, 1, 301),                   # outside all regions
            ],
        }, crs=3577)

    def test_cumulative_selections_repair_and_clip(self):
        results, repairs, excluded, _ = area.analyse(self.source, self.regions)
        self.assertEqual(results["Source records"].tolist(), [3, 4, 5])
        for got, expected in zip(results["Area (km2)"], [29, 31, 31.5]):
            self.assertAlmostEqual(got, expected, places=6)
        self.assertAlmostEqual(results["Difference from 24,081 km2"][0], 29 - 24081)
        total = repairs[(repairs.Selection == "Reef") & (repairs.Reason == "Total")].iloc[0]
        self.assertEqual(total.Records, 1)
        self.assertAlmostEqual(total["Before repair (km2)"], -24)
        self.assertAlmostEqual(total["After repair (km2)"], 24)
        self.assertIn("Hole lies outside shell", repairs.Reason.tolist())
        by_location = dict(zip(excluded.Location, excluded["Area (km2)"]))
        self.assertAlmostEqual(by_location["Torres Strait region"], 9)
        self.assertAlmostEqual(by_location["Other Analysis-regions"], 1)
        self.assertAlmostEqual(by_location["Outside all Analysis-regions"], 1)

    def test_label_id_is_not_used_for_selection(self):
        moved = self.source.copy()
        moved.loc[0, "LABEL_ID"] = "99-999"
        results, _, _, _ = area.analyse(moved, self.regions)
        self.assertAlmostEqual(results["Area (km2)"][0], 29)

    def test_absent_rock_and_sand_contribute_zero(self):
        reef_only = self.source[self.source.FEAT_NAME.eq("Reef")]
        results, _, _, _ = area.analyse(reef_only, self.regions)
        self.assertEqual(len(set(results["Area (km2)"].round(9))), 1)

    def test_geographic_source_is_projected(self):
        results, _, _, _ = area.analyse(self.source.to_crs(7844), self.regions.to_crs(7844))
        self.assertAlmostEqual(results["Area (km2)"][0], 29, places=3)

    def test_stops_on_invalid_inputs(self):
        cases = {
            "missing CRS": (self.source.set_crs(None, allow_override=True), self.regions),
            "FEAT_NAME": (self.source.rename(columns={"FEAT_NAME": "X"}), self.regions),
            "subregion": (self.source, self.regions.rename(columns={"subregion": "X"})),
            "no GBR": (self.source, self.regions[self.regions.subregion.ne("GBR")]),
            "no Reef": (self.source[self.source.FEAT_NAME.ne("Reef")], self.regions),
        }
        for message, (source, regions) in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                area.analyse(source, regions)

    def test_stops_on_non_polygon_or_empty_geometry(self):
        for geometry in (LineString([(0, 0), (1, 1)]), Polygon()):
            source = self.source.copy()
            source.loc[0, "geometry"] = geometry
            with self.subTest(geometry.geom_type), self.assertRaisesRegex(ValueError, "non-polygon"):
                area.analyse(source, self.regions)

    def test_report_contains_results_and_provenance(self):
        results, repairs, excluded, counts = area.analyse(self.source, self.regions)
        paths = {"GBR Features": ROOT / "data" / "x.shp", "Analysis regions": ROOT / "y.shp",
                 "A05 statistics": ROOT / "data" / "stats.csv"}
        reference = ("A05 national dataset countable reefs (Table B.2)",
                     "3,800", "23,700.1", "950", "305.2")
        report = area.build_report(results, repairs, excluded, counts, "test", paths,
                                   self.source, self.regions, reference)
        self.assertIn("| Reef | 3 | 29.000000 | -24,052.0 | -99.88 |", report)
        self.assertIn("18 June 2025", report)
        self.assertIn("Hole lies outside shell", report)
        self.assertIn("A08-gbr-features-reef-area.py", report)
        self.assertIn("| Countable reefs (A05 rules) |", report)
        self.assertIn("| " + " | ".join(reference) + " |", report)
        self.assertIn("A05 reports 3,800 countable coral reefs and 23,700.1 km2", report)

    def test_a05_reference_uses_current_csv(self):
        row = {"Region_dataset": "Analysis-regions v1", "Region_name": "GBR",
               "Near_region": "No", "Coral_reef_count": 3800,
               "Coral_reef_area_km2": 23700.123, "Rocky_reef_count": 950,
               "Rocky_reef_area_km2": 305.234}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "stats.csv"
            pd.DataFrame([row, {**row, "Region_dataset": "Other"}]).to_csv(path, index=False)
            self.assertEqual(area.read_a05_reference(path)[1:],
                             ("3,800", "23,700.1", "950", "305.2"))
            for rows in ([], [row, row]):
                pd.DataFrame(rows, columns=row).to_csv(path, index=False)
                with self.assertRaisesRegex(ValueError, "exactly one GBR"):
                    area.read_a05_reference(path)
            for field, value in (("Coral_reef_count", 1.5), ("Rocky_reef_count", -1),
                                 ("Coral_reef_area_km2", float("nan")),
                                 ("Rocky_reef_area_km2", float("inf"))):
                pd.DataFrame([{**row, field: value}]).to_csv(path, index=False)
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "invalid GBR"):
                    area.read_a05_reference(path)

    def test_countable_stages_apply_size_and_separation(self):
        source = gpd.GeoDataFrame({
            "FEAT_NAME": ["Reef", "Reef", "Reef", "Rock", "Reef"],
            "geometry": [
                box(1000, 1000, 1200, 1200),   # 200 m square, GBR
                box(1260, 1000, 1270, 1010),   # tiny, 60 m away: joins the first group
                box(5000, 5000, 5010, 5010),   # tiny and isolated: dropped
                box(8000, 8000, 8300, 8300),   # Rock, GBR
                box(20000, 150000, 20300, 150300),  # Torres Strait
            ],
        }, crs=3577)
        counts = area.count_stages(area.prepare_records(source),
                                   area.region_geometries(self.regions))
        coral = counts[counts.Type.eq("Coral Reef")].set_index("Stage")
        self.assertEqual(coral["GBR count"].tolist(), [3, 1, 2, 1])
        self.assertAlmostEqual(coral.loc["Source records", "GBR area (km2)"], 0.0402, places=4)
        self.assertAlmostEqual(coral.loc["Size only", "GBR area (km2)"], 0.04, places=4)
        self.assertAlmostEqual(coral.loc["Countable reefs (A05 rules)", "GBR area (km2)"],
                               0.0401, places=4)
        rocky = counts[counts.Type.eq("Rocky Reef")]
        self.assertEqual(rocky["GBR count"].tolist(), [1, 1, 1, 1])

    def test_count_goes_to_largest_non_sliver_piece(self):
        regions = gpd.GeoDataFrame({"subregion": ["GBR", "Torres Strait"],
                                    "geometry": [box(0, 0, 1000, 1000), box(1000, 0, 2000, 1000)]},
                                   crs=3577)
        sliver_heavy = box(991, 0, 1000, 1000).union(box(991, 0, 1050, 100))
        geometries = gpd.GeoSeries([box(400, 100, 1300, 200), sliver_heavy], crs=3577)
        names = area.assigned_regions(geometries, area.region_geometries(regions)["By name"])
        self.assertEqual(names.tolist(), ["GBR", "Torres Strait"])


if __name__ == "__main__":
    unittest.main()
