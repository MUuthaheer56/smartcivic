"""
SmartCivic v2 — Dynamic Clarification Menus
Provides fallback options when AI classification needs resident confirmation.
"""

CLARIFICATION_MENUS = {
    "water": [
        {"id": "no_water_supply",     "label": "No water supply"},
        {"id": "water_leakage",       "label": "Water leakage / pipe burst"},
        {"id": "sewage_overflow",     "label": "Sewage overflow"},
        {"id": "contaminated_water",  "label": "Contaminated / dirty water"},
        {"id": "low_pressure",        "label": "Low water pressure"},
        {"id": "manhole_drain",       "label": "Manhole / drain problem"},
        {"id": "other_water",         "label": "Other water issue"},
    ],
    "electricity": [
        {"id": "power_outage",        "label": "Power outage"},
        {"id": "fallen_wire",         "label": "Fallen / exposed wire"},
        {"id": "electrical_sparking", "label": "Electrical sparking / hazard"},
        {"id": "streetlight_out",     "label": "Streetlight not working"},
        {"id": "transformer_fault",   "label": "Transformer problem"},
        {"id": "other_electrical",    "label": "Other electrical issue"},
    ],
    "roads": [
        {"id": "pothole",             "label": "Pothole"},
        {"id": "road_damage",         "label": "Road damage / crumbling"},
        {"id": "road_blocked",        "label": "Road blocked / obstruction"},
        {"id": "road_collapse",       "label": "Road collapse / sinkhole"},
        {"id": "footpath_damaged",    "label": "Footpath / sidewalk damaged"},
        {"id": "other_road",          "label": "Other road issue"},
    ],
    "flooding": [
        {"id": "major_flooding",      "label": "Major flooding — people stranded"},
        {"id": "road_waterlogging",   "label": "Road waterlogging"},
        {"id": "drain_blocked",       "label": "Storm drain blocked"},
        {"id": "underpass_flooded",   "label": "Underpass flooded"},
        {"id": "residential_flooding","label": "Residential area flooding"},
    ],
    "solid_waste": [
        {"id": "garbage_not_collected","label": "Garbage not collected"},
        {"id": "illegal_dumping",     "label": "Illegal dumping"},
        {"id": "garbage_burning",     "label": "Garbage burning"},
        {"id": "bin_overflowing",     "label": "Bin overflowing"},
        {"id": "dead_animal",         "label": "Dead animal on road"},
    ],
    "trees": [
        {"id": "tree_fallen_road",    "label": "Tree fallen on road"},
        {"id": "tree_fallen_building","label": "Tree fallen on building"},
        {"id": "dangerous_tree",      "label": "Tree about to fall"},
        {"id": "branch_fallen",       "label": "Large branch fallen"},
        {"id": "tree_trimming",       "label": "Tree trimming needed"},
    ],
    "traffic": [
        {"id": "signal_not_working",  "label": "Traffic signal not working"},
        {"id": "signal_malfunction",  "label": "Signal malfunctioning"},
        {"id": "road_accident",       "label": "Road accident"},
        {"id": "illegal_parking",     "label": "Illegal parking blocking road"},
        {"id": "road_rage",           "label": "Road rage / dangerous driving"},
    ],
    "public_health": [
        {"id": "mosquito_breeding",   "label": "Mosquito breeding site"},
        {"id": "stagnant_water",      "label": "Stagnant water / dengue risk"},
        {"id": "food_safety_hazard",  "label": "Unsafe / unhygienic food area"},
        {"id": "pest_infestation",    "label": "Pest infestation"},
        {"id": "public_toilet_issue", "label": "Public toilet not functional"},
    ],
    "food_safety": [
        {"id": "restaurant_hygiene",  "label": "Unhygienic restaurant"},
        {"id": "food_adulteration",   "label": "Food adulteration / contamination"},
        {"id": "expired_product",     "label": "Expired product being sold"},
        {"id": "illegal_food_vendor", "label": "Unlicensed food vendor"},
        {"id": "other_food",          "label": "Other food safety issue"},
    ],
}

def get_clarification_menu(service: str) -> list:
    svc = (service or "roads").lower()
    return CLARIFICATION_MENUS.get(svc, [
        {"id": "describe_issue", "label": "Describe your issue in more detail"}
    ])
