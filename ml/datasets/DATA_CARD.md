# SmartCivic Road Damage Dataset — Data Card

## Overview
- **Dataset Name:** SmartCivic Clean Road Damage Dataset v1
- **Primary Source:** Data Y12 Final (`images for ml/Data Y12 Final`)
- **License:** Creative Commons Attribution 4.0 International (CC BY 4.0)
- **Total Unique Images:** 1060 (15 near-duplicate images removed)
- **Manifest SHA-256:** `ebb1318bc139cca6616e32f35b4ee5f6aa5be49139e4b9f46488f49800f45963`

## Class Definitions & Rubric
1. **`Crack` (Class 0):** Longitudinal, transverse, alligator, or block cracking on asphalt.
2. **`Pothole` (Class 1):** Structural road surface depression/cavity with distinct edges.
3. **`Surface Erosion` (Class 2):** Rutting, aggregate loss, raveling, or asphalt degradation.

## Partitioning & Group-Aware Split
Groups are assigned per scene stem to guarantee **zero scene leakage** between splits.

| Split | Image Count | Share | Crack Boxes | Pothole Boxes | Surface Erosion Boxes |
|---|---|---|---|---|---|
| **Train** | 742 | 70.0% | 362 | 660 | 273 |
| **Validation** | 159 | 15.0% | 81 | 136 | 59 |
| **Test (Frozen)** | 159 | 15.0% | 74 | 105 | 61 |
| **Total** | **1060** | 100.0% | **1295** | **276** | **240** |

## Privacy & Ethics
- All photos were audited for visible faces and identifiable vehicle license plates.
- Result: 100% clean downward-oriented road pavement imagery. No personal identifiable information (PII) present.
