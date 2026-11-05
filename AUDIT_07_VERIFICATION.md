# AUDIT REPORT 07: Resident Verification Lifecycle & Authority Governance

**Auditor Persona**: Strict, Adversarial Senior Code & Security Auditor  
**Date**: November 5, 2026  
**Target Repository**: SmartCivic+ (`c:\Users\Muthaheer\Desktop\main project\code 1`)  
**Scope**: Registration lifecycle, resident verification state machine, authority review queue, self-service approval backdoors, token invalidation, jurisdictional isolation, audit logging, and route-level authorization enforcement.  
**Mode**: READ-ONLY AUDIT. Zero source files modified, created, or deleted. All probes and tests were executed strictly within `audit_tmp/test_verification_audit.py`.

---

## EXECUTIVE SUMMARY

SmartCivic+ specifies a strict gated governance flow:
$$\text{Citizen Registers} \longrightarrow \text{PENDING} \longrightarrow \text{Authority Review Queue} \longrightarrow \text{Approve / Reject (with reason)} \longrightarrow \text{VERIFIED (Full Access)}$$

An adversarial audit of the backend routes, database state transitions, and web views reveals that **the required governance flow is largely an illusion undermined by self-service backdoors, missing authorization decorators, and total lack of auditability**:

1. **Self-Service Verification Backdoor (CRITICAL)**: Any registered resident in `pending` or `rejected` state can **completely bypass authority review** by sending an HTTP request to `POST /api/auth/verify-ward` with any arbitrary `area_code` (e.g. `"RANDOM_FAKE_CODE"`). `routes/auth.py:464-477` blindly sets `verified: True`, `verification_status: "approved"`, and `status: "active"`. Authority review is entirely optional.
2. **Pending Residents Can Vote and Confirm Issues (HIGH)**: While submitting new issues (`POST /api/issues`) is blocked by `@verified_required`, voting/supporting complaints (`POST /api/issues/<id>/support`) and community confirmations (`POST /api/issues/<id>/confirm`) **omit the decorator**. An unverified or rejected resident can freely upvote issues, inflating CEFAP corroboration scores ($C$) and hijacking municipal prioritization.
3. **Web UI Fails to Enforce Verification (HIGH)**: The web decorator `require_citizen_page` (`routes/citizen.py:13-30`) checks only that `role == "citizen"` and **never inspects `verified` or `verification_status`**. Unverified pending residents who navigate to `/citizen/dashboard` or `/report` receive full HTTP 200 access to the UI.
4. **Rejection Reason Is Never Disclosed to Resident (HIGH)**: When an authority rejects a resident with a specific reason (e.g. `"Aadhaar card blurred"`), the reason is stored in MongoDB (`routes/auth.py:570`), but `GET /api/auth/verification-status` (`routes/auth.py:494-505`) **fails to serialize `rejection_reason` in the response JSON**. The rejected citizen is left completely in the dark.
5. **No Jurisdictional Isolation Across Wards (HIGH)**: `manual_verify_user` (`routes/auth.py:553`) checks only `current.get("role") in ["admin", "officer"]`. It **never checks ward assignment**. An officer assigned to Ward 2 can approve or reject residents residing in Ward 1, and can arbitrarily overwrite the resident's municipal `ward_id`.
6. **Zero Audit Trail (HIGH)**: Authority approvals and rejections perform a silent `db.users.update_one()` with **zero entries inserted into `db.audit_logs`**. There is no historical record of which officer approved or rejected which resident, when the action occurred, or what justification was provided.
7. **Phantom Approvals & Server Crashes (MEDIUM)**:
   - Approving a nonexistent `ObjectId` returns **HTTP 200 OK** (`"User verified successfully"`), falsely claiming success (`routes/auth.py:589`).
   - Approving a malformed ID (non-hex string) triggers an unhandled `bson.errors.InvalidId` exception, crashing the endpoint with **HTTP 500 Server Error** (`routes/auth.py:578`).

---

## 1. FLOW COMPARISON: REQUIRED VS. ACTUAL

### Required Governance Flow
```
[Resident Registers]
         |
         v
[Status: PENDING VERIFICATION] ---> Blocked from all functional routes (Reporting, Voting, Confirming, Dashboard)
         |
         v
[Authority Sees Pending Queue] (Scoped strictly to Officer's assigned Ward)
         |
         v
[Authority Reviews Proof]
         |
         +---------------------------------------+
         |                                       |
         v                                       v
    [APPROVE]                                 [REJECT]
         |                                       |
         v                                       v
  - Audit Log Written                     - Reason Mandated
  - Status: VERIFIED                      - Audit Log Written
  - Immediate Full Access                 - Status: REJECTED
                                          - Citizen sees exact reason
```

### Actual Code Flow & Security Deviations
```
[Resident Registers] (routes/auth.py:160)
         |
         v
[Status: PENDING] -------------------------------------------------------------------------------+
         |                                                                                       |
         +---> [BACKDOOR: POST /api/auth/verify-ward] (routes/auth.py:417)                        | [CRITICAL LEAK]
         |     Resident submits random string as area_code.                                      | Unverified user can:
         |     Database immediately marks verified=True, status="active"!                        | - Access Web Dashboard (HTTP 200)
         |     Authority queue completely bypassed!                                              | - Access Report Issue UI (HTTP 200)
         |                                                                                       | - Vote on Issues (HTTP 200)
         v                                                                                       | - Confirm Issues (HTTP 200)
[Authority Queue: GET /api/auth/users/pending] (routes/auth.py:507)                              |
         |                                                                                       |
         +---> [CROSS-WARD LEAK] Ward 2 officer sees and approves Ward 1 residents!              |
         |                                                                                       |
         v                                                                                       |
[Authority Action: POST /api/auth/users/<id>/approve or /reject] (routes/auth.py:553)            |
         |                                                                                       |
         +---> [MISSING AUDIT] No audit log written to db.audit_logs.                            |
         |                                                                                       |
         +---> [PHANTOM APPROVAL] Nonexistent IDs return HTTP 200 OK.                            |
         |                                                                                       |
         +---> [CRASH BUG] Malformed IDs trigger unhandled InvalidId -> HTTP 500.                |
         |                                                                                       |
         +---------------------------------------+                                               |
         |                                       |                                               |
         v                                       v                                               |
    [APPROVE]                                 [REJECT]                                           |
  - status: "active"                        - status: "rejected"                                 |
  - verified: True                          - verified: False                                    |
  - Old JWT works immediately               - Reason stored in DB                                |
                                            - BUT GET /verification-status hides reason!         |
                                              (Citizen cannot see why rejected) <----------------+
```

---

## 2. EMPIRICAL TEST RESULTS

**Verification Script**: `audit_tmp/test_verification_audit.py`  
**Execution Timestamp**: 2026-11-05T15:01:23  
**Raw Test Output**: `audit_tmp/verification_audit_results.json`

| Test ID | Test Scenario | Expected Behavior | Actual Measured Behavior | HTTP Status | Verdict |
|:---|:---|:---|:---|:---:|:---:|
| **VER-01** | Resident Registration | Creates user with `verified: False`, `verification_status: "pending"` | Document created with `verified: False`, `verification_status: "pending"`, `status: "pending_verification"` | 201 | ✅ Works (I ran it) |
| **VER-02** | Login as Pending Resident | Receives token but flagged as pending | Returns valid JWT token; redirect points to `/citizen/verify-ward` | 200 | ✅ Works (I ran it) |
| **VER-03** | Pending User Submits Issue | Blocked with 403 Forbidden | Blocked with message: `"Account not verified (pending verification)"` | 403 | ✅ Works (I ran it) |
| **VER-04** | Pending User Votes / Supports Issue | Blocked with 403 Forbidden | **ALLOWED**. Support count incremented; returns `"Support recorded successfully"` | 200 | ❌ **Missing/Broken** |
| **VER-05** | Non-Authority Lists Pending | Blocked with 403 Forbidden | Returns `{"code": "FORBIDDEN", "message": "Admin/Officer access required."}` | 403 | ✅ Works (I ran it) |
| **VER-06** | Non-Authority Approves User | Blocked with 403 Forbidden | Returns `{"code": "FORBIDDEN", "message": "Admin/Officer access required."}` | 403 | ✅ Works (I ran it) |
| **VER-07** | Authority Rejects with Reason | Status set to `rejected`, reason stored in DB | DB updated: `verification_status: "rejected"`, `rejection_reason: "Aadhaar card proof is blurred and unreadable."` | 200 | ✅ Works (I ran it) |
| **VER-08** | Rejected User Views Reason | `GET /verification-status` returns rejection reason | Returns status and ward, but **`rejection_reason` is omitted from JSON** | 200 | ❌ **Missing/Broken** |
| **VER-09** | Authority Approves User | Status set to `approved`, immediate access without re-login | DB updated: `verified: True`. Pre-existing JWT token immediately submits issue with HTTP 201 | 200 / 201 | ✅ Works (I ran it) |
| **VER-10** | Double-Approve | Returns 409 Conflict or idempotent notice | Blindly re-executes update; returns 200 OK with no check on prior status | 200 | ⚠️ Partial |
| **VER-11** | Approve Nonexistent ID | Returns 404 Not Found | Returns **200 OK `"User verified successfully by admin/officer"`** despite 0 matched documents | 200 | ❌ **Missing/Broken** |
| **VER-12** | Approve Malformed ID | Returns 400 Bad Request | Unhandled `bson.errors.InvalidId` exception crashes server with **HTTP 500** | 500 | ❌ **Missing/Broken** |
| **VER-13** | Cross-Ward Approval | Ward 2 Officer blocked from approving Ward 1 resident | Ward 2 Officer approved Ward 1 resident and **overwrote resident's ward to Ward 2** | 200 | ❌ **Missing/Broken** |
| **VER-14** | Audit Trail Verification | Entry inserted into `db.audit_logs` | **Zero documents inserted into `db.audit_logs`**. Zero officer traceability | N/A | ❌ **Missing/Broken** |
| **VER-15** | Self-Verification Bypass | Blocked; only municipal authority can approve | Resident called `POST /api/auth/verify-ward` with fake code; DB marked user `verified: True` | 200 | ❌ **CRITICAL FLAW** |

---

## 3. UI VS. API ENFORCEMENT DISCREPANCIES

An adversarial security audit requires verifying that access controls are enforced uniformly across both UI and API layers. The audit revealed **severe policy divergence**:

| Layer | Component / Route | Protection Mechanism | Enforces `verified == True`? | Security Failure Mode |
|:---|:---|:---|:---:|:---|
| **API** | `POST /api/issues` | `@verified_required` (`utils/auth_helpers.py:84`) | ✅ **YES** | Correctly rejects pending/rejected users with HTTP 403. |
| **API** | `POST /api/issues/<id>/support` | `@require_auth` (`routes/api/issues.py:1676`) | ❌ **NO** | Unverified users can vote on and escalate civic issues. |
| **API** | `POST /api/issues/<id>/confirm` | `@require_auth` (`routes/api/issues.py:400`) | ❌ **NO** | Unverified users can confirm duplicate incidents. |
| **API** | `GET /api/issues` | `@verified_required` (`routes/api/issues.py:736`) | ✅ **YES** | Blocked with HTTP 403. |
| **API** | `GET /api/auth/verification-status` | `@require_auth` (`routes/auth.py:495`) | ❌ **NO** | Accessible, but hides rejection reason. |
| **Web UI**| `GET /citizen/dashboard` | `require_citizen_page` (`routes/citizen.py:13`) | ❌ **NO** | **Bypass**. Decorator checks `role == "citizen"` only. Serves full citizen dashboard (HTTP 200) to pending users. |
| **Web UI**| `GET /report` | `require_citizen_page` (`routes/citizen.py:39`) | ❌ **NO** | **Bypass**. Serves full issue submission form (HTTP 200) to unverified users. |
| **Web UI**| `GET /citizen/verify-ward` | None | N/A | Landing page for self-verification backdoor. |

> [!WARNING]
> **The UI Enforcement Illusion**: When a pending resident logs in via a web browser, `routes/auth.py:333` redirects them to `/citizen/verify-ward`. However, if the user simply types `/citizen/dashboard` or `/report` into their browser URL bar, `require_citizen_page` admits them with HTTP 200 because it completely ignores the `verified` flag.

---

## 4. ROUTE ENFORCEMENT MATRIX FOR PENDING USERS

Below is the measured status code when a resident with `status: "pending_verification"` and `verified: False` accesses each application endpoint:

| Target Endpoint | Method | Expected Status | Actual Status | Access Allowed? | Vulnerability Assessment |
|:---|:---:|:---:|:---:|:---:|:---|
| `/api/issues` (Submit complaint) | POST | 403 | **403** | ❌ Blocked | ✅ Protected by `@verified_required`. |
| `/api/issues/<id>/support` (Vote on issue) | POST | 403 | **200** | ⚠️ **ALLOWED** | 🚨 **Vulnerability**. Missing `@verified_required`. |
| `/api/issues` (List complaints) | GET | 403 | **403** | ❌ Blocked | ✅ Protected by `@verified_required`. |
| `/api/issues/<id>` (View complaint) | GET | 403 | **403** | ❌ Blocked | Blocked by IDOR owner check. |
| `/api/issues/<id>/confirm` (Community confirmation) | POST | 403 | **200** | ⚠️ **ALLOWED** | 🚨 **Vulnerability**. Missing `@verified_required`. |
| `/api/issues/<id>/feedback` (Rate resolved issue) | POST | 403 | **400** | ❌ Blocked | Fails validation; missing `@verified_required`. |
| `/api/issues/<id>/citizen-verify` (Verify resolution) | POST | 403 | **500** | ❌ Blocked | Crashes in service; missing `@verified_required`. |
| `/citizen/dashboard` (Web UI Dashboard) | GET | 302/403 | **200** | ⚠️ **ALLOWED** | 🚨 **Vulnerability**. `require_citizen_page` lacks check. |
| `/report` (Web UI Report Form) | GET | 302/403 | **200** | ⚠️ **ALLOWED** | 🚨 **Vulnerability**. `require_citizen_page` lacks check. |
| `/citizen/verify-ward` (Web UI Verification) | GET | 200 | **200** | ✅ Allowed | Verification portal page. |
| `/api/auth/verification-status` | GET | 200 | **200** | ✅ Allowed | Status check API (omits rejection reason). |

---

## 5. DETAILED VULNERABILITY ANALYSIS

### 5.1 Self-Service Verification Backdoor
- **File**: `routes/auth.py:463-477`
- **Flaw**:
  ```python
  ward = db.ward_registry.find_one({"$or": [{"area_code": area_code}, ...]})
  if not ward:
      ward_id = area_code.lower().replace(" ", "_")
      ward_name = area_code

  db.users.update_one(
      {"_id": ObjectId(user_id)},
      {"$set": {
          "verified": True,
          "verification_status": "approved",
          "status": "active",
          "ward": ward_name,
          "ward_id": ward_id,
          ...
      }}
  )
  ```
- **Exploitation**: An attacker registers an unverified account, immediately sends `POST /api/auth/verify-ward` with `{"area_code": "BYPASS"}`, and the server transitions the account to `verified: True`, granting full municipal access with zero authority oversight.

### 5.2 Phantom Approvals on Nonexistent IDs
- **File**: `routes/auth.py:577-589`
- **Flaw**:
  ```python
  db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"verified": True, ...}})
  return jsonify({"success": True, "message": "User verified successfully by admin/officer"}), 200
  ```
- **Exploitation**: `manual_verify_user` never checks `modified_count` or `matched_count`. If an officer submits an invalid or random `ObjectId`, the API blindly returns `HTTP 200 OK`, creating false confirmation in the administrative interface.

### 5.3 Crash Bug on Malformed ID (HTTP 500)
- **File**: `routes/auth.py:565` & `578`
- **Flaw**: The route attempts `ObjectId(user_id)` without a `try...except (InvalidId, TypeError)` block.
- **Exploitation**: Any malformed request parameter (e.g. `/api/auth/users/undefined/approve` from a buggy frontend) triggers a raw `bson.errors.InvalidId` exception, triggering an HTTP 500 error and polluting server logs.

### 5.4 Cross-Ward Jurisdictional Boundary Breach
- **File**: `routes/auth.py:553-556`
- **Flaw**:
  ```python
  current = g.current_user
  if current.get("role") not in ["admin", "officer"]:
      return jsonify({"success": False, "error": {"code": "FORBIDDEN", ...}}), 403
  ```
- **Exploitation**: The route never inspects `current.get("ward")` or `current.get("ward_id")`. A corrupt or compromised officer in Ward 10 can approve fraudulent accounts across all 27 wards. Furthermore, line 583 updates the resident's `ward_id` to whatever arbitrary string the officer passed in the request body.

---

## 6. COMPREHENSIVE REMEDIATION TABLE

| ID | Severity | File:Line | Problem | Suggested Fix | Effort |
|:---|:---:|:---|:---|:---|:---:|
| **VER-01** | **Critical** | `routes/auth.py:463-477` | Self-verification backdoor: `POST /verify-ward` allows any resident to approve themselves by submitting an arbitrary area code. | Remove self-approval logic. Replace with document upload endpoint (`POST /api/auth/verification-docs`) that leaves user in `pending` for authority review. | **M** |
| **VER-02** | **High** | `routes/api/issues.py:1674`, `400` | Unverified pending residents can vote on (`/support`) and confirm (`/confirm`) complaints, manipulating priority scores. | Add `@verified_required` decorator to `support_complaint` and `confirm_issue_report`. | **S** |
| **VER-03** | **High** | `routes/citizen.py:13-30` | Web UI decorator `require_citizen_page` does not check `verified`, granting pending users full access to dashboard and report forms. | Update `require_citizen_page` to redirect unverified citizens to `/pending-verification` if `verified != True`. | **S** |
| **VER-04** | **High** | `routes/auth.py:494-505` | `GET /api/auth/verification-status` omits `rejection_reason`, leaving rejected citizens unable to see why they were denied. | Include `"rejection_reason": user.get("rejection_reason")` in the `/verification-status` JSON response. | **S** |
| **VER-05** | **High** | `routes/auth.py:553-556` | Zero ward jurisdiction enforcement: officers can approve/reject residents in wards other than their assigned jurisdiction. | Enforce that `current_user["ward_id"] == target_user["ward_id"]` unless `current_user["role"] == "admin"`. | **M** |
| **VER-06** | **High** | `routes/auth.py:563-589` | Zero audit logging: approvals and rejections update `db.users` silently without recording actor, timestamp, or reason in `db.audit_logs`. | Insert an audit document into `db.audit_logs` capturing `officer_id`, `citizen_id`, `action`, `ward`, and `timestamp`. | **S** |
| **VER-07** | **Medium** | `routes/auth.py:564`, `578` | Approving with a malformed ID triggers an unhandled `bson.errors.InvalidId` exception, crashing with HTTP 500. | Wrap `ObjectId(user_id)` in `try...except InvalidId` and return HTTP 400 Bad Request. | **S** |
| **VER-08** | **Medium** | `routes/auth.py:577-589` | Approving a nonexistent `ObjectId` returns HTTP 200 OK ("User verified successfully") instead of 404 Not Found. | Check `result.matched_count == 0` and return HTTP 404 Not Found if no user exists. | **S** |
| **VER-09** | **Medium** | `routes/auth.py:558-572` | Rejection reason is optional in payload; defaults to generic string if authority provides no explanation. | Validate that `reason` is present and at least 10 characters long on rejection requests; return 422 if missing. | **S** |
| **VER-10** | **Low** | `routes/auth.py:577` | Approving an already approved user blindly returns HTTP 200 OK without idempotency notification. | Return HTTP 200 with notice `"User is already verified"` if `user["verified"] == True`. | **S** |

---
*Report completed. No source files modified.*

