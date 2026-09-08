"""
SmartCivic — Image Utilities
Handles secure image file persistence and URL generation.
"""
import os
import uuid
from config import Config
from utils.validators import validate_image

def save_uploaded_image(file, upload_folder: str = None) -> dict:
    validate_image(file)
    folder = upload_folder or Config.UPLOAD_FOLDER
    os.makedirs(folder, exist_ok=True)
    
    filename = getattr(file, "filename", "") or "image.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    safe_name = f"sc_{uuid.uuid4().hex[:12]}.{ext}"
    filepath = os.path.join(folder, safe_name)
    
    if hasattr(file, "save"):
        file.save(filepath)
    else:
        with open(filepath, "wb") as f:
            f.write(file.read())
            
    url = f"/{folder}/{safe_name}".replace("//", "/")
    return {
        "filename": safe_name,
        "filepath": filepath,
        "url": url,
        "mime_type": f"image/{'jpeg' if ext == 'jpg' else ext}"
    }
