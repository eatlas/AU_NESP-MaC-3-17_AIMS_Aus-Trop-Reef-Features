"""
Generate the SVG diagrams used in the reef identifier documentation.

Geometry is computed with shapely rather than drawn by eye, so the illustrated
overlaps, area shares and negative buffer results are real. Output is plain SVG
using presentation attributes only, with no CSS classes, pattern fills, filters
or clip paths, so that the files import cleanly into PowerPoint for editing.

World coordinates are metres. Areas are reported in km2.

Run from the repository root. Writes to figures/.
"""

import math
import os
import random

from shapely.geometry import Polygon
from shapely.affinity import scale as shp_scale
from shapely.ops import unary_union

OUT_DIR = "figures"

FONT = "Arial, Helvetica, sans-serif"
MONO = "Consolas, 'Courier New', monospace"

OLD_LINE = "#6f6f6f"
NEW_LINE = "#14527a"
NEW_FILL = "#dcebf7"
INT_FILL = "#7fa9cc"
ALT_FILL = "#efe3cf"
ALT_LINE = "#8a6d3b"
LAND_FILL = "#ece7dd"
LAND_LINE = "#b9ad99"
BAD = "#b03a2e"
GOOD = "#1e6b34"
TEXT = "#111111"
MUTED = "#555555"
BOX_FILL = "#f7f7f7"
BOX_LINE = "#c8c8c8"

OLD_DASH = "7,4"


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def blob(cx, cy, rx, ry, seed=0, amp=0.07, n=160):
    """An ellipse with a smoothly irregular outline, as a reef boundary reads."""
    rnd = random.Random(seed)
    harmonics = [(k, rnd.uniform(0.3, 1.0), rnd.uniform(0, 2 * math.pi))
                 for k in (2, 3, 5, 7)]
    total = sum(a for _, a, _ in harmonics)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        wobble = sum(a * math.sin(k * t + p) for k, a, p in harmonics) / total
        r = 1 + amp * wobble
        pts.append((cx + rx * r * math.cos(t), cy + ry * r * math.sin(t)))
    return Polygon(pts)


def scale_to_area(geom, target_km2):
    """Scale a shape about its centroid so that its area matches a target."""
    factor = math.sqrt((target_km2 * 1e6) / geom.area)
    return shp_scale(geom, xfact=factor, yfact=factor, origin='centroid')


def wobbly_cut(poly, x_at_centre, seed=0, amp=6.0, side='left'):
    """Split a polygon with an irregular near-vertical line."""
    minx, miny, maxx, maxy = poly.bounds
    rnd = random.Random(seed)
    harmonics = [(k, rnd.uniform(0.3, 1.0), rnd.uniform(0, 2 * math.pi))
                 for k in (1, 2, 3)]
    total = sum(a for _, a, _ in harmonics)
    span = maxy - miny
    edge = []
    for i in range(41):
        y = miny - span * 0.05 + (span * 1.1) * i / 40
        t = 2 * math.pi * (y - miny) / span
        offset = amp * sum(a * math.sin(k * t + p) for k, a, p in harmonics) / total
        edge.append((x_at_centre + offset, y))
    if side == 'left':
        ring = [(minx - span, edge[0][1])] + edge + [(minx - span, edge[-1][1])]
    else:
        ring = [(maxx + span, edge[0][1])] + edge + [(maxx + span, edge[-1][1])]
    return poly.intersection(Polygon(ring))


def km2(geom):
    return geom.area / 1e6


def disc_of_area(cx, cy, area_m2, seed=3):
    """A compact blob with a given area, used to contrast against a sliver."""
    d = blob(cx, cy, 1.0, 1.0, seed=seed, amp=0.05)
    factor = math.sqrt(area_m2 / d.area)
    return shp_scale(d, xfact=factor, yfact=factor, origin='centroid')


def coast_band(x0, x1, y_top, depth, seed=0, amp=60.0, n=48):
    """A band of land with an irregular seaward edge, drawn below y_top."""
    rnd = random.Random(seed)
    harmonics = [(k, rnd.uniform(0.3, 1.0), rnd.uniform(0, 2 * math.pi))
                 for k in (1, 2, 4)]
    total = sum(a for _, a, _ in harmonics)
    top = []
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        t = 2 * math.pi * (x - x0) / (x1 - x0)
        wob = sum(a * math.sin(k * t + p) for k, a, p in harmonics) / total
        top.append((x, y_top + amp * wob))
    return Polygon(top + [(x1, y_top - depth), (x0, y_top - depth)])


# ---------------------------------------------------------------------------
# SVG scaffolding
# ---------------------------------------------------------------------------

def esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


class Fig:
    def __init__(self, width, height, title=None):
        self.w = width
        self.h = height
        self.parts = []
        if title:
            self.text(24, 34, title, size=18, weight="bold")

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size=13, anchor="start", fill=TEXT,
             weight="normal", font=FONT, style="normal"):
        self.add(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font}" '
            f'font-size="{size}" font-weight="{weight}" font-style="{style}" '
            f'fill="{fill}" text-anchor="{anchor}">{esc(s)}</text>'
        )

    def rect(self, x, y, w, h, fill="none", stroke=BOX_LINE, width=1.0, rx=4):
        self.add(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>'
        )

    def line(self, x1, y1, x2, y2, stroke=MUTED, width=1.0, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ''
        self.add(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{stroke}" stroke-width="{width}"{d}/>'
        )

    def arrow(self, x1, y1, x2, y2, colour=TEXT, width=1.8):
        ang = math.atan2(y2 - y1, x2 - x1)
        h = 9
        bx, by = x2 - h * 0.9 * math.cos(ang), y2 - h * 0.9 * math.sin(ang)
        self.line(x1, y1, bx, by, stroke=colour, width=width)
        p2 = (x2 - h * math.cos(ang - 0.42), y2 - h * math.sin(ang - 0.42))
        p3 = (x2 - h * math.cos(ang + 0.42), y2 - h * math.sin(ang + 0.42))
        self.add(
            f'<polygon points="{x2:.1f},{y2:.1f} {p2[0]:.1f},{p2[1]:.1f} '
            f'{p3[0]:.1f},{p3[1]:.1f}" fill="{colour}"/>'
        )

    def attr_block(self, x, y, lines, width=200, title=None):
        """A small panel listing output attribute values."""
        row = 19
        head = 20 if title else 5
        height = head + row * len(lines) + 8
        self.rect(x, y, width, height, fill=BOX_FILL, stroke=BOX_LINE)
        if title:
            self.text(x + 9, y + 15, title, size=12, fill=MUTED, weight="bold")
        for i, (key, val) in enumerate(lines):
            ty = y + head + row * i + 10
            self.text(x + 9, ty, key, size=12.5, font=MONO, fill=MUTED)
            self.text(x + width - 9, ty, val, size=12.5, font=MONO,
                      anchor="end", fill=TEXT)
        return height

    def legend(self, x, y, entries):
        """Entries are (style, label) where style is 'old', 'new' or 'int'."""
        cx = x
        for style, label in entries:
            if style == 'old':
                self.add(f'<line x1="{cx}" y1="{y}" x2="{cx + 30}" y2="{y}" '
                         f'stroke="{OLD_LINE}" stroke-width="1.8" '
                         f'stroke-dasharray="{OLD_DASH}"/>')
            elif style == 'new':
                self.add(f'<rect x="{cx}" y="{y - 7}" width="30" height="14" '
                         f'fill="{NEW_FILL}" stroke="{NEW_LINE}" stroke-width="1.8"/>')
            else:
                self.add(f'<rect x="{cx}" y="{y - 7}" width="30" height="14" '
                         f'fill="{INT_FILL}" stroke="none"/>')
            self.text(cx + 38, y + 5, label, size=12.5, fill=MUTED)
            cx += 46 + 7.2 * len(label)

    def save(self, name):
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.join(OUT_DIR, name)
        body = "\n  ".join(self.parts)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
            f'height="{self.h}" viewBox="0 0 {self.w} {self.h}">\n'
            f'  <rect x="0" y="0" width="{self.w}" height="{self.h}" fill="#ffffff"/>\n'
            f'  {body}\n</svg>\n'
        )
        with open(path, 'w', encoding='utf-8') as f:
            f.write(svg)
        print(f"  wrote {path}")


class Panel:
    """A drawing area with its own world-to-pixel transform."""

    def __init__(self, fig, x, y, w, h, title=None):
        self.fig = fig
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.s = 1.0
        self.cx = 0.0
        self.cy = 0.0
        self.top = y
        if title:
            fig.text(x, y - 10, title, size=14, weight="bold")

    def fit(self, geoms, pad=0.10):
        u = unary_union([g for g in geoms if not g.is_empty])
        minx, miny, maxx, maxy = u.bounds
        bw = max(maxx - minx, 1e-6)
        bh = max(maxy - miny, 1e-6)
        self.cx = (minx + maxx) / 2
        self.cy = (miny + maxy) / 2
        self.s = min(self.w * (1 - pad) / bw, self.h * (1 - pad) / bh)
        return self

    def fit_world(self, cx, cy, half_w, half_h):
        """Fit to an explicit world window, so panels can share a scale."""
        self.cx = cx
        self.cy = cy
        self.s = min(self.w / (2 * half_w), self.h / (2 * half_h))
        return self

    def px(self, wx, wy):
        return (self.x + self.w / 2 + (wx - self.cx) * self.s,
                self.y + self.h / 2 - (wy - self.cy) * self.s)

    def path_d(self, geom):
        def ring(coords):
            pts = [self.px(x, y) for x, y in coords]
            return "M " + " L ".join(f"{a:.1f},{b:.1f}" for a, b in pts) + " Z"
        if geom.is_empty:
            return ""
        polys = [geom] if geom.geom_type == 'Polygon' else list(geom.geoms)
        parts = []
        for poly in polys:
            if poly.is_empty or poly.geom_type != 'Polygon':
                continue
            parts.append(ring(poly.exterior.coords))
            for r in poly.interiors:
                parts.append(ring(r.coords))
        return " ".join(parts)

    def draw(self, geom, fill="none", stroke=NEW_LINE, width=1.6, dash=None):
        d = self.path_d(geom)
        if not d:
            return
        da = f' stroke-dasharray="{dash}"' if dash else ''
        self.fig.add(
            f'<path d="{d}" fill="{fill}" fill-rule="evenodd" stroke="{stroke}" '
            f'stroke-width="{width}" stroke-linejoin="round"{da}/>'
        )

    def old(self, geom):
        self.draw(geom, fill="none", stroke=OLD_LINE, width=1.7, dash=OLD_DASH)

    def new(self, geom):
        self.draw(geom, fill=NEW_FILL, stroke=NEW_LINE, width=1.7)

    def inter(self, geom):
        self.draw(geom, fill=INT_FILL, stroke="none", width=0)

    def point(self, wx, wy, colour=BAD, label=None, dx=12, dy=5):
        px, py = self.px(wx, wy)
        self.fig.add(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="6" fill="{colour}" '
            f'stroke="#ffffff" stroke-width="1.6"/>'
        )
        if label:
            self.fig.text(px + dx, py + dy, label, size=13, weight="bold",
                          fill=colour)

    def label(self, wx, wy, s, dx=0, dy=0, size=12.5, anchor="middle",
              fill=TEXT, font=FONT, weight="normal"):
        px, py = self.px(wx, wy)
        self.fig.text(px + dx, py + dy, s, size=size, anchor=anchor, fill=fill,
                      font=font, weight=weight)

    def arrow_to(self, wx, wy, dx, dy, colour=TEXT):
        """An arrow ending near a world point, starting dx,dy pixels away."""
        px, py = self.px(wx, wy)
        self.fig.arrow(px + dx, py + dy, px, py, colour=colour)

    def leader(self, wx, wy, dx, dy, colour=MUTED):
        px, py = self.px(wx, wy)
        self.fig.line(px, py, px + dx, py + dy, stroke=colour, width=0.9)

    def scalebar(self, length_m, label):
        x0 = self.x + 16
        y0 = self.y + self.h - 16
        x1 = x0 + length_m * self.s
        self.fig.line(x0, y0, x1, y0, stroke=TEXT, width=2.6)
        self.fig.text((x0 + x1) / 2, y0 - 8, label, size=12, anchor="middle",
                      fill=TEXT)


# ---------------------------------------------------------------------------
# S1  What the two shares measure
# ---------------------------------------------------------------------------

def fig_s1_shares():
    fig = Fig(900, 360, "What share_old and share_new measure")

    old = blob(0, 0, 1200, 800, seed=11)
    new = blob(1450, 300, 800, 620, seed=12)
    inter = old.intersection(new)
    a_old, a_new, a_int = km2(old), km2(new), km2(inter)
    share_old = inter.area / old.area
    share_new = inter.area / new.area
    print(f"    s1 share_old {share_old:.2f} share_new {share_new:.2f}")

    p = Panel(fig, 40, 96, 420, 220)
    p.fit([old, new])
    p.new(new)
    p.inter(inter)
    p.old(old)
    p.label(-700, 0, "old reef", size=13, fill=OLD_LINE, weight="bold")
    p.label(2050, 300, "new feature", size=13, fill=NEW_LINE, weight="bold")
    ic = inter.centroid
    p.arrow_to(ic.x, ic.y, 0, 96)
    p.label(ic.x, ic.y, "shared area", size=13, dy=116, weight="bold")

    fig.attr_block(510, 110, [
        ("old area", f"{a_old:.2f} km2"),
        ("new area", f"{a_new:.2f} km2"),
        ("shared area", f"{a_int:.2f} km2"),
    ], width=350)
    fig.attr_block(510, 218, [
        ("share_old", f"{a_int:.2f} / {a_old:.2f}  =  {share_old:.2f}"),
        ("share_new", f"{a_int:.2f} / {a_new:.2f}  =  {share_new:.2f}"),
    ], width=350)

    fig.legend(40, 66, [('old', 'old boundary'), ('new', 'new mapping'),
                        ('int', 'shared area')])
    fig.save("s1-two-sided-shares.svg")


# ---------------------------------------------------------------------------
# S2  Sliver rejection
# ---------------------------------------------------------------------------

def fig_s2_sliver():
    fig = Fig(900, 350, "Overlaps created by a redrawn division are rejected")

    old = blob(0, 0, 120, 42, seed=31, amp=0.05)
    new = blob(0, 0, 132, 48, seed=31, amp=0.05)
    old_l = wobbly_cut(old, 0, seed=41, amp=0, side='left')
    old_r = wobbly_cut(old, 0, seed=41, amp=0, side='right')
    new_l = wobbly_cut(new, 14, seed=42, amp=0, side='left')
    new_r = wobbly_cut(new, 14, seed=42, amp=0, side='right')
    sliver = new_l.intersection(old_r)
    eroded = sliver.buffer(-10)
    print(f"    sliver {km2(sliver):.4f} km2, eroded empty: {eroded.is_empty}")

    pa = Panel(fig, 40, 96, 400, 210, "A. One reef, mapped in two parts")
    pa.fit([old, new])
    pa.new(new_l)
    pa.new(new_r)
    pa.inter(sliver)
    pa.old(old_l)
    pa.old(old_r)
    pa.label(-70, 0, "left part", size=13, dy=5, fill=NEW_LINE)
    pa.label(78, 0, "right part", size=13, dy=5, fill=NEW_LINE)
    pa.label(7, 54, "division", size=12.5, fill=MUTED)

    pb = Panel(fig, 500, 96, 360, 210, "B. The overlap this creates")
    pb.fit([sliver], pad=0.40)
    pb.draw(sliver, fill=INT_FILL, stroke=BAD, width=1.8)
    pb.scalebar(10, "10 m")
    pb.label(sliver.centroid.x, sliver.bounds[3],
             "nothing survives erosion by 10 m", size=13, dy=-12,
             weight="bold", fill=BAD)

    fig.legend(40, 66, [('old', 'old parts'), ('new', 'new parts'),
                        ('int', 'unintended overlap')])
    fig.save("s2-sliver-rejection.svg")


# ---------------------------------------------------------------------------
# S3  Dominance on a split
# ---------------------------------------------------------------------------

def _split_case(fig, x, title, pieces, seed, identifier):
    old = scale_to_area(blob(0, 0, 1100, 780, seed=seed), 8.0)
    p = Panel(fig, x, 96, 380, 220, title)
    news = []
    for (cx, cy, rx, ry, sd) in pieces:
        news.append(blob(cx, cy, rx, ry, seed=sd, amp=0.08))
    p.fit([old] + news)
    for n in news:
        p.new(n)
    areas = []
    for n in news:
        i = old.intersection(n)
        p.inter(i)
        areas.append((km2(i), i))
    p.old(old)
    for n in news:
        p.draw(n, fill="none", stroke=NEW_LINE, width=1.7)
    ranked = sorted(areas, key=lambda a: -a[0])
    for a, geom in areas:
        if geom.is_empty:
            continue
        c = geom.centroid
        p.label(c.x, c.y, f"{a:.2f} km2", size=12.5, dy=5, weight="bold",
                fill="#0b3350")
    p.label(0, 1500, f"old reef {identifier}", size=12.5, fill=OLD_LINE,
            weight="bold")
    best, second = ranked[0][0], ranked[1][0]
    ratio = best / second if second > 0 else float('inf')
    return best, second, ratio


def fig_s3_dominance():
    fig = Fig(900, 430, "Deciding which successor keeps the official identifier")

    best_a, second_a, ratio_a = _split_case(
        fig, 40, "A. One clear successor",
        [(-180, 60, 1500, 1050, 61), (1500, 600, 400, 300, 62),
         (-1500, -700, 350, 260, 63)], 60, "NN-001")

    best_b, second_b, ratio_b = _split_case(
        fig, 480, "B. No clear successor",
        [(-800, 0, 700, 760, 71), (760, 20, 560, 620, 72)], 70, "NN-002")
    print(f"    s3 ratios A {ratio_a:.1f} B {ratio_b:.1f}")

    fig.text(40, 340, f"ratio {ratio_a:.1f}, above 3", size=14,
             weight="bold", fill=GOOD)
    fig.attr_block(40, 350, [("ReefID", "NN-001"), ("PrevReefID", "null")],
                   width=185, title="largest fragment")
    fig.attr_block(235, 350, [("ReefID", "null"), ("PrevReefID", "NN-001")],
                   width=185, title="other fragments")

    fig.text(480, 340, f"ratio {ratio_b:.1f}, below 3", size=14,
             weight="bold", fill=BAD)
    fig.attr_block(480, 350, [("ReefID", "null"), ("PrevReefID", "NN-002")],
                   width=185, title="both fragments")

    fig.legend(40, 66, [('old', 'old boundary'), ('new', 'new mapping'),
                        ('int', 'shared area')])
    fig.save("s3-dominance-on-a-split.svg")


# ---------------------------------------------------------------------------
# S4  Features winning several identifiers
# ---------------------------------------------------------------------------

def fig_s4_multiple():
    fig = Fig(900, 420, "Where one new feature relates to several old identifiers")

    # Panel A: a rock nested inside the reef it sits on.
    reef = blob(0, 0, 1000, 760, seed=81)
    rock = blob(240, 90, 200, 170, seed=82)
    newa = blob(-30, -20, 960, 700, seed=83)
    pa = Panel(fig, 40, 96, 380, 210, "A. A rock nested in a reef")
    pa.fit([reef, rock, newa])
    pa.new(newa)
    pa.inter(reef.intersection(newa))
    pa.old(reef)
    pa.draw(rock, fill=ALT_FILL, stroke=ALT_LINE, width=1.5, dash=OLD_DASH)
    pa.label(-540, 400, "23-017", size=12.5, fill=OLD_LINE, weight="bold")
    pa.label(240, 90, "23-017b", size=12, dy=4, fill=ALT_LINE, weight="bold")

    # Panel B: two old reefs remapped as one, with a third just in contact.
    r1 = blob(-1500, -100, 700, 620, seed=91)
    r2 = blob(1200, 0, 1500, 1050, seed=92)
    r3 = blob(3350, 400, 800, 600, seed=94)
    newb = blob(250, 0, 2600, 1250, seed=93)
    pb = Panel(fig, 480, 96, 380, 210, "B. Two reefs remapped as one")
    pb.fit([r1, r2, r3, newb])
    pb.new(newb)
    pb.inter(r1.intersection(newb))
    pb.inter(r2.intersection(newb))
    pb.old(r1)
    pb.old(r2)
    pb.old(r3)
    touch = r3.intersection(newb)
    if not touch.is_empty:
        print(f"    s4 18-069b shares {touch.area / r3.area:.3f} / "
              f"{touch.area / newb.area:.3f}")
    pb.label(-1500, -100, "18-044", size=12, dy=4, fill=OLD_LINE, weight="bold")
    pb.label(1200, 0, "18-069a", size=12, dy=4, fill=OLD_LINE, weight="bold")
    pb.label(3350, 400, "18-069b", size=12, dy=4, fill=OLD_LINE, weight="bold")

    fig.attr_block(40, 330, [("ReefID", "23-017"), ("PrevReefID", "23-017b")],
                   width=380, title="new feature")
    fig.attr_block(480, 330, [("ReefID", "18-069a"), ("PrevReefID", "18-044")],
                   width=380, title="new feature")

    fig.legend(40, 66, [('old', 'old reef'), ('new', 'new mapping'),
                        ('int', 'shared area')])
    fig.save("s4-several-identifiers.svg")


# ---------------------------------------------------------------------------
# S5  The shared LABEL_ID quirk
# ---------------------------------------------------------------------------

def fig_s5_shared_id():
    fig = Fig(900, 400, "Dealing with reused Reef IDs in GBR Features")

    reef = blob(0, 0, 1000, 700, seed=101)
    rock = blob(-420, 120, 180, 150, seed=102)
    isle = blob(430, -110, 220, 170, seed=103)

    pa = Panel(fig, 40, 96, 380, 210, "A. What the source contains")
    pa.fit([reef, rock, isle])
    pa.old(reef)
    pa.draw(rock, fill=ALT_FILL, stroke=ALT_LINE, width=1.5, dash=OLD_DASH)
    pa.draw(isle, fill=ALT_FILL, stroke=ALT_LINE, width=1.5, dash=OLD_DASH)
    pa.label(-540, 500, "Reef 10-320", size=12.5, fill=OLD_LINE, weight="bold")
    pa.label(-420, 120, "Rock", size=11.5, dy=-2, fill=ALT_LINE)
    pa.label(-420, 120, "10-320", size=11.5, dy=13, fill=ALT_LINE,
             weight="bold")
    pa.label(430, -110, "Island", size=11.5, dy=-2, fill=ALT_LINE)
    pa.label(430, -110, "10-320", size=11.5, dy=13, fill=ALT_LINE,
             weight="bold")

    n1 = blob(-120, 0, 900, 640, seed=111)
    n2 = blob(-430, 130, 230, 190, seed=112)

    pb = Panel(fig, 480, 96, 380, 210, "B. How the claim is resolved")
    pb.fit([reef, rock, isle, n1, n2])
    pb.new(n1)
    pb.new(n2)
    pb.old(reef)
    pb.draw(rock, fill="none", stroke=ALT_LINE, width=1.5, dash=OLD_DASH)
    pb.draw(isle, fill="none", stroke=ALT_LINE, width=1.5, dash=OLD_DASH)
    pb.label(140, -430, "N1", size=13, weight="bold", fill=NEW_LINE)
    pb.label(-430, 130, "N2", size=11.5, dy=4, weight="bold", fill=NEW_LINE)

    fig.attr_block(480, 330, [("N1 ReefID", "10-320"),
                              ("N2 PrevReefID", "10-320")], width=380)
    fig.save("s5-shared-label-id.svg")


# ---------------------------------------------------------------------------
# S6  Outcome catalogue
# ---------------------------------------------------------------------------

def fig_s6_outcomes():
    fig = Fig(900, 660, "Identifier outcomes by relationship type")

    cases = []

    old1 = blob(0, 0, 900, 650, seed=121)
    new1 = blob(60, 30, 880, 700, seed=122)
    cases.append(("One to one replacement", [old1], [new1],
                  [("ReefID", "NN-001"), ("PrevReefID", "null"),
                   ("ReefFID", "NN-001")]))

    old2 = blob(0, 0, 1000, 650, seed=131)
    new2a = blob(-250, 0, 650, 560, seed=132)
    new2b = blob(800, 220, 260, 200, seed=133)
    cases.append(("Split, dominant successor", [old2], [new2a, new2b],
                  [("ReefID", "NN-002 / null"), ("PrevReefID", "null / NN-002"),
                   ("ReefFID", "NN-002 / PROV-")]))

    old3 = blob(0, 0, 1000, 650, seed=141)
    new3a = blob(-570, 0, 470, 560, seed=142)
    new3b = blob(570, 20, 470, 560, seed=143)
    cases.append(("Split, none dominant", [old3], [new3a, new3b],
                  [("ReefID", "null"), ("PrevReefID", "NN-003"),
                   ("ReefFID", "PROV-")]))

    old4a = blob(-1308, 0, 380, 340, seed=151)
    old4b = blob(400, 0, 900, 640, seed=152)
    new4 = blob(-350, 0, 1500, 780, seed=153)
    cases.append(("Merge, dominant constituent", [old4a, old4b], [new4],
                  [("ReefID", "NN-005"), ("PrevReefID", "NN-004"),
                   ("ReefFID", "NN-005")]))

    old5a = blob(-660, 0, 576, 560, seed=161)
    old5b = blob(660, 0, 576, 560, seed=162)
    new5 = blob(0, 0, 1400, 700, seed=163)
    cases.append(("Merge, none dominant", [old5a, old5b], [new5],
                  [("ReefID", "null"), ("PrevReefID", "NN-006; NN-007"),
                   ("ReefFID", "PROV-")]))

    new6 = blob(0, 0, 700, 520, seed=171)
    cases.append(("Genuinely new feature", [], [new6],
                  [("ReefID", "null"), ("PrevReefID", "null"),
                   ("ReefFID", "PROV-")]))

    for idx, (title, olds, news, rows) in enumerate(cases):
        col = idx % 3
        row = idx // 3
        x = 40 + col * 290
        y = 110 + row * 272
        p = Panel(fig, x, y, 250, 150, f"{idx + 1}. {title}")
        p.fit(olds + news)
        for n in news:
            p.new(n)
        for o in olds:
            for n in news:
                p.inter(o.intersection(n))
        for o in olds:
            p.old(o)
        for n in news:
            p.draw(n, fill="none", stroke=NEW_LINE, width=1.7)
        fig.attr_block(x, y + 162, rows, width=250)

    fig.legend(40, 66, [('old', 'old boundary'), ('new', 'new mapping'),
                        ('int', 'shared area')])
    fig.save("s6-identifier-outcomes.svg")


# ---------------------------------------------------------------------------
# R1  Anatomy of an orphaned identifier
# ---------------------------------------------------------------------------

def fig_r1_orphan():
    fig = Fig(900, 420,
              "Automatic linking only applies when the overlap is enough")

    old = blob(0, 0, 1000, 700, seed=181)
    new = blob(1450, 300, 700, 520, seed=182)
    inter = old.intersection(new)
    print(f"    r1 shares {inter.area / old.area:.3f} / "
          f"{inter.area / new.area:.3f}")

    pa = Panel(fig, 40, 96, 250, 200, "A. Overlap too low to link")
    pa.fit([old, new])
    pa.new(new)
    pa.inter(inter)
    pa.old(old)
    pa.label(-300, 0, "NN-001", size=12.5, dy=5, fill=OLD_LINE, weight="bold")
    pa.label(1900, 400, "new", size=12.5, dy=5, fill=NEW_LINE, weight="bold")
    fig.attr_block(40, 316, [("ReefID", "null"), ("PrevReefID", "null")],
                   width=250, title="new feature")
    fig.text(40, 402, "NN-001 is lost. Reported in orphaned-identifiers.",
             size=12.5, fill=BAD, weight="bold")

    pb = Panel(fig, 340, 96, 250, 200, "B. Fix with a Move point")
    pb.fit([old, new])
    pb.new(new)
    pb.inter(inter)
    pb.old(old)
    pb.point(-100, 0, colour=BAD, label="Move", dx=10, dy=5)
    pb.label(1900, 400, "CODE set", size=12, dy=5, fill=NEW_LINE)
    fig.attr_block(340, 316, [("ReefID", "NN-001"), ("PrevReefID", "null")],
                   width=250, title="new feature")
    fig.text(340, 402, "The old identifier is inherited.", size=12.5,
             fill=GOOD, weight="bold")

    pc = Panel(fig, 640, 96, 250, 200, "C. Fix with a Link point")
    pc.fit([old, new])
    pc.new(new)
    pc.inter(inter)
    pc.old(old)
    ic = inter.centroid
    pc.point(ic.x, ic.y, colour=GOOD, label="Link", dx=10, dy=5)
    fig.attr_block(640, 316, [("ReefID", "null"), ("PrevReefID", "NN-001")],
                   width=250, title="new feature")
    fig.text(640, 402, "Lineage recorded, identity not claimed.", size=12.5,
             fill=GOOD, weight="bold")

    fig.legend(40, 66, [('old', 'old boundary'), ('new', 'new mapping'),
                        ('int', 'shared area')])
    fig.save("r1-orphaned-identifier.svg")


# ---------------------------------------------------------------------------
# R2  Reading the sub-threshold overlaps
# ---------------------------------------------------------------------------

def fig_r2_subthreshold():
    fig = Fig(900, 340,
              "Examples of reefs just touching that are not automatically linked")

    def shares(old, new):
        i = old.intersection(new)
        return i, i.area / old.area, i.area / new.area

    # A. A large reef split by eye, where the division cannot be traced exactly.
    a_old = blob(0, 0, 1800, 700, seed=191, amp=0.05)
    a_new = blob(0, 0, 1850, 730, seed=191, amp=0.05)
    a_old_r = wobbly_cut(a_old, 0, seed=193, amp=60, side='right')
    a_new_l = wobbly_cut(a_new, 70, seed=194, amp=60, side='left')
    a_new_r = wobbly_cut(a_new, 70, seed=194, amp=60, side='right')
    a_int, a_so, a_sn = shares(a_old_r, a_new_l)
    pa = Panel(fig, 40, 96, 250, 210, "A. A division redrawn by eye")
    pa.fit([a_old, a_new])
    pa.new(a_new_l)
    pa.new(a_new_r)
    pa.inter(a_int)
    pa.old(wobbly_cut(a_old, 0, seed=193, amp=60, side='left'))
    pa.old(a_old_r)

    # B. Fringing reefs along a coast, remapped in more detail.
    land = coast_band(-2600, 2600, -700, 900, seed=195, amp=90)
    b_old_l = blob(-900, 60, 850, 260, seed=196, amp=0.06).difference(land)
    b_old_r = blob(950, 60, 850, 260, seed=197, amp=0.06).difference(land)
    b_new_l = blob(-610, 70, 950, 275, seed=198, amp=0.10).difference(land)
    b_new_r = blob(1150, 70, 800, 250, seed=199, amp=0.10).difference(land)
    b_int, b_so, b_sn = shares(b_old_r, b_new_l)
    pb = Panel(fig, 340, 96, 250, 210, "B. Neighbouring fringing reefs")
    pb.fit([land, b_old_l, b_old_r, b_new_l, b_new_r])
    pb.draw(land, fill=LAND_FILL, stroke=LAND_LINE, width=1.4)
    pb.new(b_new_l)
    pb.new(b_new_r)
    pb.inter(b_int)
    pb.old(b_old_l)
    pb.old(b_old_r)
    pb.label(0, -900, "land", size=12, fill=LAND_LINE)
    bc = b_int.centroid
    pb.arrow_to(bc.x, bc.y, 0, 62)

    # C. Old mapping displaced, so the real successor barely reaches it.
    c_old = blob(0, 0, 1400, 900, seed=211)
    c_new = blob(1880, -500, 800, 600, seed=212)
    c_int, c_so, c_sn = shares(c_old, c_new)
    pc = Panel(fig, 640, 96, 250, 210, "C. Displaced old mapping")
    pc.fit([c_old, c_new])
    pc.new(c_new)
    pc.inter(c_int)
    pc.old(c_old)

    print(f"    r2 shares  A {a_so:.3f}/{a_sn:.3f}  B {b_so:.3f}/{b_sn:.3f}  "
          f"C {c_so:.3f}/{c_sn:.3f}")

    fig.legend(40, 66, [('old', 'old boundary'), ('new', 'new mapping'),
                        ('int', 'shared area')])
    fig.save("r2-sub-threshold-overlaps.svg")


# ---------------------------------------------------------------------------
# R3  Placing control points
# ---------------------------------------------------------------------------

def fig_r3_points():
    fig = Fig(900, 330, "Where each control point goes")

    old = scale_to_area(blob(0, 0, 900, 640, seed=221), 2.0)
    new_far = scale_to_area(blob(2100, 150, 850, 620, seed=222), 1.8)
    new_over = scale_to_area(blob(1050, 120, 850, 620, seed=223), 1.8)
    rock = scale_to_area(blob(180, -80, 200, 160, seed=224), 0.05)

    pa = Panel(fig, 40, 96, 250, 210, "A. Move")
    pa.fit([old, new_far])
    pa.new(new_far)
    pa.old(old)
    pa.point(0, 0, colour=BAD, label="", dx=0)
    pa.label(2100, 150, "CODE set", size=12, dy=5, fill=NEW_LINE)

    pb = Panel(fig, 340, 96, 250, 210, "B. Remove")
    pb.fit([old, new_far])
    pb.old(old)
    pb.point(0, 0, colour=BAD, label="", dx=0)

    pc = Panel(fig, 640, 96, 250, 210, "C. Link")
    pc.fit([old, new_over, rock])
    pc.new(new_over)
    inter = old.intersection(new_over)
    pc.inter(inter)
    pc.old(old)
    pc.draw(rock, fill=ALT_FILL, stroke=ALT_LINE, width=1.5, dash=OLD_DASH)
    ic = inter.centroid
    pc.point(ic.x, ic.y, colour=GOOD, label="", dx=0)
    pc.point(180, -80, colour=BAD, label="", dx=0)
    pc.label(180, -80, "avoid", size=12, dx=0, dy=-14, fill=BAD,
             weight="bold")

    fig.legend(40, 66, [('old', 'old boundary'), ('new', 'new mapping'),
                        ('int', 'shared area')])
    fig.save("r3-control-points.svg")


def main():
    print("Generating documentation diagrams")
    fig_s1_shares()
    fig_s2_sliver()
    fig_s3_dominance()
    fig_s4_multiple()
    fig_s5_shared_id()
    fig_s6_outcomes()
    fig_r1_orphan()
    fig_r2_subthreshold()
    fig_r3_points()
    print("Done")


if __name__ == '__main__':
    main()
