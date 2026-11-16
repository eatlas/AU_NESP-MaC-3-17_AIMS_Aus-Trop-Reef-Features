"""Check both report workflow graphs, editable SVGs and explicit geometry."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workflow", ROOT / "A03-create-workflow-diagram.py")
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)
NS = {"svg": "http://www.w3.org/2000/svg"}


def segments_intersect(a, b, c, d):
    if a[0] == b[0] and c[1] == d[1]:
        return (min(c[0], d[0]) <= a[0] <= max(c[0], d[0])
                and min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))
    if a[1] == b[1] and c[0] == d[0]:
        return segments_intersect(c, d, a, b)
    if a[0] == b[0] == c[0] == d[0]:
        return max(min(a[1], b[1]), min(c[1], d[1])) <= min(
            max(a[1], b[1]), max(c[1], d[1]))
    if a[1] == b[1] == c[1] == d[1]:
        return max(min(a[0], b[0]), min(c[0], d[0])) <= min(
            max(a[0], b[0]), max(c[0], d[0]))
    return False


class WorkflowDiagramTests(unittest.TestCase):
    def test_exact_processing_graphs(self):
        required_overview = {
            ("nw", "nw_prepare"), ("cs", "cs_prepare"),
            ("gbr_ts", "update"), ("edits", "update"),
            ("nw_prepare", "merge"), ("cs_prepare", "merge"), ("update", "merge"),
            ("merge", "sovereignty"), ("country", "sovereignty"),
            ("sovereignty", "depth"), ("bathymetry", "depth"),
            ("depth", "classifications"), ("classifications", "full"),
            ("full", "dissolve"), ("bathymetry", "dissolve"),
            ("dissolve", "simplified"),
        }
        required_update = {
            ("gbr_ts", "refresh"), ("latest_gbr", "refresh"),
            ("imagery", "digitise"), ("bathymetry", "digitise"),
            ("digitise", "edits"), ("digitise", "controls"),
            ("edits", "clip_edits"), ("edit_landmask", "clip_edits"),
            ("refresh", "integrate"), ("clip_edits", "integrate"),
            ("controls", "integrate"), ("regional_crosswalk", "refresh"),
            ("integrate", "clip_legacy"), ("legacy_landmask", "clip_legacy"),
            ("clip_legacy", "updated"),
        }
        for figure, required in ((workflow.OVERVIEW, required_overview),
                                 (workflow.UPDATE, required_update)):
            self.assertEqual({(e.source, e.target) for e in figure.edges}, required)
            self.assertEqual(len(figure.edges), len(required))

    def test_xml_and_visible_content(self):
        for figure in workflow.FIGURES:
            with self.subTest(figure=figure.filename):
                root = ET.fromstring(workflow.build_svg(figure))
                self.assertEqual(root.attrib["viewBox"], f"0 0 900 {figure.height}")
                self.assertEqual(root.attrib["width"], "160mm")
                self.assertAlmostEqual(float(root.attrib["height"][:-2]),
                                       160 * figure.height / 900, places=3)
                self.assertLessEqual(figure.height, 1240)
                texts = root.findall(".//svg:text", NS)
                visible = " ".join(element.text for element in texts)
                self.assertLessEqual(len(visible.split()), 150)
                self.assertTrue(all(float(t.attrib["font-size"]) >= 18 for t in texts))
                for phrase in ("pier", "A05", "comprehensive", "partial updates", ".py"):
                    self.assertNotIn(phrase, visible)
                forbidden = {"style", "filter", "pattern", "clipPath", "image",
                             "foreignObject", "marker"}
                for element in root.iter():
                    self.assertNotIn(element.tag.split("}")[-1], forbidden)
                    self.assertNotIn("class", element.attrib)
                    self.assertNotIn("style", element.attrib)
                links = root.findall(".//svg:g[@data-source]", NS)
                self.assertEqual(len(links), len(figure.edges))
                for link in links:
                    self.assertEqual(len(link.findall("svg:polyline", NS)), 1)
                    self.assertEqual(len(link.findall("svg:polygon", NS)), 1)
                if figure is workflow.OVERVIEW:
                    self.assertNotIn("crosswalk", visible.lower())
                    self.assertIn("Full classification", visible)
                    self.assertIn("Simplified classification", visible)
                    self.assertIn("North and West Australian Features", visible)
                    self.assertIn("Coral Sea Features", visible)
                    self.assertEqual(visible.count("EOT20 tides"), 1)
                    for phrase in ("MultiRes-Bathy-", "EEZ_2024",
                                   "Australia 250 m 2024", "(fallback)"):
                        self.assertIn(phrase, visible)
                else:
                    for phrase in ("S2 All Tide", "S2 Low Tide",
                                   "Queensland Globe aerial imagery",
                                   "MultiRes-Bathy- EEZ_2024", "GBR DEM 2020, 30 m",
                                   "Torres Strait DEM 2023, 30 m", "Manual interpretation",
                                   "Retain TS mapping", "Preserve ReefIDs",
                                   "Updated GBR + TS Features"):
                        self.assertIn(phrase, visible)
                    bathymetry = root.find(".//svg:g[@id='bathymetry']", NS)
                    self.assertEqual(len(bathymetry.findall("svg:polyline", NS)), 1)
                    self.assertEqual(workflow.UPDATE_NODES["bathymetry"].nested_lines, 4)
                    evidence_text = bathymetry.findall("svg:text", NS)
                    self.assertEqual(evidence_text[0].text, "Bathymetry")
                    composite_x = float(evidence_text[1].attrib["x"])
                    for text in evidence_text[3:]:
                        self.assertEqual(text.attrib["text-anchor"], "start")
                        self.assertGreater(float(text.attrib["x"]), composite_x)
                    self.assertEqual(root.find(".//svg:g[@id='imagery']/svg:text", NS).text,
                                     "Imagery")

    def test_group_only_encloses_update(self):
        group, = workflow.OVERVIEW.groups
        enclosed = {
            key for key, n in workflow.OVERVIEW.nodes.items()
            if group.x <= n.x and n.x + n.w <= group.x + group.w
            and group.y <= n.y and n.y + n.h <= group.y + group.h
        }
        self.assertEqual(enclosed, {"gbr_ts", "edits", "update"})
        self.assertGreaterEqual(group.x - (workflow.OVERVIEW_NODES["cs"].x
                                          + workflow.OVERVIEW_NODES["cs"].w), 16)
        self.assertEqual(workflow.UPDATE.groups, ())

    def test_standard_widths_and_gold_roles(self):
        for figure, sets, gold in (
            (workflow.OVERVIEW,
             (("nw", "cs", "gbr_ts", "edits", "nw_prepare", "cs_prepare"),
              ("sovereignty", "depth", "classifications", "full", "dissolve", "simplified"),
              ("country", "bathymetry")),
             {"edits", "full", "simplified"}),
            (workflow.UPDATE,
             (("gbr_ts", "latest_gbr"),
              ("imagery", "bathymetry", "edits", "controls", "clip_edits"),
              ("edit_landmask", "legacy_landmask", "regional_crosswalk"),
              ("refresh", "clip_legacy", "updated")),
             {"edits", "controls"}),
        ):
            for identifiers in sets:
                self.assertEqual(len({figure.nodes[key].w for key in identifiers}), 1)
            self.assertEqual({key for key, node in figure.nodes.items()
                              if node.role == "new"}, gold)
            root = ET.fromstring(workflow.build_svg(figure))
            for key, node in figure.nodes.items():
                rect = root.find(f".//svg:g[@id='{key}']/svg:rect", NS)
                self.assertEqual(rect.attrib["stroke"] == workflow.GOLD, key in gold)
                if node.role == "process":
                    text = root.find(f".//svg:g[@id='{key}']/svg:text", NS)
                    self.assertEqual(text.attrib["font-size"], "20")
                    self.assertEqual(text.attrib["font-weight"], "bold")
        nodes = workflow.OVERVIEW_NODES
        self.assertEqual(nodes["update"].w, nodes["gbr_ts"].w * 2 + 28)
        self.assertEqual(nodes["merge"].w, nodes["nw"].w * 4 + 28 * 3)

    def test_left_to_right_inputs_and_bold_products(self):
        figure = workflow.OVERVIEW
        nodes = figure.nodes
        for source, target in (("country", "sovereignty"), ("bathymetry", "depth"),
                               ("bathymetry", "dissolve")):
            self.assertLess(nodes[source].x + nodes[source].w, nodes[target].x)
            edge, = [e for e in figure.edges if (e.source, e.target) == (source, target)]
            self.assertEqual(edge.points[-1][0], nodes[target].x)
        bathymetry = nodes["bathymetry"]
        top, = [e for e in figure.edges if e.source == "bathymetry" and e.target == "depth"]
        bottom, = [e for e in figure.edges
                   if e.source == "bathymetry" and e.target == "dissolve"]
        self.assertEqual(top.points[0][1], bathymetry.y)
        self.assertEqual(bottom.points[0][1], bathymetry.y + bathymetry.h)
        self.assertEqual(top.points[0][0], top.points[1][0])
        self.assertLess(top.points[1][1], top.points[0][1])
        self.assertEqual(bottom.points[0][0], bottom.points[1][0])
        self.assertGreater(bottom.points[1][1], bottom.points[0][1])
        root = ET.fromstring(workflow.build_svg(figure))
        for key in ("full", "simplified"):
            title, subtitle = root.findall(f".//svg:g[@id='{key}']/svg:text", NS)
            self.assertEqual(title.text, "Australian Tropical Reef Features")
            self.assertEqual(title.attrib["font-weight"], "bold")
            self.assertEqual(subtitle.attrib["font-weight"], "normal")

    def test_direct_legacy_flow_and_separate_interpretation_sources(self):
        figure = workflow.UPDATE
        nodes = figure.nodes
        self.assertEqual(nodes["gbr_ts"].y, nodes["latest_gbr"].y)
        self.assertLess(nodes["gbr_ts"].x + nodes["gbr_ts"].w, nodes["latest_gbr"].x)
        for source, target in (("gbr_ts", "refresh"), ("latest_gbr", "refresh"),
                               ("refresh", "integrate"), ("imagery", "digitise"),
                               ("bathymetry", "digitise")):
            edge, = [e for e in figure.edges if (e.source, e.target) == (source, target)]
            self.assertEqual(len(edge.points), 2)
            self.assertEqual(edge.points[0][0], edge.points[1][0])
            self.assertLess(edge.points[0][1], edge.points[1][1])
        self.assertEqual(nodes["imagery"].y, nodes["bathymetry"].y)
        self.assertIn("Standardise legacy classes", nodes["refresh"].lines)
        self.assertNotIn("standardise", " ".join(nodes["integrate"].lines).lower())

    def test_geometry_and_connector_clearance(self):
        for figure in workflow.FIGURES:
            for node in figure.nodes.values():
                self.assertTrue(0 <= node.x < node.x + node.w <= workflow.WIDTH)
                self.assertTrue(0 <= node.y < node.y + node.h <= figure.height)
            for index, (identifier, node) in enumerate(figure.nodes.items()):
                for other_id, other in list(figure.nodes.items())[index + 1:]:
                    self.assertFalse(
                        max(node.x, other.x) < min(node.x + node.w, other.x + other.w)
                        and max(node.y, other.y) < min(node.y + node.h, other.y + other.h),
                        f"{identifier} overlaps {other_id}",
                    )
            for edge in figure.edges:
                name = f"{figure.filename}: {edge.source} -> {edge.target}"
                for key, point in ((edge.source, edge.points[0]),
                                   (edge.target, edge.points[-1])):
                    node = figure.nodes[key]
                    x, y = point
                    self.assertTrue(
                        (x in (node.x, node.x + node.w) and node.y <= y <= node.y + node.h)
                        or (y in (node.y, node.y + node.h)
                            and node.x <= x <= node.x + node.w), name,
                    )
                for segment_index, (a, b) in enumerate(zip(edge.points, edge.points[1:])):
                    x1, y1 = a
                    x2, y2 = b
                    self.assertTrue(x1 == x2 or y1 == y2, name)
                    self.assertNotEqual(a, b, name)
                    for x, y in (a, b):
                        self.assertTrue(0 <= x <= workflow.WIDTH and 0 <= y <= figure.height)
                    for key, node in figure.nodes.items():
                        # Only the actual attachment segment may touch an endpoint box.
                        if ((key == edge.source and segment_index == 0)
                                or (key == edge.target
                                    and segment_index == len(edge.points) - 2)):
                            continue
                        if x1 == x2:
                            touches = (node.x <= x1 <= node.x + node.w
                                       and max(min(y1, y2), node.y)
                                       < min(max(y1, y2), node.y + node.h))
                        else:
                            touches = (node.y <= y1 <= node.y + node.h
                                       and max(min(x1, x2), node.x)
                                       < min(max(x1, x2), node.x + node.w))
                        self.assertFalse(touches, f"{name} touches {key}")
            for index, edge in enumerate(figure.edges):
                for other in figure.edges[index + 1:]:
                    for a, b in zip(edge.points, edge.points[1:]):
                        for c, d in zip(other.points, other.points[1:]):
                            self.assertFalse(
                                segments_intersect(a, b, c, d),
                                f"{figure.filename}: {edge.source} -> {edge.target} "
                                f"crosses {other.source} -> {other.target}",
                            )

    def test_deterministic_generation_and_targeted_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "figures"
            directory.mkdir()
            obsolete = directory / "dataset-creation-workflow.svg"
            obsolete.write_text("superseded", encoding="utf-8")
            unrelated = directory / "identifier.svg"
            unrelated.write_text("untouched", encoding="utf-8")
            with patch.object(workflow, "OUT_DIR", directory):
                workflow.main()
                first = {f.filename: (directory / f.filename).read_bytes()
                         for f in workflow.FIGURES}
                workflow.main()
            self.assertFalse(obsolete.exists())
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "untouched")
            self.assertEqual({p.name for p in directory.iterdir()},
                             set(first) | {"identifier.svg"})
            for figure in workflow.FIGURES:
                self.assertEqual((directory / figure.filename).read_bytes(),
                                 first[figure.filename])
                self.assertEqual((directory / figure.filename).read_text(encoding="utf-8"),
                                 workflow.build_svg(figure))

    def test_committed_figures_match_generator(self):
        for figure in workflow.FIGURES:
            self.assertEqual((ROOT / "figures" / figure.filename).read_text(encoding="utf-8"),
                             workflow.build_svg(figure))
        self.assertFalse((ROOT / "figures" / "dataset-creation-workflow.svg").exists())

    def test_running_from_another_directory(self):
        before = {p.name: p.read_bytes() for p in (ROOT / "figures").glob("*.svg")}
        with tempfile.TemporaryDirectory() as temporary:
            subprocess.run([sys.executable, str(ROOT / "A03-create-workflow-diagram.py")],
                           cwd=temporary, check=True, capture_output=True, text=True)
            self.assertEqual(list(Path(temporary).iterdir()), [])
        self.assertEqual({p.name: p.read_bytes() for p in (ROOT / "figures").glob("*.svg")},
                         before)


if __name__ == "__main__":
    unittest.main()
