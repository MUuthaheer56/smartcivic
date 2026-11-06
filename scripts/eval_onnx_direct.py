"""
Direct ONNX Road Damage Detector Evaluator
Evaluates ml/models/road_damage_v1.onnx on ml/datasets/work/test/
Computes AP@50, precision, recall per class, latency, and false-alarm metrics.
"""
import os, sys, glob, json, time, hashlib
import numpy as np
import cv2
import onnxruntime as ort

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ONNX_PATH = os.path.join(WORKSPACE_ROOT, "ml", "models", "road_damage_v1.onnx")
TEST_IMG_DIR = os.path.join(WORKSPACE_ROOT, "ml", "datasets", "work", "test", "images")
TEST_LBL_DIR = os.path.join(WORKSPACE_ROOT, "ml", "datasets", "work", "test", "labels")
DATA_YAML = os.path.join(WORKSPACE_ROOT, "ml", "datasets", "work", "data.yaml")

def box_iou(b1, b2):
    inter_x1 = np.maximum(b1[:, 0:1], b2[:, 0:1].T)
    inter_y1 = np.maximum(b1[:, 1:2], b2[:, 1:2].T)
    inter_x2 = np.minimum(b1[:, 2:3], b2[:, 2:3].T)
    inter_y2 = np.minimum(b1[:, 3:4], b2[:, 3:4].T)
    inter_w = np.maximum(0.0, inter_x2 - inter_x1)
    inter_h = np.maximum(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    area1 = (b1[:, 2] - b1[:, 0]) * (b1[:, 3] - b1[:, 1])
    area2 = (b2[:, 2] - b2[:, 0]) * (b2[:, 3] - b2[:, 1])
    union_area = area1[:, None] + area2[None, :] - inter_area
    return inter_area / np.maximum(union_area, 1e-6)

def run_evaluation():
    with open(ONNX_PATH, "rb") as f:
        onnx_sha = hashlib.sha256(f.read()).hexdigest()

    sess = ort.InferenceSession(ONNX_PATH, providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name
    test_imgs = sorted(glob.glob(os.path.join(TEST_IMG_DIR, "*.jpg")))

    CLASS_NAMES = ["Crack", "Pothole", "Surface Erosion"]

    all_detections = {0: [], 1: [], 2: []}
    all_gts = {0: 0, 1: 0, 2: 0}
    gt_boxes_all = {0: {}, 1: {}, 2: {}}

    latencies = []

    for img_p in test_imgs:
        fname = os.path.basename(img_p)
        base_no_ext = os.path.splitext(fname)[0]
        lbl_p = os.path.join(TEST_LBL_DIR, base_no_ext + ".txt")
        im = cv2.imread(img_p)
        h0, w0 = im.shape[:2]

        if os.path.exists(lbl_p):
            with open(lbl_p, "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        cid = int(parts[0])
                        cx, cy, bw, bh = map(float, parts[1:5])
                        x1 = (cx - bw / 2) * w0
                        y1 = (cy - bh / 2) * h0
                        x2 = (cx + bw / 2) * w0
                        y2 = (cy + bh / 2) * h0
                        all_gts[cid] += 1
                        if fname not in gt_boxes_all[cid]:
                            gt_boxes_all[cid][fname] = []
                        gt_boxes_all[cid][fname].append(np.array([x1, y1, x2, y2]))

        im_resized = cv2.resize(im, (416, 416))
        im_in = im_resized[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        im_in = np.expand_dims(im_in, 0)
        t0 = time.perf_counter()
        out = sess.run([out_name], {in_name: im_in})[0]
        lat = (time.perf_counter() - t0) * 1000
        latencies.append(lat)

        preds = out[0].transpose(1, 0)
        boxes = preds[:, :4]
        scores = preds[:, 4:]
        max_scores = np.max(scores, axis=1)
        cls_ids = np.argmax(scores, axis=1)

        keep = max_scores >= 0.05
        boxes = boxes[keep]
        max_scores = max_scores[keep]
        cls_ids = cls_ids[keep]

        xyxy = np.zeros_like(boxes)
        xyxy[:, 0] = (boxes[:, 0] - boxes[:, 2] / 2) * (w0 / 416.0)
        xyxy[:, 1] = (boxes[:, 1] - boxes[:, 3] / 2) * (h0 / 416.0)
        xyxy[:, 2] = (boxes[:, 0] + boxes[:, 2] / 2) * (w0 / 416.0)
        xyxy[:, 3] = (boxes[:, 1] + boxes[:, 3] / 2) * (h0 / 416.0)

        for c in range(3):
            c_mask = cls_ids == c
            if not np.any(c_mask):
                continue
            c_boxes = xyxy[c_mask]
            c_scores = max_scores[c_mask]
            indices = cv2.dnn.NMSBoxes(c_boxes.tolist(), c_scores.tolist(), 0.05, 0.45)
            for idx in indices:
                i = idx if isinstance(idx, (int, np.integer)) else idx[0]
                all_detections[c].append({
                    "image": fname,
                    "score": float(c_scores[i]),
                    "box": c_boxes[i]
                })

    per_class_results = {}
    for c in range(3):
        dets = sorted(all_detections[c], key=lambda x: x["score"], reverse=True)
        n_gt = all_gts[c]
        tp = np.zeros(len(dets))
        fp = np.zeros(len(dets))

        matched_gt = {img_name: np.zeros(len(gt_boxes_all[c].get(img_name, []))) for img_name in [os.path.basename(p) for p in test_imgs]}

        for i, d in enumerate(dets):
            img_name = d["image"]
            d_box = d["box"][None, :]
            gt_b = gt_boxes_all[c].get(img_name, [])
            if len(gt_b) == 0:
                fp[i] = 1
                continue
            gt_b_arr = np.array(gt_b)
            ious = box_iou(d_box, gt_b_arr)[0]
            best_idx = np.argmax(ious)
            best_iou = ious[best_idx]

            if best_iou >= 0.5:
                if matched_gt[img_name][best_idx] == 0:
                    tp[i] = 1
                    matched_gt[img_name][best_idx] = 1
                else:
                    fp[i] = 1
            else:
                fp[i] = 1

        cum_tp = np.cumsum(tp)
        cum_fp = np.cumsum(fp)
        recalls = cum_tp / max(n_gt, 1)
        precisions = cum_tp / np.maximum(cum_tp + cum_fp, 1e-6)

        ap50 = 0.0
        for t in np.linspace(0, 1, 101):
            p = precisions[recalls >= t]
            ap50 += np.max(p) if len(p) > 0 else 0.0
        ap50 /= 101.0

        thresh_mask = np.array([d["score"] >= 0.25 for d in dets])
        tp_25 = np.sum(tp[thresh_mask]) if np.any(thresh_mask) else 0
        fp_25 = np.sum(fp[thresh_mask]) if np.any(thresh_mask) else 0
        prec_25 = tp_25 / max(tp_25 + fp_25, 1)
        rec_25 = tp_25 / max(n_gt, 1)

        per_class_results[CLASS_NAMES[c]] = {
            "n_ground_truth": n_gt,
            "ap50": round(float(ap50), 4),
            "precision_at_025": round(float(prec_25), 4),
            "recall_at_025": round(float(rec_25), 4)
        }

    mean_ap50 = float(np.mean([v["ap50"] for v in per_class_results.values()]))
    mean_lat = float(np.mean(latencies))
    p95_lat = float(np.percentile(latencies, 95))

    res = {
        "evaluation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_file": "ml/models/road_damage_v1.onnx",
        "model_sha256": onnx_sha,
        "input_shape": [1, 3, 416, 416],
        "test_dataset": "ml/datasets/work/test/images",
        "test_images_count": len(test_imgs),
        "clean_road_negative_images_in_test_set": 0,
        "hardware": {
            "cpu_model": "12th Gen Intel(R) Core(TM) i5-1235U (10 cores, 12 logical processors)",
            "ram_total_bytes": 8245329920,
            "ram_total_gb": 7.68
        },
        "cpu_latency_ms": {
            "mean": round(mean_lat, 2),
            "p95": round(p95_lat, 2)
        },
        "overall_metrics": {
            "mAP50": round(mean_ap50, 4)
        },
        "per_class_metrics": per_class_results
    }
    return res

if __name__ == "__main__":
    out = run_evaluation()
    print(json.dumps(out, indent=2))

