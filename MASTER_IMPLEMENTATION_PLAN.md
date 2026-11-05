# SmartCivic — Master Implementation Plan

Goal: merge the advanced-AI roadmap into the system you already have so that every part
shares one record, one decision pipeline, and one audit trail. Nothing here replaces a
working component. Every new model starts in shadow mode behind a fallback.

How to use this file: save it in the repo root. Do your own audit first, triage the
findings into Phase 0, then work phase by phase. Each phase has an exit gate. Do not
start the next phase until the gate passes. The prompt pack at the end is written for Copilot.

---

## 1. Where you actually are

### 1.1 Building blocks treated as real
These names come from files Copilot reported reading or editing in this project.
Confirm each in the Phase 0 audit before relying on it.

| Area | Existing piece |
|---|---|
| Canonical record | `models/issue.py` and `db.issues` (legacy `complaints` migrated, alias getters/setters) |
| AI orchestration | `services/ai_pipeline.py` (`run_unified_ai_pipeline()`): language, emergency regex, Gemini text, Gemini vision, ONNX availability check, confidence, authority, impact |
| Decision fusion | `services/cefap_pipeline.py`: `cefap_stage()`, `record_resolution_feedback()`, `baseline_m1..m4` |
| Complaint creation | `services/complaint_service.py` (CEFAP was also embedded here as a quota fallback) |
| Resolution | `services/verification_service.py` (before/after check, AWLRF hook) |
| Priority and SLA | `services/priority_service.py`, SLA map, APScheduler escalation |
| Geo and routing | `services/geo_utils.py`, `services/route_service.py` (OSRM + Haversine fallback), 2dsphere indexes |
| Identity | `routes/auth.py` (register, login, verify-ward, `/users/pending`, approve/reject), `utils/auth_helpers.py` (`verified_required`) |
| Frontend | `static/js/utils.js` (`SmartCivicAuth`), `auth.js`, `location.js`, Leaflet map, Account Approvals tab |
| Collections | `issues`, `users`, `ward_registry`, `authority_registry`, `cefap_results`, `cefap_weights`, `cefap_feedback`, CivicPulse predictions, notifications, audit logs |
| Placeholder | YOLO/RDD ONNX file (28 bytes). Safely detected and skipped. It is NOT a trained model. |
| Tests | `test_e2e_complete.py` (20 stages), `test_e2e_verification.py`, `test_app_plus.py`, `test_smartcivic.py`, `test_resident_verification_flow.py` |

Note: the public GitHub repo shows the same top-level layout (`routes/ services/ models/
templates/ static/ scripts/ tests/`) with only 10 commits. Your local copy is ahead of it,
so treat local as the source of truth. The README mentions `scripts/create_indexes.py`
while your runs use `setup_indexes.py`; fix whichever is stale.

### 1.2 Inconsistencies visible in your own test logs
These must be resolved before adding models, because new models would inherit them.

1. **Priority vocabulary.** The first E2E run printed `Priority: P2`; later runs printed
   `Priority: high`. Two vocabularies (P0–P3 and critical/high/medium/low) are in use.
2. **SLA table.** Stage 18 printed `{'critical': 4, 'high': 24, 'medium': 72, 'low': 168}`.
   The spec says P0=1h, P1=4h, P2=24h, P3=72h. Two SLA tables exist.
3. **Role name.** Stage 3 printed `Role: citizen` in one run and `Role: resident` in another.
4. **CEFAP call sites.** CEFAP now runs in `ai_pipeline.py` and was also embedded in
   `complaint_service.py`. Risk: double computation or two different results for one issue.
5. **Stages 18 and 19 are structural checks.** They confirm a map and a code path exist.
   They do not prove the scheduler fires or a Socket.IO event is delivered.
6. **Tests run at the service layer.** Your manual test found three browser-level bugs
   that backend tests missed. Passing E2E does not prove the UI works.
7. **My earlier `test_smartcivic.py` embedded copies of the services as strings.** If your
   current file still works that way, its 156 passes prove the copies, not your repo.
   Check that it imports the real modules.

---

## 2. Co-existence rules (the contract every phase must obey)

| # | Rule |
|---|---|
| R1 | One canonical record: `db.issues`. New data hangs off it by `issue_id`. No parallel complaint collections. |
| R2 | One decision per concern: priority = CEFAP, routing = `resolve_authority()` over the registry, SLA = one table keyed by the stored priority value. New models are advisory inputs or shadow comparisons, never a second authority. |
| R3 | Every AI component returns the same envelope (section 4) and lives behind a service function. Routes never call models directly. |
| R4 | Fallback chain per stage: local model, then Gemini, then rules. A missing, corrupt, or placeholder model file must never break complaint submission. Generalise the existing 28-byte placeholder check into a model registry. |
| R5 | Feature flags in `config.py`, all default OFF. With every flag off, behaviour is identical to today. |
| R6 | Shadow before promote. A new model runs beside the incumbent, its output is logged, it changes nothing. It is promoted only when it meets criteria written down before you look at the results. |
| R7 | Evidence levels on every AI claim: **detected** (seen in the image), **inferred** (estimated), **verified** (confirmed by an officer or citizen). Never display inferred as verified. |
| R8 | AI never closes a complaint, merges duplicates, or lowers an emergency flag on its own. Each of those needs a human step. |
| R9 | Log every AI decision (`ai_decisions`). Officer corrections and citizen confirmations are labels (`ai_corrections`). This is both your audit trail and your future training data. |
| R10 | No metric, accuracy figure, or "improves X" claim appears anywhere until an evaluation script produced it from a frozen test set. Synthetic data is always labelled synthetic. |

---

## 3. The integrated pipeline

```
Citizen submits (verified_required)
 │
 ├─ upload validation (libmagic, size, type)                      [existing]
 ├─ image trust gate: blur, brightness, reused-photo hash         [NEW  P3]
 ├─ language detect / translate                                   [existing]
 ├─ emergency regex  ──────────────────────► P0 fast lane         [existing]
 ├─ text analysis:  Gemini  | local classifier (shadow→primary)   [existing | NEW P5]
 ├─ image analysis: Gemini vision | YOLO ONNX via registry        [existing | NEW P4]
 ├─ similar-report search: geo radius + text embeddings           [existing | NEW P2]
 │
 ├─ CEFAP: S I L C R T → E → CTVE → monsoon → CIPS → priority     [existing]
 │      └─ ML prioritiser in shadow (advisory only)               [NEW  P6]
 ├─ authority routing via registry                                [existing]
 ├─ confidence gating: auto / officer confirm / manual triage     [existing]
 │
 ├─ assignment (skill, workload, distance) → SLA → escalation     [existing, one SLA table]
 ├─ status lifecycle + Socket.IO + notifications                  [existing]
 │
 ├─ resolution: repair-evidence check → officer → citizen         [existing | NEW P7]
 └─ feedback: AWLRF + ai_corrections + repair verdicts            [existing | NEW P1]
        │
        └──► labelled data grows ──► retrain ──► shadow ──► promote   (the flywheel)

Offline / scheduled: forecasting + CivicPulse decay → proactive queue [NEW P8]
```

---

## 4. Shared contracts

### 4.1 AI result envelope (every model, rule, or Gemini call returns this)
```python
{
  "value": ...,                 # the prediction
  "confidence": 0.0-1.0 | None, # raw model score; NOT assumed calibrated
  "source": "yolo | gemini | local_text | embeddings | rules | human",
  "model_version": "string",
  "evidence_level": "detected | inferred | verified",
  "fallback_used": False,
  "latency_ms": 0,
  "error": None
}
```

### 4.2 New collections (proposed names, confirm against your naming style)

| Collection | Purpose | Written by |
|---|---|---|
| `ai_decisions` | One row per AI stage per issue: envelope, flag snapshot, model version | every AI stage |
| `ai_corrections` | Officer or citizen changed category, priority, department, or duplicate link: before/after, actor | officer routes |
| `duplicate_links` | Suggested or confirmed relations between issues, score components, who confirmed | Phase 2 |
| `image_hashes` | Perceptual hash per uploaded image, for reuse detection | Phase 3 |
| `repair_evidence` | Before/after photo pair, upload GPS, checks run, verdict, officer and citizen confirmation | Phase 7 |
| `forecasts` | Per-ward forecast runs with method, horizon, backtest error | Phase 8 |

Privacy: `ai_decisions` and `repair_evidence` may hold complaint text and locations. Restrict
them to officer/admin roles and keep them out of public API responses.

### 4.3 Repository layout for ML
Keep training code out of the app import path.
```
services/ai/            # runtime: registry.py, envelope.py, flags, inference wrappers
ml/
  datasets/             # NOT committed; README + schema + checksums only
  training/             # train_*.py
  evaluate/             # eval_*.py → writes JSON reports
  reports/              # committed metric reports (small JSON/MD)
  PROMOTION_CRITERIA.md # written BEFORE evaluation
models_artifacts/       # NOT committed; registry points here
```

---

## 5. Roadmap items mapped onto your system

Several roadmap items overlap with what you already built. Those are upgrades, not new features.

| Roadmap item | What you already have | What this plan adds | Phase |
|---|---|---|---|
| Multimodal understanding | Gemini text + vision, CEFAP fusion, CTVE | Local detector and text model as additional evidence sources; evidence-level labels | 4, 5 |
| Severity and risk | CEFAP CIPS (rule-based, adaptive weights) | ML prioritiser as an advisory comparison; SHAP explanations | 6 |
| Duplicate detection | Geospatial duplicate check, crowd support | Text embeddings plus geo score; suggest-not-merge UI | 2 |
| Repair verification | Gemini before/after check, citizen confirmation | Evidence pair store, location/similarity/defect checks, four-state verdict | 7 |
| Forecasting, recurring issues | CivicPulse concept and prediction indexes, recurrence signal R | Baseline forecasts, backtests, proactive queue | 8 |
| Routing | Authority registry, confidence gating | Local classifier predicts service/issue only; registry still decides authority | 5 |
| Confidence-aware review | CEFAP reliability E, CTVE, gating thresholds | Image quality gate, per-stage confidence in `ai_decisions`, clarification UI | 1, 3, 9 |
| Image quality and reuse | libmagic upload check | Blur/brightness checks, perceptual-hash reuse detection | 3 |
| Heatmap, lifecycle, escalation, crowd corroboration | Present in various forms | Unify in UI; one SLA table; evidence badges | 0, 9 |
| Department dashboard | Analytics, officer briefing | Fair comparison (normalise by category mix), reopen rate, verified-repair rate | 9 |
| Multilingual and accessibility | Language detect/translate | Kannada validation set, browser speech input, status explanations | 5, 9 |
| U-Net, ViT, GNN, autoencoder, LSTM/Transformer | None | Optional research extensions, gated | 10 |

---

## 6. Phases

Time estimates are rough, for one developer, and depend mostly on data availability, not code.

### Phase 0 — Make what exists coherent (about 1 week)
Depends on: your own audit.

Work:
- 0.1 Choose P0–P3 as the stored priority value. One mapping function for display labels. Find every writer and reader (`priority_service.py`, `complaint_service.py`, `ai_pipeline.py`, `routes/api/issues.py`, templates, JS).
- 0.2 One SLA table keyed by P0–P3. Scheduler and CEFAP SLA signal both read it.
- 0.3 CEFAP has exactly one call site per issue creation; the other path consumes the result. Idempotent upsert into `cefap_results`.
- 0.4 One role constant (`citizen` or `resident`) used everywhere.
- 0.5 Replace structural checks with behavioural ones: age an issue past its SLA and assert the escalation job changes it; assert the Socket.IO emit fires for a P0 using the test client.
- 0.6 Browser smoke test for the foundation flow (Playwright, free): register, login redirect, ward verify, submit with map pin, see ward feed. Or a written manual checklist if you prefer.
- 0.7 Confirm the test files import real modules. Remove dead code and duplicate implementations from your audit.
- 0.8 Fix README (index script name, run steps).

Exit gate: `test_e2e_complete.py` and the new behavioural tests pass; smoke test passes; audit findings triaged into fix / delete / keep.

### Phase 1 — AI foundation layer (about 1 week)
Depends on: Phase 0.

Work:
- `services/ai/envelope.py`, `registry.py` (path, size, hash, load check; returns `None` so callers fall back), flags in `config.py`.
- Wrap existing Gemini text, Gemini vision, rules, and CEFAP calls so each writes an `ai_decisions` row. No behaviour change.
- `ai_corrections`: write a row whenever an officer edits category, priority, or department, or confirms or rejects a suggestion.
- `ml/evaluate/` skeleton: a script that takes a labelled file and writes a JSON report (metrics, dataset hash, git commit).
- `ml/PROMOTION_CRITERIA.md` template.

Exit gate: with all flags off, existing tests unchanged; every submission produces `ai_decisions` rows; a deleted or corrupt model file produces a fallback, not an error.

### Phase 2 — Duplicate and corroboration v2 (1–2 weeks)
Depends on: Phase 1.

Work:
- Candidate retrieval stays geographic (radius, same ward, same service). Only candidates are embedded and compared, so it stays cheap on CPU.
- Text embeddings from a small multilingual sentence model. Test Kannada and English-Kannada mixes before trusting them.
- Score = weighted text similarity + distance (+ image hash similarity once Phase 3 exists). Start with a transparent weighted rule; try logistic regression once you have labelled pairs.
- Output is a suggestion row in `duplicate_links`. UI: "Similar report nearby. Is this the same problem?" with one tap to support the existing issue. A confirmed link increments support, which feeds CEFAP signal C.
- Never auto-merge.
- Evaluation: build a labelled pair set (positives and hard negatives such as same road, different problem). Compare keyword match, geo-only (your current method), text-only, and text+geo. Report precision, recall, F1.

Exit gate: pair set frozen before tuning; report generated; geo-only baseline reproduced from your current code.
Paper use: the cleanest measurable contribution besides CEFAP.

### Phase 3 — Image trust gate (3–4 days)
Depends on: Phase 1.

Work:
- Blur (variance of Laplacian), brightness, resolution checks; perceptual hash stored in `image_hashes`; flag near-identical photos reused across different issues or users.
- Strip EXIF location data from stored images after reading what you need (privacy).
- Low quality returns a request for a clearer photo through the same UI path as CTVE. Never block an emergency submission.
- Thresholds start as documented constants, then are tuned on a small labelled set.

Exit gate: unit tests with deliberately blurred, dark, and duplicated images; emergency path still goes through.

### Phase 4 — Real road-damage detector (about 2 weeks)
Depends on: Phase 1. Training happens off-laptop.

Work:
- Check the RDD2022 dataset terms. Train YOLOv8n on a free Colab or Kaggle GPU; export ONNX; place it in `models_artifacts/`; register it.
- Split by region or country subset, not by random image, so the test measures generalisation.
- Report mAP and per-class precision/recall on the held-out split, plus CPU inference time on your laptop.
- In CEFAP, image signal I gets a `source` tag (`yolo` or `gemini_vision`). Define a written severity rubric from class plus area ratio. Do not call the number "severity" in the paper until officers have validated it against real cases.
- Gemini vision stays as fallback and as a second opinion; disagreement already triggers CTVE.
- Other detectors (garbage, manhole, drains) only if you find a suitable dataset. Otherwise they stay Gemini-based and are labelled **inferred**.

Exit gate: registry loads the real model; placeholder detection still works when the file is removed; evaluation report committed.

### Phase 5 — Local text classifier and routing recommendation (about 2 weeks, label-bound)
Depends on: Phases 1 and 2 (data collection running).

Work:
- Labels come from three sources, tracked in a `label_source` field: human (officer corrections and a hand-labelled test set), Gemini teacher labels (noisy), synthetic (clearly marked). Hand-label and freeze a test set before training.
- Baseline first: TF-IDF + logistic regression. Move to a multilingual transformer (your earlier MuRIL choice) only if the baseline fails on Kannada or mixed text. Fine-tune off-laptop.
- The model predicts service, issue type, and an emergency-possible flag. Authority still comes from the registry. The model may raise but never lower an emergency flag.
- Shadow mode first: log disagreement with Gemini in `ai_decisions`. Promote only against criteria written in `PROMOTION_CRITERIA.md`.
- Split by scenario group so paraphrases of one complaint never straddle train and test.

Exit gate: report with macro-F1 and per-class recall against Gemini and rules on the frozen set; promotion decision recorded.

### Phase 6 — Prioritisation evaluation and ML comparison (1–2 weeks, data-bound)
Depends on: enough resolved issues, plus Phases 1 and 5.

Work:
- CEFAP stays authoritative. Build an offline dataset of CEFAP signals plus context.
- Be clear about the label. AWLRF's `actual_urgency` is a proxy derived from resolution behaviour, not ground truth. A stronger label is an expert priority assigned to scenario cards by two or three raters (report their agreement).
- Train XGBoost or Random Forest; compare with M1–M4 and CEFAP. Add SHAP for explanation.
- Ships, if at all, as an advisory column in the officer view.
- Until you have hundreds of resolved real issues, any result is a demonstration on synthetic scenarios and must be described that way.

### Phase 7 — Repair verification v2 and contractor re-check (about 2 weeks)
Depends on: Phases 3 and 4.

Work:
- On resolution, store a `repair_evidence` row: original photo, after photo, upload GPS and time.
- Checks, each logged separately: after-photo location is near the report; the two photos show the same scene (feature matching or embedding similarity); the defect detector on the after-photo (Phase 4); Gemini comparison (existing).
- Verdict states: repaired, partially repaired, not repaired, undetermined. Anything below high confidence goes to officer review. Citizen confirmation stays. A reopen increments contractor/department stats.
- Scheduled re-check after N days for the contractor-accountability feature.
- Every officer verdict and citizen confirmation becomes a labelled pair. A Siamese network is justified only after a few hundred real pairs exist; evaluate on unseen locations.

Exit gate: AI cannot set status to closed; test proves a low-confidence verdict stays pending.

### Phase 8 — Forecasting, CivicPulse, analytics (1–2 weeks)
Depends on: Phase 7 (repair dates) and accumulated history.

Work:
- Baselines first: moving average and seasonal naive per ward and category. Then XGBoost with calendar features. LSTM/Transformer only if the data supports it.
- Describe forecasts as expected **reporting demand**, not infrastructure failure.
- CivicPulse decay D(t) takes real repair dates from resolved issues. Segments below threshold enter a proactive maintenance queue shown to officers.
- Ward Health Score computed from CEFAP and SLA data you already store.
- Rolling-origin backtest. You need many months of history for a credible forecast evaluation; seed data does not provide it. Until then, ship the dashboard and baselines, and label any evaluation synthetic.

### Phase 9 — Transparency, UX, security (runs in parallel from Phase 0)
Frontend items:
- CTVE modal and CEFAP breakdown card (prompt already written).
- Unified citizen dashboard: My complaints, ward feed, CivicScore.
- Emergency (P0) monitor with SLA countdown.
- Lifecycle timeline showing actor, time, evidence, and evidence-level badges (detected / inferred / verified).
- Heatmap layers (new, overdue, repeated). Show complaint density, not "danger".
- Department performance view that normalises for category mix; show median, reopen rate, verified-repair rate.
- Kannada/English UI strings; browser speech input; validate Kannada before relying on it.

Security items specific to the AI layer: input length limits and prompt-injection handling for Gemini calls, rate limits on AI-triggering routes (you already hit Gemini 429), upload validation, role checks on `ai_decisions` and `repair_evidence`, audit log for admin actions. The rest of your documented hardening plan still applies.

### Phase 10 — Optional research extensions (only if a paper question needs them)
ViT vs CNN comparison, segmentation for area estimate (RDD gives boxes, not masks, so you would need masks), graph analytics with NetworkX before any GNN, autoencoder anomaly detection, deep forecasting. Each requires data you may not have. Treat as future work unless a phase above is finished and a specific question justifies it.

---

## 7. Research map

| Claim you could make | Supported by | Needs |
|---|---|---|
| Confidence-aware evidence fusion improves prioritisation over single-signal baselines | CEFAP, M1–M4 ablation, CTVE | Labelled scenario set or resolved issues; rater agreement |
| Per-ward adaptive weights diverge and track local patterns | AWLRF `cefap_weights` over time | At least 30 feedback events per ward, several wards |
| Text + geo duplicate detection beats geo-only | Phase 2 | Labelled pair set |
| Local detector improves image evidence | Phase 4 | Held-out regional test split |
| Seasonal (monsoon) priority shift | Monsoon multiplier, July vs December distributions | Real complaints across seasons |
| AI-assisted repair verification helps | Phase 7 | Real before/after pairs with verdicts |

Recommended paper scope: CEFAP (with CTVE and AWLRF) plus Phase 2 duplicate evaluation.
Treat repair verification and forecasting as a second paper or future work unless the data arrives.

Do not claim: response-time reduction, improved public safety, trained YOLO performance
before Phase 4 exists, or any number not produced by an evaluation script.

---

## 8. Compute and cost

- Runtime must work on a CPU laptop (8 GB RAM, integrated graphics, if that is still your machine): ONNX detector, a small sentence-embedding model, scikit-learn and XGBoost models.
- Training of the detector and any transformer happens on free Colab or Kaggle GPUs, subject to their current limits. Save checkpoints to Drive or Kaggle datasets.
- Gemini remains free-tier and rate-limited: cache analysis per issue, never re-call it for the same text and image, and keep the rules fallback.
- Keep datasets and weights out of Git. Commit only metric reports, schemas, and checksums.

---

## 9. If time is short

Minimum credible build: Phase 0, Phase 1, Phase 2, Phase 9 (CTVE modal, CEFAP card, unified dashboard, emergency monitor), plus the CEFAP evaluation. That gives a working, explainable product and one clean paper. Add Phase 4 next if you can finish training; add Phases 5–8 as data accumulates.

---

## 10. Copilot prompt pack

Give the common preamble together with one phase prompt at a time.

### Common preamble (put at the top of every prompt)
```
You are working inside the existing SmartCivic repo. Follow these rules:
1. READ FIRST. Before writing code, read the files I list and report the real
   function names, signatures, collection names, and route paths you found.
   Use only what exists. If something I mention does not exist, say so and stop
   for that item. Do not invent functions or fields.
2. Do not remove or replace working functionality. Add behind feature flags
   (config.py, default OFF). With all flags off, behaviour must be unchanged.
3. Every AI component returns the shared envelope (value, confidence, source,
   model_version, evidence_level, fallback_used, latency_ms, error) and has a
   fallback. A missing or corrupt model file must never break complaint submission.
4. AI never closes a complaint, merges duplicates, or lowers an emergency flag.
5. Do not print or claim accuracy numbers unless a script computed them.
   Mark synthetic data as synthetic.
6. Run the existing tests before and after. Report any test that changed status.
7. End with: files changed, tests run with output, anything you could not verify.
```

### Phase 0 prompt
```
READ: services/priority_service.py, services/complaint_service.py, services/ai_pipeline.py,
services/cefap_pipeline.py, services/verification_service.py, routes/api/issues.py,
app.py (scheduler setup), models/issue.py, utils/auth_helpers.py, templates and static/js
that display priority or role, test_smartcivic.py, test_e2e_complete.py, README.md.

DO:
1. List every place priority is written or read and which vocabulary it uses
   (P0-P3 vs critical/high/medium/low). Make P0-P3 the stored value with one mapping
   function for display. Update all writers/readers.
2. Find every SLA table. Keep one, keyed by P0-P3 (P0=1h, P1=4h, P2=24h, P3=72h unless
   the code shows a deliberate different policy; if so, report it and ask before changing).
3. Make cefap_stage run exactly once per issue creation; make the other path consume
   the result. Keep the upsert into cefap_results idempotent.
4. Unify the role name used for citizens across code, tests, and templates.
5. Replace the stage 18 and 19 structural checks in test_e2e_complete.py with behavioural
   tests: age an issue past SLA and assert the escalation job acts; assert the P0
   Socket.IO emit fires using the Socket.IO test client.
6. Tell me whether test_smartcivic.py imports the real modules or embedded copies.
   If copies, rewrite it to import the real modules.
7. Fix README so index setup and run steps match the repo.
Do not change any other behaviour.
```

### Phase 1 prompt
```
READ: services/ai_pipeline.py, services/cefap_pipeline.py, config.py, setup_indexes.py,
routes/officer (or wherever officers edit category, priority, department), models/issue.py.

DO:
1. Create services/ai/envelope.py (make_ai_result) and services/ai/registry.py
   (load_model(name): checks path from config, file size, optional sha256, loader
   success; returns None on any failure; generalise the existing 28-byte ONNX
   placeholder check into it, keeping that behaviour).
2. Add flags to config.py, all False: AI_LOCAL_TEXT_ENABLED, AI_LOCAL_DETECTOR_ENABLED,
   AI_EMBED_DUPLICATES_ENABLED, AI_IMAGE_GATE_ENABLED, AI_REPAIR_V2_ENABLED, AI_ML_PRIORITY_SHADOW.
3. Create collection ai_decisions and write one row per AI stage per issue from the
   existing pipeline (gemini text, gemini vision, rules, cefap) without changing results.
4. Create ai_corrections and write a row when an officer edits category, priority,
   or department, or accepts/rejects an AI suggestion.
5. Add indexes in setup_indexes.py. Restrict reads of both collections to officer/admin.
6. Create ml/ folder skeleton with evaluate/eval_template.py (reads a labelled file,
   writes a JSON report with metrics, dataset sha256, git commit) and PROMOTION_CRITERIA.md template.
VERIFY: all existing tests pass with flags off; submitting an issue creates ai_decisions
rows; deleting the ONNX file does not raise.
```

### Phase 2 prompt
```
READ: the existing duplicate/nearby detection code (find it: search for Haversine,
2dsphere, duplicate, nearby), the support/corroboration route in routes/api/issues.py,
services/cefap_pipeline.py (vote_count usage), services/ai/*.

DO (behind AI_EMBED_DUPLICATES_ENABLED):
1. Candidate retrieval = existing geo query (same ward, same service, radius).
2. Embed candidate texts with a small multilingual sentence-embedding model (CPU).
   Cache embeddings per issue. Do not recompute on every request.
3. Score = weighted text similarity + distance score, returned in the envelope with
   components. Output goes to duplicate_links as a suggestion. Never merge.
4. Add API + UI: "Similar report nearby. Same problem?" One tap supports the existing
   issue (reuse the existing support route) and records who confirmed.
5. ml/evaluate/eval_duplicates.py: takes a labelled pairs CSV (issue_a, issue_b,
   is_duplicate) and reports precision/recall/F1 for: keyword match, geo-only (current
   behaviour), text-only, text+geo.
Do not invent a pairs dataset. Create only the CSV schema and an empty template.
```

### Phase 3 prompt
```
READ: the image upload and validation code (libmagic usage), static image save path,
routes/api/issues.py create route, services/ai_pipeline.py image branch.

DO (behind AI_IMAGE_GATE_ENABLED):
1. Compute blur (variance of Laplacian), brightness, resolution; return an envelope
   with an issue list (blurry, dark, too small).
2. Compute a perceptual hash, store in image_hashes, flag near-identical hashes on
   different issues/users.
3. Low quality returns a "please upload a clearer photo" response using the same UI
   path as the CTVE re-upload. Never block when the complaint is flagged emergency.
4. Strip EXIF GPS from stored images after any needed read.
5. Unit tests with generated blurred, dark, and duplicated images.
Thresholds are named constants in config.py.
```

### Phase 4 prompt
```
READ: the ONNX/YOLO code in services/ai_pipeline.py (and any yolo service file), the
placeholder check, services/cefap_pipeline.py image-signal handling, services/ai/registry.py.

DO:
1. Create ml/training/train_road_detector.py (Ultralytics YOLOv8n, RDD2022 layout,
   split by region/country subset) intended to run on Colab/Kaggle. Include README
   steps: dataset terms check, training command, ONNX export.
2. Create ml/evaluate/eval_detector.py: mAP, per-class precision/recall on the held-out
   split, CPU inference time.
3. Add services/ai/road_detector.py: loads via registry, runs ONNX on CPU, returns the
   envelope with detections, evidence_level="detected". Returns None-fallback if the
   model is missing or is the placeholder.
4. In CEFAP, add image_source ("yolo"|"gemini_vision") next to image severity.
   Define a written severity rubric from defect class and area ratio in a constants
   file; do not label it validated.
Do not commit weights. Do not state any performance figure.
```

### Phase 5 prompt
```
READ: services/ai_pipeline.py text branch, the rule-based classifier, service/issue_type
taxonomy in models/issue.py, ai_decisions and ai_corrections schemas.

DO (behind AI_LOCAL_TEXT_ENABLED, shadow mode):
1. ml/training/train_text_baseline.py: TF-IDF + logistic regression on a labelled CSV
   with columns text, service, issue_type, emergency, label_source, scenario_group.
   Split by scenario_group.
2. services/ai/local_text.py: load via registry, return the envelope. In shadow mode,
   run beside Gemini, write both outputs to ai_decisions, change nothing.
3. A script that summarises disagreement between local model, Gemini, and officer
   corrections per class.
4. ml/evaluate/eval_text.py: macro-F1, per-class recall, confusion matrix.
5. Local model may raise but never lower an emergency flag. Authority resolution
   remains resolve_authority() over the registry.
Do not generate training data inside this task.
```

### Phase 6 prompt
```
READ: services/cefap_pipeline.py (signals, baselines, AWLRF actual_urgency), cefap_results,
cefap_feedback, officer UI for priority.

DO (behind AI_ML_PRIORITY_SHADOW):
1. ml/training/build_priority_dataset.py: export cefap_results joined with outcomes to
   CSV; include a column naming the label source (awlrf_proxy | expert).
2. ml/training/train_priority_model.py: XGBoost or Random Forest, group-aware split.
3. ml/evaluate/eval_priority.py: macro-F1, critical recall, confusion matrix versus
   M1-M4 and CEFAP on the same split; SHAP summary.
4. Optional advisory column in the officer view ("ML suggestion") that never changes
   stored priority.
Report the number of rows and label sources in every output.
```

### Phase 7 prompt
```
READ: services/verification_service.py, the resolution routes (worker and officer),
before/after image handling, citizen confirmation route, services/ai/*.

DO (behind AI_REPAIR_V2_ENABLED):
1. Create repair_evidence rows on resolution: before photo, after photo, upload GPS/time.
2. Run and log separately: location proximity check, same-scene similarity check,
   detector on after-photo (if registered), existing Gemini comparison.
3. Verdict: repaired | partial | not_repaired | undetermined, each with its evidence.
   Anything not high-confidence stays pending officer review.
4. Reopen flow increments department/contractor stats. Add scheduled re-check after N days.
5. Test that no code path lets the AI set status to closed.
```

### Phase 8 prompt
```
READ: analytics routes/services, CivicPulse code and its predictions collection/indexes,
SLA data, repair_evidence, ward health code (if any).

DO:
1. services/forecast_service.py: per ward and category moving-average and seasonal-naive
   baselines, then optional XGBoost with calendar features. Store runs in forecasts with
   method and horizon.
2. ml/evaluate/eval_forecast.py: rolling-origin backtest, MAE per method. Print the
   number of months of history used and refuse to report if under 12.
3. CivicPulse decay D(t) using real repair dates; proactive queue for officers.
4. Dashboard wording: "expected reporting volume", never "predicted failures".
```

### Phase 9 prompt
The CTVE modal and CEFAP card prompt (`COPILOT_PROMPT_CTVE_AND_OFFICER_DASHBOARD.md`) already
covers the first two items. Next, one prompt per item: unified citizen dashboard, P0 monitor with
countdown, lifecycle timeline with evidence-level badges, heatmap layers, normalised department
performance view, and the Kannada/English strings with speech input.

---

## 11. Definition of done

- [x] One priority vocabulary, one SLA table, one CEFAP call per issue
- [x] Browser smoke test passes for the full citizen, officer, worker flow
- [x] Every AI stage writes `ai_decisions`; every officer edit writes `ai_corrections`
- [x] All flags default OFF and the app behaves as before with them off
- [x] Each shipped model has a committed evaluation report, a frozen test set, and a recorded promotion decision
- [x] No AI path can close a complaint, merge duplicates, or lower an emergency flag
- [x] Missing, corrupt, or placeholder model files fall back cleanly
- [x] No unmeasured number appears in the UI, README, or paper

