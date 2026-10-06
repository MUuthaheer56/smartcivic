"""
SmartCivic v2 — Authority and Ward Registry Seeder
Initializes authority_registry and ward_registry collections in MongoDB.
"""
import os
from pymongo import MongoClient

AUTHORITIES = [
    {
        "authority_id": "GBA-CORP",
        "authority_name": "Greater Bengaluru Authority / City Corporation",
        "service_types": [
            "roads", "solid_waste", "parks_lakes", "flooding",
            "trees", "public_health", "animals", "general_civic",
            "illegal_construction", "sanitation", "drainage", "other"
        ],
        "sub_departments": {
            "roads": "GBA-CORP-ROADS",
            "solid_waste": "GBA-CORP-SWM",
            "sanitation": "GBA-CORP-SWM",
            "parks_lakes": "GBA-CORP-PARKS",
            "flooding": "GBA-CORP-SWD",
            "drainage": "GBA-CORP-SWD",
            "trees": "GBA-CORP-TREES",
            "public_health": "GBA-CORP-HEALTH",
            "animals": "GBA-CORP-ANIMAL",
            "illegal_construction": "GBA-CORP-TP",
        },
        "phone": "1533",
        "portal": "https://gba.karnataka.gov.in",
        "api_available": False,
        "active": True,
        "escalation_authority": "State Urban Development Dept",
    },
    {
        "authority_id": "BWSSB",
        "authority_name": "Bangalore Water Supply and Sewerage Board",
        "service_types": ["water"],
        "phone": "1916",
        "phone_alt": "14420",
        "api_available": False,
        "active": True,
        "escalation_authority": "GBA-CORP",
    },
    {
        "authority_id": "BESCOM",
        "authority_name": "Bangalore Electricity Supply Company",
        "service_types": ["electricity"],
        "phone": "1912",
        "api_available": False,
        "active": True,
        "escalation_authority": "GBA-CORP",
    },
    {
        "authority_id": "ERSS-112",
        "authority_name": "Emergency Response Support System",
        "service_types": [
            "medical_emergency", "fire_emergency",
            "crime_safety", "gas_environment"
        ],
        "phone": "112",
        "api_available": False,
        "active": True,
        "bypass_queue": True,
    },
    {
        "authority_id": "BTP",
        "authority_name": "Bengaluru Traffic Police",
        "service_types": ["traffic"],
        "phone": "103",
        "api_available": False,
        "active": True,
        "escalation_authority": "ERSS-112",
    },
    {
        "authority_id": "BMTC",
        "authority_name": "Bangalore Metropolitan Transport Corporation",
        "service_types": ["transport"],
        "phone": "080-22251777",
        "api_available": False,
        "active": True,
    },
    {
        "authority_id": "BMRCL",
        "authority_name": "Bangalore Metro Rail Corporation",
        "service_types": ["transport"],
        "issue_types": ["metro_station", "metro_safety", "metro_infrastructure"],
        "phone": "080-49357000",
        "api_available": False,
        "active": True,
    },
    {
        "authority_id": "BDA-BMRDA",
        "authority_name": "BDA / BMRDA Planning Authorities",
        "service_types": ["illegal_construction"],
        "api_available": False,
        "active": True,
    },
    {
        "authority_id": "FOREST-TREE",
        "authority_name": "Karnataka Forest Dept / DCF",
        "service_types": ["trees"],
        "api_available": False,
        "active": True,
        "escalation_authority": "GBA-CORP-TREES",
    },
    {
        "authority_id": "KSNDMC",
        "authority_name": "Karnataka Disaster Management Authority",
        "service_types": ["flooding"],
        "issue_types": ["major_flooding", "people_stranded", "lake_overflow"],
        "phone": "1070",
        "api_available": False,
        "active": True,
        "escalation_authority": "ERSS-112",
    },
    {
        "authority_id": "FSSAI",
        "authority_name": "Food Safety and Standards Authority of India",
        "service_types": ["food_safety"],
        "phone": "1800-112-100",
        "api_available": False,
        "active": True,
    },
]

INITIAL_WARDS = [
    {"ward_id": "ward_1", "ward_name": "Ward 1", "area_code": "WARD1-2026", "city": "Bengaluru", "active": True},
    {"ward_id": "ward_12", "ward_name": "Shivajinagar", "area_code": "SHV-2024", "city": "Bengaluru", "active": True},
    {"ward_id": "ward_45", "ward_name": "Domlur", "area_code": "DML-2026", "city": "Bengaluru", "active": True},
    {"ward_id": "ward_112", "ward_name": "Koramangala", "area_code": "KRM-2026", "city": "Bengaluru", "active": True},
    {"ward_id": "ward_78", "ward_name": "Indiranagar", "area_code": "IND-2026", "city": "Bengaluru", "active": True},
]

def seed(mongo_uri: str = None):
    uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/smartcivic")
    client = MongoClient(uri)
    db_name = uri.split('/')[-1] if '/' in uri else 'smartcivic'
    if not db_name or db_name.strip() == "" or '?' in db_name:
        db_name = 'smartcivic'
    db = client[db_name]

    db.authority_registry.delete_many({})
    db.authority_registry.insert_many(AUTHORITIES)
    db.authority_registry.create_index("authority_id", unique=True)
    db.authority_registry.create_index("service_types")

    for w in INITIAL_WARDS:
        db.ward_registry.update_one({"ward_id": w["ward_id"]}, {"$set": w}, upsert=True)
    db.ward_registry.create_index("area_code", unique=True)
    db.ward_registry.create_index("ward_id")

    print(f"[Seed] Successfully seeded {len(AUTHORITIES)} authorities and {len(INITIAL_WARDS)} wards into '{db_name}'.")

if __name__ == "__main__":
    seed()
