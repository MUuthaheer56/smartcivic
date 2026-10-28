"""
Update ward boundaries with GeoJSON Polygons in MongoDB ward_registry.
"""
from app import db
from pymongo import GEOSPHERE

def update_boundaries():
    count = 0
    for w in db.ward_registry.find():
        clat = w.get('center_lat', 12.9716)
        clng = w.get('center_lng', 77.5946)
        d = 0.018
        poly = {
            'type': 'Polygon',
            'coordinates': [[
                [round(clng - d, 4), round(clat - d, 4)],
                [round(clng + d, 4), round(clat - d, 4)],
                [round(clng + d, 4), round(clat + d, 4)],
                [round(clng - d, 4), round(clat + d, 4)],
                [round(clng - d, 4), round(clat - d, 4)]
            ]]
        }
        res = db.ward_registry.update_one({'_id': w['_id']}, {'$set': {'boundary': poly}})
        if res.modified_count > 0 or res.matched_count > 0:
            count += 1

    try:
        db.ward_registry.create_index([("boundary", GEOSPHERE)])
    except Exception as e:
        print(f"Index creation note: {e}")

    total = db.ward_registry.count_documents({'boundary': {'$exists': True}})
    print(f"Successfully populated boundaries for {total} wards.")

if __name__ == '__main__':
    update_boundaries()
