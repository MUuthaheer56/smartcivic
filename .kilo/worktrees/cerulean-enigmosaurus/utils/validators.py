"""
SmartCivic — Validation Utilities
Implements strict validation for complaints, images, and status machine transitions.
"""
from config import Config
import os
import re
import logging
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB ceiling limit

def allowed_image_file(filename: str) -> bool:
    """Validates file extension against permitted image types."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def sanitize_text_input(text: str) -> str:
    """Removes potential script injection or raw HTML tags from text inputs."""
    if not text:
        return ""
    # Strip basic HTML tags to protect against XSS
    clean_text = re.sub(r'<[^>]*>', '', text)
    return clean_text.strip()

def validate_complaint_payload(form_data, files) -> dict:
    """Validates incoming complaint submissions prior to pipeline execution."""
    description = sanitize_text_input(form_data.get("description", ""))
    if len(description) < 5:
        return {"valid": False, "error": "Description must be at least 5 characters long."}

    # Validate image attachment if present
    image_file = files.get("image")
    if image_file and getattr(image_file, 'filename', '') != '':
        if not allowed_image_file(image_file.filename):
            return {"valid": False, "error": "Invalid image format. Allowed formats: png, jpg, jpeg, webp."}
        
        # Check file length/size
        image_file.seek(0, os.SEEK_END)
        size = image_file.tell()
        image_file.seek(0) # Reset stream pointer
        
        if size > MAX_FILE_SIZE_BYTES:
            return {"valid": False, "error": "Image file size exceeds the 5MB maximum limit."}

    return {"valid": True, "description": description}


ALLOWED_TRANSITIONS = {
    "submitted":             ["under_review", "rejected", "duplicate", "ai_reviewed", "officer_reviewed", "assigned"],
    "under_review":          ["verified", "rejected", "duplicate", "assigned"],
    "ai_reviewed":           ["officer_reviewed", "assigned", "rejected"],
    "officer_reviewed":      ["assigned", "rejected"],
    "verified":              ["assigned"],
    "assigned":              ["en_route", "in_progress", "work_started"],
    "en_route":              ["in_progress", "work_started"],
    "in_progress":           ["resolved", "work_completed"],
    "work_started":          ["work_completed", "resolved"],
    "work_completed":        ["officer_verified", "resolved", "closed"],
    "officer_verified":      ["citizen_verification", "closed"],
    "citizen_verification":  ["closed", "reopened"],
    "resolved":              ["closed"],
    "reopened":              ["assigned"]
}

class ValidationError(Exception):
    def __init__(self, message, status_code=400, errors=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.errors = errors or {}

def validate_complaint(data: dict) -> None:
    errors = {}
    
    desc = data.get("description")
    if not desc or not isinstance(desc, str) or len(desc.strip()) < 20:
        errors["description"] = "Description is required and must be at least 20 characters long."
        
    lat = data.get("latitude") if "latitude" in data else data.get("lat")
    if lat is None:
        errors["latitude"] = "Latitude is required."
    else:
        try:
            lat_f = float(lat)
            if not (-90.0 <= lat_f <= 90.0):
                errors["latitude"] = "Latitude must be between -90 and 90 degrees."
        except (ValueError, TypeError):
            errors["latitude"] = "Latitude must be a valid float."
            
    lng = data.get("longitude") if "longitude" in data else data.get("lng")
    if lng is None:
        errors["longitude"] = "Longitude is required."
    else:
        try:
            lng_f = float(lng)
            if not (-180.0 <= lng_f <= 180.0):
                errors["longitude"] = "Longitude must be between -180 and 180 degrees."
        except (ValueError, TypeError):
            errors["longitude"] = "Longitude must be a valid float."

    if errors:
        raise ValidationError("Complaint validation failed.", status_code=400, errors=errors)

def validate_image(file) -> None:
    if not file:
        raise ValidationError("Image file is required.", status_code=400)
        
    filename = getattr(file, "filename", "") or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in Config.ALLOWED_EXTENSIONS:
        raise ValidationError(f"Invalid file extension. Allowed: {Config.ALLOWED_EXTENSIONS}", status_code=400)
        
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    
    if size > Config.MAX_IMAGE_BYTES:
        raise ValidationError("File exceeds maximum allowed size (10MB).", status_code=400)

def validate_status_transition(current_status: str, new_status: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        raise ValidationError(
            f"Invalid status transition from '{current_status}' to '{new_status}'. Allowed: {allowed}",
            status_code=422
        )
