# SmartCivic master fix plan (security first)

This replaces the earlier Phase 1 to 5 split. Security now has its own phases (1 to 3) and comes before everything else. Save it as `SMARTCIVIC_FIX_PLAN.md` in the repo so the agent can read it.

**What I haven't seen:** the outputs of Stage 1 (uploads) and Stage 4 (security checklist). Phase 3 and Phase 8 include verify-first steps for them. Paste those two reports and I'll tighten the plan.

**Rough effort** for one person working with an AI agent: about 2 to 3 weeks in total. Don't skip the gates.

---

## Phase 0: Containment (do this by hand, about half a day)

- [ ] Rotate everything that appeared in the git history scan: all three Mongo users, `SECRET_KEY`, JWT secret, Gemini key, and anything else among the 52 hits.
- [ ] Purge `security/` and `.env` from history (`git-filter-repo` or BFG), force-push, and re-clone. Assume the old secrets are public, so rotation is what actually protects you.
- [ ] Check the GitHub repo visibility and enable secret scanning.
- [ ] Add `security/`, `*.uri`, `.env`, `logs/`, `*.log`, `.coverage`, `htmlcov/` and `uploads/` to `.gitignore`. Add a gitleaks pre-commit hook (free).
- [ ] MongoDB: authentication on, bound to `127.0.0.1` or an Atlas IP allowlist, and the app connecting as the least-privilege app user, never admin.
- [ ] Take a full DB backup, create a `smartcivic_test` database, and cut a branch per phase.

**Gate:** old credentials no longer work, and `git log -p` shows no secrets.

---

## Phase 1: Identity, verification and authorization

**1.1 Verification flow** (VER-01 to 10, FLOW-01, 02, DB-02)
- `verify-ward` never sets `verified=True`. An unknown code returns 400, and a valid code only records the request for authority review.
- Rejected users are blocked at login, or limited to a read-only status page.
- Approve and reject must: validate the ObjectId (400), return 404 on no match, be idempotent, require a rejection reason of at least 10 characters, write an `audit_logs` entry, and enforce ward jurisdiction. Officers must not overwrite a resident's ward.
- `/verification-status` returns `rejection_reason`.

**1.2 Default-deny authorization** (new)
- Generate a route matrix (method, path, decorators) from the Flask URL map. Add a `before_request` that rejects any route not on an explicit public allowlist.
- Add `@role_required` to every officer, admin and worker API. Fix the "frontend-only role checks" finding.
- Add one `authorize_issue_access(user, issue)` helper (owner, ward officer, assigned worker, admin) and use it on every `/<id>` route. Add `@verified_required` to `support`, `confirm`, `feedback` and `citizen-verify`, and block self-support.
- `require_citizen_page` redirects unverified users.
- State machine: citizens can't jump `submitted → closed` after triage. Only officers and workers advance the later states.

**1.3 Authorization test matrix** (the key security test)
- Write `tests/test_authz_matrix.py` that runs every route as anonymous, pending, rejected, citizen A, citizen B, worker, officer (ward 1), officer (ward 2) and admin. The expected status code for each cell lives in one table, and any route not in the table fails the test.

**1.4 Passwords and brute force**
- Move to argon2id with rehash-on-login. Enforce a password policy.
- Add per-account and per-IP lockout with backoff, and generic login errors.

**Gate:** the authz matrix passes, the bogus ward code returns 400, and cross-ward approval returns 403.

---

## Phase 2: Sessions, tokens, browser defenses

**2.1 Token model**
- Web: a 15-minute access token in an HttpOnly, Secure, SameSite=Lax cookie. The refresh token rotates and its hash is stored in Mongo with a `jti`. Reuse of an old refresh token revokes the whole session family.
- Logout, password change, role change and rejection all revoke tokens.
- Mobile keeps Bearer tokens in SecureStore, validated by the same server logic.
- Remove the `localStorage` tokens and the orphaned `auth.js` (FE-07).

**2.2 CSRF**
- Remove the blanket `csrf.exempt` on blueprints that use cookie auth. JS sends `X-CSRFToken` from a meta tag. Bearer-only mobile requests stay exempt. Add `csrf_token` hidden inputs to the HTML forms.

**2.3 XSS defense in depth** (FE-01 to 04, RT-01, DEP-13)
- Shared `escapeHtml()` or `textContent` everywhere. Add a test that fails on any new unescaped `innerHTML` with dynamic data.
- Remove `'unsafe-inline'` and `'unsafe-eval'` from the CSP by moving inline scripts out or using nonces. Keep the CSP in report-only mode first and fix what breaks.
- Confirm there is no `|safe` on user data in the templates.

**2.4 Headers, CORS, cookies**
- Keep HSTS, `nosniff` and `X-Frame-Options`. Add `Referrer-Policy` and `Permissions-Policy` (geolocation and camera for self only).
- Replace Socket.IO `cors_allowed_origins="*"` and any Flask CORS wildcard with an env allowlist.
- `COOKIE_SECURE` defaults to true. Fix `--forwarded-allow-ips` so rate limiting can't be bypassed with a forged `X-Forwarded-For`.

**2.5 Rate limits**
- Flask-Limiter with persistent storage (Redis or Mongo), because the in-memory default resets per worker. Apply it to login, register, verify, upload, support and confirm, and to every AI endpoint.
- Add a Gemini cost cap and circuit breaker so spam can't burn your quota.

**Gate:** a stored-XSS payload fails in every render path, a stolen cookie can't be read by JS, CSRF tests pass, and the 500-request flood gets throttled.

---

## Phase 3: Uploads, PII and privacy

**3.0 Verify first:** run or paste the Stage 1 upload report. Then fix the following.

**3.1 Upload hardening**
- Validate by content (open and `verify()` with Pillow, magic bytes for PDF). Set `MAX_CONTENT_LENGTH`, a pixel cap against decompression bombs, and allowed formats.
- Use random UUID filenames and never trust the client's filename.
- Extract GPS from EXIF first, then re-encode and strip all metadata.
- Never serve user uploads from public `static/`. Serve them through an authorized route (owner, ward officer or assigned worker) or short-lived signed URLs. Send `X-Content-Type-Options: nosniff`, and `Content-Disposition: attachment` for PDFs.
- Optional storage interface with R2 or S3 (free tiers) for ephemeral hosts (DEP-09).

**3.2 Verification documents are your most sensitive data**
- Only the owner and the ward's officers can access them. Encrypt them at rest (Fernet, key in an env var) and delete them N days after the decision. Never log them.

**3.3 Real anonymous reporting** (design decision for you)
- Recommended design: store no `citizen_id` on the issue. Keep a salted hash in a separate restricted collection, used only for abuse and rate limiting and never returned by any API, socket or log. Strip EXIF completely and show only fuzzed locations to the public.

**3.4 Stop leaking raw documents**
- Create explicit serializers (`public_issue`, `citizen_issue`, `officer_issue`) with field whitelists. Never `serialize(raw_doc)`: that is where the 85 fields, `citizen_id`, coordinates and `text_embedding` leak from. Apply them to REST and Socket.IO alike.

**3.5 Privacy and logging**
- Scrub phone numbers, emails and names before sending text to Gemini.
- Add a log redaction filter (tokens, passwords, phones, anonymous coordinates). Make `audit_logs` write-only for the app.
- Mask worker phone numbers in API responses. Add an account-deletion path and a consent notice. India's DPDP Act 2023 is worth reading for this, and I'm not a lawyer.

**Gate:** uploading a `.php` renamed to `.jpg` is rejected, a path-traversal filename is neutralized, image EXIF is gone, another citizen's upload URL returns 403, and an anonymous report exposes no identity anywhere.

---

## Phase 4: Real-time, deployment and CI security

- **Real-time:** connect auth on `/civic`, `namespace="/civic"` on every emit, `officers → role_officer`, event name `notification`, per-sid rate limit, 1 MB buffer, officer dashboard listeners, reconnect and error handlers (RT-03 to 12, FLOW-08).
- **Server:** remove `--proxy-protocol` by default, run `-k eventlet -w 1`, document the Windows/waitress limit, and require Redis if workers > 1 (DEP-02 to 04, 16).
- **Docker:** non-root user, no secrets baked into the image, healthcheck, `/health` alias.
- **Config:** split into Dev, Test and Prod, with tests only touching `smartcivic_test`.
- **CI (free GitHub Actions):** gitleaks, `pip-audit`, bandit, semgrep, plus the test suite on every push.

**Gate:** WebSocket upgrade works, an officer receives an emergency alert in under a second, and CI is green.

---

## Phase 5: Data integrity

- **First:** grep for `db.complaints` vs `db.issues` and resolve the contradiction between audits 05B and 05C before consolidating anything.
- Make backup restore recreate indexes (DB-01), and add `restore_db.py` and a restore test.
- Add the `ward + created_at` compound index and drop the redundant ones. Bound the map query. Remove N+1 queries.
- Atomic community confirmation, atomic worker assignment, and a transaction or compensating write for state transitions.
- SLA escalation spacing (FLOW-07). Standardize ObjectIds and `read`/`is_read` through a dry-run migration with a backup first.

**Gate:** parallel-request tests pass, `explain()` shows no in-memory sorts, and a restore round-trip works.

---

## Phase 6: AI layer (and AI security)

- Single shared service-class vocabulary (AI-01). Expanded emergency detection in English, Kannada and Hinglish, with a false-positive fix (AI-02). Offline Indic fallback (AI-03, 08).
- One AI pipeline run per complaint. Fail fast on 429. Computed, calibrated confidence (AI-04, 05, 07).
- CEFAP disagreement fix, then re-run the ablation (AI-06). Decide whether AUTO_ROUTE should really dispatch or be renamed (AI-09).
- **AI security:** validate model output against an enum schema, and treat everything the model returns as untrusted input. The model can never set priority or authority directly without the deterministic checks. Keep the input sanitizer.

**Gate:** before/after tables for the 66-complaint set and the 60-emergency set, with emergency recall as the priority metric.

---

## Phase 7: Mobile, dependencies, tests, frontend quality

- Mobile: `after_image` vs `image`, API URL from config, remove Capacitor.
- Dependencies: add missing packages, upgrade Pillow and pymongo according to your own `pip-audit` run, and keep requirements pinned.
- Tests: mock Gemini so the suite passes offline, fix the YOLO model path, and raise coverage on auth, issues and upload.
- Frontend: CTVE scoping bug, duplicate Leaflet and `showToast`, label `for=` attributes, fonts, double-submit protection, responsive CSS.

**Gate:** a clean-venv install starts the app, tests pass offline three runs in a row, and the mobile resolve works against the real route.

---

## Phase 8: Security verification (release gate)

- Run OWASP ZAP baseline against a local instance (free), then manual XSS and IDOR passes.
- Re-run audits 05A to 07 and the Stage 1 and Stage 4 prompts. The agent produces `AUDIT_RERUN.md` with Fixed / Still broken / Regressed for every ID.
- Sign-off checklist: no secrets in history, debug off, cookies Secure, CSP without unsafe, authz matrix green, uploads private, no PII in logs or broadcasts, rate limits working, DB not publicly reachable, backups restore.

---

## Phase 9: Deferred features (after security)

3-citizen crowd verification, SMS and email, and Indic embeddings. Each needs a design decision first.

---

## Kickoff prompt for Antigravity

```
Read SMARTCIVIC_FIX_PLAN.md and the audit reports AUDIT_05A to AUDIT_07.

Execute the plan ONE PHASE AT A TIME, starting with Phase 1 (I handle Phase 0 by hand).

RULES:
1. New git branch per phase: fix/phase-N. Commit after each task.
2. Reproduce each issue first. If an audit claim does not reproduce, mark it "Not reproducible" and skip it. Do not fix imaginary bugs.
3. Test first: write a failing test, make the minimal fix, then run that test and the full suite (Gemini mocked, test DB smartcivic_test only).
4. Never rename routes, element IDs, field names or classes that JS or the mobile app depend on. No visual redesign.
5. Zero-cost only: free libraries and services.
6. Anything that needs a decision from me (anonymity design, collection consolidation, AUTO_ROUTE behavior, data migrations) -> stop and ask, with options and a recommendation.
7. Do not touch real data. Migrations must have a dry-run mode and a backup step.
8. At the end of each phase write FIX_REPORT_PHASE_N.md (per ID: Fixed / Not reproducible / Deferred, files changed, test name, manual steps for me), then STOP and wait for my approval before starting the next phase.
```

If you want, I can put this into a file you can download, or write the full authz-matrix test spec for Phase 1.3, since that single test catches most future security regressions.
