"""Verify version isolation and producer/consumer paths without processing data."""

import ast
import configparser
from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKING_FIELDS = {
    "01d-refresh-TS-GBR-Features.py": ("output_dir", "output_path"),
    "01e-clip-TS-GBR-reef-edit.py": (
        "OUT_DIR", "OUT_PATH", "PARENTS_PATH", "SPLITS_PATH", "REMOVED_PATH"),
    "02a-patch-TS-GBR-Features.py": (
        "gbr_path", "reef_edit_path", "output_dir", "output_path", "review_path"),
    "02d-clip-TS-GBR-legacy.py": (
        "IN_PATH", "OUT_DIR", "OUT_PATH", "PARENTS_PATH", "SPLITS_PATH", "REMOVED_PATH"),
    "05-add-depth.py": ("INPUT_SHAPE", "OUTPUT_DIR", "MULTIRES_VRT", "OUTPUT_SHAPE"),
    "06-crosswalk.py": ("INPUT_SHP", "MISMATCHED_SHP"),
    "07-example-attributes.py": ("output_csv",),
    "08-make-RB_Type_L2.py": (
        "MULTIRES_VRT", "MULTI_ATTACHMENT_SHP", "CONFIDENCE_QA_CSV"),
    "A05-reef-distribution.py": ("WORK_DIR", "COUNTABLE_CACHE"),
}


class StopBeforeDataRead(Exception):
    pass


def load_script(filename):
    path = ROOT / filename
    spec = importlib.util.spec_from_file_location(f"working_paths_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_main_paths(module, arguments=()):
    """Run real path setup, stopping before the first spatial dataset is read."""
    with patch("sys.argv", [module.__file__, *arguments]), \
            patch("os.path.exists", return_value=True), \
            patch("os.makedirs"), \
            patch("geopandas.read_file", side_effect=StopBeforeDataRead), \
            redirect_stdout(io.StringIO()):
        try:
            module.main()
        except StopBeforeDataRead as exc:
            traceback = exc.__traceback__
            while traceback is not None:
                if traceback.tb_frame.f_code == module.main.__code__:
                    return SimpleNamespace(**traceback.tb_frame.f_locals.copy())
                traceback = traceback.tb_next
    raise AssertionError("Script did not reach its first dataset read")


def country_path_settings():
    """Stage 04 runs on import, so execute only its actual path declarations."""
    path = ROOT / "04-add-country-attribute.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {"config", "in_3p_path", "version", "reef_features_path", "output_path"}
    nodes = [
        node for node in tree.body
        if (isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in names
                    for target in node.targets))
        or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "config" and node.value.func.attr == "read")
    ]
    namespace = {"configparser": configparser, "os": os}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return SimpleNamespace(**namespace)


class WorkingPathTests(unittest.TestCase):
    def resolved(self, path):
        return (ROOT / path).resolve()

    def assert_same_path(self, producer, consumer):
        self.assertEqual(self.resolved(producer), self.resolved(consumer))

    def test_versions_isolate_all_working_paths_and_keep_pipeline_connected(self):
        paths_by_version = []
        for version in ("path-test-v1", "path-test-v2"):
            with self.subTest(version=version):
                def read_config(parser, *args, **kwargs):
                    parser.read_dict({"general": {
                        "version": version, "in_path": "inputs",
                        "in_3p_path": "third-party-inputs",
                        "nw_aus_feat_version": "nw-source-version",
                        "cs_feat_version": "cs-source-version",
                    }})
                    return [str(ROOT / "config.ini")]

                with patch.object(configparser.ConfigParser, "read", read_config), \
                        patch("os.makedirs"), \
                        patch("geopandas.read_file", side_effect=AssertionError(
                            "Importing a script must not read spatial data")):
                    modules = {name: load_script(name) for name in WORKING_FIELDS}
                    legacy = load_script("02a-patch-TS-GBR-Features_v0-1.py")
                    northwest = load_script("02b-patch-NW-Aus-Features.py")
                    coral_sea = load_script("02c-patch-CS-Features.py")
                    merge = load_script("03-merge-TS-GBR-CS-NW.py")
                    nw_paths = capture_main_paths(northwest)
                    merge_paths = capture_main_paths(merge)
                    review_paths = capture_main_paths(merge, ["--allow-review"])
                    cs_output = coral_sea.get_filepaths()[-1]
                    country = country_path_settings()

                expected_root = ROOT / "working" / version
                working_paths = [
                    getattr(modules[filename], field)
                    for filename, fields in WORKING_FIELDS.items() for field in fields
                ] + [
                    nw_paths.output_file, cs_output, country.reef_features_path,
                    country.output_path, merge_paths.output_path, review_paths.output_path,
                    merge_paths.cs_features_path, merge_paths.nw_aus_features_path,
                    merge_paths.ts_gbr_features_path, review_paths.ts_gbr_features_path,
                ]
                resolved = {self.resolved(path) for path in working_paths}
                for path in resolved:
                    self.assertTrue(path.is_relative_to(expected_root), str(path))
                paths_by_version.append(resolved)

                refresh = modules["01d-refresh-TS-GBR-Features.py"]
                edit = modules["01e-clip-TS-GBR-reef-edit.py"]
                patch_ts = modules["02a-patch-TS-GBR-Features.py"]
                clip_legacy = modules["02d-clip-TS-GBR-legacy.py"]
                depth = modules["05-add-depth.py"]
                crosswalk = modules["06-crosswalk.py"]
                examples = modules["07-example-attributes.py"]
                l2 = modules["08-make-RB_Type_L2.py"]
                distribution = modules["A05-reef-distribution.py"]
                pairs = [
                    (refresh.output_path, patch_ts.gbr_path),
                    (edit.OUT_PATH, patch_ts.reef_edit_path),
                    (patch_ts.output_path, clip_legacy.IN_PATH),
                    (patch_ts.output_path, review_paths.ts_gbr_features_path),
                    (clip_legacy.OUT_PATH, merge_paths.ts_gbr_features_path),
                    (nw_paths.output_file, merge_paths.nw_aus_features_path),
                    (cs_output, merge_paths.cs_features_path),
                    (merge_paths.output_path, country.reef_features_path),
                    (country.output_path, depth.INPUT_SHAPE),
                    (depth.OUTPUT_SHAPE, crosswalk.INPUT_SHP),
                    (depth.MULTIRES_VRT, l2.MULTIRES_VRT),
                    (crosswalk.output_shp, examples.input_shp),
                    (crosswalk.output_shp, l2.INPUT_SHP),
                    (l2.OUTPUT_SHP, distribution.INPUT_REEFS),
                ]
                for producer, consumer in pairs:
                    self.assert_same_path(producer, consumer)
                self.assertEqual(self.resolved(merge_paths.output_dir), expected_root / "03")
                self.assertEqual(self.resolved(review_paths.output_dir), expected_root / "03-review")
                self.assertEqual(self.resolved(legacy.output_dir), ROOT / "working" / "v0-1" / "02")
                self.assertNotEqual(self.resolved(legacy.output_path),
                                    self.resolved(patch_ts.output_path))
        self.assertTrue(paths_by_version[0].isdisjoint(paths_by_version[1]))


if __name__ == "__main__":
    unittest.main()
