# PrevReefID Allocation Rules — Summary

This document summarises the rules used in `02a-patch-TS-GBR-Features.py` to allocate
`ReefID`, `ReefFID`, and `PrevReefID` when integrating newly mapped reef features with an
existing GBR-TS features dataset. It covers handling of new and old IDs, slivers, overlaps,
splits, merges, and manual overrides.

---

## 1. Key Parameters

| Parameter | Value | Purpose |
|---|---|---|
| `SLIVER_TOLERANCE_M` | 10 | Erosion distance (m) below which an intersection is treated as a digitising artefact |
| `SLIVER_WIDTH_FRACTION` | 0.25 | Cap on erosion distance as a fraction of the smaller feature's width |
| `CANDIDATE_SHARE` | 0.1 | Minimum share of either polygon's area for a candidate relationship |
| `DOMINANCE_RATIO` | 3.0 | Factor by which the best candidate must exceed the next best to inherit an ID |
| `SIZE_CHANGE_REPORT` | 5.0 | Area ratio above which an inherited relationship is reported for review |

---

## 2. Two-Sided Share Calculation

For each intersecting old/new polygon pair, two asymmetric shares are computed in an
equal-area projection (EPSG:3577):

- `share_old = intersection_area / old_polygon_area`
- `share_new = intersection_area / new_polygon_area`

Using both shares (rather than a single symmetric measure like IoU) allows the system to
distinguish splits (low `share_old`, high `share_new`) from merges (high `share_old`, low
`share_new`).

---

## 3. Step-by-Step Allocation Rules

### Step 1: Reject Digitising Slivers

An intersection is discarded if it disappears when eroded. The erosion process works as follows:

1. **Standard test:** The intersection is eroded by 10 m (`intersection.buffer(-10).is_empty`).
   If it disappears, it is a candidate sliver.

2. **Reduced tolerance for small features:** If the standard test rejects the pair, a reduced
   tolerance is applied. The tolerance is capped at 25% of the inscribed width (narrowest part)
   of the smaller polygon. This prevents features whose whole width is comparable to the
   tolerance from being automatically discarded.

3. **Result:** Above ~40 m width, the full 10 m tolerance applies. Below that, the tolerance
   scales down. A pair survives the sliver test only if *any* disjoint piece of the
   intersection survives erosion. Shares are then computed from the *full* intersection area
   (including pieces that did not survive erosion).

### Step 2: Identify Candidate Relationships

A surviving intersection becomes a candidate relationship if **either** `share_old` **or**
`share_new` is at least 0.1 (10%).

Additionally, features carrying a `CODE` (an explicit link to an old feature) force a
candidate relationship regardless of geometry. This handles moved features that have no
geometric overlap with their original boundary.

### Step 3: Allocate Official Identifier (Split Handling)

Candidates are grouped by old `LABEL_ID` (which is not unique — a reef and its nested rock
may share one identifier across multiple polygons). Within each group:

1. Candidates are ranked by total intersection area.
2. The best candidate inherits the official identifier **if** its intersection area is at
   least 3× that of the next best candidate (`DOMINANCE_RATIO = 3.0`).
3. If no candidate is dominant, **no feature** inherits the identifier. It is recorded as
   `PrevReefID` on every candidate, and the determination is referred to GBRMPA.
4. A single-candidate group (no runner-up) always inherits — this covers straightforward
   one-to-one replacements without needing a separate rule.

### Step 4: Resolve Features That Win Several Identifiers (Merge Handling)

A new feature can win more than one official identifier (e.g., where two old reefs are
remapped as one feature, or where a new polygon covers both a reef and a nested rock).
Since a feature can hold only one identity, a second dominance test is applied:

1. The identifiers won by a single new feature are ranked by their intersection areas.
2. If the largest is at least 3× the next largest, the feature **keeps** the dominant
   identifier and records the others as `PrevReefID`.
3. If no identifier is dominant, the feature takes **none** of them. All are recorded as
   `PrevReefID`, and the merge is referred to GBRMPA.

### Step 5: Final Identifier Assignment

For each new feature:

| Scenario | `ReefID` | `ReefFID` | `PrevReefID` |
|---|---|---|---|
| Clear one-to-one replacement | Inherited official ID | Inherited `ReefID` | Other candidates, or null |
| Old feature split — dominant successor exists | Official ID on successor | Official ID on successor; provisional on others | Old ID on non-successors |
| Old feature split — no dominant successor | Null | Provisional (`PROV-{lat}-{lon}`) | Old ID on every candidate |
| Merge — one dominant constituent | Dominant constituent's ID | Inherited `ReefID` | Other constituents' IDs |
| Merge — no dominant constituent | Null | Provisional | All candidate IDs |
| Genuinely new (no candidates) | Null | Provisional (`PROV-{lat}-{lon}`) | Null |
| Retained old feature (no overlap) | Existing `LABEL_ID` | Existing `LABEL_ID` (with `-Fnn` where shared) | Null |

---

## 4. Provisional Identifier (`ReefFID`) Generation

Features that do not inherit an official ID receive a provisional identifier in the form
`PROV-{lat}-{lon}`, derived from the centroid coordinates (rounded to 2 decimal places,
absolute values). On collision, a letter suffix (`a`, `b`, etc.) is appended.

---

## 5. Manual Override Mechanisms

### `ACTION = 'Link'` (Implemented)

A Link point placed where a new and an old polygon overlap **forces a candidate relationship**
but **never** allows the new feature to inherit the official identifier. It produces only a
`PrevReefID`.

This is used for marginal overlaps that editors confirm are real but which the automated
thresholds reject.

A Link point is validated on every run:
- It must fall inside both a new and an old polygon.
- The pair must intersect.
- If the relationship already qualifies on its own, or was already set by CODE, it is
  reported as unnecessary.
- If the point no longer resolves to intersecting polygons, it is reported as obsolete.

### `ACTION = 'ReefID'` (Deferred — Not Implemented)

A ReefID point would name a new polygon as the recipient of the official identifier,
overriding the dominance test. This would be used when several features share a code and an
editor knows which one should carry the identity. This override has not been implemented.

### `ACTION = 'NoLink'` (Deferred — Not Implemented)

This would suppress reporting of certain overlaps. Deferred until review outputs demonstrate
a need.

---

## 6. Old Feature Deletion Rules

Old features are deleted (and removed from output) when:

- **Move operation:** A CODE on the new feature references the old feature.
- **Remove operation:** A Remove point intersects the old feature.
- **Overlap:** Any new feature intersects the old feature (regardless of whether the
  intersection passes the sliver test or share threshold).

Deletion and lineage are decided **independently** — an old feature can be deleted without
its identifier being carried forward. This is the main case surfaced by the "orphaned
identifiers" review layer.

---

## 7. Review Outputs

Six GeoPackage layers are produced for review:

| Layer | Contents |
|---|---|
| `orphaned-identifiers` | Deleted old features whose identifier appears in no `ReefID` or `PrevReefID` |
| `sub-threshold-overlaps` | Intersections that survive the sliver test but fail the 0.1 share threshold |
| `extreme-size-changes` | Inherited relationships where area differs by more than 5× |
| `override-problems` | Obsolete or unnecessary manual override points |
| `inshore-gaps` | Old features within the remapped inshore extent that survived without being replaced |
| `shared-reefid` | Features sharing an official `ReefID` (from non-unique source `LABEL_ID`) |

None of these layers stops processing — they are reports, not blocking checks.

---

## 8. Decision Flowchart Summary

```
New feature intersects old feature(s)?
  No → Retain old feature with existing LABEL_ID (PrevReefID = null)
  Yes → Intersection survives sliver test?
    No → Discard pair (unless forced by CODE/Link)
    Yes → Is share_old >= 0.1 OR share_new >= 0.1?
      No → No candidate relationship (unless forced by CODE/Link)
      Yes → Candidate relationship established
            Group candidates by old LABEL_ID
              One candidate, no runner-up → Inherit official ID (one-to-one replacement)
              Multiple candidates, best >= 3× runner-up → Best inherits, others → PrevReefID
              Multiple candidates, best < 3× runner-up → No inheritance; all → PrevReefID
            If new feature wins multiple identifiers:
              One >= 3× others → Keep dominant, others → PrevReefID
              None >= 3× others → None inherited; all → PrevReefID
            If no candidates at all → Genuinely new (PROV-{lat}-{lon})
```

---

## 9. Reference: Identifier Outcome Table

| Relationship Type | `ReefFID` | `ReefID` | `PrevReefID` |
|---|---|---|---|
| Clear one-to-one replacement | Inherited `ReefID` | Official identifier | Other candidates or null |
| Split with dominant successor | Inherited on successor; provisional on others | Official ID on successor; null on others | Old ID on non-successors |
| Split with no dominant successor | Provisional on every candidate | Null | Old ID on every candidate |
| Merge — one dominant | Inherited `ReefID` | Dominant constituent's ID | Other constituents' IDs |
| Merge — no dominant | Provisional | Null | All candidate IDs |
| Genuinely new feature | Provisional | Null | Null |
| Retained old feature | Existing `LABEL_ID` (with `-Fnn` where shared) | Existing `LABEL_ID` | Null |
