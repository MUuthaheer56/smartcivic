import os
import uuid
from io import BytesIO
from typing import Tuple

# Allowed image signatures (Magic Bytes)
ALLOWED_MAGIC_BYTES = {
    b'\xFF\xD8\xFF': 'image/jpeg',
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'RIFF': 'image/webp'
}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

def validate_and_sanitize_image(file_bytes: bytes, original_filename: str) -> Tuple[bytes, str]:
    """
    Validates file payload by inspect magic bytes (not just file extension),
    enforces maximum file size, and generates a safe cryptographically random filename.
    """
    if len(file_bytes) > MAX_FILE_SIZE:
        raise ValueError("File exceeds maximum allowed size of 5MB.")

    # Validate Magic Bytes
    detected_mime = None
    if file_bytes.startswith(b'\xFF\xD8\xFF'):
        detected_mime = 'image/jpeg'
        ext = '.jpg'
    elif file_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        detected_mime = 'image/png'
        ext = '.png'
    elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'WEBP':
        detected_mime = 'image/webp'
        ext = '.webp'
    else:
        raise ValueError("Invalid file format. Only verified JPEG, PNG, and WebP images are allowed.")

    # Strip EXIF/metadata: For JPEG, discard APP1/Exif markers or rebuild via safe buffer
    clean_bytes = file_bytes
    if detected_mime == 'image/jpeg':
        # Clean basic EXIF markers if present
        clean_buffer = BytesIO()
        clean_buffer.write(file_bytes[:2])  # SOI marker
        pos = 2
        while pos < len(file_bytes):
            if file_bytes[pos] == 0xFF:
                marker = file_bytes[pos+1]
                if marker in [0xE1, 0xE2]:  # APP1 (EXIF), APP2
                    length = int.from_bytes(file_bytes[pos+2:pos+4], 'big')
                    pos += 2 + length
                    continue
            clean_buffer.write(file_bytes[pos:pos+1])
            pos += 1
        clean_bytes = clean_buffer.getvalue()

    safe_filename = f"{uuid.uuid4().hex}{ext}"
    return clean_bytes, safe_filename
