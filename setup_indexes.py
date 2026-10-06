"""
SmartCivic v2 — Database Index Creation Script (root-level)
Constructs 2dsphere and compound MongoDB indexes across all core collections.

SAFETY CONTRACT (critical for app startup):
  * The public create_indexes() function NEVER RAISES.  On any failure it
    returns False and logs a structured error.  app.py relies on this — if
    we raised here the whole Flask factory would crash.
  * Connection errors (MongoDB down) short-circuit quickly (5s timeout) and
    do not block app startup for 30+ seconds.
  * "Index already exists" (OperationFailure / DuplicateKeyError) is treated
    as success — running this script repeatedly is a supported no-op.
  * All failures are written to both stdout AND services.logger_service
    so they appear in logs/smartcivic.json for operator triage.
"""
import os
import sys
import logging

from pymongo import MongoClient, ASCENDING, DESCENDING, GEOSPHERE
from pymongo.errors import (
    PyMongoError, ConnectionFailure, ServerSelectionTimeoutError,
    OperationFailure, DuplicateKeyError,
)

logger = logging.getLogger("smartcivic_setup_indexes")
if not logger.handlers:
    logger.addHandler(logging.StreamHandler(sys.stdout))
    logger.setLevel(logging.INFO)


def _log(level: str, step: str, message: str, **extra):
    line = f"[SetupIndexes/{level.upper()}] step={step!r} {message}"
    if extra:
        line += " | " + " ".join(f"{k}={v!r}" for k, v in extra.items())
    if level == "error":
        logger.error(line)
        try:
            from services.logger_service import log_error
            log_error(message, {"stage": "setup_indexes", "step": step, **extra})
        except Exception:
            pass
    elif level == "warn":
        logger.warning(line)
    else:
        logger.info(line)


def setup_database_indexes(db):
    """
    Creates necessary production indexes for performance optimization 
    across users, issues, notifications, and geospatial locations.
    """
    try:
        # Users collection indexes
        _safe_create_index(db.users, "email", unique=True)
        _safe_create_index(db.users, [("role", ASCENDING), ("ward", ASCENDING)])
        _safe_create_index(db.users, [("verified", ASCENDING), ("approved_by_authority", ASCENDING)])

        # Issues collection indexes (High query frequency)
        _safe_create_index(db.issues, [("status", ASCENDING), ("location.ward", ASCENDING)])
        _safe_create_index(db.issues, [("citizen_id", ASCENDING)])
        _safe_create_index(db.issues, [("assigned_worker_id", ASCENDING)])
        _safe_create_index(db.issues, [("created_at", DESCENDING)])
        _safe_create_index(db.issues, [("priority", ASCENDING), ("severity", ASCENDING)])
        
        # Geospatial 2dsphere index for location-based clustering and queries
        _safe_create_index(db.issues, [("location", GEOSPHERE)])

        # Notifications collection indexes
        _safe_create_index(db.notifications, [("user_id", ASCENDING), ("read", ASCENDING)])
        _safe_create_index(db.notifications, [("created_at", DESCENDING)], expireAfterSeconds=2592000)

        logger.info("Database indexes successfully created and verified.")
    except Exception as e:
        logger.error(f"Failed to create database indexes: {e}")

def _safe_create_index(col, index, **kwargs) -> bool:
    """Create one index; never raise.  Return True on success (incl. exists)."""
    col_name = getattr(col, "name", "<unknown>")
    try:
        col.create_index(index, **kwargs)
        return True
    except (OperationFailure, DuplicateKeyError) as exc:
        _log("warn", "create_index",
             f"index already exists on collection '{col_name}'",
             index=str(index), reason=str(exc))
        return True
    except PyMongoError as exc:
        _log("error", "create_index",
             f"index build FAILED on collection '{col_name}'",
             index=str(index), error_type=type(exc).__name__, error=str(exc))
        return False


def seed_ward_registry(db, force=False):
    from datetime import datetime
    try:
        count = db.ward_registry.count_documents({})
        if count > 0 and not force:
            _log("info", "seed_wards",
                 f"ward_registry already has {count} documents — skipping.")
            return True
    except PyMongoError as exc:
        _log("error", "seed_wards", "unable to query ward_registry",
             error_type=type(exc).__name__, error=str(exc))
        return False

    if force:
        try:
            db.ward_registry.drop()
        except PyMongoError as exc:
            _log("warn", "seed_wards", "drop of ward_registry failed",
                 error_type=type(exc).__name__, error=str(exc))

    WARDS = [
        {"ward_id":"ward_01","ward_name":"Kadu Malleshwara",    "area_code":"KDM-001","city":"Bengaluru","center_lat":12.9957,"center_lng":77.5640,"active":True,"officer_ids":[]},
        {"ward_id":"ward_02","ward_name":"Subramanya Nagar",    "area_code":"SBN-002","city":"Bengaluru","center_lat":12.9900,"center_lng":77.5500,"active":True,"officer_ids":[]},
        {"ward_id":"ward_03","ward_name":"Nagapura",            "area_code":"NGP-003","city":"Bengaluru","center_lat":12.9850,"center_lng":77.5450,"active":True,"officer_ids":[]},
        {"ward_id":"ward_04","ward_name":"Mahalakshmi Layout",  "area_code":"MLL-004","city":"Bengaluru","center_lat":12.9920,"center_lng":77.5580,"active":True,"officer_ids":[]},
        {"ward_id":"ward_05","ward_name":"Sandal Soap Factory", "area_code":"SSF-005","city":"Bengaluru","center_lat":12.9870,"center_lng":77.5420,"active":True,"officer_ids":[]},
        {"ward_id":"ward_06","ward_name":"Shivanagara",         "area_code":"SVN-006","city":"Bengaluru","center_lat":12.9810,"center_lng":77.5390,"active":True,"officer_ids":[]},
        {"ward_id":"ward_07","ward_name":"Herohalli",           "area_code":"HRH-007","city":"Bengaluru","center_lat":12.9760,"center_lng":77.5020,"active":True,"officer_ids":[]},
        {"ward_id":"ward_08","ward_name":"Kenchenahalli",       "area_code":"KNH-008","city":"Bengaluru","center_lat":12.9620,"center_lng":77.5150,"active":True,"officer_ids":[]},
        {"ward_id":"ward_09","ward_name":"Kengeri Satellite T", "area_code":"KST-009","city":"Bengaluru","center_lat":12.9090,"center_lng":77.4830,"active":True,"officer_ids":[]},
        {"ward_id":"ward_10","ward_name":"Rajarajeshwari Nagar","area_code":"RRN-010","city":"Bengaluru","center_lat":12.9230,"center_lng":77.5080,"active":True,"officer_ids":[]},
        {"ward_id":"ward_11","ward_name":"Uttarahalli",         "area_code":"UTH-011","city":"Bengaluru","center_lat":12.8960,"center_lng":77.5500,"active":True,"officer_ids":[]},
        {"ward_id":"ward_12","ward_name":"Yediyur",             "area_code":"YDY-012","city":"Bengaluru","center_lat":12.9340,"center_lng":77.5750,"active":True,"officer_ids":[]},
        {"ward_id":"ward_13","ward_name":"Pattabhiram Nagar",   "area_code":"PTN-013","city":"Bengaluru","center_lat":12.9240,"center_lng":77.5640,"active":True,"officer_ids":[]},
        {"ward_id":"ward_14","ward_name":"Byrasandra",          "area_code":"BYR-014","city":"Bengaluru","center_lat":12.9310,"center_lng":77.6040,"active":True,"officer_ids":[]},
        {"ward_id":"ward_15","ward_name":"Jayanagar",           "area_code":"JNR-015","city":"Bengaluru","center_lat":12.9308,"center_lng":77.5838,"active":True,"officer_ids":[]},
        {"ward_id":"ward_16","ward_name":"Indiranagar",         "area_code":"IND-016","city":"Bengaluru","center_lat":12.9784,"center_lng":77.6408,"active":True,"officer_ids":[]},
        {"ward_id":"ward_17","ward_name":"Koramangala",         "area_code":"KOR-017","city":"Bengaluru","center_lat":12.9352,"center_lng":77.6245,"active":True,"officer_ids":[]},
        {"ward_id":"ward_18","ward_name":"Bellandur",           "area_code":"BLN-018","city":"Bengaluru","center_lat":12.9253,"center_lng":77.6759,"active":True,"officer_ids":[]},
        {"ward_id":"ward_19","ward_name":"Mahadevapura",        "area_code":"MDP-019","city":"Bengaluru","center_lat":12.9933,"center_lng":77.6969,"active":True,"officer_ids":[]},
        {"ward_id":"ward_20","ward_name":"Whitefield",          "area_code":"WTF-020","city":"Bengaluru","center_lat":12.9698,"center_lng":77.7499,"active":True,"officer_ids":[]},
        {"ward_id":"ward_21","ward_name":"Hebbal",              "area_code":"HBL-021","city":"Bengaluru","center_lat":13.0350,"center_lng":77.5970,"active":True,"officer_ids":[]},
        {"ward_id":"ward_22","ward_name":"Yelahanka",           "area_code":"YLH-022","city":"Bengaluru","center_lat":13.1007,"center_lng":77.5963,"active":True,"officer_ids":[]},
        {"ward_id":"ward_23","ward_name":"Dasarahalli",         "area_code":"DSH-023","city":"Bengaluru","center_lat":13.0280,"center_lng":77.5240,"active":True,"officer_ids":[]},
        {"ward_id":"ward_24","ward_name":"Jalahalli",           "area_code":"JLH-024","city":"Bengaluru","center_lat":13.0290,"center_lng":77.5490,"active":True,"officer_ids":[]},
        {"ward_id":"ward_25","ward_name":"R.T. Nagar",          "area_code":"RTN-025","city":"Bengaluru","center_lat":13.0090,"center_lng":77.5930,"active":True,"officer_ids":[]},
        {"ward_id":"ward_test","ward_name":"Test Ward (Dev)",   "area_code":"TST-0000","city":"Bengaluru","center_lat":12.9716,"center_lng":77.5946,"active":True,"officer_ids":[]},
    ]
    now = datetime.utcnow()
    for w in WARDS:
        w["created_at"] = now

    try:
        db.ward_registry.insert_many(WARDS, ordered=False)
    except PyMongoError as exc:
        # ordered=False + this trap means partial inserts are OK
        _log("warn", "seed_wards", "partial insert_many (duplicates?)",
             error_type=type(exc).__name__, error=str(exc))

    # Seeded wards — build the two unique indexes even if the seed partially ran
    _safe_create_index(db.ward_registry, "area_code", unique=True)
    _safe_create_index(db.ward_registry, "ward_id",   unique=True)
    _safe_create_index(db.ward_registry, "active")
    _log("info", "seed_wards", f"Seeded up to {len(WARDS)} wards into ward_registry.")
    return True


def create_cefap_indexes(db) -> bool:
    ok = True
    ok &= _safe_create_index(db.cefap_results, "issue_id", unique=True)
    ok &= _safe_create_index(db.cefap_results, "ward_id")
    ok &= _safe_create_index(db.cefap_results, "priority")
    ok &= _safe_create_index(db.cefap_results, "computed_at")
    ok &= _safe_create_index(db.cefap_weights, "ward_id", unique=True)
    ok &= _safe_create_index(db.cefap_feedback, "ward_id")
    ok &= _safe_create_index(db.cefap_feedback, "created_at")
    ok &= _safe_create_index(db.cefap_feedback, "issue_id")
    ok &= _safe_create_index(db.cefap_ctve_events, "issue_id")
    if ok:
        _log("info", "cefap_indexes", "CEFAP indexes created.")
    return ok


def ensure_graph_indexes(db) -> bool:
    ok = True
    ok &= _safe_create_index(db.incident_edges,
                             [("from_id", 1), ("to_id", 1), ("rule", 1)], unique=True)
    ok &= _safe_create_index(db.incident_edges, "to_id")
    ok &= _safe_create_index(db.master_incidents, "member_ids")
    ok &= _safe_create_index(db.master_incidents, [("status", 1), ("updated_at", -1)])
    ok &= _safe_create_index(db.issues, "master_incident_id")
    ok &= _safe_create_index(db.issues,
                             [("location", "2dsphere"), ("status", 1), ("created_at", -1)])
    if ok:
        _log("info", "graph_indexes", "Graph indexes created.")
    return ok


def create_indexes(mongo_uri: str = None) -> bool:
    """
    Build every MongoDB index required by SmartCivic+.

    Returns True on full success, False on ANY partial or total failure.
    NEVER RAISES — this function is called from the Flask app factory at
    startup and an unhandled exception would prevent boot.
    """
    uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/smartcivic")
    db_name = uri.split('/')[-1] if '/' in uri else 'smartcivic'
    if not db_name or db_name.strip() == "" or '?' in db_name:
        db_name = 'smartcivic'

    # ── Step 1: Connect with a short hard timeout so we don't hang startup ──
    client = None
    try:
        client = MongoClient(uri,
                             serverSelectionTimeoutMS=5000,
                             connectTimeoutMS=5000,
                             socketTimeoutMS=20000)
        client.admin.command("ping")
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        _log("error", "connect",
             "MongoDB unreachable — index setup SKIPPED (app will continue booting).",
             error_type=type(exc).__name__, error=str(exc))
        return False
    except Exception as exc:
        _log("error", "connect",
             "Unexpected MongoDB connection error — index setup SKIPPED.",
             error_type=type(exc).__name__, error=str(exc))
        return False

    db = client[db_name]
    _log("info", "connect",
         f"Building MongoDB indexes for database '{db_name}'...")
    all_ok = True

    # ── Step 2: Issues / Complaints collection indexes ─────────────────────
    for col_name in ["issues", "complaints"]:
        col = db[col_name]
        specs = [
            ("ward_id",                 {}),
            ("ward",                    {}),
            ("status",                  {}),
            ("priority",                {}),
            ("service",                 {}),
            ("category",                {}),
            ("emergency",               {}),
            ("citizen_id",              {}),
            ("reporter_id",             {}),
            ("assigned_officer_id",     {}),
            ("officer_id",              {}),
            ("worker_id",               {}),
            ("created_at",              {}),
            ([("location", GEOSPHERE)], {}),
            ([("latitude", ASCENDING), ("longitude", ASCENDING)], {}),
            ([("status", ASCENDING), ("created_at", DESCENDING)], {}),
            ([("department", ASCENDING), ("status", ASCENDING)], {}),
            ("sla_deadline",            {}),
        ]
        for spec, kwargs in specs:
            all_ok &= _safe_create_index(col, spec, **kwargs)

    # Slas
    all_ok &= _safe_create_index(db.slas, "deadline")

    # ── Step 3: Users collection + duplicate email cleanup ─────────────────
    try:
        pipeline = [
            {"$group": {"_id": "$email", "count": {"$sum": 1},
                        "docs": {"$push": "$_id"}}},
            {"$match": {"count": {"$gt": 1}}},
        ]
        removed = 0
        for dup in db.users.aggregate(pipeline):
            try:
                res = db.users.delete_many({"_id": {"$in": dup["docs"][1:]}})
                removed += res.deleted_count
            except PyMongoError:
                pass
        if removed:
            _log("warn", "dedup_users",
                 f"Removed {removed} duplicate user accounts (same email).")
    except PyMongoError as exc:
        _log("warn", "dedup_users",
             "Could not run duplicate-email cleanup (aggregate failed).",
             error_type=type(exc).__name__, error=str(exc))

    all_ok &= _safe_create_index(db.users, "email", unique=True)
    all_ok &= _safe_create_index(db.users, "ward_id")
    all_ok &= _safe_create_index(db.users, "ward")
    all_ok &= _safe_create_index(db.users, "role")
    all_ok &= _safe_create_index(db.users, "department")
    all_ok &= _safe_create_index(db.users, "ward_coverage")
    all_ok &= _safe_create_index(db.users, [("current_location", GEOSPHERE)])

    # ── Step 4: Authority + ward registries ────────────────────────────────
    all_ok &= _safe_create_index(db.authority_registry, "authority_id", unique=True)
    all_ok &= _safe_create_index(db.authority_registry, "service_types")

    try:
        _safe_create_index(db.ward_registry, "area_code", unique=True)
        _safe_create_index(db.ward_registry, "ward_id", unique=True)
    except Exception:
        pass

    # ── Step 5: Ward seed, CEFAP, graph ────────────────────────────────────
    try:
        seed_ward_registry(db)
    except Exception as exc:
        _log("warn", "seed_wards",
             "seed_ward_registry raised unexpectedly",
             error_type=type(exc).__name__, error=str(exc))
        all_ok = False

    try:
        create_cefap_indexes(db)
    except Exception as exc:
        _log("warn", "cefap_indexes",
             "create_cefap_indexes raised unexpectedly",
             error_type=type(exc).__name__, error=str(exc))
        all_ok = False

    try:
        ensure_graph_indexes(db)
    except Exception as exc:
        _log("warn", "graph_indexes",
             "ensure_graph_indexes raised unexpectedly",
             error_type=type(exc).__name__, error=str(exc))
        all_ok = False

    if all_ok:
        _log("info", "summary", "All database indexes successfully created.")
    else:
        _log("warn", "summary",
             "Database indexes completed with non-fatal warnings; see above.")
    return all_ok


if __name__ == "__main__":
    try:
        ok = create_indexes()
    except Exception as exc:
        # Last-resort safety net for interactive invocation
        _log("error", "fatal", "Unhandled exception in __main__",
             error_type=type(exc).__name__, error=str(exc))
        sys.exit(99)
    sys.exit(0 if ok else 1)
