# FIX REPORT: Phase 5 — Data Integrity, Indexing, and Concurrency Hardening

**Branch**: `fix/phase-5`  
**Date**: November 5, 2026  
**Status**: COMPLETE & VERIFIED  

---

## 1. Executive Summary

Phase 5 remediation targeted systemic database fragmentation, unindexed in-memory sorts, destructive backup/restore routines, race conditions in community confirmation and worker assignment, and cascading SLA escalation glitches identified in `AUDIT_05B_DATABASE.md` and `AUDIT_05C_FLOWS.md`.

All database operations have been verified against the canonical collection `db.issues` (with legacy documents from `db.complaints` safely synchronized). Compound indexing (`ward` + `created_at DESC`) was added to `setup_indexes.py`, and `explain()` plans were verified to eliminate in-memory sorting. `scripts/backup_db.py` and the newly added `restore_db.py` now automatically invoke `setup_indexes.create_indexes()` upon restoration, ensuring index preservation across backups. Concurrency race conditions in `add_community_confirmation` and `assign_worker` were remediated using atomic MongoDB conditional updates, and SLA escalation spacing was enforced to prevent rapid cascading promotions across cron cycles.

---

## 2. Issues Remediated

| Vulnerability ID | Component | Defect | Resolution Applied | Verification |
| :--- | :--- | :--- | :--- | :--- |
| **FLOW-14** | Architecture / DB | Dual collection split (`db.complaints` vs canonical `db.issues`). | Verified that active application routes and services strictly use `db.issues`. Ran `scripts/migrate_canonical_issues.py` to copy remaining legacy complaints into canonical `db.issues`. | Document counts verified (`db.issues.count_documents({}) == 227`). |
| **DB-01** | `scripts/backup_db.py`, `restore_db.py` | Restoring database dropped collections and inserted JSON documents without rebuilding indexes, permanently wiping 2dsphere, unique, and compound indexes. | Integrated automatic invocation of `create_indexes(mongo_uri=mongo_uri)` directly into `run_restore()`. Created standalone CLI utility `restore_db.py`. | `tests/test_phase5_data_integrity.py::test_backup_restore_roundtrip` (verified indexes intact after restore). |
| **DB-03 / DB-10** | `setup_indexes.py` | Ward feed queries (`ward` + `created_at DESC`) lacked a compound index, forcing an in-memory `SORT` stage (32MB RAM crash risk). Redundant `created_at_1` index existed. | Added compound index `[("ward", ASCENDING), ("created_at", DESCENDING)]` and removed redundant ASC index in favor of reversible DESC traversal. | `tests/test_phase5_data_integrity.py::test_explain_plan_no_in_memory_sort` (`winningPlan.stage == 'FETCH'`, index `ward_1_created_at_-1`). |
| **DB-06** | `routes/api/map.py` | Unbounded `.find()` query on active issues across the municipality loaded thousands of documents without limit. | Enforced pagination/limiting (`limit = min(int(request.args.get("limit", 250)), 500)`). | `tests/test_phase5_data_integrity.py::test_bounded_map_query` |
| **DB-08** | `routes/api/analytics.py` | N+1 queries executing inside loops fetching `db.ward_scores.find_one(...)` for each aggregated ward. | Replaced loop queries with a single batch `$in` query: `db.ward_scores.find({"ward": {"$in": ward_names}})`. | Code inspection & regression test |
| **DB-09** | `services/complaint_service.py` | `add_community_confirmation` used check-then-act `$push` prone to parallel confirmation race conditions. | Updated to atomic query filter: `{"_id": ObjectId(issue_id), "community_confirmations.citizen_id": {"$ne": cit_oid}}`. | `tests/test_phase5_data_integrity.py::test_atomic_community_confirmation_parallel` (8 concurrent threads $\rightarrow$ 1 success, 7 rejections). |
| **DB-05 / Concurrency** | `services/assignment_service.py` | Worker assignment to an issue lacked atomic CAS gating on `worker_id`, allowing race conditions under concurrent dispatch. | Added atomic query condition `worker_id: {"$in": [None, ""]}`. If already taken, active load increment is safely rolled back and 409 conflict returned. | `tests/test_phase5_data_integrity.py::test_atomic_worker_assignment_parallel` (2 concurrent threads $\rightarrow$ 1 success, 1 rejection). |
| **FLOW-07** | `services/sla_escalation.py` | Rapid cascading escalation bug: `now > deadline` triggered escalation level increments on every 5-min cron run (L0 $\rightarrow$ L3 in 15 mins). | Enforced mandatory 24-hour spacing interval (`last_escalated_at`) between escalation transitions. | `tests/test_phase5_data_integrity.py::test_sla_escalation_spacing` (consecutive immediate runs remain at L1). |
| **DB-11 / DB-07** | `scripts/migrate_data_integrity.py` | Inconsistent `read` vs `is_read` booleans and missing `ward_id` field sync on legacy records. | Created automated migration script with `--dry-run` and `--apply` flags; synchronized 2,058 notification records (`read == is_read`) and 84 issue documents (`ward <-> ward_id`). | Applied via `python scripts/migrate_data_integrity.py --apply`. |
| **Code Polish** | `routes/api/issues.py` | `list_issues` threw `AttributeError: 'NoneType' object has no attribute 'get'` when `image` attribute was `None`. | Hardened image extraction to handle `NoneType`, `dict`, and string formats safely. | `tests/test_integration.py` passed. |

---

## 3. Test Verification & Results

### Dedicated Phase 5 Test Suite (`tests/test_phase5_data_integrity.py`)
- `test_explain_plan_no_in_memory_sort`: **PASSED** (execution plan uses `ward_1_created_at_-1`, no blocking `SORT`).
- `test_bounded_map_query`: **PASSED** (`/api/map/issues` respects limit cap).
- `test_atomic_community_confirmation_parallel`: **PASSED** (8 parallel threads result in exactly 1 confirmation, count=1).
- `test_atomic_worker_assignment_parallel`: **PASSED** (2 parallel worker assignments result in exactly 1 assignment).
- `test_sla_escalation_spacing`: **PASSED** (overdue issue escalates to L1, second run 5 mins later stays at L1).
- `test_backup_restore_roundtrip`: **PASSED** (creates zip backup, restores database, verifies 2dsphere and compound indexes are automatically rebuilt).

```
============================= 6 passed in 16.19s ==============================
```

### Full Regression Suite
- **168 passed in 40.44s** (0 failures, 0 regressions across all phases).

---

## 4. Next Phase Gate

Phase 5 remediation is fully tested and committed to branch `fix/phase-5`. Per the Master Fix Plan, the agent must halt and wait for user confirmation before proceeding to **Phase 6: AI layer (and AI security)** (single shared vocabulary, Kannada/Hinglish emergency recall, offline Indic fallback, calibrated confidence, CTVE ablation rerun, output schema validation).
