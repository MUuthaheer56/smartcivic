# SmartCivic — Road Damage Image Dataset Audit (Stage A)

**Audit Timestamp:** 2026-11-04
**Dataset Source Path:** `C:\Users\Muthaheer\Desktop\main project\code 1\images for ml\Data Y12 Final`

## 1. Candidate Folders Evaluated
| Candidate | Path | Type | Images | Assessment |
|---|---|---|---|---|
| **Candidate 1 (Chosen)** | `images for ml/Data Y12 Final` | YOLO Detection (train/valid) | 1075 | High-quality road damage annotations (Crack, Pothole, Surface Erosion) |
| Candidate 2 | `images for ml/Multi-Weather Pothole Detection (MWPD)/MWPD.zip` | YOLO Detection (Potholes only) | ~3,000 | Multi-weather archive; candidate for Stage C external/augmentation data |
| Candidate 3 | `uploads/issues` | Citizen mobile photos | 144 | Production unlabelled reports (used for real citizen distribution check) |

## 2. File Health & Metadata
- **Total Images Audited:** 1075
- **Corrupt / Unreadable Files:** 0 (All images passed PIL verification)
- **Extensions:** {'.jpg': 1075}
- **Subfolder Breakdown:** Train = 914, Valid = 161
- **File Size (KB):** Min = 25.99 KB, Max = 163.19 KB, Median = 73.06 KB
- **Resolution:** Most common resolution: 640x640 (1075 imgs)
- **EXIF Orientation Issues:** 0 (images are pre-oriented)

## 3. Image Quality Distribution
- **Variance of Laplacian (Blur):** Mean = 1415.87, Median = 1008.82
- **Blurry Images (< 100):** 136 (12.65%)
- **Brightness (Mean Luminance):** Mean = 125.97, Median = 126.05
- **Dark Images (< 50):** 1 (0.09%)
- **Overexposed Images (> 200):** 0 (0.0%)

## 4. Duplicate & Near-Duplicate Analysis
- **Exact Duplicates (SHA-256):** 0 clusters (0 redundant copies)
- **Near-Duplicates (dHash Hamming distance <= 4):** 15 clusters (30 images involved)
- **Largest Near-Duplicate Cluster:** 2 images

## 5. Source, Stems & Group-Aware Partitioning
- **Inferred Groups (Roboflow stems):** 1075 distinct scene stems
- **Mean Images per Group:** 1.0
- **Assessment:** Grouping is **highly reliable** based on original filename prefixes prior to Roboflow `.rf.<hash>` tokens. Crucial for Stage C group-aware splitting to prevent data leakage.

## 6. Label Format & Coverage
- **Format:** YOLO normalized bounding box format (`<class_id> <x_center> <y_center> <width> <height>`)
- **Images with Bounding Boxes:** 1071
- **True Background Images (Empty Label Files):** 4
- **Missing Label Files:** 0

## 7. Label Sanity & Class Imbalance
- **Total Bounding Boxes:** 1846
- **Class Breakdown:**
  - `Crack`: **522 boxes** (28.3%)
  - `Surface Erosion`: **397 boxes** (21.5%)
  - `Pothole`: **927 boxes** (50.2%)
- **Boxes Per Image:** Mean = 1.72, Max = 24
- **Box Size Distribution:**
  - small (<5% image): 689 boxes (37.3%)
  - medium (5-25% image): 574 boxes (31.1%)
  - large (>25% image): 583 boxes (31.6%)
- **Zero-Area Boxes:** 0
- **Out-of-Bounds Boxes:** 0
- **Invalid Class IDs:** 0

## 8. Visual Checks
- Saved 40 annotated bounding box overlays in: `C:\Users\Muthaheer\Desktop\main project\code 1\ml\reports\audit\visual_samples\annotated`
- Saved 40 unlabelled/background verification samples in: `C:\Users\Muthaheer\Desktop\main project\code 1\ml\reports\audit\visual_samples\unlabelled`
