"""Validate shared pier exclusions and their use by both clipping stages."""

from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import geopandas as gpd
from shapely.geometry import Point, Polygon, box

import reef_utils


ROOT = Path(__file__).resolve().parents[1]


def load_stage(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EDIT = load_stage("pier_edit_clipping", "01e-clip-TS-GBR-reef-edit.py")
LEGACY = load_stage("pier_legacy_clipping", "02d-clip-TS-GBR-legacy.py")


class PierExclusionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.inputs = self.root / "inputs"
        self.thirdparty = self.root / "thirdparty"
        self.exclusions = self.inputs / "Land-exclusion" / "Land-exclusion-piers.shp"
        self.coastline = (
            self.thirdparty / "Coastline50k" / "Split"
            / "AU_NESP-MaC-3-17_AIMS_Aus-Coastline-50k_2024_V1-1_split.shp"
        )
        self.exclusions.parent.mkdir(parents=True)
        self.coastline.parent.mkdir(parents=True)
        self.reef = box(147, -18, 147.01, -17.99)
        self.shore = box(146.998, -18.002, 147.002, -17.988)
        self.pier = box(147.004, -18.002, 147.006, -17.988)
        self.exception = box(147.0039, -18.0021, 147.0061, -17.9879)
        gpd.GeoDataFrame(geometry=[self.shore, self.pier], crs=4326).to_file(self.coastline)
        self.write_exclusions([self.exception], crs=3577)

    def write_exclusions(self, geometries, crs=4326):
        frame = gpd.GeoDataFrame(geometry=geometries, crs=4326).to_crs(crs)
        frame.to_file(self.exclusions)

    def test_pier_exclusion_rejoins_reef_but_preserves_shore_and_sources(self):
        before = {path: path.read_bytes()
                  for path in self.root.rglob("*") if path.is_file()}
        raw = reef_utils.prepare_coastline(self.coastline)
        self.assertEqual(len(reef_utils.clip_polygon(self.reef, raw)[0]), 2)
        prepared = reef_utils.prepare_coastline(self.coastline, self.exclusions)
        parts, fragments, changed = reef_utils.clip_polygon(self.reef, prepared)
        self.assertEqual(prepared.n_exclusions, 1)
        self.assertEqual(prepared.n_land_changed, 1)
        self.assertEqual(len(parts), 1)
        self.assertTrue(changed)
        self.assertEqual(fragments, 0)
        self.assertTrue(parts[0].equals(self.reef.difference(self.shore)))
        self.assertTrue(parts[0].covers(self.reef.intersection(self.pier)))
        self.assertTrue(all(g.is_valid and not g.is_empty for g in prepared.geoms))
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_empty_exclusion_layer_preserves_original_mask(self):
        self.write_exclusions([])
        prepared = reef_utils.prepare_coastline(self.coastline, self.exclusions)
        self.assertEqual(prepared.n_exclusions, 0)
        self.assertEqual(prepared.n_land_changed, 0)
        self.assertEqual(len(reef_utils.clip_polygon(self.reef, prepared)[0]), 2)

    def test_small_remaining_land_is_not_fragment_filtered(self):
        small_land = box(147.004, -18, 147.0041, -17.9999)
        gpd.GeoDataFrame(geometry=[small_land], crs=4326).to_file(self.coastline)
        self.write_exclusions([box(147.00405, -18.0001, 147.0042, -17.9998)])
        prepared = reef_utils.prepare_coastline(self.coastline, self.exclusions)
        self.assertEqual(len(prepared.geoms), 1)
        self.assertGreater(reef_utils.area_m2(prepared.geoms[0]), 0)
        self.assertLess(reef_utils.area_m2(prepared.geoms[0]), 100)

    def test_invalid_and_nonpolygon_exclusions_identify_record(self):
        invalid = Polygon([(147, -18), (147.01, -17.99), (147, -17.99),
                           (147.01, -18), (147, -18)])
        for geometry in [invalid, Point(147, -18), None]:
            with self.subTest(geometry=geometry):
                self.write_exclusions([geometry])
                with self.assertRaises(reef_utils.ClipError) as caught:
                    reef_utils.prepare_coastline(self.coastline, self.exclusions)
                self.assertEqual(caught.exception.step, "validating pier exclusions")
                self.assertIn("exclusion record 1", caught.exception.detail)
                self.assertIn(str(self.exclusions), caught.exception.detail)

    def test_missing_exclusion_crs_is_rejected(self):
        self.exclusions.with_suffix(".prj").unlink()
        with self.assertRaises(reef_utils.ClipError) as caught:
            reef_utils.prepare_coastline(self.coastline, self.exclusions)
        self.assertIn("no defined CRS", caught.exception.detail)

    def test_failed_exclusion_difference_identifies_coastline_record(self):
        with patch.object(Polygon, "difference", side_effect=RuntimeError("test failure")), \
                self.assertRaises(reef_utils.ClipError) as caught:
            reef_utils.prepare_coastline(self.coastline, self.exclusions)
        self.assertEqual(caught.exception.step, "subtracting pier exclusions from coastline")
        self.assertIn("coastline record 2", caught.exception.detail)
        self.assertIn(str(self.exclusions), caught.exception.detail)
        self.assertIn("test failure", caught.exception.detail)

    def test_invalid_union_and_difference_results_are_rejected_without_repair(self):
        invalid = Polygon([(147, -18), (147.01, -17.99), (147, -17.99),
                           (147.01, -18), (147, -18)])
        for operation, target, name, step in [
            ("union", reef_utils, "unary_union", "union of pier exclusions"),
            ("difference", Polygon, "difference",
             "subtracting pier exclusions from coastline"),
        ]:
            with self.subTest(operation=operation), \
                    patch.object(target, name, return_value=invalid), \
                    patch.object(Polygon, "buffer", side_effect=AssertionError("repair attempted")), \
                    self.assertRaises(reef_utils.ClipError) as caught:
                reef_utils.prepare_coastline(self.coastline, self.exclusions)
            self.assertEqual(caught.exception.step, step)
            self.assertIn(str(self.exclusions), caught.exception.detail)
            self.assertIn("Self-intersection", caught.exception.detail)

    def prepare_stage_input(self, stage):
        if stage is EDIT:
            path = self.inputs / "Reef-edit" / "AIMS_GBR-TS-Features_Edit_Vtest.shp"
        else:
            path = self.root / "patched.shp"
        path.parent.mkdir(parents=True, exist_ok=True)
        attrs = {field: "test" for field in stage.REQUIRED_FIELDS}
        attrs.update(RB_Type_L3="Coral Reef", EdgeAcc_m="50", CODE="A")
        records = [{**attrs, "geometry": self.reef}]
        if stage is LEGACY:
            attrs.update(Dataset="TS Features", RE_row=None, RE_part=None)
            records = [
                {**attrs, "geometry": self.reef},
                {**attrs, "Dataset": "Aus-Trop-Reef-Features_Vtest",
                 "RE_row": 1, "RE_part": 1, "geometry": self.reef.difference(self.shore)},
            ]
        frame = gpd.GeoDataFrame(records, crs=reef_utils.CLIP_CRS)
        frame.to_file(path)
        return path, gpd.read_file(path)

    def run_stage(self, stage, source_path):
        config = Mock()
        config.get.side_effect = lambda section, key: {
            "in_path": str(self.inputs), "in_3p_path": str(self.thirdparty),
            "version": "Vtest",
        }[key]
        output = self.root / stage.OUT_DIR
        output.mkdir(parents=True, exist_ok=True)
        console = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.object(stage, "config", config))
            stack.enter_context(patch.object(stage, "OUT_DIR", str(output)))
            for name in ["OUT_PATH", "PARENTS_PATH", "SPLITS_PATH", "REMOVED_PATH"]:
                stack.enter_context(patch.object(stage, name,
                                                 str(output / Path(getattr(stage, name)).name)))
            if stage is LEGACY:
                stack.enter_context(patch.object(stage, "IN_PATH", str(source_path)))
            stack.enter_context(redirect_stdout(console))
            try:
                stage.main()
            except SystemExit as exc:
                return exc.code, console.getvalue(), output
        return 0, console.getvalue(), output

    def test_both_stages_apply_exclusions_and_preserve_attributes(self):
        for stage in [EDIT, LEGACY]:
            with self.subTest(stage=stage.__name__):
                path, source = self.prepare_stage_input(stage)
                status, console, output = self.run_stage(stage, path)
                self.assertEqual(status, 0, console)
                self.assertIn("1 pier exclusion polygons applied", console)
                self.assertIn("1 coastline records changed", console)
                accepted = gpd.read_file(output / Path(stage.OUT_PATH).name)
                self.assertEqual(len(accepted), len(source))
                self.assertTrue(accepted.geometry.iloc[0].equals(
                    self.reef.difference(self.shore)))
                self.assertEqual(accepted.crs.to_epsg(), 4283)
                for field in source.columns.drop("geometry"):
                    self.assertEqual(accepted[field].fillna("").tolist(),
                                     source[field].fillna("").tolist())
                self.assertFalse((output / Path(stage.SPLITS_PATH).name).exists())
                if stage is LEGACY:
                    self.assertTrue(accepted.geometry.iloc[1].equals(source.geometry.iloc[1]))

    def test_missing_required_exclusions_block_both_stages_and_clear_old_output(self):
        self.exclusions.unlink()
        for stage in [EDIT, LEGACY]:
            with self.subTest(stage=stage.__name__):
                path, _ = self.prepare_stage_input(stage)
                output = self.root / stage.OUT_DIR
                output.mkdir(parents=True, exist_ok=True)
                accepted_path = output / Path(stage.OUT_PATH).name
                accepted_path.write_bytes(b"previous accepted output")
                status, console, _ = self.run_stage(stage, path)
                self.assertEqual(status, 1)
                self.assertIn("reading pier exclusions", console)
                self.assertIn(str(self.exclusions), console)
                self.assertFalse(accepted_path.exists())


if __name__ == "__main__":
    unittest.main()
