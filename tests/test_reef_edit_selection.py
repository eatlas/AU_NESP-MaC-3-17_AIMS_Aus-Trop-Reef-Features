"""Check QGIS selection guidance for multipart Reef Edit source records."""

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import geopandas as gpd
from geopandas.testing import assert_geodataframe_equal
from shapely.geometry import MultiPolygon, box


SCRIPT = Path(__file__).resolve().parents[1] / "01e-clip-TS-GBR-reef-edit.py"
SPEC = importlib.util.spec_from_file_location("reef_edit_clipping", SCRIPT)
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)


class ReefEditSelectionTests(unittest.TestCase):
    def test_multipart_expression_uses_source_fids_not_read_positions(self):
        polygon = box(147, -18, 147.001, -17.999)
        multipart = MultiPolygon([
            polygon, box(147.002, -18, 147.003, -17.999),
        ])
        source = gpd.GeoDataFrame(
            {field: [None] * 3 for field in stage.REQUIRED_FIELDS},
            geometry=[multipart, polygon, multipart],
            index=[8, 31, 52], crs="EPSG:4326",
        )
        original = source.copy()
        config = Mock()
        config.get.side_effect = lambda section, key: {
            "in_path": "inputs", "in_3p_path": "thirdparty", "version": "Vtest",
        }[key]
        console = io.StringIO()
        with patch.object(stage, "config", config), \
                patch.object(stage.os.path, "exists", return_value=True), \
                patch.object(stage.os, "makedirs"), \
                patch.object(stage, "remove_shapefile"), \
                patch.object(stage.gpd, "read_file", return_value=source.copy()) as read_file, \
                redirect_stdout(console), \
                self.assertRaises(SystemExit) as stopped:
            stage.main()

        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(read_file.call_args.kwargs,
                         {"engine": "pyogrio", "fid_as_index": True})
        output = console.getvalue()
        self.assertIn("RE_row 1, 3", output)
        self.assertIn("Select features using an expression", output)
        self.assertIn("$id IN (8, 52)", output)
        self.assertIn("Attribute-table sorting does not affect", output)
        self.assertIn("source Reef Edit layer", output)
        assert_geodataframe_equal(source, original)

    def test_shapefile_fid_read_preserves_attributes_and_geometry(self):
        source = gpd.GeoDataFrame(
            {"CODE": ["A", None], "EdgeAcc_m": ["50", "100"]},
            geometry=[box(147, -18, 147.001, -17.999),
                      box(148, -18, 148.001, -17.999)],
            crs="EPSG:4326",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.shp"
            source.to_file(path)
            result = gpd.read_file(path, engine="pyogrio", fid_as_index=True)
        self.assertEqual(result.index.tolist(), [0, 1])
        assert_geodataframe_equal(result.reset_index(drop=True), source)


if __name__ == "__main__":
    unittest.main()
