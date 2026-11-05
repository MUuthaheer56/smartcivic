# Phase 3 Fix Report: Uploads, PII and Privacy

**Branch:** `fix/phase-3`  
**Status:** ✅ Completed & Fully Verified  
**Date:** 2026-11-05  
**Automated Tests:** 154 passed (including 8 new dedicated Phase 3 security test cases)

---

## 1. Executive Summary

Phase 3 remediation hardens the file upload pipeline, secures municipal verification documents with encryption at rest, implements genuine anonymous grievance filing without identity traces, establishes strict field-whitelisted serializers to prevent raw MongoDB document leakage, and scrubs Personally Identifiable Information (PII) before external AI dispatch.

All requirements under **Phase 3: Uploads, PII and privacy** in [SMARTCIVIC_FIX_PLAN.md](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/SMARTCIVIC_FIX_PLAN.md#L79-L105) have been implemented and verified against the `smartcivic_test` environment.

---

## 2. Detailed Task Remediation Breakdown

### Task 3.1: Upload Hardening
- **Content Inspection & Verification:** Implemented strict file content validation.
  - Image uploads are opened and verified with Pillow (`img.verify()`). Disguised malicious files (such as PHP scripts renamed to `.jpg`) are rejected with HTTP 400.
  - PDF verification documents check for the `%PDF-` magic header bytes before acceptance.
  - Set `Image.MAX_IMAGE_PIXELS = 10_000_000` in [utils/image_utils.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/utils/image_utils.py) to mitigate decompression bomb denial-of-service vectors.
- **Random UUID Filenames & Path Traversal Neutralization:** All uploaded files are stored under random hex UUID filenames (`f"{uuid.uuid4().hex}.{ext}"`). Client-supplied paths containing path-traversal sequences (e.g. `../../../../etc/cron.d/malicious.jpg`) are stripped of directory components and neutralized.
- **EXIF Metadata Stripping:** Re-encoded images upon saving in [utils/image_utils.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/utils/image_utils.py) and cleared `img.info['exif']` and ICC profiles, ensuring camera models, software tags, and device timestamps are eliminated.
- **Secure File Serving Headers:** Configured [app.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/app.py) to set `X-Content-Type-Options: nosniff` on all served files and `Content-Disposition: attachment; filename="{filename}"` on PDF downloads.

### Task 3.2: Verification Documents Protection & At-Rest Encryption
- **Fernet Encryption at Rest:** Created [utils/crypto_utils.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/utils/crypto_utils.py) implementing symmetric Fernet encryption at rest (`encrypt_bytes`, `decrypt_bytes`).
  - Resident verification documents are encrypted immediately upon upload in [routes/auth.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/routes/auth.py) before writing to disk.
  - Stored files start with Fernet tokens (`gAAAAA...`) and cannot be read if file storage is compromised.
  - Authorized requests to `/files/verification_docs/<filename>` decrypt on the fly and stream with correct MIME types.
- **Ward Jurisdiction Enforcement on Sensitive Documents:** Hardened `can_view_file` in [utils/security.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/utils/security.py).
  - Cross-ward officers (e.g., Ward 2 officer attempting to inspect a Ward 1 resident's verification ID) receive HTTP 403 Forbidden.
  - Only the owning resident, the assigned ward officer, or a global administrator can view the document.

### Task 3.3: Real Anonymous Reporting
- **Zero Identity Footprint on Issues:** When `is_anonymous` is specified during issue filing:
  - `citizen_id` and `reporter_id` are set to `None` on the MongoDB issue document.
  - No user name, email, or profile identifier is attached to the record.
- **Salted Hash Abuse Tracking:** A cryptographic HMAC-SHA256 salted hash of the user ID is generated using the application `SECRET_KEY` and stored in a restricted collection (`db.anonymous_reporters`). This hash is isolated, never linked directly in issue queries, and never returned in API responses or Socket.IO events.
- **Location Fuzzing:** Public serializers round anonymous location coordinates to 3 decimal places (~110m precision), protecting the reporter's residence or precise physical origin.

### Task 3.4: Explicit Document Serializers (Eliminating Raw Data Leaks)
- Created [utils/serializers.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/utils/serializers.py) providing three distinct whitelisted serializers:
  1. `serialize_public_issue(doc)`: Strictly whitelisted public fields (`_id`, `id`, `title`, `description`, `category`, `type`, `status`, `severity`, `ward`, `fuzzed_location`, `images`, `confirmation_count`). Discards `citizen_id`, embeddings, and internal scores.
  2. `serialize_citizen_issue(doc, user_id)`: Appends `is_owner`, own `feedback`, and status. Omits `citizen_id` unless the requester is the verified author and the report is non-anonymous.
  3. `serialize_officer_issue(doc)`: Adds priority decisions, SLA deadlines, AI analysis summaries, and assigned personnel without de-anonymizing anonymous reporters.
- Replaced blanket `serialize(issue)` dumps in [routes/api/issues.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/routes/api/issues.py) and [routes/api/map.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/routes/api/map.py).

### Task 3.5: Privacy, Logging & Worker Protection
- **PII Scrubbing for AI:** Enhanced `sanitize_gemini_prompt` in [services/ai_service.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/services/ai_service.py) with regex scrubbers for email addresses (`[REDACTED_EMAIL]`) and phone numbers (`[REDACTED_PHONE]`) before sending prompts to the Gemini API.
- **Structured Log Redaction:** Updated `_write_log` in [services/logger_service.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/services/logger_service.py) with `_redact_sensitive_data` to automatically redact passwords, tokens, API keys, and phone numbers before writing to `logs/smartcivic.log`.
- **Worker Phone Number Masking:** Added `mask_phone_number` in [routes/api/workers.py](file:///c:/Users/Muthaheer/Desktop/main%20project/code%201/routes/api/workers.py), masking municipal worker contact numbers (e.g. `+91 98*** **210`).

---

## 3. Gate Verification & Test Evidence

### Gate Checklist Verification
| Gate Requirement | Status | Verification Method |
| :--- | :--- | :--- |
| **`.php` renamed to `.jpg` rejected** | ✅ Pass | `test_gate_php_renamed_to_jpg_is_rejected` (`Pillow.verify()` returns 400) |
| **Path-traversal filename neutralized** | ✅ Pass | `test_gate_path_traversal_filename_neutralized` (Saved as hex UUID, no `..` or path segments) |
| **Image EXIF metadata stripped** | ✅ Pass | `test_gate_image_exif_metadata_stripped` (Saved file reloaded; `getexif()` has 0 keys) |
| **Cross-ward / unauthorized upload 403** | ✅ Pass | `test_gate_cross_ward_officer_cannot_view_verification_doc` (Ward 2 officer returns 403; Ward 1 returns 200) |
| **Anonymous report exposes no identity** | ✅ Pass | `test_gate_anonymous_report_exposes_no_identity` (`citizen_id` is None, HMAC hash stored in restricted collection) |

### Dedicated Phase 3 Test Suite
Command: `pytest tests/test_phase3_uploads_privacy.py -v`
```
============================= test session starts =============================
platform win32 -- Python 3.10.11, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\Muthaheer\Desktop\main project\code 1
configfile: pytest.ini
collected 8 items

tests/test_phase3_uploads_privacy.py::TestPhase3UploadsAndPrivacy::test_gate_anonymous_report_exposes_no_identity PASSED [ 12%]
tests/test_phase3_uploads_privacy.py::TestPhase3UploadsAndPrivacy::test_gate_cross_ward_officer_cannot_view_verification_doc PASSED [ 25%]
tests/test_phase3_uploads_privacy.py::TestPhase3UploadsAndPrivacy::test_gate_image_exif_metadata_stripped PASSED [ 37%]
tests/test_phase3_uploads_privacy.py::TestPhase3UploadsAndPrivacy::test_gate_path_traversal_filename_neutralized PASSED [ 50%]
tests/test_phase3_uploads_privacy.py::TestPhase3UploadsAndPrivacy::test_gate_php_renamed_to_jpg_is_rejected PASSED [ 62%]
tests/test_phase3_uploads_privacy.py::TestPhase3UploadsAndPrivacy::test_pii_scrubbing_before_gemini PASSED [ 75%]
tests/test_phase3_uploads_privacy.py::TestPhase3UploadsAndPrivacy::test_serializers_field_whitelisting PASSED [ 87%]
tests/test_phase3_uploads_privacy.py::TestPhase3UploadsAndPrivacy::test_worker_phone_masking PASSED [100%]

============================== 8 passed in 2.93s ==============================
```

### Full Regression Suite
Command: `pytest tests/`
```
============================ 154 passed in 24.95s =============================
```

---

## 4. Remediation Matrix

| ID | Finding | File(s) | Fix Summary | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **P3-01** | Content-type Spoofing | `routes/auth.py`, `utils/image_utils.py` | Validated content via `Image.open().verify()` and PDF magic bytes `%PDF-`. | ✅ Verified |
| **P3-02** | Path Traversal Uploads | `routes/api/issues.py`, `utils/image_utils.py` | Enforced strict UUID hex naming on all uploads. | ✅ Verified |
| **P3-03** | EXIF Privacy Leak | `utils/image_utils.py` | Stripped EXIF metadata and ICC profiles upon re-encoding. | ✅ Verified |
| **P3-04** | Plaintext Verification Docs | `utils/crypto_utils.py`, `routes/auth.py` | Fernet symmetric encryption at rest for verification docs. | ✅ Verified |
| **P3-05** | Cross-Ward Document Access | `utils/security.py` | Restricted officer verification doc access to matching ward jurisdiction. | ✅ Verified |
| **P3-06** | Incomplete Anonymous Filing | `services/complaint_service.py`, `routes/api/issues.py` | Stripped `citizen_id` from issue; stored salted HMAC hash in `anonymous_reporters`. | ✅ Verified |
| **P3-07** | Raw Document Data Leaks | `utils/serializers.py`, `routes/api/issues.py`, `map.py` | Implemented strict field whitelists for public, citizen, and officer serializers. | ✅ Verified |
| **P3-08** | PII Transmission to Gemini | `services/ai_service.py` | Added regex redaction for phone numbers and emails in `sanitize_gemini_prompt`. | ✅ Verified |
| **P3-09** | Log Credential & PII Leak | `services/logger_service.py` | Redacted passwords, tokens, API keys, and phone numbers in JSON logs. | ✅ Verified |
| **P3-10** | Worker Phone Exposure | `routes/api/workers.py`, `utils/serializers.py` | Masked phone numbers in worker profile responses. | ✅ Verified |

---

## 5. Next Steps

With Phase 3 complete and verified, the next phase per `SMARTCIVIC_FIX_PLAN.md` is:
**Phase 4: Real-time, deployment and CI security**
- Connect authentication on `/civic` namespace.
- Ensure `namespace="/civic"` on every Socket.IO emit.
- Role-based Socket.IO room isolation (`officers → role_officer`).
- Standardize event name to `notification`.
- Socket.IO per-sid rate limiting and 1MB buffer ceiling.
- Server configuration hardening (Gunicorn eventlet single worker recipe, proxy protocol cleanup).
- Automated CI security workflow (gitleaks, pip-audit, bandit, semgrep).
