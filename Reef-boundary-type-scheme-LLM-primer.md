# LLM Primer - Reef Boundary Type Classification Scheme (v0-4)

This primer distils the essential concepts, definitions and rules behind the Reef Boundary Type classification used to map tropical Australian reef features. It is designed for embedding alongside a dataset description so that an LLM can confidently answer questions about what each class means, how attributes are assigned, how to interpret polygons, and how to crosswalk to related schemes. The scheme was developed for whole-reef features identifiable from remote sensing and is applied to the North and West Australian Tropical Reef Features and the Australian Tropical Reef Features datasets. The material is a preprint dated 16 September 2025 and will be published with the NESP MaC 3.17 final report. 

## Where is this used
This classification scheme is used in the following datasets:
- Lawrey, E., Bycroft, R. (2025). Australian Tropical Reef Features - Boundaries of coral and rocky reefs (NESP MaC 3.17, AIMS) (Version v0-1) [Data set]. eAtlas. https://doi.org/10.26274/4RRW-RR88. LLM Primer: https://raw.githubusercontent.com/eatlas/AU_NESP-MaC-3-17_AIMS_Aus-Trop-Reef-Features/refs/heads/main/Aus-Trop-Reef-Features-LLM-primer.md
- Lawrey, E., Bycroft, R. (2025). North and West Australian Tropical Reef Features - Boundaries of coral reefs, rocky reefs and sand banks (NESP-MaC 3.17, AIMS, Aerial Architecture). [Data set]. eAtlas. https://doi.org/10.26274/xj4v-2739

## Purpose and scope

The scheme captures the geomorphic footprint and expected ecological potential of tropical reefs at scales of roughly 50 m to 5 km. It trades species-level certainty for reliable inference from physical form visible in satellite and aerial imagery. Consolidated, structurally complex substrates are treated as proxies for richer ecological assemblages, while extensive unconsolidated sediments generally indicate lower structural complexity. The classification spans coral, rocky and sedimentary reef forms, intertidal and subtidal sediments, cays, islands and anthropogenic structures, with a consistent attribute model to support rapid manual digitisation and downstream crosswalks. 

## Design philosophy

A hybrid approach is used. A single primary class at Level 3 (RB_Type_L3) encodes nuanced, expert definitions that are difficult to express with orthogonal attributes alone, while a small number of supplementary attributes preserves interoperability and avoids a combinatorial explosion of types. This supports automated crosswalks to Seamap Australia and Natural Values Common Language while maintaining expressiveness for northern Australian reef diversity. 

## Core attributes

The three descriptive attributes you will see on each mapped feature are RB_Type_L3, Attachment and DepthCat. Additional metadata fields record provenance, uncertainty and positional accuracy for auditability and analysis. 

### RB_Type_L3 - Level 3 type

RB_Type_L3 is the detailed feature type reflecting geological origin and typical benthic community. It is the core label used for analysis and crosswalking. Where remote sensing cannot reliably distinguish fine biotic states, the scheme encodes what can be inferred consistently from form and context.

The Level 3 classes and their working definitions are below. Where relevant, rules for combining polygons to recover the full geomorphic footprint are noted.

#### Coral reef classes

**Coral Reef.** Raised carbonate framework with exposed hard substrate supporting coral on reef slope, crest, outer flat and rubbly areas. When large parts of a reef are sand-covered or the infilled interior of a platform, they are mapped as Coral Reef Flat. Merge with adjacent Coral Reef Flat to obtain the full coral reef footprint. 

**Coral Reef Bank.** Isolated deep shelf reef with a largely soft-sediment flat top, often halimeda, and limited exposed hard substrate, typically 25 - 35 m depth and oval planform. Merge with touching Coral Reef to recover the bank’s outer boundary. 

**Coral Reef Flat.** Shallow, sediment-dominated parts of a coral reef or infilled planar platform lacking exposed hard substrate or rubble. Common in macrotidal fringing systems and senile planar reefs; used where a substantial portion of the reef is sandy. Merge with adjacent Coral Reef for the complete geomorphic reef boundary. 

**High Intertidal Coral Reef.** Macrotidal coral reef with a flat top grown to within about 1 m of mean sea level and algal ridges that limit drying at low tide, for example Montgomery and Turtle reefs in the Kimberley. 

**Oceanic-specific coral reef subclasses.** For atoll systems the scheme distinguishes:

* Oceanic Rim Coral Reef on the outer atoll edge with ocean-facing slopes and sandy lagoonal backs.
* Oceanic Flow Coral Reef in current-forced channels with low relief and cross-reef spurs and grooves.
* Oceanic Lagoon Patch Coral Reef as small, isolated lagoonal patches, often near-circular with steep sides and grazing halos.
* Oceanic Platform Coral Reef as the coral component on infilled atoll platforms lacking a lagoon.
* Oceanic Lagoon Coral Reef where shallow lagoon floors are substantially hard-coral covered rather than sediment-filled. 

#### Non-coral consolidated reef classes

**Rocky Reef.** Reef formed from terrestrial rock, including margins of large loose boulders where rocks exceed about 20 percent cover. Corals may occur but without sufficient framework accretion to qualify as Coral Reef. If slabs are very low-profile with low structural complexity, use Low Relief Rocky Reef. 

**Low Relief Rocky Reef.** Low-profile sedimentary rock features with limited structural complexity; often distinguished by plate-like forms that minimally perturb surrounding sand. 

**Limestone Reef.** Consolidated limestone, typically ancient reef rock with low relief and frequent macroalgae. Consider Coral Reef only where there is evidence of modern accretion. 

**Sandy Limestone Pavement.** Broad, very low-relief consolidated limestone platform with a thin sandy veneer and patches of rubble, supporting macroalgae and, where sanded, seagrass. Excludes broken limestone shorelines with >1 m relief and areas with significant modern coral framework. 

**Paleo Coast Rocky Reef.** Relict rocky shorelines now submerged or partly connected, often 15 - 30 m depth in the Pilbara, with long, near-coast-parallel ridges suggesting past sea-level stillstands. 

**Stromatolite Reef.** Reefs formed by stromatolites; mapped only at very coarse fidelity. 

#### Unconsolidated and other substrates

**Sand Bank.** Mobile, unconsolidated sediment banks or dunes that rise at least about 2 m above surrounding seabed. No upper depth limit is imposed. 

**Non-reef Bank.** Broad, low-relief rises usually 20 - 50 m deep without evidence of consolidated calcareous framework or living coral. Considered relict or erosional terrestrial landforms that are generally soft-substrate. 

**Intertidal Sediment.** Fringing intertidal sediment wedges associated with the mainland or islands down to LAT where not covered by seagrass. Included for alignment with NVCL; concept defined but not mapped in v0-4. 

**Shallow Sediment.** Intertidal to shallow subtidal sediment, including areas with seagrass, used as a mask for UQ habitat mapping in v0-3 but not retained in v0-4 due to loose depth definition. 

**Seagrass on Sediment** and **Seagrass on Coral Reef.** Seagrass meadows on terrigenous sediment or on coral reef bases respectively. 

**Oceanic vegetated sediments** and **Oceanic Platform.** Lagoonal soft sediments with algae between atoll reefs, and the limestone base of an atoll around 100 m depth respectively. 

#### Islands and anthropogenic

**Vegetated Cay** and **Unvegetated Cay.** Carbonate sand islands on reefs, mapped as the area occupied over a 5 - 10 year window to accommodate movement. 

**Island** and **Mainland.** Terrestrial land above mean high water; cays are explicitly separated as reef islands. 

**Man Made.** Non-natural structures such as rigs, pearl farm pontoons and channel markers. 

**Unknown.** Non-sand features with insufficient evidence for a more precise class; placeholders pending additional information. 

### Attachment

Attachment describes how the feature relates spatially to landforms and the continental shelf. It is used consistently across connected polygon parts so a deeper segment inherits the fringing status of an adjoining fringing feature when they are part of one geomorphic system.

| Value    | Working definition                                                                                                                                                                                    |   |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | - |
| Fringing | Directly attached to or clearly shaped by the near-shore slope of a terrestrial island or mainland. Coral fringing reefs typically grow seaward from the island. A cay does not make a reef fringing. |   |
| Isolated | A shelf reef surrounded by deeper water or sediment and not associated with mainland or island.                                                                                                       |   |
| Oceanic  | Any coral reef beyond the 200 m shelf break, including reefs on oceanic atolls or around raised oceanic islands.                                                                                      |   |
| Land     | Any area above mean high water.                                                                                                                                                                       |   |

### DepthCat and DepthCatSr

DepthCat encodes the shallowest part of a feature in broad categories chosen for remote-sensing detectability and NVCL alignment. DepthCatSr records how that estimate was derived.

| DepthCat     | Definition                                                     |   |
| ------------ | -------------------------------------------------------------- | - |
| Land         | Above mean high water.                                         |   |
| Surface      | Floating structures moving with tide (specific Man Made only). |   |
| Intertidal   | Above LAT.                                                     |   |
| Very Shallow | Shallower than approximately -2.5 m LAT.                       |   |
| Shallow      | Shallower than approximately -30 m MSL.                        |   |
| Deep         | Deeper than approximately -30 m MSL.                           |   |

Depth sources include Sentinel-2 visibility thresholds in Red (B4), Green (B3) and NIR (B5) composites, DEA Intertidal, individual dated Sentinel-2 scenes, WA aerial imagery, Google Satellite, and project composite products. Each source implies different certainty about being Intertidal, Very Shallow or Shallow depending on turbidity and calibration. 

### Confidence and positional accuracy

Two categorical confidences support quality assessment. FeatConf is the likelihood the feature exists rather than being artefact or benthic noise, and TypeConf is the likelihood the RB_Type_L3 allocation is correct. Categories are Very Low, Low, Medium and High with approximate probability bands: about >40 percent for Very Low FeatConf through to about 95 percent for High FeatConf, and <50 percent to 90 - 98 percent for TypeConf High depending on texture visibility and distinctiveness. EdgeAcc_m is the mapper’s estimate of the 80th percentile boundary error in metres, considering image noise, turbidity, slope, complexity and atypicality; larger features tend to carry larger EdgeAcc_m due to longer uncertain perimeters. 

### EdgeSrc

EdgeSrc is a free-text provenance field that records the imagery used to digitise or refine a boundary, including specific composite versions with DOIs, dated single-scene references and basemap sources. This supports reproducibility and re-assessment. 

## Derived attributes and hierarchy

RB_Type_L2 and RB_Type_L1 are algorithmically derived from RB_Type_L3. Level 2 clusters related detailed classes, for example all coral reef subclasses, all rocky reef subclasses, sediment classes and land classes. Level 1 collapses to the most general substrate grouping of Reef, Sediment, Land or Other. These levels underpin simple queries such as filtering for consolidated reef vs unconsolidated sediment. 

## Crosswalks and interoperability

Automated crosswalks use RB_Type_L3, Attachment and DepthCat to populate selected attributes in other schemes. For the Queensland Intertidal and Subtidal Ecosystem Classification, robust mappings exist for Benthic Depth (B_DEPTH), Consolidation (CONSOL), Substrate composition (SUB_CMP), Inundation (INUNDTN) and Structural macrobiota composition (SMB_CMP). Many terrain attributes in that scheme do not align with whole-reef boundary mapping or require bathymetry not available across the study area, so they are not populated. This selective mapping enables broader ecosystem reporting while acknowledging differences in unit-of-analysis. 

## Geological boundary logic

Polygons may be split to represent different ecological activity levels on the same structure. The key example is the Coral Reef and Coral Reef Flat split, and the segregation of Coral Reef Bank tops from exposed Coral Reef patches. To recover the complete geomorphic footprint of a coral structure, merge touching Coral Reef, Coral Reef Flat and, where applicable, Coral Reef Bank. This reduces fragmentation for geomorphic analyses while retaining biologically meaningful partitions for habitat queries. 

## Oceanic vs shelf nuances

Oceanic atoll classes are specialised to capture processes and forms unique to atoll rims, channels, platforms and lagoons. On the north-west shelf, deep shelf coral banks can be morphologically similar on top to oceanic platforms, but differ mainly in surrounding water depth. Users should take care when comparing oceanic and shelf contexts, particularly for bank-type features. 

## Practical interpretation guidance

When answering questions about a feature, first state the RB_Type_L3 definition, then provide Attachment and DepthCat to clarify setting and detectability. If a user asks for the full reef boundary, advise merging Coral Reef with Coral Reef Flat and Coral Reef Bank where polygons touch. If confidence is in question, report FeatConf, TypeConf and EdgeAcc_m to communicate the certainty and expected boundary error. If a crosswalk attribute is requested that is not robust for whole-reef features, explain the limitation and provide the closest mapped fields. 

## Frequently asked distinctions

A Coral Reef is the exposed, accreting coral framework, whereas a Coral Reef Flat is the adjoining carbonate platform that is predominantly sand-covered or infilled and has lower structural complexity. A Coral Reef Bank indicates a deep, largely sediment-mantled bank with limited exposed framework on the top, while a Non-reef Bank lacks evidence of a consolidated calcareous framework and is interpreted as a relict or erosional landform. Sand Bank is a mobile sediment body rising at least around 2 m; Intertidal Sediment is the fringing sediment wedge associated with terrestrial landforms down to LAT. Sandy Limestone Pavement is a very low-relief consolidated platform with veneer; Limestone Reef is consolidated limestone reef rock, often macroalgal, but not necessarily accreting today. High Intertidal Coral Reef has macrotidal flats near mean sea level with algal ridges; High Intertidal Sediment Reef is a rounded, dark macrotidal consolidated sediment feature lacking algal ridges and currently only known from the Kimberley. 

## Known limitations

Remote sensing cannot always separate bare rock from macroalgal cover or quantify rugosity precisely, so some biological inferences remain qualitative. The v0-4 mapping does not include Intertidal Sediment polygons, although the concept is defined for future alignment. Confidence and accuracy metrics are expert estimates and can vary with feature size and imagery quality. Differences between oceanic and shelf classification emphasis can complicate direct comparisons for some bank features. 

## References and provenance inside the dataset

Where provided, EdgeSrc lists imagery products and dates used to digitise the feature, including Sentinel-2 composite versions with DOIs, individual scene dates, DEA Intertidal and high-resolution aerial or basemap sources. These citations should be retained when exporting or subsetting the dataset to enable reproducibility and re-evaluation. The primer summarises the preprint by Lawrey and colleagues and associated dataset DOIs for the collections where the classification is applied. 
