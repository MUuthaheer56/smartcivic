from bson import ObjectId
from datetime import datetime

def parse_object_id(value):
    try:
        if value is None:
            return None
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)
    except Exception:
        return None

def serialize(obj):
    if isinstance(obj, list): return [serialize(i) for i in obj]
    if isinstance(obj, dict): return {k: serialize(v) for k, v in obj.items()}
    if isinstance(obj, ObjectId): return str(obj)
    if isinstance(obj, datetime): return obj.isoformat()
    return obj

import re
import time
import threading
import functools
from typing import Callable

_CACHE: dict = {}
_LOCK = threading.Lock()

def cached(key_fn: Callable, ttl: int = 300):
    """
    Decorator-based in-memory cache using a dict with TTL expiry.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = key_fn(*args, **kwargs)
            with _LOCK:
                entry = _CACHE.get(key)
                if entry and time.monotonic() < entry["expires"]:
                    return entry["value"]
            result = fn(*args, **kwargs)
            with _LOCK:
                _CACHE[key] = {
                    "value": result,
                    "expires": time.monotonic() + ttl
                }
            return result
        return wrapper
    return decorator

def invalidate_cache(key: str):
    with _LOCK:
        _CACHE.pop(key, None)

def clear_all_cache():
    with _LOCK:
        _CACHE.clear()

# 2. Description Sanitizer
_PROFANITY = {"badword1", "badword2"}
_HTML_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<script.*?>.*?</script>", re.IGNORECASE | re.DOTALL)
_PHONE_PII = re.compile(r"\b[6-9]\d{9}\b") # Indian mobile pattern
_EMAIL_PII = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
MAX_DESC_LENGTH = 500

def sanitize_description(description: str) -> str:
    """
    Strips HTML/script tags, removes embedded PII, strips profanity, and truncates to 500 chars.
    """
    if not description:
        return ""
    text = str(description)
    # 1. Strip scripts and HTML tags
    text = _SCRIPT.sub("", text)
    text = _HTML_TAG.sub("", text)
    # 2. Remove PII patterns
    text = _PHONE_PII.sub("[phone removed]", text)
    text = _EMAIL_PII.sub("[email removed]", text)
    # 3. Strip profanity
    words = []
    for w in text.split():
        clean_w = re.sub(r'[^\w]', '', w).lower()
        if clean_w in _PROFANITY:
            words.append("[removed]")
        else:
            words.append(w)
    text = " ".join(words)
    # 4. Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # 5. Truncate
    return text[:MAX_DESC_LENGTH]
