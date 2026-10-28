"""
SmartCivic — F2 Migration Script: Make Uploads Private
1. Moves all files from static/uploads/ to uploads/{docs,verification_docs,issues,resolution}/
2. Deletes static/uploads/ directory completely
3. Strips EXIF GPS and metadata from stored images using Pillow
4. Idempotently rewrites all stored URLs in MongoDB (users and issues) from /static/uploads/... to /files/...
"""
import os
import shutil
import re
from PIL import Image, ImageOps
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_UPLOADS = os.path.join(BASE_DIR, "static", "uploads")
PRIVATE_UPLOADS = os.path.join(BASE_DIR, "uploads")

KINDS = ["docs", "verification_docs", "issues", "resolution"]

def ensure_private_directories():
    for k in KINDS:
        d = os.path.join(PRIVATE_UPLOADS, k)
        os.makedirs(d, exist_ok=True)

def strip_exif_from_image(file_path: str) -> bool:
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        return False
    try:
        with Image.open(file_path) as img:
            fmt = img.format or ("JPEG" if ext in [".jpg", ".jpeg"] else ext.lstrip(".").upper())
            img = ImageOps.exif_transpose(img)
            # Create a clean image copy without EXIF dictionary
            clean_img = Image.new(img.mode, img.size)
            clean_img.putdata(list(img.getdata()))
            clean_img.save(file_path, format=fmt)
        return True
    except Exception as exc:
        # Some images might already be clean or cannot be modified in-place
        return False

def move_files() -> dict:
    ensure_private_directories()
    stats = {"docs": 0, "verification_docs": 0, "issues": 0, "resolution": 0, "exif_stripped": 0}
    
    # 1. Relocate files from static/uploads
    if os.path.exists(STATIC_UPLOADS):
        print(f"Scanning {STATIC_UPLOADS} for files to migrate...")
        for root, dirs, files in os.walk(STATIC_UPLOADS):
            for file in files:
                if file == ".gitkeep":
                    continue
                src = os.path.join(root, file)
                rel = os.path.relpath(src, STATIC_UPLOADS).replace("\\", "/")
                
                # Determine destination kind
                if "verification_docs" in rel or file.startswith("doc_"):
                    dst_kind = "verification_docs"
                elif "docs" in rel:
                    dst_kind = "docs"
                elif "_after_" in file or "resolution" in rel:
                    dst_kind = "resolution"
                else:
                    dst_kind = "issues"
                    
                dst = os.path.join(PRIVATE_UPLOADS, dst_kind, file)
                shutil.move(src, dst)
                stats[dst_kind] += 1
                
        # Delete static/uploads directory
        try:
            shutil.rmtree(STATIC_UPLOADS)
            print(f"Successfully removed public {STATIC_UPLOADS}")
        except Exception as e:
            print(f"Warning: could not delete {STATIC_UPLOADS}: {e}")
            
    # 2. Check for resolution files mistakenly placed in uploads/issues
    issues_dir = os.path.join(PRIVATE_UPLOADS, "issues")
    resolution_dir = os.path.join(PRIVATE_UPLOADS, "resolution")
    if os.path.exists(issues_dir):
        for f in os.listdir(issues_dir):
            if "_after_" in f:
                src = os.path.join(issues_dir, f)
                dst = os.path.join(resolution_dir, f)
                shutil.move(src, dst)
                stats["resolution"] += 1

    # 3. Strip EXIF from images in private directories
    for kind in ["issues", "resolution"]:
        target_dir = os.path.join(PRIVATE_UPLOADS, kind)
        if os.path.exists(target_dir):
            for f in os.listdir(target_dir):
                fp = os.path.join(target_dir, f)
                if os.path.isfile(fp):
                    if strip_exif_from_image(fp):
                        stats["exif_stripped"] += 1

    return stats

def migrate_database_urls():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGO_DB_NAME", "smartcivic")
    client = MongoClient(mongo_uri)
    db = client[db_name]
    
    user_updated = 0
    issue_updated = 0
    
    # 1. Migrate Users verification_doc and documents
    users = db.users.find({
        "$or": [
            {"verification_doc": {"$regex": r"/(static/)?uploads/"}},
            {"documents": {"$regex": r"/(static/)?uploads/"}}
        ]
    })
    
    for u in users:
        updates = {}
        vdoc = u.get("verification_doc")
        if vdoc and ("uploads/" in vdoc):
            new_vdoc = re.sub(r"^/?(static/)?uploads/(verification_docs|docs)/", r"/files/\2/", vdoc)
            if new_vdoc != vdoc:
                updates["verification_doc"] = new_vdoc
                
        docs = u.get("documents", [])
        if docs:
            new_docs = []
            changed_docs = False
            for d in docs:
                if isinstance(d, str) and ("uploads/" in d):
                    nd = re.sub(r"^/?(static/)?uploads/(verification_docs|docs)/", r"/files/\2/", d)
                    new_docs.append(nd)
                    if nd != d:
                        changed_docs = True
                else:
                    new_docs.append(d)
            if changed_docs:
                updates["documents"] = new_docs
                
        if updates:
            db.users.update_one({"_id": u["_id"]}, {"$set": updates})
            user_updated += 1

    # 2. Migrate Issues images, photos, media_urls
    issues = db.issues.find({
        "$or": [
            {"images.url": {"$regex": r"/(static/)?uploads/"}},
            {"photos": {"$regex": r"/(static/)?uploads/"}},
            {"media_urls": {"$regex": r"/(static/)?uploads/"}},
            {"resolution_notes.after_image": {"$regex": r"/(static/)?uploads/"}}
        ]
    })
    
    for iss in issues:
        updates = {}
        images = iss.get("images", [])
        if images and isinstance(images, list):
            new_images = []
            changed = False
            for img in images:
                if isinstance(img, dict):
                    img_copy = dict(img)
                    url = img_copy.get("url", "")
                    fn = img_copy.get("filename", "")
                    img_type = img_copy.get("type", "")
                    
                    if "/uploads/" in url or url.startswith("static/"):
                        kind = "resolution" if ("_after_" in fn or img_type == "after") else "issues"
                        if not fn and "/" in url:
                            fn = url.rsplit("/", 1)[-1]
                        new_url = f"/files/{kind}/{fn}"
                        img_copy["url"] = new_url
                        img_copy["filepath"] = f"uploads/{kind}/{fn}"
                        changed = True
                    new_images.append(img_copy)
                else:
                    new_images.append(img)
            if changed:
                updates["images"] = new_images

        # photos
        photos = iss.get("photos", [])
        if photos and isinstance(photos, list):
            new_photos = []
            p_changed = False
            for p in photos:
                if isinstance(p, str) and "uploads/" in p:
                    np = re.sub(r"^/?(static/)?uploads/(issues|resolution)/", r"/files/\2/", p)
                    new_photos.append(np)
                    if np != p:
                        p_changed = True
                else:
                    new_photos.append(p)
            if p_changed:
                updates["photos"] = new_photos

        # media_urls
        media_urls = iss.get("media_urls", [])
        if media_urls and isinstance(media_urls, list):
            new_media = []
            m_changed = False
            for m in media_urls:
                if isinstance(m, str) and "uploads/" in m:
                    nm = re.sub(r"^/?(static/)?uploads/(issues|resolution)/", r"/files/\2/", m)
                    new_media.append(nm)
                    if nm != m:
                        m_changed = True
                else:
                    new_media.append(m)
            if m_changed:
                updates["media_urls"] = new_media

        # resolution_notes
        res_notes = iss.get("resolution_notes")
        if isinstance(res_notes, dict):
            after_img = res_notes.get("after_image")
            if after_img and isinstance(after_img, str) and "uploads/" in after_img:
                fn = after_img.rsplit("/", 1)[-1]
                updates["resolution_notes.after_image"] = f"/files/resolution/{fn}"

        if updates:
            db.issues.update_one({"_id": iss["_id"]}, {"$set": updates})
            issue_updated += 1

    return user_updated, issue_updated

if __name__ == "__main__":
    print("=" * 60)
    print("Starting F2 Upload Privacy Migration...")
    print("=" * 60)
    
    file_stats = move_files()
    print("\nFile Migration Summary:")
    for k, count in file_stats.items():
        print(f" - {k}: {count}")
        
    user_cnt, issue_cnt = migrate_database_urls()
    print("\nDatabase Migration Summary:")
    print(f" - Users migrated:  {user_cnt}")
    print(f" - Issues migrated: {issue_cnt}")
    print("\nF2 Migration Complete.")
    print("=" * 60)
