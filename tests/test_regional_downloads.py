"""Verify regional download wiring without making network requests."""

import ast
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import create_autospec

from data_downloader import DataDownloader


ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_SCRIPT = ROOT / "01a-download-input-data.py"


class RegionalDownloadTests(unittest.TestCase):
    def test_capad_and_analysis_download_calls_match_installed_api(self):
        tree = ast.parse(DOWNLOAD_SCRIPT.read_text(encoding="utf-8"))
        downloader = create_autospec(DataDownloader, instance=True)
        wanted = {"CAPAD-2024", "nesp-3-17-analysis-regions"}
        calls = [node for node in tree.body
                 if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                 and len(node.value.args) >= 2
                 and isinstance(node.value.args[1], ast.Constant)
                 and node.value.args[1].value in wanted]
        self.assertEqual(len(calls), 2)
        exec(compile(ast.Module(body=calls, type_ignores=[]), str(DOWNLOAD_SCRIPT), "exec"),
             {"downloader": downloader})
        self.assertEqual({call.args[1] for call in downloader.download_and_unzip.call_args_list},
                         wanted)
        for call in downloader.download_and_unzip.call_args_list:
            self.assertTrue(call.kwargs["flatten_directory"])
            self.assertTrue(call.args[0].startswith("https://"))

    def test_imcra_shortens_all_sidecars_before_moving_and_is_restartable(self):
        tree = ast.parse(DOWNLOAD_SCRIPT.read_text(encoding="utf-8"))
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "download_imcra")
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "inputs"
            downloader = create_autospec(DataDownloader, instance=True)
            calls = []

            def factory(download_path):
                def unpack(url, dataset_name, subfolder_name=None, flatten_directory=False):
                    calls.append((url, dataset_name, flatten_directory))
                    folder = Path(download_path) / dataset_name
                    folder.mkdir()
                    long_stem = (
                        "Integrated_Marine_and_Coastal_Regionalisation_of_Australia_"
                        "(IMCRA)_v4.0_-_Meso-scale_Bioregions")
                    for extension in (".shp", ".shx", ".dbf", ".prj", ".shp.xml", ".cpg"):
                        (folder / f"{long_stem}{extension}").touch()
                downloader.download_and_unzip.side_effect = unpack
                return downloader

            namespace = {"DataDownloader": factory, "Path": Path, "shutil": shutil,
                         "tempfile": tempfile, "download_path": str(target)}
            exec(compile(ast.Module(body=[function], type_ignores=[]),
                         str(DOWNLOAD_SCRIPT), "exec"), namespace)
            namespace["download_imcra"]()
            destination = target / "IMCRA-v4-0-Meso-Bioregions"
            self.assertEqual({path.name for path in destination.iterdir()}, {
                f"IMCRA-v4-Mesoscale-Bioregions{extension}"
                for extension in (".shp", ".shx", ".dbf", ".prj", ".shp.xml", ".cpg")})
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0][2])
            namespace["download_imcra"]()
            self.assertEqual(len(calls), 1)
            (destination / "IMCRA-v4-Mesoscale-Bioregions.dbf").unlink()
            with self.assertRaisesRegex(FileNotFoundError, "Incomplete IMCRA"):
                namespace["download_imcra"]()


if __name__ == "__main__":
    unittest.main()
