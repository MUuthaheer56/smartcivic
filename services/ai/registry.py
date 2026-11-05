"""
SmartCivic — Model Registry & Integrity Guard
Loads registered models safely: verifies file existence, enforces non-trivial file size
(guarding against corrupt, empty, or 28-byte placeholder files), verifies optional SHA256 checksums,
and safely invokes loaders. Returns None on any failure so callers fall back cleanly.
"""
import os
import hashlib
import logging
from typing import Any, Callable, Optional, Dict

logger = logging.getLogger(__name__)

# Minimum valid size for any serialized model (e.g., ONNX, joblib, weights)
# Catches the legacy 28-byte placeholder and empty files
MIN_MODEL_BYTES = 100

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

class ModelRegistry:
    """Central registry of registered AI model loaders and metadata."""
    def __init__(self):
        self._registry: Dict[str, Dict[str, Any]] = {}
        self._cached_instances: Dict[str, Any] = {}

    def register(self, name: str, default_rel_path: str, loader_fn: Optional[Callable[[str], Any]] = None, expected_sha256: Optional[str] = None):
        self._registry[name] = {
            "default_path": default_rel_path,
            "loader_fn": loader_fn,
            "expected_sha256": expected_sha256
        }

    def load_model(self, name: str, custom_path: Optional[str] = None, expected_sha256: Optional[str] = None, min_bytes: int = MIN_MODEL_BYTES) -> Optional[Any]:
        """
        Safely loads a model by name. Returns None on any failure. Never raises.
        """
        reg_info = self._registry.get(name, {})
        target_path = custom_path or reg_info.get("default_path")
        if not target_path:
            logger.debug(f"[ModelRegistry] Model '{name}' has no configured path.")
            return None

        # Resolve relative to project root if not absolute
        if not os.path.isabs(target_path):
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            target_path = os.path.join(base_dir, target_path)

        if not os.path.exists(target_path):
            logger.debug(f"[ModelRegistry] Model '{name}' file does not exist: {target_path}")
            return None

        try:
            size = os.path.getsize(target_path)
            if size <= min_bytes:
                logger.warning(
                    f"[ModelRegistry] Model '{name}' file is only {size} bytes (minimum {min_bytes}b). "
                    f"Treating as placeholder or corrupt; falling back to None."
                )
                return None
        except Exception as e:
            logger.warning(f"[ModelRegistry] Could not stat model file '{target_path}': {e}")
            return None

        chk = expected_sha256 or reg_info.get("expected_sha256")
        if chk:
            try:
                actual_hash = _sha256(target_path)
                if actual_hash.lower() != chk.lower():
                    logger.warning(f"[ModelRegistry] SHA256 mismatch for model '{name}'. Expected {chk}, got {actual_hash}. Falling back.")
                    return None
            except Exception as e:
                logger.warning(f"[ModelRegistry] Could not hash model file '{target_path}': {e}")
                return None

        loader = reg_info.get("loader_fn")
        if loader:
            try:
                model_obj = loader(target_path)
                return model_obj
            except Exception as e:
                logger.warning(f"[ModelRegistry] Loader function failed for model '{name}': {e}")
                return None

        # If no custom loader provided, return verified file path as confirmed artifact
        return target_path

registry = ModelRegistry()

def load_model(name: str, **kwargs) -> Optional[Any]:
    return registry.load_model(name, **kwargs)

