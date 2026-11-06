# SmartCivic Data Sheet

## Datasets Overview
SmartCivic uses curated and structured civic datasets for multi-modal complaint classification, road surface defect detection, geographic prioritization, and automated audit logging.

### 1. Road Damage Dataset (RDD2022 / Roboflow Derivative)
- **Modality:** RGB Road Surface Imagery (416x416).
- **Splits:**
  - Train: 1,817 images
  - Validation: 159 images
  - Test (Frozen): 159 images (`ml/datasets/work/test/images/`)
- **Annotation Format:** YOLO bounding boxes (`[class_id, x_center, y_center, width, height]`).
- **Classes:** `Crack` (0), `Pothole` (1), `Surface Erosion` (2).
- **License:** Creative Commons Attribution 4.0 International (CC BY 4.0).
- **Data Provenance:** RDD2022 Crowdsourced road image challenge with localized augmentation for Indian municipal road conditions.

### 2. Multi-Lingual Civic Complaint Benchmark (Bengaluru)
- **Modality:** Natural Language Civic Complaints.
- **Size:** 66 carefully structured municipal problem scenarios.
- **Languages:** English, Kannada (ಕನ್ನಡ), Hinglish / Vernacular colloquialisms.
- **Categories:** Road repair, water supply leakage, sanitation / solid waste accumulation, drainage flooding, and electrical streetlight failure.
- **Emergency Holdout:** 20 verified high-urgency vs. non-emergency cases (chlorine leak, live sparking cable, toddler in open drain, severe vehicular accident, cylinder explosion).

### 3. Bengaluru Municipal Administrative Boundaries
- **Wards:** 27 verified Bruhat Bengaluru Mahanagara Palike (BBMP) wards with GeoJSON polygon boundaries.
- **Coordinate System:** WGS 84 (`EPSG:4326`), GeoJSON standard lon-lat order.
- **Location Fuzzing:** Citizen-facing endpoints automatically fuzz raw coordinates to ~100m radii (`fuzzed: True`) to protect reporter residency privacy.

## Data Ethics and Privacy Compliance
- **No Personally Identifiable Information (PII):** Test datasets and synthetic benchmark files contain zero real resident contact numbers or physical addresses.
- **Upload Hardening:** Uploaded images have all EXIF metadata (including hardware serials and exact GPS timestamps) stripped upon ingestion prior to secure disk persistence.

