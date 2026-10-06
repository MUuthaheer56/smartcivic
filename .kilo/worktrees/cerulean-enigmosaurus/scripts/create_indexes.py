"""
SmartCivic+ — Database Indexes Setup Script (scripts/ variant)
Configures high-performance indexes for complaints routing, maps, and audit logs.

SAFETY: Every PyMongo call is wrapped in try/except with structured logs to
the JSON logger service.  Missing MongoDB, connection timeouts, or duplicate
index creation (harmless OperationFailure errors) never abort the process —
the script exits with a non-zero code on *unrecoverable* failures only.
"""
import os
import sys
import logging

from pymongo import MongoClient
from pymongo.errors import (
    PyMongoError, ConnectionFailure, ServerSelectionTimeoutError,
    OperationFailure, DuplicateKeyError,
)

# Resolve the project root (one directory up from scripts/) so we can import
# services.logger_service regardless of the process CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from services.logger_service import log_error
except Exception:
    # Standalone fallback — the logger service itself may not be importable if
    # the working directory is wrong.  We'll use print + logging in that case.
    def log_error(msg: str, context=None):
        print(f"[Indexes/ERR] {msg} | context={context}")

logger = logging.getLogger("smartcivic_indexes_script")
if not logger.handlers:
    logger.addHandler(logging.StreamHandler(sys.stdout))
    logger.setLevel(logging.INFO)


def _log(level: str, step: str, message: str, **extra):
    """Uniform structured log line for this script."""
    line = f"[Indexes/{level.upper()}] step={step!r} {message}"
    if extra:
        extras = " ".join(f"{k}={v!r}" for k, v in extra.items())
        line += " | " + extras
    if level == "error":
        logger.error(line)
        try:
            log_error(message, {"step": step, **extra})
        except Exception:
            pass
    else:
        logger.info(line)


def _safe_create_index(col, index, **kwargs) -> bool:
    """Create a single index; never raise, return True on success."""
    col_name = getattr(col, "name", "<unknown>")
    try:
        col.create_index(index, **kwargs)
        return True
    except (OperationFailure, DuplicateKeyError) as exc:
        # OperationFailure usually means "index already exists" which is fine.
        _log("warn", "create_index",
             f"index already exists or skipped on {col_name}",
             index=str(index), reason=str(exc))
        return True
    except PyMongoError as exc:
        _log("error", "create_index",
             f"failed to build index on {col_name}",
             index=str(index), error_type=type(exc).__name__, error=str(exc))
        return False


def setup_indexes():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/smartcivic")
    db_name = mongo_uri.rsplit("/", 1)[-1].split("?")[0] if '/' in mongo_uri else "smartcivic"
    if not db_name or db_name.strip() in ("", "mongodb:", "mongodb"):
        db_name = "smartcivic"

    client = None
    failure_count = 0
    created_count = 0

    # ── Connection with explicit timeout + retries hint ─────────────────────
    try:
        _log("info", "connect",
             f"connecting to MongoDB — db={db_name}",
             uri_host=(mongo_uri.split("@")[-1].split("/")[0] if "@" in mongo_uri
                       else mongo_uri.split("://")[-1].split("/")[0]))
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000,
                             connectTimeoutMS=5000, socketTimeoutMS=15000)
        # Force a ping to surface connection errors BEFORE we start creating
        # indexes — otherwise the first create_index() would hang for 30s.
        client.admin.command("ping")
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        _log("error", "connect",
             "MongoDB unreachable; skipping index creation entirely.",
             error_type=type(exc).__name__, error=str(exc))
        return 2  # specific exit code for "DB down"
    except Exception as exc:
        _log("error", "connect",
             "unexpected connection error; skipping index creation.",
             error_type=type(exc).__name__, error=str(exc))
        return 3

    db = client[db_name]

    # ── Helper for indexing a batch of (index_spec, kwargs) tuples ──────────
    def _index_batch(col_name: str, spec_list) -> None:
        nonlocal failure_count, created_count
        col = db[col_name]
        _log("info", "batch", f"indexing collection {col_name}",
             count=len(spec_list))
        for spec, kwargs in spec_list:
            ok = _safe_create_index(col, spec, **kwargs)
            if ok:
                created_count += 1
            else:
                failure_count += 1

    # ── users ───────────────────────────────────────────────────────────────
    _index_batch("users", [
        ([("email", 1)], {"unique": True}),
        ([("role", 1)], {}),
        ([("status", 1)], {}),
    ])

    # ── issues ──────────────────────────────────────────────────────────────
    _index_batch("issues", [
        ([("issue_id", 1)], {"unique": True}),
        ([("status", 1)], {}),
        ([("ward", 1)], {}),
        ([("department", 1)], {}),
        ([("severity", 1)], {}),
        ([("citizen_id", 1)], {}),
        ([("worker_id", 1)], {}),
        ([("created_at", -1)], {}),
        ([("sla_deadline", 1), ("status", 1)], {}),
        ([("status", 1), ("sla_deadline", 1)], {}),
        ([("location", "2dsphere")], {}),
        ([("priority_score", -1)], {}),
    ])

    # ── audit_logs ──────────────────────────────────────────────────────────
    _index_batch("audit_logs", [
        ([("entity_id", 1)], {}),
        ([("timestamp", -1)], {}),
    ])

    # ── notifications ───────────────────────────────────────────────────────
    _index_batch("notifications", [
        ([("user_id", 1), ("is_read", 1)], {}),
        ([("recipient_id", 1), ("read", 1)], {}),
        ([("created_at", -1)], {}),
    ])

    # ── infrastructure ──────────────────────────────────────────────────────
    _index_batch("infrastructure", [
        ([("segment_id", 1)], {"unique": True}),
        ([("location", "2dsphere")], {}),
        ([("health_score", 1)], {}),
    ])

    # ── civicpulse_predictions ──────────────────────────────────────────────
    _index_batch("civicpulse_predictions", [
        ("segment_id", {"unique": True}),
        ("ward", {}),
        ([("days_until_failure", 1)], {}),
        ("risk_band", {}),
    ])

    _log("info", "summary",
         "MongoDB index configurations finished.",
         created=created_count, failures=failure_count)

    if failure_count:
        _log("warn", "summary",
             f"{failure_count} index(es) failed — review prior log lines.")
    return 1 if failure_count > 0 else 0


setup_production_indexes = setup_indexes

if __name__ == '__main__':
    try:
        rc = setup_indexes()
    except Exception as exc:
        # Last-resort safety net: never let an unexpected traceback bubble
        # to the shell without a structured log entry.
        _log("error", "fatal", "unhandled top-level exception",
             error_type=type(exc).__name__, error=str(exc))
        rc = 99
    sys.exit(rc)
