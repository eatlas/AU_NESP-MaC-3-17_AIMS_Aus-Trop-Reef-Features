# Assigning previous reef identifiers: problem statement

## Context

The Australian Tropical Reef Features dataset replaces or substantially revises many polygons from the GBRMPA Great Barrier Reef Features dataset. The output needs to retain useful links to the historical mapping without claiming that a revised polygon is the same persistent feature when that has not been established.

Three identifiers are relevant. `ReefFID` is the unique identifier for a polygon in this dataset. `ReefID` is the official persistent reef identifier assigned by the responsible authority. `PrevReefID` records official identifiers previously associated with the location of a revised feature. GBRMPA is the authority for official identifiers in the Great Barrier Reef region. This project cannot assign new official GBRMPA identifiers to split, merged, newly mapped, or substantially revised features.

## The matching problem

The old and new boundaries often differ substantially. The old mapping has variable positional accuracy. Some features are displaced, generalised, or much larger than the reef habitat visible in newer imagery and bathymetry. A simple geometric similarity test can therefore fail even where the old and new polygons clearly represent related mapping.

Splits and merges create asymmetric overlap. A small new polygon may lie almost entirely within a large old polygon, while covering only a small proportion of the old polygon. Conversely, a large new polygon may contain most of a small old polygon, while that overlap forms only a small proportion of the new polygon. Both cases can represent meaningful lineage even though the polygons have low overall geometric similarity.

Small boundary contacts create the opposite problem. Neighbouring reefs may touch because of positional error or changes in boundary interpretation. Recording every intersection as lineage could associate a new feature with an unrelated old reef. This is especially problematic in dense reef areas. Very marginal overlaps can also arise when a boundary refinement extends slightly into a neighbouring old feature.

Not every geometric intersection is spatially meaningful. Some intersections are narrow slivers caused by coordinate precision, reprojection, or small differences in boundary construction. Other intersections extend far enough into both polygons to represent a plausible relationship, even though they cover only a small percentage of each feature. Area percentage alone does not distinguish these cases. A long narrow sliver can have more area than a compact overlap on a small reef.

## Digitisation history

During digitisation, an explicit move operation was normally added when the corrected feature did not overlap its old boundary. If any overlap remained, the feature was often expected to be matched spatially and no move operation was added. The amount of overlap was not measured during editing. This approach was used because the editor could not give an indication of the amount of overlap by area. 

This creates uncertain cases where the old and new polygons overlap only slightly. Some are intended replacements verified from marine charts or feature names. Others are incidental contacts with neighbouring features. The geometry alone may not distinguish these cases. The problem is most apparent for small inshore reefs, where the old positional error can be large relative to feature size.

These slight intersections also hide missing move records. A feature with no overlap was readily recognised as requiring an explicit move. A feature with a small overlap appeared connected during editing, but the overlap may be too weak for later automated matching. It is difficult for an editor to judge this from the map because the required comparison depends on polygon areas as well as the visible contact. The editor needs a way to know if a manual move operation needs to be specified.

A further source of unintended overlap comes from divisions carried over from the old mapping. Some reefs were historically mapped as two or more parts, typically halves of a single reef platform. When the reef is remapped as a whole, the division has to be re-added so that the new mapping keeps the same parts. The position of that division is judged by eye against imagery, because the old boundary is not accurate enough to trace. Each new part therefore overlaps the old part on the other side of the division by a small amount, even though there is no relationship across it. The accuracy of an eye judged division is typically around 10 m, and is likely to be poorer on large features.

The `CODE` attribute on a new feature records the old feature it derives from. It is used where the new mapping cannot be matched to the old feature by overlap, either because the old feature was mapped in the wrong position, or because the new feature covers only a small part of it. Several new features can carry the same code, which records that they all derive from one old feature. Carrying the code does not by itself mean that a feature takes the old official identifier. It records the relationship, and the identifier is allocated separately.

## Quirks in the GBR Features source mapping

The GBRMPA Great Barrier Reef Features dataset carries several conventions that are not obvious from its documentation but that any identifier method has to accommodate. They were found by inspecting the refreshed input during implementation, and they are recorded here because each one invalidates an assumption that would otherwise be reasonable to make.

The official identifier is not unique to a polygon. In the refreshed input, 660 of 9,050 rows share a `LABEL_ID` with at least one other row. This happens because a reef and the rock, island, cay or sand bank sitting on it are commonly given the same identifier. The identifier `10-320`, for example, appears on a Reef, a Rock and an Island. The identifier therefore names a reef complex or a location rather than a mapped boundary. Any rule that assumes one identifier corresponds to one polygon will fail on these features, and a validation check requiring an official identifier to appear once in the output cannot be enforced as stated. The practical consequence is that identifier allocation has to be grouped by identifier rather than by polygon, so that a group of old polygons sharing an identifier is treated as a single claim rather than as several competing ones.

The `CODE` attribute is close to unique but not quite. There are 9,046 distinct values across 9,050 rows. The genuine duplicate pairs are `10-458-104-103` and `11-222-101-106`, with the remainder arising from island and mainland features. `CODE` is a better key than `LABEL_ID`, and it is what the Reef Edit layer references, but it is still not safe to treat as a primary key.

The fourth segment of `CODE` encodes feature type for Great Barrier Reef features. In the refreshed input, 104 corresponds to Reef on 3,687 features, 102 to Island on 819, 103 to Cay on 254, 106 to Rock on 222 with 4 exceptions typed as Island, 108 to Rock on 129 with 1 exception, 100 to Island or Mainland, and 107 to Sand. Torres Strait features use a different convention, so the segment cannot be relied on across the whole processing extent. Where it does apply it establishes which polygon in a shared identifier group is the reef, which is useful when deciding which polygon has the stronger claim to the identifier.

Smaller features are nested inside larger ones. Island, cay and rock polygons sit within the reef polygon they belong to, and the layer is not planar. This has two consequences. A point placed to record a manual decision can fall inside two old polygons at once, so override points have to be resolved against a filtered layer rather than the full one. More importantly, a new polygon that replaces a reef will almost always also overlap the rock or island nested within it. That new polygon therefore acquires candidate relationships to two official identifiers, one from the reef and one from the nested feature, even though only one relationship is meaningful. Pelican Island Reef `23-017` is a worked case. The 0.908 km² reef contains Rock `23-017b`, and the new 0.772 km² polygon becomes a candidate for both.

Island and Mainland features are present in the source but are excluded from this dataset. They still hold official identifiers, so they can absorb or block an identifier during processing even though they never appear in the output. The filtering has to be applied at the right point for this not to distort the allocation.

## Observed scale

Split relationships are a small proportion of the dataset, but they are common enough that they cannot be handled case by case. A single old feature is in some cases remapped as eight separate features. Most groups of this kind contain one new feature that is much larger than the rest and is the obvious replacement, but a substantial minority do not. In one group the largest fragment covers only a few per cent of an old reef of over 11 km². In another the old feature is divided almost exactly in half. Measurement cannot decide which piece should inherit the identifier in these cases, so the dataset needs a way to say that no replacement has been chosen.

Some new features have no intersection at all with the old feature they derive from. In one case an old reef is fully contained within a much larger new feature, while a second new feature carrying the same code lies entirely outside the old boundary. Geometry alone cannot recover that second relationship, so a manually recorded link is the only available evidence.

Figures quoted here should be produced by the processing rather than counted by hand, so that they can be refreshed as the input mapping is corrected. Counts of split groups, of groups with and without an obvious replacement, and of coded features with no overlap all change whenever the editing files are revised.

## Required distinctions

The processing must distinguish several outcomes. An unchanged or clearly corresponding feature may retain an official `ReefID`. A split, merge, or materially revised feature may need a new dataset feature identifier while retaining links to one or more previous official identifiers. A genuinely new feature has no previous identifier. An incidental overlap should not create a lineage relationship.

These outcomes require different levels of evidence. Evidence sufficient to show that an old feature previously occupied the same location may not be sufficient to claim that the new polygon retains the same official identity. Classifying ambiguous cases as either matched or new can therefore lose important uncertainty.

Only one new feature can be given the official identifier of an old reef. When an old reef is remapped as several new features, there are two possible results. If one of the new features is much the largest and covers most of the old reef, it is the obvious replacement and should keep the official identifier. The other pieces then record it as a previous identifier. If instead the old reef is divided into pieces of similar size, there is no obvious replacement, and none of them should be given the official identifier automatically. GBRMPA would need to decide which one, if any, inherits it. The dataset needs to represent both results. If they are treated the same way, either an identifier is dropped when it could have been kept, or it is attached to a piece chosen more or less at random.

A feature can carry both an official identifier and a previous identifier at the same time. For example, a new reef may be a good match for old reef A and keep its official identifier, while the corrected boundary also covers a large part of neighbouring old reef B. In that case the feature keeps the identifier of A and records B as a previous identifier. If the two fields were treated as mutually exclusive, the link to B would be lost.

Removing an old boundary and carrying its identifier forward are separate decisions. An old feature is removed whenever new mapping covers its location, because the old boundary is no longer the best available. Whether the identifier carries forward depends on whether the new feature represents the same reef, which is a different question. Because the two are judged differently, an old feature can be removed while its identifier appears nowhere in the output. The identifier is then lost with no record of where it went, so the processing needs to report these cases rather than leave them to be found by inspection.

## Identifier outcomes

The intended identifier states for the main relationship types are shown below. These describe the required output semantics, not how the relationship is detected.

| Relationship | `ReefFID` | `ReefID` | `PrevReefID` |
|---|---|---|---|
| Clear one-to-one replacement | Existing official `ReefID` | Existing official `ReefID` | Any other old official `ReefID` values also associated with the location, otherwise null |
| One old feature split, with one new feature the obvious replacement | The old official `ReefID` on the replacement, a unique provisional identifier on the others | The old official `ReefID` on the replacement, null on the others | The old official `ReefID` on the other pieces |
| One old feature split, with no obvious replacement | A unique provisional identifier for each child | Null until assigned by the responsible authority | The old official `ReefID` on every qualifying child |
| One new feature combining several old features | A unique provisional identifier | Null until assigned by the responsible authority | All qualifying old official `ReefID` values |
| Genuinely new feature | A unique provisional identifier | Null until assigned by the responsible authority | Null |
| Retained old feature | Existing official `ReefID` | Existing official `ReefID` | Null |

The split and merge cases preserve historical association without claiming that an old official identity belongs to one particular new polygon. A one-to-one replacement retains the official identity because the persistent feature has not changed, even where the boundary or the area changes substantially. An identifier names a reef rather than a shape, and much of the change reflects correction of poor original mapping rather than change in the reef itself. A genuinely new feature has neither a current official identifier nor a previous one.

An identifier held as `ReefID` on a feature is not repeated in that feature's `PrevReefID`. Values in `PrevReefID` are unordered. Ordering by strength of association could not be maintained across releases without recomputing the comparison against every earlier version. In later releases the field needs to accumulate as a set union, so that it reads as the set of identifiers by which a location has previously been known.

## Display and labelling

The dataset is intended to be usable in place of GBR Features in maps and reports. Users identify reefs by their official number, and a map labelled from `ReefID` alone would show a blank wherever an identifier was not carried forward. In the current input, 1,019 new features carry only a previous identifier and 2,338 have neither. Around a third of the new mapping would therefore be unlabelled, including features that users already know by number. This is a presentation problem rather than an identifier problem, but it is a direct cost of the conservative allocation and it has to be addressed for the dataset to be adopted.

The requirement is a label that shows the official identifier where one exists, shows the previous identifiers where one does not, and makes clear which of the two is being shown. A previous identifier is not a claim of identity, so it cannot be presented in the same way as an official one without misleading the reader. Where a feature carries several previous identifiers, all of them are relevant, because the reader is otherwise given an arbitrary subset of the location's history. How the distinction is marked is a matter of map legibility and has to be judged against a real labelled map rather than decided in the abstract.

## Practical constraints

The processing must work across thousands of polygons and remain reproducible. It must tolerate poor historical geometry without creating broad false associations. It must also account for the existing editing record, in which explicit move points and source `CODE` values identify manually verified replacements.

The positional error of the old mapping ranges from roughly 50 m to 1,000 m. No per-feature estimate of this error exists, and the range is too wide for a single value to be representative. Feature size varies over a similar breadth. Reefs as small as 30 m across must be treated on the same terms as reefs of tens of square kilometres, so any test based on an absolute area or an absolute distance will suit one end of that range and fail at the other.

Any criteria adopted need to be explained in the dataset documentation and defended to users. A small number of criteria that resolve most cases, combined with an explicit override for the remainder, is preferable to a larger set that each improve a narrow class of case. None of the values currently proposed have been tested against manual assessment, so the processing needs to report the cases sitting near any threshold in a form that can be reviewed on a map. Review is nearly always positional, so review outputs need to be spatial rather than tabular.

This problem applies to the Great Barrier Reef and Torres Strait processing only. The Coral Sea and North West Australia datasets maintain their own identifiers and arrive at the merge stage complete. Version 1.0 has not been published and `ReefFID` is a new field, so there is no published allocation to preserve. Stability is required from version 1.0 onward rather than retrospectively.

Some ambiguous relationships have already been assessed manually, but those decisions are not always recorded in a form that processing can reuse. An incidental overlap that has been assessed remains geometrically identical to an unresolved overlap, so it can be repeatedly raised during later processing. Geometry edits can also make a decision difficult to associate with the same feature later. This is complicated by the lack of a stable input identifier for every Reef Edit polygon.

Any manual record used to resolve these cases has to stay cheap to create. There are thousands of features, so a mechanism that requires an identifier to be entered and maintained on both the old and new mapping would not be used consistently. The existing move and remove operations work by placing a point on the map, which keeps the relationship visual and requires no identifier to be typed. A comparable effort is the practical limit for any additional record.
