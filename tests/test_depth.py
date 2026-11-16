"""Synthetic raster checks for the shared stage 05 and L2 depth processing."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import rasterio
from rasterio.transform import from_bounds, from_origin
from shapely.geometry import box

from reef_utils import (
    AUS_BATHY_TOPO_NODATA,
    DEM_FIELDS,
    DEM_PERCENTILE_FIELDS,
    LPTLookup,
    MULTIRES_BATHY_NODATA,
    _depth_transformer,
    assign_depth_percentiles,
    calculate_depth_statistics,
    get_percentiles_with_lat,
    prepare_depth_rasters,
)


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("depth_stage05", ROOT / "05-add-depth.py")
stage05 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage05)


class DepthTests(unittest.TestCase):
    def setUp(self):
        _depth_transformer.cache_clear()
        self.addCleanup(_depth_transformer.cache_clear)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.dem = np.arange(-40, -24, dtype="float32").reshape(4, 4)
        self.dem[1, 0] = -9999
        self.dem_path = self.write_raster("dem.tif", self.dem, from_origin(0, 4, 1, 1))
        rows, cols = np.indices((6, 6))
        self.lpt = (-rows - 2 * cols).astype("float32")
        self.lpt_path = self.write_raster(
            "lpt.tif", self.lpt, from_origin(-0.5, 4.5, 1, 1))
        self.lookup = LPTLookup(self.lpt_path)
        self.rasters = [(self.dem_path, -9999, "Synthetic DEM")]
        self.reefs = gpd.GeoDataFrame({
            "DepthCat": ["Surface"], "DepthCatSr": ["Satellite imagery"],
            "geometry": [box(0, 0, 4, 4)],
        }, crs=4326, index=[17])

    def write_raster(self, filename, data, transform, crs=4326):
        path = self.directory / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
                path, "w", driver="GTiff", count=1, height=data.shape[0],
                width=data.shape[1], dtype="float32", crs=crs,
                transform=transform, nodata=-9999) as dst:
            dst.write(data.astype("float32"), 1)
        return path

    def expected_percentiles(self):
        valid = self.dem != -9999
        msl = self.dem[valid]
        lat = (self.dem - self.lpt[1:5, 1:5])[valid]
        return np.concatenate([np.percentile(msl, [10, 50, 90]),
                               np.percentile(lat, [10, 50, 90])])

    def test_pixelwise_lat_percentiles_rounding_index_and_categories(self):
        original = self.reefs.copy()
        result = calculate_depth_statistics(self.reefs, self.rasters, self.lookup)
        self.assertEqual(list(result.columns), list(DEM_FIELDS))
        self.assertEqual(result.index.tolist(), [17])
        expected = [round(float(value), 1) for value in self.expected_percentiles()]
        np.testing.assert_allclose(result[list(DEM_PERCENTILE_FIELDS)].iloc[0], expected)
        self.assertEqual(result.DEMSr.iloc[0], "Synthetic DEM;EOT20")
        pd.testing.assert_frame_equal(self.reefs, original)

    def test_projected_geometry_and_lpt_coordinate_reprojection(self):
        projected = self.reefs.to_crs(3857)
        result = calculate_depth_statistics(projected, self.rasters, self.lookup)
        expected = [round(float(value), 1) for value in self.expected_percentiles()]
        np.testing.assert_allclose(result[list(DEM_PERCENTILE_FIELDS)].iloc[0], expected)
        projected_point = gpd.GeoSeries.from_xy([0.5], [3.5], crs=4326).to_crs(3857)
        looked_up = self.lookup.get_values_for_coords(
            projected_point.x.to_numpy(), projected_point.y.to_numpy(), projected_point.crs)
        np.testing.assert_allclose(looked_up, [self.lpt[1, 1]])

    def test_float32_percentiles_match_stage05_scalar_precision(self):
        dem = (self.dem / 7.3).astype("float32")
        path = self.write_raster("float32-dem.tif", dem, from_origin(0, 4, 1, 1))
        with rasterio.open(path) as src:
            result = assign_depth_percentiles(
                self.reefs.geometry.iloc[0], [(src, -9999, "DEM")],
                self.lookup, geometry_crs=self.reefs.crs)
        expected = [float(np.nanpercentile(dem.ravel(), percentile))
                    for percentile in (10, 50, 90)]
        self.assertEqual(list(result[:3]), expected)

    def test_subpixel_centroid_sampling_in_both_crs(self):
        tiny = self.reefs.copy()
        tiny.geometry = [box(0.1, 3.1, 0.2, 3.2)]
        for crs in (4326, 3857):
            with self.subTest(crs=crs):
                result = calculate_depth_statistics(tiny.to_crs(crs), self.rasters, self.lookup)
                np.testing.assert_allclose(
                    result[list(DEM_PERCENTILE_FIELDS)].iloc[0], [-40] * 3 + [-37] * 3)
                self.assertEqual(result.DEMSr.iloc[0], "Synthetic DEM;EOT20")

    def test_lat_provenance_uses_lookup_source_label(self):
        lookup = LPTLookup(self.lpt_path, source_name="Synthetic tides")
        result = calculate_depth_statistics(self.reefs, self.rasters, lookup)
        self.assertEqual(result.DEMSr.iloc[0], "Synthetic DEM;Synthetic tides")

    def test_projected_dem_with_geographic_lpt(self):
        bounds = self.reefs.to_crs(3857).total_bounds
        dem_path = self.write_raster(
            "projected-dem.tif", self.dem, from_bounds(*bounds, 4, 4), crs=3857)
        result = calculate_depth_statistics(
            self.reefs, [(dem_path, -9999, "Projected DEM")], self.lookup)
        expected = [round(float(value), 1) for value in self.expected_percentiles()]
        np.testing.assert_allclose(result[list(DEM_PERCENTILE_FIELDS)].iloc[0], expected)

    def test_missing_and_partial_lpt_leave_msl_intact(self):
        for partial in (False, True):
            with self.subTest(partial=partial):
                lpt = self.lpt.copy()
                if partial:
                    lpt[1:3, 1:5] = -9999
                else:
                    lpt[:] = -9999
                lookup = LPTLookup(self.write_raster(
                    "missing-lpt.tif", lpt, from_origin(-0.5, 4.5, 1, 1)))
                result = calculate_depth_statistics(self.reefs, self.rasters, lookup)
                expected_msl = self.expected_percentiles()[:3]
                np.testing.assert_allclose(
                    result[list(DEM_PERCENTILE_FIELDS[:3])].iloc[0],
                    [round(float(value), 1) for value in expected_msl])
                if partial:
                    expected_lat = np.percentile(
                        (self.dem - self.lpt[1:5, 1:5])[2:, :], [10, 50, 90])
                    np.testing.assert_allclose(
                        result[list(DEM_PERCENTILE_FIELDS[3:])].iloc[0],
                        [round(float(value), 1) for value in expected_lat])
                else:
                    self.assertTrue(result[list(DEM_PERCENTILE_FIELDS[3:])].isna().all().all())
                    tiny = self.reefs.copy()
                    tiny.geometry = [box(0.1, 3.1, 0.2, 3.2)]
                    tiny_result = calculate_depth_statistics(tiny, self.rasters, lookup)
                    self.assertTrue(
                        tiny_result[list(DEM_PERCENTILE_FIELDS[3:])].isna().all().all())
                    self.assertEqual(tiny_result.DEMSr.iloc[0], "Synthetic DEM")
                expected_source = "Synthetic DEM;EOT20" if partial else "Synthetic DEM"
                self.assertEqual(result.DEMSr.iloc[0], expected_source)

    def test_fallback_for_nodata_missing_and_nonoverlapping_dems(self):
        nodata = self.write_raster(
            "nodata.tif", np.full((4, 4), -9999), from_origin(0, 4, 1, 1))
        elsewhere = self.write_raster(
            "elsewhere.tif", self.dem, from_origin(20, 24, 1, 1))
        for path in (nodata, elsewhere, self.directory / "absent.tif"):
            with self.subTest(path=path):
                result = calculate_depth_statistics(
                    self.reefs,
                    [(path, -9999, "Unusable"), *self.rasters],
                    self.lookup)
                expected = [round(float(value), 1) for value in self.expected_percentiles()]
                np.testing.assert_allclose(result[list(DEM_PERCENTILE_FIELDS)].iloc[0], expected)
                self.assertEqual(result.DEMSr.iloc[0], "Synthetic DEM;EOT20")
        result = calculate_depth_statistics(
            self.reefs, [(nodata, -9999, "Empty")], self.lookup)
        self.assertTrue(result.isna().all().all())

    def test_dataset_nodata_constants_exclude_missing_centroid_samples(self):
        tiny = self.reefs.copy()
        tiny.geometry = [box(0.1, 3.1, 0.2, 3.2)]
        for nodata in (MULTIRES_BATHY_NODATA, AUS_BATHY_TOPO_NODATA):
            with self.subTest(nodata=nodata):
                path = self.write_raster(
                    "dataset-nodata.tif", np.full((4, 4), nodata, dtype="float32"),
                    from_origin(0, 4, 1, 1))
                with rasterio.open(path, "r+") as src:
                    src.nodata = nodata
                result = calculate_depth_statistics(
                    tiny, [(path, nodata, "Missing DEM")], self.lookup)
                self.assertTrue(result.isna().all().all())

    def test_unexpected_sampling_errors_propagate(self):
        with rasterio.open(self.dem_path) as src:
            with patch("rasterio.mask.mask", side_effect=ValueError("Invalid input")):
                with self.assertRaisesRegex(ValueError, "Invalid input"):
                    get_percentiles_with_lat(
                        self.reefs.geometry.iloc[0], src, -9999, self.lookup)

    def test_rasters_open_once_and_close_on_success_or_sampling_error(self):
        reefs = pd.concat([self.reefs] * 3, ignore_index=True)
        fallback_path = self.write_raster(
            "fallback.tif", self.dem, from_origin(0, 4, 1, 1))
        rasters = [*self.rasters, (fallback_path, -9999, "Fallback")]
        for fail in (False, True):
            with self.subTest(fail=fail):
                opened = []
                original_open = rasterio.open

                def track_open(*args, **kwargs):
                    src = original_open(*args, **kwargs)
                    opened.append(src)
                    return src

                with patch("rasterio.open", side_effect=track_open):
                    if fail:
                        with patch("rasterio.mask.mask", side_effect=ValueError("Invalid input")):
                            with self.assertRaisesRegex(ValueError, "Invalid input"):
                                calculate_depth_statistics(reefs, rasters, self.lookup)
                    else:
                        result = calculate_depth_statistics(reefs, rasters, self.lookup)
                        self.assertEqual(len(result), 3)
                self.assertEqual(len(opened), 2)
                self.assertTrue(all(src.closed for src in opened))

    def test_open_rasters_close_if_later_raster_fails_to_open(self):
        corrupt_path = self.directory / "corrupt.tif"
        corrupt_path.touch()
        with rasterio.open(self.dem_path) as src:
            with patch("rasterio.open", side_effect=[
                    src, rasterio.errors.RasterioIOError("Unreadable DEM")]):
                with self.assertRaisesRegex(rasterio.errors.RasterioIOError, "Unreadable DEM"):
                    calculate_depth_statistics(
                        self.reefs, [*self.rasters, (corrupt_path, -9999, "Corrupt")],
                        self.lookup)
            self.assertTrue(src.closed)

    def test_transformers_reused_for_polygons_pixels_and_centroids(self):
        bounds = self.reefs.to_crs(3857).total_bounds
        dem_path = self.write_raster(
            "projected-dem.tif", self.dem, from_bounds(*bounds, 4, 4), crs=3857)
        reefs = pd.concat([self.reefs] * 3, ignore_index=True)
        reefs.loc[2, "geometry"] = box(0.1, 3.1, 0.2, 3.2)
        with patch("pyproj.Transformer.from_crs",
                   wraps=pyproj.Transformer.from_crs) as create:
            calculate_depth_statistics(reefs, [(dem_path, -9999, "DEM")], self.lookup)
        self.assertEqual(create.call_count, 2)
        self.assertGreaterEqual(_depth_transformer.cache_info().hits, 3)

    def test_raster_preparation_builds_mosaic_and_reuses_it(self):
        download = self.directory / "inputs"
        for filename in ("01_shallow_bathy.tif", "02_mesophotic_bathy.tif"):
            self.write_raster(
                str(Path("inputs") / "MultiRes-Bathy-EEZ_2024" / filename),
                self.dem, from_origin(0, 4, 1, 1))
        vrt = self.directory / "working" / "test-version" / "05" / "depth.vrt"
        rasters = prepare_depth_rasters(download, vrt)
        self.assertEqual([entry[2] for entry in rasters],
                         ["MultiResBathyEEZ_2024", "AusBathyTopo-250m_2024"])
        self.assertEqual([entry[1] for entry in rasters], [3.4e+38, -32767.0])
        with rasterio.open(vrt) as src:
            np.testing.assert_array_equal(src.read(1), self.dem)
        with patch("osgeo.gdal.BuildVRT", side_effect=AssertionError("Must reuse VRT")):
            self.assertEqual(prepare_depth_rasters(download, vrt), rasters)
        with self.assertRaisesRegex(FileNotFoundError, "Missing MultiResBathyEEZ"):
            prepare_depth_rasters(self.directory / "missing", self.directory / "missing.vrt")

    def test_stage05_refreshes_dem_provenance_and_preserves_category_rules(self):
        reefs = pd.concat([self.reefs] * 4, ignore_index=True)
        reefs.index = [17, 21, 35, 42]
        reefs["DepthCat"] = ["Surface", None, None, "Surface"]
        reefs["RB_Type_L3"] = ["Coral Reef", "Island", "Coral Reef", "Coral Reef"]
        reefs["Attachment"] = "Isolated"
        reefs.loc[42, "geometry"] = box(10, 10, 11, 11)
        reefs["DEMSr"] = "Existing DEM source"
        output = self.directory / "stage05.shp"
        with patch.multiple(
                stage05, OUTPUT_SHAPE=output, MULTIRES_VRT=self.dem_path,
                LPT_TIF=self.lpt_path):
            with patch.object(stage05.gpd, "read_file", return_value=reefs):
                with patch.object(stage05, "prepare_depth_rasters", return_value=self.rasters):
                    with patch("sys.argv", ["05-add-depth.py"]):
                        stage05.main()
        result = gpd.read_file(output)
        expected = [round(float(value), 1) for value in self.expected_percentiles()]
        for position in range(3):
            np.testing.assert_allclose(result[list(DEM_PERCENTILE_FIELDS)].iloc[position], expected)
        self.assertTrue(result[list(DEM_PERCENTILE_FIELDS)].iloc[3].isna().all())
        self.assertEqual(result.DepthCat.tolist(), ["Surface", "Land", "Shallow", "Surface"])
        self.assertEqual(result.DepthCatSr.tolist(), [
            "Satellite imagery", "RB_Type_L3 rule", "Synthetic DEM;EOT20", "Satellite imagery"])
        self.assertEqual(result.DEMSr.iloc[:3].tolist(), ["Synthetic DEM;EOT20"] * 3)
        self.assertTrue(pd.isna(result.DEMSr.iloc[3]))


if __name__ == "__main__":
    unittest.main()
