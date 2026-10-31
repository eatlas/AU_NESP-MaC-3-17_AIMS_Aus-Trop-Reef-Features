"""Check retained Torres Strait confidence preparation without spatial processing."""

import ast
from pathlib import Path
import unittest

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "02a-patch-TS-GBR-Features.py"


def prepare_type_confidence(features):
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    main = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "main")
    assignments = [
        node for node in main.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name) and target.value.id == "gbr"
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "TypeConf" for target in node.targets)
    ]
    if len(assignments) != 1:
        raise AssertionError("Expected one retained-feature TypeConf assignment")
    namespace = {"gbr": features.copy(), "pd": pd}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), str(SCRIPT), "exec"),
         namespace)
    return namespace["gbr"]


class TorresStraitConfidenceTests(unittest.TestCase):
    def test_lowhigh_maps_to_low_and_other_values_are_unchanged(self):
        source = pd.DataFrame({
            "CLASS_CONF": ["LowHigh", "Low", "High", "Medium", "Very Low",
                           None, "", "HighLow", "Very high"],
            "ReefID": [f"09-{index:03d}" for index in range(9)],
        }, index=range(10, 19))
        original = source.copy()
        result = prepare_type_confidence(source)
        self.assertEqual(result.TypeConf.tolist(),
                         ["Low", "Low", "High", "Medium", "Very Low",
                          None, "", "HighLow", "Very high"])
        pd.testing.assert_frame_equal(source, original)
        pd.testing.assert_series_equal(result.CLASS_CONF, source.CLASS_CONF)
        pd.testing.assert_series_equal(result.ReefID, source.ReefID)
        repeated = prepare_type_confidence(result)
        pd.testing.assert_series_equal(result.TypeConf, repeated.TypeConf)

    def test_missing_source_confidence_remains_missing(self):
        source = pd.DataFrame({"ReefID": ["09-552", "09-517"]})
        result = prepare_type_confidence(source)
        self.assertTrue(result.TypeConf.isna().all())
        self.assertEqual(result.ReefID.tolist(), source.ReefID.tolist())


if __name__ == "__main__":
    unittest.main()
