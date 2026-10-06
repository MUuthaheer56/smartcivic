"""
SmartCivic — Hardened Image Utilities
Handles secure image file validation, metadata stripping, thumbnailing, and re-encoding.
"""
import os
import uuid
from PIL import Image, ImageOps

ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}
ALLOWED_FMT = {"JPEG", "PNG", "WEBP"}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_BYTES = 5 * 1024 * 1024  # 5MB limit
MAX_DIMENSION = 4096

def save_secure_image(file_storage, upload_folder="static/uploads/issues"):
    """
    Secure image persistence: validates format, dimension bounds (<=4096px),
    transposes EXIF orientation, converts mode to RGB, and saves JPEG to secure directory.
    Returns (url_path, error_str).
    """
    if not file_storage:
        return None, "No file provided"
    try:
        stream = getattr(file_storage, "stream", file_storage)
        image = Image.open(stream)
        if image.format not in ALLOWED_FORMATS:
            return None, f"Unsupported format: {image.format}"

        if image.width > MAX_DIMENSION or image.height > MAX_DIMENSION:
            return None, "Dimensions exceed limits."

        image = ImageOps.exif_transpose(image)
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGB")

        filename = f"{uuid.uuid4().hex}.jpg"
        os.makedirs(upload_folder, exist_ok=True)
        save_path = os.path.join(upload_folder, filename)
        image.save(save_path, "JPEG", quality=85)

        return f"/secure-uploads/{filename}", None
    except Exception as e:
        return None, str(e)

def save_image(file_storage, upload_dir: str = "static/uploads/issues") -> str:
    """
    Hardened image persistence handler.
    Validates extension, size (<=5MB), Pillow integrity, format,
    re-encodes to strip metadata/EXIF payloads via ImageOps.exif_transpose,
    and resizes to max 2048px.
    Returns filename string.
    """
    name = getattr(file_storage, "filename", "") or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXT:
        raise ValueError("Unsupported file type")

    stream = getattr(file_storage, "stream", file_storage)
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)

    if size == 0 or size > MAX_BYTES:
        raise ValueError("Invalid file size (max 5MB)")

    try:
        # Integrity check
        img = Image.open(stream)
        img.verify()
        
        # Re-open stream after verify()
        stream.seek(0)
        img = Image.open(stream)

        fmt = (img.format or "JPEG").upper()
        if fmt not in ALLOWED_FMT:
            raise ValueError("Unsupported image format")

        if img.width > MAX_DIMENSION or img.height > MAX_DIMENSION:
            raise ValueError("Dimensions exceed limits.")

        img = ImageOps.exif_transpose(img)

        # Convert palette/alpha modes if saving as JPEG
        if fmt == "JPEG" and img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        # Resize max 2048x2048 to optimize sync compression
        img.thumbnail((2048, 2048))

        os.makedirs(upload_dir, exist_ok=True)
        fname = f"{uuid.uuid4().hex}.{fmt.lower()}"
        filepath = os.path.join(upload_dir, fname)

        # Save re-encoded image without EXIF/metadata
        img.save(filepath, format=fmt)
        return fname
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("Corrupt or non-image file") from e

def save_uploaded_image(file, upload_folder: str = "static/uploads/issues") -> dict:
    """
    Wrapper around save_image returning detailed dictionary.
    """
    fname = save_image(file, upload_folder)
    filepath = os.path.join(upload_folder, fname)
    url = f"/{upload_folder}/{fname}".replace("//", "/")
    ext = fname.rsplit(".", 1)[-1].lower()
    return {
        "filename": fname,
        "filepath": filepath,
        "url": url,
        "mime_type": f"image/{'jpeg' if ext in ['jpg', 'jpeg'] else ext}"
    }

