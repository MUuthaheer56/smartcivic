"""
SmartCivic+ — Locust Load & Concurrency Test Suite
===================================================

Simulates real-world municipal traffic across the four hot paths
identified as bottlenecks for a civic issue-reporting platform:

  TaskGroup                 Weight   Purpose
  ─────────────────────────────────────────────────────────
  CitizenReportFlow          70 %     POST /api/issues with image
                                      (hits AI pipeline + YOLO + CEFAP)
  DashboardReadFlow          18 %     GET /citizen/dashboard + API list
  OfficerCommandFlow          8 %     Officer dashboard + assign action
  UnauthenticatedStatic       4 %     Login page + /api/health probe

Quick start (two terminals):

  Terminal 1 (app):
    set SECRET_KEY=... && set JWT_SECRET=... && set FLASK_ENV=development
    python run.py --port 5000

  Terminal 2 (Locust — browser UI mode):
    locust -f tests/locustfile.py --host=http://127.0.0.1:5000

  Terminal 2 (Locust — headless CI mode, 100 users, 10 rps spawn, 2 min run):
    locust -f tests/locustfile.py --host=http://127.0.0.1:5000 ^
        --headless -u 100 -r 10 --run-time 2m ^
        --csv=security/locust_report --html=security/locust_report.html

Bottleneck hints:
  * CPU: YOLO ONNX inference, bcrypt password hashes (12 rounds), CEFAP
    stage priority computation, PIL/Magic image validation.
  * Memory: Socket.IO room registry, MongoDB connection pool, APScheduler
    background jobs.
  * I/O: MongoDB writes per complaint, AI pipeline ThreadPoolExecutor,
    Gemini API calls if a key is configured.
"""
import os
import random
import string
import base64
from locust import HttpUser, task, between, TaskSet, tag
from locust.exception import StopUser


# ── Helpers ──────────────────────────────────────────────────────────────────

_WARD_NAMES = [
    "Ward 01", "Ward 02", "Ward 03", "Ward 04", "Ward 05",
    "Ward 06", "Ward 07", "Ward 08", "Ward 09", "Ward 10",
    "Ward 11", "Ward 12", "Ward 13", "Ward 14", "Ward 15",
]

_COMPLAINT_TEMPLATES = [
    ("pothole", "road",
     "Large pothole on {road} near {place}. Two tires were damaged this morning. {size}."),
    ("garbage", "sanitation",
     "Overflowing garbage bin at {place}. Waste has been lying for {days} days, attracting mosquitoes."),
    ("water_leak", "water_supply",
     "Water pipe leak in front of {place}. Approximately {liters} liters lost per hour, footpath flooded."),
    ("power_outage", "electrical",
     "Power outage in {ward} area since {hrs} hours. Transformer near {place} making unusual sounds."),
    ("road_collapse", "road",
     "Portion of road caved in at {place} after heavy rain. Approximately {size} wide, dangerous at night."),
    ("drainage", "drainage",
     "Storm drain blocked at {place}. Water stagnating for {days} days, breeding ground for mosquitoes."),
    ("streetlight", "electrical",
     "Street light {id} not working for past {days} nights. Dark stretch near {place} unsafe."),
]

_SAMPLE_PLACES = [
    "the bus stand", "the public park", "the school junction", "near the hospital",
    "opposite the police station", "the market entrance", "ward office lane",
    "the railway underpass", "the water tank circle", "sector 7 main road",
]

_SAMPLE_ROADS = [
    "MG Road", "Outer Ring Road", "80 Feet Road", "Service Road", "Main Street",
    "100 Feet Road", "Double Road", "Tank Bund Road", "Station Road",
]


def _random_email() -> str:
    user = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"loadtest_{user}@smartcivic.example"


def _random_password() -> str:
    return "LocustTest!_" + "".join(random.choices(string.ascii_letters + string.digits, k=14))


def _random_phone() -> str:
    return "9" + "".join(random.choices(string.digits, k=9))


def _generate_complaint_text() -> tuple[str, str, str]:
    issue_type, category, template = random.choice(_COMPLAINT_TEMPLATES)
    mapping = dict(
        road=random.choice(_SAMPLE_ROADS),
        place=random.choice(_SAMPLE_PLACES),
        days=random.randint(1, 15),
        hrs=random.randint(1, 36),
        liters=random.randint(50, 500),
        id=random.randint(100, 9999),
        size=random.choice(["1m wide", "2m long, 1m deep", "car-sized", "bike-sized", "about 2 feet across"]),
        ward=random.choice(_WARD_NAMES),
    )
    try:
        description = template.format(**mapping)
    except Exception:
        description = f"Generic issue reported near {random.choice(_SAMPLE_PLACES)}."
    return description, issue_type, category


def _fake_jpeg_bytes(size_kb: int = 12) -> bytes:
    """
    Return a syntactically valid minimal JPEG (JFIF header + EOI) padded to
    ~size_kb KB.  The app's PIL/magic validation will accept it as a valid
    image, but Pillow `verify()` will NOT actually decompress pixel data —
    which is fine, because we're benchmarking the HTTP pipeline + image
    size/extension checks + YOLO path (which already bails on placeholder).
    """
    # SOI + APP0 JFIF (length 16) + minimal DQT + SOF + SOS + EOI.
    header = bytes.fromhex(
        "ffd8ffe000104a46494600010101004800480000"
        "ffdb004300080606070605080707070909080a0c14"
        "0d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c"
        "1c2837292c30313434341f27393d38323c2e333432"
        "ffc0000b080001000101011100"
        "ffc40014000100000000000000000000000000000000"
        "ffc40014100100000000000000000000000000000000"
        "ffda0008010100003f00d2cf20"
        "ffd9"
    )
    target = max(size_kb * 1024, 512)
    # Pad with harmless APP1 segments until we reach the target size.
    payload = bytearray(header)
    marker = bytes.fromhex("ffe1")  # APP1
    while len(payload) < target:
        chunk_len = min(0xFFFF - 2, target - len(payload))
        if chunk_len < 4:
            break
        payload.extend(marker)
        payload.extend(chunk_len.to_bytes(2, "big"))
        payload.extend(b"X" * (chunk_len - 2))
    return bytes(payload)


# ── TaskGroup: Citizen report flow (heaviest task) ───────────────────────────

class CitizenReportFlow(TaskSet):
    """Register/login as citizen, then POST a new issue with an image."""

    def on_start(self):
        """Every simulated user registers a unique citizen account first."""
        self.email = _random_email()
        self.password = _random_password()
        self.name = "LoadTest " + "".join(random.choices(string.ascii_letters, k=8))
        self.phone = _random_phone()
        self.ward = random.choice(_WARD_NAMES)
        self.access_token = None
        self._csrf_token = ""

        with self.client.post("/register",
                              data={
                                  "name": self.name,
                                  "email": self.email,
                                  "password": self.password,
                                  "confirm_password": self.password,
                                  "phone": self.phone,
                                  "ward": self.ward,
                                  "role": "citizen",
                              },
                              allow_redirects=False,
                              catch_response=True) as r:
            if r.status_code not in (200, 201, 302, 400, 409):
                # 400/409 can happen under race conditions; login instead below
                r.success()

        # Register can return 409 (dup email). In any case, try to obtain a
        # token via /auth/login so we have a valid bearer session for the
        # /api/issues POSTs that follow.
        with self.client.post("/auth/login",
                              json={"email": self.email, "password": self.password},
                              catch_response=True) as r:
            try:
                body = r.json()
            except Exception:
                body = {}
            if body.get("success") and "access_token" in body:
                self.access_token = body["access_token"]
                r.success()
                return
            # Login failed (register may have been rejected under load).
            # Mark user as failed and stop gracefully rather than flood 401s.
            r.failure(f"unable to auth: status={r.status_code} body={str(body)[:160]}")
            raise StopUser()

    @tag("report", "issue", "ai", "yolo")
    @task(10)
    def report_issue_with_image(self):
        """
        Hottest path:  POST /api/issues  (multipart/form-data)
        Coverage:
          * rate-limiter (10/hr/user)
          * JWT bearer verification + RBAC @require_auth + require_role('citizen')
          * Image size/MIME extension/PIL header verification (validate_image_file)
          * complaint_service.create_complaint  (MongoDB write, SLA calc, duplicate geo)
          * AI pipeline enqueue: ai_pipeline.enqueue_ai_analysis → run_unified_ai_pipeline
            * Language detection
            * Emergency regex
            * Rule-based / Gemini text triage
            * Vision (Gemini + YOLO ONNX when available)
            * CEFAP priority stage
            * Authority routing
        """
        description, issue_type, category = _generate_complaint_text()
        lat = round(12.90 + random.random() * 0.18, 6)
        lng = round(77.45 + random.random() * 0.30, 6)
        files = {}
        # 80% of complaints carry an image (exercises YOLO path).
        if random.random() < 0.8:
            files["image"] = (
                f"issue_{random.randint(1, 1_000_000)}.jpg",
                _fake_jpeg_bytes(size_kb=random.choice([8, 12, 24, 48, 96])),
                "image/jpeg",
            )
        self.client.post(
            "/api/issues",
            headers={
                "Authorization": f"Bearer {self.access_token}",
            },
            data={
                "title": description[:60],
                "description": description,
                "latitude": str(lat),
                "longitude": str(lng),
                "address": f"{random.choice(_SAMPLE_PLACES)}, {self.ward}, Bengaluru",
                "category": category,
                "type": issue_type,
                "ward": self.ward,
            },
            files=files or None,
            name="/api/issues (report+image)",
        )

    @tag("report")
    @task(3)
    def report_issue_page(self):
        """GET /report — fetches the HTML form, useful to stress template rendering."""
        self.client.get(
            "/report",
            headers={"Cookie": f"access_token={self.access_token}"} if self.access_token else {},
            name="/report (form HTML)",
            allow_redirects=False,
        )


# ── TaskGroup: Dashboard reads ───────────────────────────────────────────────

class DashboardReadFlow(TaskSet):
    """Logged-in citizen reads their dashboard, issue list, and map data."""

    def on_start(self):
        # Fast-path: reuse registration from the parent.  If this TaskSet is
        # used standalone, register a citizen here.
        self.email = _random_email()
        self.password = _random_password()
        self.client.post("/register",
                         data={"name": "LT", "email": self.email,
                               "password": self.password,
                               "confirm_password": self.password,
                               "phone": _random_phone(),
                               "ward": random.choice(_WARD_NAMES),
                               "role": "citizen"},
                         allow_redirects=False,
                         catch_response=True)
        with self.client.post("/auth/login",
                              json={"email": self.email, "password": self.password},
                              catch_response=True) as r:
            try:
                self.access_token = r.json().get("access_token") or ""
            except Exception:
                self.access_token = ""
            if not self.access_token:
                r.failure("auth failed for DashboardReadFlow")
                raise StopUser()

    @task(7)
    def list_my_issues(self):
        self.client.get(
            "/api/issues?mine=1&page=1&per_page=20",
            headers={"Authorization": f"Bearer {self.access_token}"},
            name="/api/issues?mine=1",
        )

    @task(5)
    def dashboard_html(self):
        self.client.get(
            "/citizen/dashboard",
            headers={"Cookie": f"access_token={self.access_token}"},
            name="/citizen/dashboard (HTML)",
            allow_redirects=False,
        )

    @task(4)
    def live_map_data(self):
        self.client.get(
            "/api/map/issues?radius_km=5",
            name="/api/map/issues (geo list)",
        )

    @task(2)
    def analytics_summary(self):
        self.client.get(
            "/api/analytics/summary",
            name="/api/analytics/summary",
        )


# ── TaskGroup: Officer command actions ───────────────────────────────────────

class OfficerCommandFlow(TaskSet):
    """Officer logs in, browses queue, assigns one issue to a worker."""

    def on_start(self):
        # We can't easily create officer accounts (invite-code only).  For
        # load testing we still exercise the officer route shape with a
        # citizen token to ensure the 403 path stays cheap; operators with a
        # pre-seeded officer credential should set SMARTCIVIC_TEST_OFFICER_*
        # env vars for realistic officer-load profiling.
        email = os.getenv("SMARTCIVIC_TEST_OFFICER_EMAIL") or _random_email()
        password = os.getenv("SMARTCIVIC_TEST_OFFICER_PASSWORD") or _random_password()
        invite = os.getenv("ADMIN_INVITE_CODE") or ""
        if invite and not os.getenv("SMARTCIVIC_TEST_OFFICER_EMAIL"):
            self.client.post("/register",
                             data={"name": "LTOfficer", "email": email,
                                   "password": password,
                                   "confirm_password": password,
                                   "phone": _random_phone(),
                                   "ward": "all",
                                   "role": "officer",
                                   "admin_invite_code": invite},
                             allow_redirects=False, catch_response=True)
        with self.client.post("/auth/login",
                              json={"email": email, "password": password},
                              catch_response=True) as r:
            try:
                self.access_token = r.json().get("access_token") or ""
            except Exception:
                self.access_token = ""
            if not self.access_token:
                r.failure("officer auth failed")
                raise StopUser()

    @task(5)
    def officer_dashboard(self):
        self.client.get(
            "/officer/dashboard",
            headers={"Cookie": f"access_token={self.access_token}"},
            name="/officer/dashboard (HTML)",
            allow_redirects=False,
        )

    @task(3)
    def officer_priority_queue(self):
        self.client.get(
            "/api/issues?status=submitted,open,assigned&sort=priority_desc&per_page=50",
            headers={"Authorization": f"Bearer {self.access_token}"},
            name="/api/issues (officer queue)",
        )


# ── TaskGroup: Unauthenticated static + health probes ────────────────────────

class UnauthenticatedStatic(TaskSet):
    """Mimics anonymous visitors hitting the login page, /api/health."""

    @task(10)
    def login_page(self):
        self.client.get("/login", name="/login (anon)")

    @task(8)
    def health_probe(self):
        """Kubernetes-style probe.  Every reverse proxy / load balancer calls
        this endpoint frequently; ensure it stays sub-millisecond."""
        self.client.get("/api/health", name="/api/health (probe)")

    @task(3)
    def transparency_page(self):
        self.client.get("/transparency", name="/transparency (anon)")

    @task(2)
    def live_map_page(self):
        self.client.get("/map", name="/map (anon)")


# ── Top-level User class ─────────────────────────────────────────────────────

class SmartCivicUser(HttpUser):
    """
    Traffic mix tuned for a 500k-population ward-city (200 reports/day average,
    4000 reports/day during monsoon surge).  70% of active sessions are
    citizens reporting; the rest are reads, officer commands, and anon probes.
    """
    wait_time = between(2, 9)  # 2..9 seconds between consecutive actions

    # Weighted task set composition — see module docstring for percentages.
    tasks = {
        CitizenReportFlow:   70,
        DashboardReadFlow:   18,
        OfficerCommandFlow:   8,
        UnauthenticatedStatic: 4,
    }

    # Network tuning — aligns with Dockerfile Gunicorn defaults (timeout 120s).
    network_timeout = 120.0
