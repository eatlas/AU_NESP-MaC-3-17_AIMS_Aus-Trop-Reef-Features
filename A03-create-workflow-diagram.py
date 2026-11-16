"""Generate the two editable, report-sized workflow SVGs using only stdlib.

Run with ``python A03-create-workflow-diagram.py`` from any directory.
Geometry and processing graphs are explicit so both can be tested independently.
See A03-create-workflow-diagram-spec.md for provenance and report captions.
"""

from dataclasses import dataclass
from html import escape
from pathlib import Path


WIDTH = 900
OUT_DIR = Path(__file__).resolve().parent / "figures"
BLUE = "#005A9C"
CYAN = "#00A3DF"
OUTLINE = "#354054"
GOLD = "#C89600"
NEW_FILL = "#FFF8ED"
CONNECTOR = "#8CB6D6"
FONT = "Arial, Helvetica, sans-serif"


@dataclass(frozen=True)
class Node:
    x: int
    y: int
    w: int
    h: int
    lines: tuple[str, ...]
    role: str = "input"
    title_lines: int = 0
    nested_lines: int = 0


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    points: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Group:
    x: int
    y: int
    w: int
    h: int
    label: str


@dataclass(frozen=True)
class Figure:
    filename: str
    title: str
    description: str
    height: int
    nodes: dict[str, Node]
    edges: tuple[Edge, ...]
    groups: tuple[Group, ...] = ()


OVERVIEW_NODES = {
    "nw": Node(24, 52, 190, 64, ("North and West", "Australian Features")),
    "cs": Node(242, 52, 190, 64, ("Coral Sea Features",)),
    "gbr_ts": Node(460, 52, 190, 64, ("GBR + TS Features",)),
    "edits": Node(678, 52, 190, 64, ("Reef Edits",), "new"),
    "nw_prepare": Node(24, 156, 190, 76, ("Prepare", "attributes"), "process", 2),
    "cs_prepare": Node(242, 156, 190, 76,
                       ("Combine reefs", "and platforms"), "process", 2),
    "update": Node(460, 156, 408, 76,
                   ("Update GBR + TS mapping",), "process", 1),
    "merge": Node(24, 280, 844, 60, ("Merge regional datasets",), "process", 1),
    "sovereignty": Node(255, 380, 390, 60, ("Assign sovereignty",), "process", 1),
    "country": Node(24, 378, 204, 64, ("Country + EEZ", "union, 2024")),
    "depth": Node(255, 480, 390, 76,
                  ("Add depth statistics", "and categories"), "process", 2),
    "classifications": Node(255, 596, 390, 76,
                            ("Add external classifications",
                             "NVCL / Seamap / Qld Wetlands"), "process", 1),
    "full": Node(255, 712, 390, 96,
                 ("Australian Tropical Reef Features", "Full classification (L3)"), "new", 1),
    "dissolve": Node(255, 848, 390, 76,
                     ("Dissolve by L2 class", "Recalculate depth statistics"), "process", 1),
    "simplified": Node(255, 964, 390, 96,
                       ("Australian Tropical Reef Features",
                        "Simplified classification (L2)"), "new", 1),
    "bathymetry": Node(24, 664, 204, 168,
                       ("MultiRes-Bathy-", "EEZ_2024",
                        "AusBathyTopo", "Australia 250 m 2024",
                        "(fallback)", "EOT20 tides")),
}

OVERVIEW_EDGES = (
    Edge("nw", "nw_prepare", ((119, 116), (119, 156))),
    Edge("cs", "cs_prepare", ((337, 116), (337, 156))),
    Edge("gbr_ts", "update", ((555, 116), (555, 156))),
    Edge("edits", "update", ((773, 116), (773, 156))),
    Edge("nw_prepare", "merge", ((119, 232), (119, 280))),
    Edge("cs_prepare", "merge", ((337, 232), (337, 280))),
    Edge("update", "merge", ((664, 232), (664, 280))),
    Edge("merge", "sovereignty", ((450, 340), (450, 380))),
    Edge("country", "sovereignty", ((228, 410), (255, 410))),
    Edge("sovereignty", "depth", ((450, 440), (450, 480))),
    Edge("bathymetry", "depth", ((126, 664), (126, 518), (255, 518))),
    Edge("depth", "classifications", ((450, 556), (450, 596))),
    Edge("classifications", "full", ((450, 672), (450, 712))),
    Edge("full", "dissolve", ((450, 808), (450, 848))),
    Edge("bathymetry", "dissolve", ((126, 832), (126, 886), (255, 886))),
    Edge("dissolve", "simplified", ((450, 924), (450, 964))),
)

OVERVIEW = Figure(
    "A03-dataset-creation-workflow.svg",
    "Creation of the Australian Tropical Reef Features dataset",
    "Regional mapping is combined, enriched and published as full and simplified "
    "classification products. The dotted GBR + TS update is expanded in the companion figure.",
    1084, OVERVIEW_NODES, OVERVIEW_EDGES,
    (Group(448, 8, 436, 240, "GBR + TS update"),),
)

UPDATE_NODES = {
    "gbr_ts": Node(24, 40, 170, 76, ("GBR + TS", "Features")),
    "latest_gbr": Node(214, 40, 170, 76, ("Latest GBRMPA", "GBR Features")),
    "regional_crosswalk": Node(119, 158, 170, 76,
                               ("RB classification", "crosswalk")),
    "refresh": Node(24, 284, 360, 96,
                    ("Refresh GBR mapping", "Retain TS mapping",
                     "Standardise legacy classes"), "process", 1),
    "imagery": Node(408, 24, 222, 218,
                    ("Imagery", "S2 All Tide", "S2 Low Tide",
                     "Queensland Globe", "aerial imagery"), title_lines=1),
    "bathymetry": Node(654, 24, 222, 218,
                       ("Bathymetry", "MultiRes-Bathy-", "EEZ_2024",
                        "GBR DEM 2020,", "30 m", "Torres Strait DEM", "2023, 30 m"),
                       title_lines=1, nested_lines=4),
    "digitise": Node(408, 284, 468, 96,
                     ("Digitise edits and controls", "Manual interpretation"), "process", 1),
    "edits": Node(408, 428, 222, 76, ("Reef Edits",), "new"),
    "controls": Node(654, 428, 222, 76,
                     ("Move / Remove /", "Link + CODE"), "new"),
    "edit_landmask": Node(214, 548, 170, 76, ("Coastline50k", "landmask")),
    "clip_edits": Node(408, 548, 222, 76,
                       ("Clip Reef Edits", "to coastline"), "process", 2),
    "integrate": Node(24, 704, 852, 80,
                      ("Integrate edits", "Preserve ReefIDs"), "process", 1),
    "legacy_landmask": Node(24, 854, 170, 76, ("Coastline50k", "landmask")),
    "clip_legacy": Node(270, 852, 360, 80,
                        ("Clip retained legacy features",), "process", 1),
    "updated": Node(270, 980, 360, 76, ("Updated GBR + TS Features",)),
}

UPDATE_EDGES = (
    Edge("gbr_ts", "refresh", ((109, 116), (109, 284))),
    Edge("latest_gbr", "refresh", ((299, 116), (299, 284))),
    Edge("regional_crosswalk", "refresh", ((204, 234), (204, 284))),
    Edge("imagery", "digitise", ((519, 242), (519, 284))),
    Edge("bathymetry", "digitise", ((765, 242), (765, 284))),
    Edge("digitise", "edits", ((519, 380), (519, 428))),
    Edge("digitise", "controls", ((765, 380), (765, 428))),
    Edge("edits", "clip_edits", ((519, 504), (519, 548))),
    Edge("edit_landmask", "clip_edits", ((384, 586), (408, 586))),
    Edge("refresh", "integrate", ((204, 380), (204, 704))),
    Edge("clip_edits", "integrate", ((519, 624), (519, 704))),
    Edge("controls", "integrate", ((765, 504), (765, 704))),
    Edge("integrate", "clip_legacy", ((450, 784), (450, 852))),
    Edge("legacy_landmask", "clip_legacy", ((194, 892), (270, 892))),
    Edge("clip_legacy", "updated", ((450, 932), (450, 980))),
)

UPDATE = Figure(
    "A03-gbr-ts-update-workflow.svg",
    "Update of the GBR and Torres Strait mapping",
    "Existing GBR mapping is refreshed while TS mapping is retained, and legacy classes "
    "are standardised. Manual interpretation of imagery and bathymetry produces Reef Edits "
    "and correction controls. Edits are clipped before integration, "
    "identifiers are preserved, and retained legacy features are clipped afterwards. "
    "The repeated Coastline50k boxes refer to the same landmask.",
    1080, UPDATE_NODES, UPDATE_EDGES,
)

FIGURES = (OVERVIEW, UPDATE)


def _text(x: float, y: float, label: str, *, size: int = 18,
          colour: str = BLUE, bold: bool = False, anchor: str = "middle") -> str:
    return (
        f'<text x="{x:g}" y="{y:g}" font-family="{FONT}" font-size="{size}" '
        f'font-weight="{"bold" if bold else "normal"}" fill="{colour}" '
        f'text-anchor="{anchor}">{escape(label)}</text>'
    )


def _node(identifier: str, node: Node) -> str:
    process = node.role == "process"
    fill = CYAN if process else NEW_FILL if node.role == "new" else "#FFFFFF"
    stroke = GOLD if node.role == "new" else OUTLINE
    elements = [
        f'<g id="{escape(identifier, quote=True)}">',
        f'<rect x="{node.x}" y="{node.y}" width="{node.w}" height="{node.h}" '
        f'rx="{10 if process else 4}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
    ]
    spacing = 26
    first_baseline = node.y + node.h / 2 - (len(node.lines) - 1) * spacing / 2 + 6
    for index, label in enumerate(node.lines):
        nested = node.nested_lines and index >= len(node.lines) - node.nested_lines
        x = node.x + node.w / 2
        if node.nested_lines:
            x = node.x + (40 if nested else 24)
        elements.append(_text(
            x, first_baseline + index * spacing, label,
            size=20 if index < node.title_lines else 18,
            colour="#FFFFFF" if process else BLUE,
            bold=index < node.title_lines, anchor="start" if node.nested_lines else "middle",
        ))
    if node.nested_lines:
        top = first_baseline + (len(node.lines) - node.nested_lines) * spacing - 16
        bottom = first_baseline + (len(node.lines) - 1) * spacing + 4
        elements.append(
            f'<polyline points="{node.x + 34},{top:g} {node.x + 28},{top:g} '
            f'{node.x + 28},{bottom:g} {node.x + 34},{bottom:g}" '
            f'fill="none" stroke="{OUTLINE}" stroke-width="1"/>'
        )
    elements.append("</g>")
    return "\n".join(elements)


def _edge(edge: Edge) -> str:
    points = " ".join(f"{x},{y}" for x, y in edge.points)
    x, y = edge.points[-1]
    previous_x, previous_y = edge.points[-2]
    dx = (x > previous_x) - (x < previous_x)
    dy = (y > previous_y) - (y < previous_y)
    base_x, base_y = x - dx * 10, y - dy * 10
    arrow = (f"{x},{y} {base_x - dy * 5},{base_y + dx * 5} "
             f"{base_x + dy * 5},{base_y - dx * 5}")
    return (
        f'<g data-source="{edge.source}" data-target="{edge.target}">\n'
        f'<polyline points="{points}" fill="none" stroke="{CONNECTOR}" '
        f'stroke-width="3" stroke-linejoin="round"/>\n'
        f'<polygon points="{arrow}" fill="{CONNECTOR}"/>\n</g>'
    )


def build_svg(figure: Figure) -> str:
    height_mm = 160 * figure.height / WIDTH
    elements = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="160mm" height="{height_mm:.3f}mm" '
        f'viewBox="0 0 {WIDTH} {figure.height}" role="img" aria-labelledby="title description">',
        f'<title id="title">{escape(figure.title)}</title>',
        f'<desc id="description">{escape(figure.description)}</desc>',
    ]
    for group in figure.groups:
        elements.append(
            f'<rect x="{group.x}" y="{group.y}" width="{group.w}" height="{group.h}" '
            f'rx="10" fill="none" stroke="{OUTLINE}" stroke-width="1.5" '
            'stroke-dasharray="2,5"/>'
        )
        elements.append(_text(group.x + 16, group.y + 26, group.label, anchor="start"))
    elements.extend(_edge(edge) for edge in figure.edges)
    elements.extend(_node(identifier, node) for identifier, node in figure.nodes.items())
    elements.append("</svg>")
    return "\n".join(elements) + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for figure in FIGURES:
        output = OUT_DIR / figure.filename
        output.write_text(build_svg(figure), encoding="utf-8")
        print(f"Wrote {output}")
    obsolete = OUT_DIR / "dataset-creation-workflow.svg"
    if obsolete.exists():
        obsolete.unlink()
        print(f"Removed superseded {obsolete}")


if __name__ == "__main__":
    main()
