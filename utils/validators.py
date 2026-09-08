"""
SmartCivic — Validation Utilities
Implements strict validation for complaints, images, and status machine transitions.
"""
from config import Config

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
