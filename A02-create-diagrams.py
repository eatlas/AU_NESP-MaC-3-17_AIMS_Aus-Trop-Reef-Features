"""
Generate the SVG diagrams used in the reef identifier documentation.

Geometry is computed with shapely rather than drawn by eye, so the illustrated
overlaps, area shares and negative buffer results are real. Output is plain SVG
using presentation attributes only, with no CSS classes, pattern fills, filters
or clip paths, so that the files import cleanly into PowerPoint for editing.

World coordinates are metres. Areas are reported in km2.

Run from the repository root. Writes to figures/.

Each figure illustrates part of the identifier allocation in
02a-patch-TS-GBR-Features.py (referred to below as "02a"). The docstring of
each fig_* function is the figure's metadata, and the source for its caption:
  Shows    what is drawn
  When     the mapping situation in which the case arises
  Why      why the method handles it this way
  Code     where the concept lives in 02a, by Step heading, function, variable
           or constant (names rather than line numbers, so they stay valid)
  Used in  the document and figure number that embeds it
s1-s6 are used in 02a-PrevReefID-solution.md and r1-r2 in
02a-PrevReefID-review-guide.md. Some are also intended for the final report.

Background common to all figures. Old features are the GBR Features (GBRMPA)
polygons, whose LABEL_ID becomes ReefID. New features are the Reef Edit
polygons, which are authoritative wherever they are drawn. Only GBRMPA can
assign or reassign an official identifier, so the method passes ReefID across
only when the case is strong, and otherwise records the association in
PrevReefID ("part of this feature was previously known by this identifier"),
which is a statement about history that can safely be made at a low threshold.

Geometry is chosen so that applying the 02a rules to it gives the outcome
shown (shares, sliver erosion, dominance ratio). Printed values on each run
allow this to be checked. Identifiers are placeholders except in S4, where they
are real cases cited in the solution document. If the 02a constants
SLIVER_TOLERANCE_M (10 m), CANDIDATE_SHARE (0.1) or DOMINANCE_RATIO (3) change,
the figures must be checked again.
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
    """S1: the two directional overlap shares.

    Shows: one old reef and one new feature that partly overlap. The shared
    area divided by each polygon's own area gives two different shares
    (here share_old 0.09, share_new 0.18).
    When: every intersecting old/new pair is scored this way. The shares
    differ whenever the two polygons differ in size, which is common because
    the remapping often splits large old reefs or absorbs small ones.
    Why: a single symmetric score (intersection over union, used previously)
    falls away whenever sizes differ, so a small fragment lying wholly inside
    a large old reef, or a large new reef containing a small old one, scored
    below threshold and the identifier was silently lost. Two shares let the
    relationship be recognised from either side. The pair drawn is a candidate
    because share_new passes 0.1 even though share_old does not.
    Code: 02a score_pair() returns share_old and share_new, computed in
    EPSG:3577 (equal area). Step 4 "Candidate relationships" keeps a pair when
    max(share_old, share_new) >= CANDIDATE_SHARE.
    Used in: 02a-PrevReefID-solution.md, figure 1.
    """
    fig =  Fig(900, 360, "What share_old and share_new measure")

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
    """S2: rejection of digitising slivers by erosion.

    Shows: a reef mapped in two parts, remapped in two parts with the internal
    division drawn about 14 m from its old position. The new left part
    overlaps the old right part in a long thin strip (panel A), which vanishes
    when eroded by 10 m (panel B), so the two unrelated halves are not linked.
    When: whenever a reef is divided into parts, since the division is judged
    by eye and cannot be retraced exactly. Coordinate precision and small
    differences in boundary construction produce the same thin contacts.
    Why: the strip shares 0.15 / 0.11 of the two polygons, enough to pass the
    share test, so without this step the halves of one reef would record each
    other as previous identifiers. Erosion measures how deeply the polygons
    interpenetrate rather than how much area they share; area alone cannot
    separate a long sliver on a large reef from a compact overlap on a small
    one. The old right part is still deleted, because any intersection with
    authoritative new mapping deletes the old feature, but that does not lose
    its identifier, which passes to the new right part.
    Code: 02a score_pair() 'survives' (intersection.buffer(-tolerance)),
    SLIVER_TOLERANCE_M; pairs that do not survive are skipped in Step 4
    "Candidate relationships" before the share test. Not shown: the reduced
    tolerance for features under about 40 m wide, sliver_tolerance() with
    SLIVER_WIDTH_FRACTION.
    Used in: 02a-PrevReefID-solution.md, figure 2.
    """
    fig =  Fig(900, 350, "Overlaps created by a redrawn division are rejected")

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
    """Draw one old reef split into several new pieces and rank shared areas.

    Returns the best and runner-up shared areas and their ratio, mirroring the
    ranking in 02a Step 5.
    """
    old =  scale_to_area(blob(0, 0, 1100, 900, seed=seed), 8.0)
    p = Panel(fig, x, 105, 380, 220, title)
    news = []
    for (cx, cy, rx, ry, sd) in pieces:
        news.append(blob(cx, cy, rx, ry, seed=sd, amp=0.15))
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
    """S3: the dominance test when one old reef is split.

    Shows: (A) one fragment holds most of the old reef; its shared area is
    11.5 times the next, so it keeps ReefID NN-001 and the two small fragments
    record NN-001 in PrevReefID. (B) two comparable fragments, ratio 1.3, so
    neither inherits and both record NN-002 in PrevReefID. Shared areas in km2
    are computed, not drawn.
    When: an old reef is remapped as several features, either because closer
    mapping shows it is really several reefs, or because small outlying
    patches are now mapped separately from the main reef.
    Why: an official identifier can only pass to one feature, and choosing
    between comparable successors is GBRMPA's decision, not this project's.
    A ratio of 3 is deliberately conservative: it only passes ReefID across
    when there is a clear winner, as in A. Lower ratios correspond to messy
    cases that need judgement, so the identifier is kept as PrevReefID on
    every candidate rather than lost. A one-to-one replacement has no runner
    up and always inherits, so it needs no separate rule. Note the smallest
    fragment in A shares only 0.01 of the old reef but 0.28 of itself, so it
    is a candidate through share_new (see S1).
    Code: 02a Step 5 "Allocate ReefID, PrevReefID and ReefFID", the loop over candidates_by_id:
    candidates ranked by summed area, winner only if
    best['area'] >= DOMINANCE_RATIO * runner_up. Non-winners get a provisional
    ReefFID from make_provisional_id() and the identifier in
    reef_edit_prevreefid.
    Used in: 02a-PrevReefID-solution.md, figure 3.
    """
    fig =  Fig(900, 430, "Deciding which successor keeps the official identifier")

    best_a, second_a, ratio_a = _split_case(
        fig, 40, "A. One clear successor",
        [(-100, 0, 1200, 800, 61), (1250, 600, 350, 250, 62),
         (-1500, -900, 350, 260, 63)], 60, "NN-001")

    best_b, second_b, ratio_b = _split_case(
        fig, 480, "B. No clear successor",
        [(-1250, 0, 700, 900, 71), (760, 20, 900, 800, 72)], 70, "NN-002")
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

    fig.legend(40, 55, [('old', 'old boundary'), ('new', 'new mapping'),
                        ('int', 'shared area')])
    fig.save("s3-dominance-on-a-split.svg")


# ---------------------------------------------------------------------------
# S4  Features winning several identifiers
# ---------------------------------------------------------------------------

def fig_s4_multiple():
    """S4: a new feature that wins several old identifiers (merges).

    Shows: (A) a new reef polygon covering both reef 23-017 and the rock
    23-017b nested in it. It wins both identifiers; the reef overlap is about
    20 times the rock's, so it keeps 23-017 and records 23-017b. (B) reefs
    18-044 and 18-069a remapped as one feature. 18-069a's overlap is about 3.6
    times 18-044's, so it keeps 18-069a and records 18-044. Reef 18-069b only
    touches the new feature (shares 0.075 / 0.011, below CANDIDATE_SHARE), so
    it is not a candidate and does not appear in PrevReefID. Identifiers are
    the real cases cited in the solution document; geometry is schematic.
    When: routinely where a new reef polygon covers a rock or island polygon
    sitting on the old reef, and where two old reefs turn out to be one.
    Why: a feature can hold only one official identity. Without this step a
    merged feature takes none of its identifiers, which is wrong in the common
    nested-rock case. The same ratio of 3 is reused rather than adding a fourth
    threshold, keeping the method explainable; where no constituent dominates,
    all identifiers go to PrevReefID and the merge is left to GBRMPA.
    Code: 02a Step 5 "Allocate ReefID, PrevReefID and ReefFID", won_by_edit, resolve_merge()
    and inherited_by_edit; winners is rebuilt afterwards so a released
    identifier is not reported as inherited.
    Used in: 02a-PrevReefID-solution.md, figure 5.
    """
    fig =  Fig(900, 420, "Where one new feature relates to several old identifiers")

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
    """S5: one LABEL_ID shared by several source polygons.

    Shows: (A) in GBR Features a reef, a rock and an island all carry 10-320,
    because the a/b suffix convention was missed. (B) N1 covers most of the
    reef and N2 is a rock mapped separately (N1 is cut around it, as Reef Edit
    polygons do not overlap). The overlaps of every 10-320 polygon are summed
    per new feature, N1 dominates, so 10-320 is awarded once, to N1, and N2
    records it in PrevReefID.
    When: 660 of the 9,050 source rows share a LABEL_ID with another polygon,
    typically a reef with the rock or island on it.
    Why: grouping by polygon would make two independent claims on 10-320 (the
    reef claimed by N1, the rock by N2), and both could win, putting one
    official identifier on two features. Grouping by identifier guarantees a
    single winner or none.
    Code: 02a Step 5 "Allocate ReefID, PrevReefID and ReefFID", candidates_by_id (areas summed
    per edit_idx across old polygons with the same LABEL_ID). Step 10 warns
    where a ReefID still covers several output features. Note that Island and
    Mainland polygons are excluded from scoring in Step 4 (filter_mask), so in
    the code the island in this figure is not part of the claim; the outcome
    is the same.
    Used in: 02a-PrevReefID-solution.md, figure 4.
    """
    fig =  Fig(900, 400, "Dealing with reused Reef IDs in GBR Features")

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

    n2 = blob(-430, 130, 230, 190, seed=112)
    # Reef Edit polygons never overlap each other, so N1 is cut around N2.
    n1 = blob(-120, 0, 900, 640, seed=111).difference(n2)

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
    """S6: catalogue of ReefID / PrevReefID / ReefFID outcomes.

    Shows six relationship types and the attributes they produce:
    1 one-to-one replacement (single candidate, inherits); 2 split with a
    dominant successor (ratio 8.9); 3 split with none dominant (1.0);
    4 merge with a dominant constituent (4.0); 5 merge with none dominant
    (1.0); 6 genuinely new feature (no candidate). "a / b" values give the
    dominant / other fragments. PROV- is a provisional ReefFID.
    When: every new feature falls into one of these types.
    Why: ReefID is a claim about which reef this is, which only GBRMPA can
    make, so it is kept only where one successor or constituent clearly
    dominates. Everywhere else the association is still recorded as
    PrevReefID, a statement about history that is safe to make. ReefFID is
    always populated, so every feature has a dataset identifier.
    Code: 02a Step 5 "Allocate ReefID, PrevReefID and ReefFID" as a whole: dominance on
    candidates_by_id (types 1-3), resolve_merge() (types 4-5), and the final
    loop that fills reef_edit_reefid, reef_edit_reeffid (make_provisional_id)
    and reef_edit_prevreefid (type 6 when candidates_by_edit is empty).
    Used in: 02a-PrevReefID-solution.md, figure 6.
    """
    fig =  Fig(900, 660, "Identifier outcomes by relationship type")

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
# R1  Overlap thresholds and explicit corrections
# ---------------------------------------------------------------------------

def fig_r1_overlap():
    """R1: overlap shares and control-point placement.

    Shows: (A) the same shared area is less than 10% of the old polygon but
    more than 10% of the new polygon, so the pair qualifies. (B) both shares
    are too low, so the old reef is deleted without passing on its identifier.
    (C) Move plus the old CODE on the replacement forces succession despite
    weak overlap. (D) three old reefs become one new feature. The dominant
    overlap supplies ReefID 15-004b; 15-004c qualifies as PrevReefID, while
    15-004a needs a Link point because both its shares are below 10%.
    (E) Move plus CODE also works with no overlap. (F) Remove on an old
    false positive deletes it without a successor.
    When: reviewing a lost identifier or correcting displaced old mapping.
    Why: 10% of either polygon is sufficient, not 10% of both. The equivalent
    area threshold is 0.1 times the smaller polygon's area. Automatic pairs
    must also pass the sliver test. Deletion is separate from lineage.
    Code: 02a score_pair(), Step 4 candidates and force_candidate(); Steps
    2 and 3 move/remove deletion; Step 5 identifier allocation, including
    resolve_merge(). Other outcomes assume one old identifier and one
    successor. Link points must avoid nested rocks and cays.
    Layout: A4-proportioned portrait, two columns, without a bottom caption.
    The merge is schematic, not a reconstruction of the source boundaries.
    Used in: 02a-PrevReefID-review-guide.md, figure 1.
    """
    fig = Fig(720, 720 * 297 / 210, "Overlap and identifier corrections")
    fig.legend(24, 59, [('old', 'old boundary'), ('new', 'new mapping'),
                        ('int', 'shared area')])
    fig.rect(24, 77, 672, 31, fill=BOX_FILL)
    fig.text(360, 98,
             "Automatic linking when shared area is at least 10% of either polygon.",
             size=15, anchor="middle", weight="bold")

    enough_old = blob(0, 0, 1200, 800, seed=11)
    enough_new = blob(1450, 300, 800, 620, seed=12)
    old = blob(0, 0, 1000, 700, seed=181)
    weak_new = blob(1450, 300, 700, 520, seed=182)
    far_new = blob(2350, 300, 700, 520, seed=182)
    merge_new = blob(650, 0, 800, 1000, seed=231)
    merge_a = blob(-450, 450, 500, 500, seed=234)
    merge_b = blob(1150, 400, 750, 650, seed=232)
    merge_c = blob(350, -1000, 360, 240, seed=233)
    merge_a, merge_b, merge_c, merge_new = [
        shp_scale(g, xfact=1.6, yfact=0.65, origin=(0, 0))
        for g in (merge_a, merge_b, merge_c, merge_new)
    ]

    def draw_case(x, y, title, subtitle, old_geom, new_geom, action=None):
        fig.text(x, y, title, size=16, weight="bold")
        fig.text(x, y + 24, subtitle, size=15,
                 fill=BAD if title.startswith("B.") else TEXT)
        panel = Panel(fig, x, y + 40, 318, 112)
        is_merge = action == 'Link'
        old_geoms = [merge_a, merge_b, merge_c] if is_merge else [old_geom]
        panel.fit(old_geoms + ([new_geom] if new_geom is not None else []))
        inter = old_geom.intersection(new_geom) if new_geom is not None else None
        if new_geom is not None:
            panel.new(new_geom)
            for geom in old_geoms:
                panel.inter(geom.intersection(new_geom))
            nc = new_geom.representative_point()
            panel.label(nc.x + 180, nc.y, "new", size=14, fill=NEW_LINE,
                        weight="bold")
        for geom in old_geoms:
            panel.old(geom)
        oc = old_geom.representative_point()
        if is_merge:
            for wx, wy, label, colour in (
                    (-720, 650, "15-004a", GOOD),
                    (2160, 550, "15-004b", OLD_LINE),
                    (560, -900, "15-004c", OLD_LINE)):
                px, py = panel.px(wx, wy)
                fig.rect(px - 27, py - 13, 54, 17,
                         fill="#ffffff", stroke="none", rx=0)
                panel.label(wx, wy, label, size=13, fill=colour, weight="bold")
        else:
            panel.label(oc.x - 280, oc.y + 240, "NN-001", size=14,
                        fill=OLD_LINE, weight="bold")
        if action in ('Move', 'Remove'):
            panel.point(oc.x - 180, oc.y - 100, colour=BAD, label=action, dx=10)
        if action == 'Move':
            panel.label(nc.x + 120, nc.y - 240, "CODE = 12345", size=13,
                        fill=NEW_LINE)
            panel.label(oc.x - 200, oc.y - 430, "CODE: 12345", size=13,
                        fill=OLD_LINE)
        elif action == 'Link':
            lp = inter.representative_point()
            panel.point(lp.x, lp.y, colour=GOOD)
            panel.arrow_to(lp.x, lp.y, -18, 26, colour=GOOD)
            px, py = panel.px(lp.x, lp.y)
            fig.text(px - 20, py + 43, "Link", size=14, anchor="end",
                     fill=GOOD, weight="bold")

        if new_geom is None:
            fig.text(x, y + 168, "No replacement polygon.", size=14, fill=MUTED)
            fig.text(x, y + 192, "Use only if mapped in error.", size=14)
            print("    r1 F: deliberate removal, no successor")
            return

        share_old = inter.area / old_geom.area
        share_new = inter.area / new_geom.area
        for i, (name, value) in enumerate((("share_old", share_old),
                                          ("share_new", share_new))):
            ty = y + 168 + i * 24
            colour = GOOD if value >= 0.1 else BAD
            fig.text(x, ty, name, size=13.5, font=MONO, fill=MUTED)
            # The full bar is 100%; the black tick marks the 10% threshold.
            bx, by, bw = x + 94, ty - 11, 155
            fig.rect(bx, by, bw, 12, fill=BOX_FILL, rx=0)
            fig.rect(bx, by, bw * value, 12, fill=colour, stroke="none", rx=0)
            fig.line(bx + bw * 0.1, by - 3, bx + bw * 0.1, by + 15,
                     stroke=TEXT, width=1.5)
            fig.text(x + 318, ty, f"{100 * value:.1f}%", size=14,
                     anchor="end", fill=colour, weight="bold")
        print(f"    r1 {title}: shares {share_old:.3f} / {share_new:.3f}; "
              f"survives 10 m erosion: {not inter.buffer(-10).is_empty}")
        if is_merge:
            b_area = merge_b.intersection(new_geom).area
            c_area = merge_c.intersection(new_geom).area
            print(f"    r1 D: b/c overlap dominance {b_area / c_area:.3f}")

    cases = [
        (24, 132, "A. Enough on one side", "Automatic link",
         enough_old, enough_new, None,
         [("ReefID", "NN-001"), ("PrevReefID", "null")],
         "Only share_new needs to pass.", GOOD),
        (378, 132, "B. Too little on both sides", "No link", old, weak_new, None,
         [("ReefID", "null"), ("PrevReefID", "null")],
         "Old reef deleted; NN-001 is lost.", BAD),
        (24, 432, "C. Low overlap replacement", "Move + CODE",
         old, weak_new, 'Move',
         [("ReefID", "NN-001"), ("PrevReefID", "null")],
         "Move on old; its CODE on the replacement.", GOOD),
        (378, 432, "D. Weak overlap in a merge", "Link to retain a previous ID",
         merge_a, merge_new, 'Link',
         [("ReefID", "15-004b"), ("PrevReefID", "15-004c, 15-004a")],
         "15-004b dominates; Link retains 15-004a.", GOOD),
        (24, 732, "E. No overlap", "Move + CODE", old, far_new, 'Move',
         [("ReefID", "NN-001"), ("PrevReefID", "null")],
         "Deletes old and links new despite zero overlap.", GOOD),
        (378, 732, "F. No successor", "Remove", old, None, 'Remove',
         [("ReefID", "none"), ("PrevReefID", "none")],
         "Deliberate removal: reason 'Remove point'.", MUTED),
    ]
    for x, y, title, subtitle, old_geom, new_geom, action, attrs, note, colour in cases:
        draw_case(x, y, title, subtitle, old_geom, new_geom, action)
        fig.rect(x, y + 204, 318, 51, fill=BOX_FILL)
        for i, (key, value) in enumerate(attrs):
            ty = y + 225 + i * 21
            fig.text(x + 8, ty, key, size=14, font=MONO, fill=MUTED)
            if action == 'Link' and key == "PrevReefID":
                fig.text(x + 310 - 7 * 14 * 0.6, ty, "15-004c, ", size=14,
                         font=MONO, anchor="end")
                fig.text(x + 310, ty, "15-004a", size=14, font=MONO,
                         anchor="end", fill=GOOD, weight="bold")
            else:
                fig.text(x + 310, ty, value, size=14, font=MONO, anchor="end")
        fig.text(x, y + 272, note, size=13.5, fill=colour)

    fig.line(360, 123, 360, 1007, stroke=BOX_LINE)
    for y in (412, 712):
        fig.line(24, y, 696, y, stroke=BOX_LINE)
    fig.save("r1-orphaned-identifier.svg")


# ---------------------------------------------------------------------------
# R2  Reading the sub-threshold overlaps
# ---------------------------------------------------------------------------

def fig_r2_subthreshold():
    """R2: typical sub-threshold overlaps a reviewer will see.

    Shows three contacts that survive sliver erosion but are below
    CANDIDATE_SHARE on both sides, so no relationship is recorded:
    (A) a large reef's internal division redrawn by eye (0.05 / 0.045); on a
    reef this large the offset is wider than the sliver test can catch.
    (B) neighbouring fringing reefs remapped in more detail, the left one
    reaching into its neighbour, arrowed (0.058 / 0.053). (C) old mapping
    displaced from the true reef, so its real successor barely reaches it
    (0.016 / 0.043). Under each panel the shared area is compared with the
    area needed to link, 0.1 x the smaller of the two polygons, which is the
    same test as max(share_old, share_new) >= CANDIDATE_SHARE.
    When: A and B are common and are correct rejections; in both the old
    feature also has a strong candidate elsewhere, so no identifier is lost.
    C is the case the review exists to catch, and also appears as an orphan.
    Why: the low 0.1 threshold lets PrevReefID flow through easily, but small
    overlaps from redrawn divisions and neighbouring reefs must not, as they
    would associate unrelated reefs. The layer makes these rejections
    checkable rather than assumed, and is the evidence for whether 0.1 is
    set correctly.
    Code: 02a Step 6.2 "Sub-threshold overlaps": pairs where p['survives'] is
    true but the pair is not in candidates, written to the
    'sub-threshold-overlaps' layer with share_old, share_new and sole_pair.
    Used in: 02a-PrevReefID-review-guide.md, figure 2.
    """
    fig = Fig(900, 430,
              "Examples of reefs just touching that are not automatically linked")
    top = 122

    def shares(old, new):
        i = old.intersection(new)
        return i, i.area / old.area, i.area / new.area

    def share_block(x, old, new, inter):
        """Shared area against the area needed to pass CANDIDATE_SHARE."""
        needed = 0.1 * min(old.area, new.area)
        fig.attr_block(x, top + 184, [
            ("shared", f"{km2(inter):.3f} km2"),
            ("needed", f"{needed / 1e6:.3f} km2"),
            ("old / new", f"{inter.area / old.area:.2f} / "
                          f"{inter.area / new.area:.2f}"),
        ], width=266, title="shared area vs needed to link")

    # A. A large reef split by eye, where the division cannot be traced exactly.
    a_old = blob(0, 0, 1800, 700, seed=191, amp=0.05)
    a_new = blob(0, 0, 1850, 730, seed=191, amp=0.05)
    a_old_r = wobbly_cut(a_old, 0, seed=193, amp=30, side='right')
    a_new_l = wobbly_cut(a_new, 70, seed=194, amp=30, side='left')
    a_new_r = wobbly_cut(a_new, 70, seed=194, amp=30, side='right')
    a_int, a_so, a_sn = shares(a_old_r, a_new_l)
    pa = Panel(fig, 40, top, 266, 170, "A. A division redrawn by eye")
    pa.fit([a_old, a_new])
    pa.new(a_new_l)
    pa.new(a_new_r)
    pa.inter(a_int)
    pa.old(wobbly_cut(a_old, 0, seed=193, amp=30, side='left'))
    pa.old(a_old_r)
    share_block(40, a_old_r, a_new_l, a_int)

    # B. Fringing reefs along a coast, remapped in more detail. The land is
    # trimmed to the reefs' extent so the reefs fill the panel width.
    land = coast_band(-1800, 2300, -120, 700, seed=195, amp=60)
    b_old_l = blob(-900, 60, 850, 260, seed=196, amp=0.06).difference(land)
    b_old_r = blob(950, 60, 850, 260, seed=197, amp=0.06).difference(land)
    b_new_l = blob(-610, 70, 950, 275, seed=198, amp=0.10).difference(land)
    b_new_r = blob(1450, 70, 800, 250, seed=199, amp=0.10).difference(land)
    b_int, b_so, b_sn = shares(b_old_r, b_new_l)
    pb = Panel(fig, 331, top, 266, 170, "B. Neighbouring fringing reefs")
    pb.fit([land, b_old_l, b_old_r, b_new_l, b_new_r], pad=0.02)
    pb.draw(land, fill=LAND_FILL, stroke=LAND_LINE, width=1.4)
    pb.new(b_new_l)
    pb.new(b_new_r)
    pb.inter(b_int)
    pb.old(b_old_l)
    pb.old(b_old_r)
    lc = land.centroid
    pb.label(lc.x, lc.y, "land", size=12, dy=4, fill=LAND_LINE)
    bx, by = b_int.centroid.x, b_int.bounds[3]
    pb.arrow_to(bx, by, 0, -30)
    pb.label(bx, by, "overlaps neighbouring", size=11.5, dy=-50, fill=MUTED)
    pb.label(bx, by, "old reef", size=11.5, dy=-36, fill=MUTED)
    share_block(331, b_old_r, b_new_l, b_int)

    # C. Old mapping displaced, so the real successor barely reaches it.
    c_old = blob(0, 0, 1400, 900, seed=211)
    c_new = blob(1880, -500, 800, 600, seed=212)
    c_int, c_so, c_sn = shares(c_old, c_new)
    pc = Panel(fig, 622, top, 266, 170, "C. Displaced old mapping")
    pc.fit([c_old, c_new])
    pc.new(c_new)
    pc.inter(c_int)
    pc.old(c_old)
    share_block(622, c_old, c_new, c_int)

    print(f"    r2 shares  A {a_so:.3f}/{a_sn:.3f}  B {b_so:.3f}/{b_sn:.3f}  "
          f"C {c_so:.3f}/{c_sn:.3f}")

    fig.text(40, 416, "Linking needs the shared area to be at least 10% of "
             "the old or the new feature, whichever is smaller.",
             size=13, fill=TEXT, weight="bold")

    fig.legend(40, 66, [('old', 'old boundary'), ('new', 'new mapping'),
                        ('int', 'shared area')])
    fig.save("r2-sub-threshold-overlaps.svg")


def main():
    print("Generating documentation diagrams")
    fig_s1_shares()
    fig_s2_sliver()
    fig_s3_dominance()
    fig_s4_multiple()
    fig_s5_shared_id()
    fig_s6_outcomes()
    fig_r1_overlap()
    fig_r2_subthreshold()
    print("Done")


if __name__ == '__main__':
    main()
