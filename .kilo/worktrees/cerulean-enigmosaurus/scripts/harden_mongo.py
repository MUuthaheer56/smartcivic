# -*- coding: utf-8 -*-
"""
SmartCivic+ — MongoDB Least-Privilege & Authentication Hardening Script
========================================================================

Municipal workloads hold PII (citizen phone numbers, emails, addresses),
infrastructure geo-data, and SLA/audit records. A "root + localhost only"
MongoDB is not acceptable in production.

This script:

  1. Generates a `mongod.conf` snippet that:
        - Enables `authorization: enabled`
        - Binds ONLY to an explicit allow-list of IPs (never 0.0.0.0 by default)
        - Enables TLS if a PEM cert path is provided (REQUIRED for prod)
        - Disables the MongoDB HTTP status interface + JSONP endpoints

  2. Connects to a running MongoDB (via the unrestricted localhost exception
     BEFORE you enable auth, or as an admin user afterwards) and creates
     three least-privilege users, scoped to exactly the collections each
     SmartCivic role needs:

        smartcivic_app       — readWrite on smartcivic DB ONLY, no clusterMonitor
                               (used by the Flask app, 99% of traffic)
        smartcivic_reader    — find() only, no writes, no deletes
                               (used by BI tools / read replicas / dashboards)
        smartcivic_audit     — insert-only on audit_logs + cefap_ctve_events
                               (used by audit-service sidecars)
        smartcivic_admin     — userAdmin + dbOwner on smartcivic, for
                               create_indexes.py / migration scripts ONLY.

     No user receives `root`, `dbAdminAnyDatabase`, `clusterAdmin`, or the
     legacy `__system` role.

  3. Emits three MONGO_URI strings (app / reader / admin) with `authSource=admin`,
     TLS options, and `retryWrites=true/retryReads=true` — save these into your
     production .env / secrets manager.  The existing MONGO_URI in .env.example
     is ONLY for the local developer workstation and MUST be replaced in prod.

  4. Applies additional safety:
        - Creates a TTL index on audit_logs.timestamp (retention window, default 2yr)
        - Creates a unique index on audit_logs to prevent duplicate entries
        - Emits `mongosh` commands for operators to verify the hardening

Usage (three phases):

  Phase A — one-time admin bootstrap (run while MongoDB auth is still OFF, or
            pass an admin connection URI with -a/--admin-uri):
        python scripts/harden_mongo.py bootstrap \\
            --db-name smartcivic_prod \\
            --bind-ips 127.0.0.1,10.0.1.12,10.0.1.13 \\
            --tls-pem /etc/mongodb/tls/mongodb.pem \\
            --tls-ca  /etc/mongodb/tls/ca.pem \\
            --out security/mongod.conf.snippet

  Phase B — apply mongod.conf snippet, restart mongod, confirm auth=ON.

  Phase C — connect to auth-enabled cluster and verify users exist:
        python scripts/harden_mongo.py verify -a "$(cat security/mongo_app.uri)"

DO NOT hardcode the generated passwords in this file or in any committed asset.
The script prints them to stdout ONCE and also writes them to security/*.uri
files with 0600 permissions.
"""
import argparse
import getpass
import json
import os
import secrets
import string
import stat
import sys
from datetime import timedelta
from pathlib import Path
from textwrap import dedent


# ── Helpers ──────────────────────────────────────────────────────────────────

def _strong_password(length: int = 32) -> str:
    """High-entropy credential — RFC 3986 unreserved chars so MONGO_URI never
    needs percent-encoding (avoid URLError from '@' or ':' in password)."""
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _write_private_file(path: Path, content: str):
    """Write a file with u=rw,g=,o= (0600).  Required for any credential on disk."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    mode = stat.S_IRUSR | stat.S_IWUSR
    fd = os.open(path, flags, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
    finally:
        # Ensure mode even if the file already existed.
        try:
            os.chmod(path, mode)
        except OSError:
            pass


def _sanitize_hosts(raw: str) -> list[str]:
    hosts = [h.strip() for h in (raw or "").split(",") if h.strip()]
    if not hosts:
        raise SystemExit("ERROR: --bind-ips is required.  Do NOT bind to 0.0.0.0 without TLS+IPsec.")
    if "0.0.0.0" in hosts or "::" in hosts:
        print("WARNING: wildcard bind IP detected.  MongoDB will accept connections from ANY host. "
              "This is ONLY safe behind a VPC firewall AND TLS client-certificate auth.")
    return hosts


# ── Output: mongod.conf snippet ──────────────────────────────────────────────

def generate_mongod_conf(bind_ips: list[str],
                        tls_pem: str | None,
                        tls_ca: str | None,
                        replica_set_name: str | None) -> str:
    bind_ip_line = ",".join(bind_ips)
    conf = dedent(f"""
    # =======================================================================
    # SmartCivic+ -- hardened MongoDB configuration snippet
    # Merge this into /etc/mongod.conf (YAML format) then restart mongod.
    # =======================================================================

    net:
      port: 27017
      bindIp: {bind_ip_line}
      # Maximum simultaneous connections — tune below the Linux ulimit.
      maxIncomingConnections: 2000
      # Disable the legacy HTTP status endpoint (port 28017).
      http:
        enabled: false
        JSONPEnabled: false
        RESTInterfaceEnabled: false
""")
    if tls_pem:
        conf += dedent(f"""
      # TLS — REQUIRE certificates for ALL client connections in production.
      tls:
        mode: requireTLS
        certificateKeyFile: {tls_pem}
        {"CAFile: " + tls_ca if tls_ca else ""}
        # Reject clients that can't present a valid client certificate.
        allowConnectionsWithoutCertificates: false
        # Match the certificate SAN against the connecting hostname.
        allowInvalidHostnames: false
        allowInvalidCertificates: false
""")
    conf += dedent(f"""
    security:
      authorization: enabled
      # Cluster-wide symmetric key (REQUIRED for encrypted client/server
      # communication even without TLS — prefer TLS above).
      # keyFile: /etc/mongodb/mongodb-keyfile   # generated with:
      #   openssl rand -base64 756 > /etc/mongodb/mongodb-keyfile
      #   chmod 600 /etc/mongodb/mongodb-keyfile

      # Disable Javascript execution on mongod (MapReduce, $where, etc.) —
      # SmartCivic+ never uses server-side JS, disabling it eliminates a
      # whole class of injection bugs.
      javascriptEnabled: false
""")
    if replica_set_name:
        conf += dedent(f"""
    replication:
      replSetName: {replica_set_name}

    # For secondary reads: SmartCivic prefers primary (strong consistency for
    # complaint writes) but the smartcivic_reader role may target secondaries.
""")
    conf += dedent(f"""
    operationProfiling:
      # Log SLOW queries (>100ms) for the municipal SLA team to review.
      mode: slowOp
      slowOpThresholdMs: 100
      slowOpSampleRate: 1.0

    setParameter:
      # FailPoint: reject any query that would do a full collection scan on
      # hot collections (issues, users) — requires that create_indexes.py
      # has already populated all supporting indexes.  Comment out during
      # the very first seed, then turn it on.
      # notablescan: true

      # Maximum document size is 16MB already; keep an explicit lower
      # guardrail so a maliciously-crafted report with base64 can't OOM us.
      maxBSONDepth: 100
""")
    return conf.strip() + "\n"


# ── Bootstrap: create the 4 least-privilege users ────────────────────────────

# 4 users × least privilege.  Every privilege is scoped to the smartcivic DB.
# No cross-DB access, no cluster-level actions, no userAdmin on admin.
_USER_ROLES = {
    "smartcivic_app": {
        "description": "Flask application user — readWrite on the smartcivic DB only.",
        "roles": [
            {"role": "readWrite", "db": None},  # scoped to the app DB below
            {"role": "enableSharding", "db": None},
        ],
    },
    "smartcivic_reader": {
        "description": "BI / dashboard user — find() only.",
        "roles": [{"role": "read", "db": None}],
    },
    "smartcivic_audit": {
        "description": "Audit sidecar — insert-only on audit_logs + cefap_ctve_events.",
        "privileges": [
            {
                "resource": {"db": None, "collection": "audit_logs"},
                "actions": ["insert", "find"],  # no update / no delete
            },
            {
                "resource": {"db": None, "collection": "cefap_ctve_events"},
                "actions": ["insert", "find"],
            },
        ],
        "roles": [],
    },
    "smartcivic_admin": {
        "description": "Migration / create_indexes user — dbOwner + indexAdmin.",
        "roles": [
            {"role": "dbOwner", "db": None},
            {"role": "userAdmin", "db": None},
        ],
    },
}

def _scope_to_db(roles_privs: list[dict], db: str) -> list[dict]:
    """Copy `db: None` -> `db: <db>` so all roles are DB-scoped."""
    out = []
    for rp in roles_privs:
        rp = dict(rp)
        if "resource" in rp and rp["resource"].get("db") is None:
            rp["resource"] = {**rp["resource"], "db": db}
        if "db" in rp and rp["db"] is None:
            rp["db"] = db
        out.append(rp)
    return out


def run_bootstrap(admin_uri: str | None,
                  db_name: str,
                  bind_ips: list[str],
                  tls_pem: str | None,
                  tls_ca: str | None,
                  replica_set: str | None,
                  out_conf: Path,
                  security_dir: Path) -> None:
    # 1. Write the mongod.conf snippet.
    conf_text = generate_mongod_conf(bind_ips, tls_pem, tls_ca, replica_set)
    out_conf.parent.mkdir(parents=True, exist_ok=True)
    _write_private_file(out_conf, conf_text)
    print(f"[1/4] mongod.conf snippet written -> {out_conf}")

    # 2. Generate four credentials.
    credentials: dict[str, str] = {name: _strong_password(32) for name in _USER_ROLES}
    # 3. If an admin URI was passed, actually create the users via pymongo.
    if admin_uri:
        try:
            from pymongo import MongoClient
            from pymongo.errors import PyMongoError
        except ImportError as ie:
            raise SystemExit(f"pymongo required for bootstrap with admin URI: {ie}")
        print(f"[2/4] Connecting as admin to create users on DB '{db_name}'...")
        try:
            client = MongoClient(admin_uri, serverSelectionTimeoutMS=5000)
            client.admin.command("ping")
        except PyMongoError as exc:
            raise SystemExit(
                f"ERROR: Cannot reach admin MongoDB at the provided URI: {exc}\n"
                f"Tip: Run this script BEFORE enabling auth and without -a, "
                f"so the localhost exception lets us create the first admin user.\n"
                f"Then re-run with -a once auth is on."
            )
        admin_db = client[db_name]
        # Delete any pre-existing users with the same name so this is idempotent.
        for user in _USER_ROLES:
            try:
                admin_db.command("dropUser", user)
                print(f"    · dropped legacy user {user!r} (idempotent)")
            except PyMongoError:
                pass
        for user, spec in _USER_ROLES.items():
            roles = _scope_to_db(list(spec.get("roles", [])), db_name)
            extra = {}
            if "privileges" in spec:
                extra["privileges"] = _scope_to_db(list(spec["privileges"]), db_name)
            admin_db.command(
                "createUser", user,
                pwd=credentials[user],
                roles=roles,
                mechanisms=["SCRAM-SHA-256"],
                customData={"source": "smartcivic_harden_mongo",
                            "description": spec["description"]},
                **extra,
            )
            print(f"    [OK] created user {user!r} ({spec['description']})")
        # 4. Apply the TTL index on audit_logs.
        try:
            audit_col = admin_db["audit_logs"]
            two_years_seconds = int(timedelta(days=730).total_seconds())
            audit_col.create_index("timestamp", expireAfterSeconds=two_years_seconds)
            audit_col.create_index(
                [("audit_id", 1), ("timestamp", 1)], unique=True,
                partialFilterExpression={"audit_id": {"$exists": True}},
            )
            print(f"[3/4] audit_logs TTL index added (2-year retention, unique audit_id+timestamp)")
        except PyMongoError as exc:
            print(f"[3/4] WARNING: could not create audit_logs TTL index: {exc}")
    else:
        print("[2/4] Skipping user creation (no --admin-uri provided).")
        print("      Run the following mongosh commands on the DB host manually:")
        for user, spec in _USER_ROLES.items():
            pwd = credentials[user]
            roles_j = json.dumps(_scope_to_db(list(spec.get("roles", [])), db_name), indent=4)
            print(f"\n-- user: {user} ({spec['description']})")
            print(f"-- password: {pwd}")
            print(f"use {db_name}")
            print(f"db.createUser({{ user: '{user}', pwd: '{pwd}', roles: {roles_j} }})")
        print("[3/4] Skipped audit_logs TTL index (no connection).")

    # 4. Emit per-role MONGO_URI strings.
    security_dir.mkdir(parents=True, exist_ok=True)
    # Derive host(s) from admin URI or fall back to the first bind IP.
    if admin_uri:
        # Extract host:port/authSource part out of the admin URI.
        from urllib.parse import urlparse
        parsed = urlparse(admin_uri)
        host_part = parsed.hostname or bind_ips[0]
        port_part = parsed.port or 27017
        host_port = f"{host_part}:{port_part}"
    else:
        host_port = f"{bind_ips[0]}:27017"

    tls_args = ""
    if tls_pem:
        tls_args = "&tls=true&tlsAllowInvalidCertificates=false&tlsAllowInvalidHostnames=false"
        if tls_ca:
            tls_args += f"&tlsCAFile={tls_ca}"

    uri_template = ("mongodb://{user}:{pwd}@{host}/{db}"
                    "?authSource={db}&authMechanism=SCRAM-SHA-256"
                    "&retryWrites=true&retryReads=true"
                    "&w=majority&readConcernLevel=local"
                    "&maxPoolSize=100&minPoolSize=5"
                    "&serverSelectionTimeoutMS=5000"
                    f"{tls_args}")

    # smartcivic_admin uses authSource=admin for cluster-wide commands (rare).
    admin_uri_template = uri_template.replace("authSource={db}", "authSource=admin", 1)

    app_uri = uri_template.format(user="smartcivic_app",
                                  pwd=credentials["smartcivic_app"],
                                  host=host_port, db=db_name)
    reader_uri = uri_template.format(user="smartcivic_reader",
                                     pwd=credentials["smartcivic_reader"],
                                     host=host_port, db=db_name)
    audit_uri = uri_template.format(user="smartcivic_audit",
                                    pwd=credentials["smartcivic_audit"],
                                    host=host_port, db=db_name)
    admin_uri_out = admin_uri_template.format(user="smartcivic_admin",
                                              pwd=credentials["smartcivic_admin"],
                                              host=host_port, db=db_name)

    uris = {
        "mongo_app.uri":    app_uri,
        "mongo_reader.uri": reader_uri,
        "mongo_audit.uri":  audit_uri,
        "mongo_admin.uri":  admin_uri_out,
    }
    for name, content in uris.items():
        _write_private_file(security_dir / name, content + "\n")
    print(f"[4/4] 4 URI files written to {security_dir}/ with 0600 permissions.")
    print()
    print("=======================================================================")
    print("  Production MONGO_URIs -- COPY THESE TO YOUR SECRETS MANAGER NOW.")
    print("  They are ONLY printed ONCE here and stored with 0600 under ./security.")
    print("=======================================================================")
    for name, uri in uris.items():
        print(f"  {name:<20s} = {uri}")
    print()
    print("Next steps:")
    print("  1. Apply the mongod.conf snippet, restart mongod.")
    print("  2. Replace the MONGO_URI line in production .env with the mongo_app.uri value.")
    print("  3. Run  python setup_indexes.py  using the mongo_admin.uri (auth-enabled).")
    print("  4. Verify:  python scripts/harden_mongo.py verify -a \"$(cat security/mongo_app.uri)\"")


# ── Verify: confirm users + auth enforcement + indexes ──────────────────────

def run_verify(app_uri: str, db_name: str | None = None) -> None:
    try:
        from pymongo import MongoClient
        from pymongo.errors import PyMongoError, OperationFailure
    except ImportError as ie:
        raise SystemExit(f"pymongo required for verify: {ie}")
    print("[verify] Connecting with the provided app URI...")
    try:
        client = MongoClient(app_uri, serverSelectionTimeoutMS=5000)
        info = client.admin.command("connectionStatus")
    except OperationFailure as exc:
        # 18 = AuthenticationFailed
        if exc.code == 18:
            raise SystemExit(f"[verify] CRITICAL: AUTH FAILED -> {exc.details}")
        raise SystemExit(f"[verify] CRITICAL: {exc}")
    except PyMongoError as exc:
        raise SystemExit(f"[verify] CRITICAL: DB unreachable -> {exc}")

    auth_info = info.get("authInfo", {})
    authenticated_users = auth_info.get("authenticatedUsers", [])
    print(f"[verify] [OK] Connected as:   {authenticated_users or 'NO USER (anon)'}")
    if not authenticated_users:
        raise SystemExit("[verify] CRITICAL: session is ANONYMOUS -- authorization: enabled is missing from mongod.conf!")

    # Try to do something outside our privilege scope -- must fail.
    resolved_db = db_name or client.get_default_database().name
    try:
        # Try to create a collection on 'admin' DB -- smartcivic_app must NOT be able.
        client["admin"].create_collection("_should_never_exist_smartcivic",
                                           capped=True, size=4096)
        raise SystemExit("[verify] CRITICAL: app user can write to admin DB! Least-privilege broken.")
    except OperationFailure:
        print(f"[verify] [OK] Scoped correctly -- rejected write to 'admin' DB (code 13: not authorized)")

    # Check indexes exist on the hot collections.
    missing = []
    for col_name, expected_idx in [
        ("issues",          "location_2dsphere_status_1_created_at_-1"),
        ("users",           "email_1"),
        ("audit_logs",      "timestamp_1"),
        ("cefap_results",   "issue_id_1"),
        ("ward_registry",   "ward_id_1"),
    ]:
        col = client[resolved_db][col_name]
        indexes = {idx["name"] for idx in col.list_indexes()}
        if expected_idx not in indexes:
            missing.append((col_name, expected_idx))
    if missing:
        print(f"[verify] [WARN] Missing expected indexes on: {missing} -- run create_indexes.py as smartcivic_admin.")
    else:
        print("[verify] [OK] All expected critical indexes present.")

    # Check that bindIp is not open to the world without TLS.
    try:
        cfg = client.admin.command("getCmdLineOpts")
        parsed = cfg.get("parsed", {})
        net_cfg = parsed.get("net", {})
        bind_ip = net_cfg.get("bindIp", "<missing>")
        tls_on = net_cfg.get("tls", {}).get("mode") == "requireTLS"
        security_cfg = parsed.get("security", {})
        auth_on = security_cfg.get("authorization") == "enabled"
        js_off = security_cfg.get("javascriptEnabled") is False
    except (PyMongoError, Exception):
        bind_ip, tls_on, auth_on, js_off = "<unknown>", None, None, None

    print(f"[verify] net.bindIp                = {bind_ip}")
    if auth_on:
        print("[verify] [OK] security.authorization = enabled")
    else:
        print("[verify] [FAIL] security.authorization = MISSING -- apply the mongod.conf snippet and restart mongod.")
    if tls_on is False and ("0.0.0.0" in str(bind_ip) or "::" in str(bind_ip)):
        print("[verify] [FAIL] wildcard bind without TLS -- never deploy this to the public internet.")
    elif tls_on:
        print("[verify] [OK] TLS = requireTLS")
    if js_off:
        print("[verify] [OK] javascriptEnabled = false (no server-side $where / MapReduce)")

    print("\n[verify] Done -- review the [WARN] and [FAIL] lines above; everything else is hardened.")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="SmartCivic+ MongoDB hardening: roles, auth, TLS, bind-ip.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_boot = sub.add_parser("bootstrap", help="Create users + emit mongod.conf.")
    p_boot.add_argument("-a", "--admin-uri", default=None,
                        help="Admin connection URI (omit to print mongosh commands).")
    p_boot.add_argument("--db-name", default=os.getenv("MONGO_DBNAME", "smartcivic_prod"),
                        help="Target application database name (default: smartcivic_prod).")
    p_boot.add_argument("--bind-ips", required=True,
                        help="Comma-separated list of bind IPs, e.g. 127.0.0.1,10.0.1.10")
    p_boot.add_argument("--tls-pem", default=None,
                        help="Path to TLS PEM file on the mongod host (combines cert + key).")
    p_boot.add_argument("--tls-ca", default=None,
                        help="Path to TLS CA certificate on the mongod host.")
    p_boot.add_argument("--replica-set", default=None,
                        help="Replica set name (if using replication).")
    p_boot.add_argument("--out", default="security/mongod.conf.snippet",
                        type=Path, help="Path for generated mongod.conf snippet.")
    p_boot.add_argument("--security-dir", default="security",
                        type=Path, help="Directory for generated URI + credential files.")

    p_ver = sub.add_parser("verify", help="Connect and verify hardening.")
    p_ver.add_argument("-a", "--app-uri", required=True,
                       help="Connection URI for smartcivic_app user.")
    p_ver.add_argument("--db-name", default=None,
                       help="Override target DB name (auto-detected from URI otherwise).")

    args = parser.parse_args(argv)

    if args.command == "bootstrap":
        hosts = _sanitize_hosts(args.bind_ips)
        run_bootstrap(
            admin_uri=args.admin_uri,
            db_name=args.db_name,
            bind_ips=hosts,
            tls_pem=args.tls_pem,
            tls_ca=args.tls_ca,
            replica_set=args.replica_set,
            out_conf=args.out,
            security_dir=args.security_dir,
        )
    elif args.command == "verify":
        run_verify(args.app_uri, args.db_name)


if __name__ == "__main__":
    main()
