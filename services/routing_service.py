"""
services/routing_service.py — Deprecation Shim
Re-exports navigation routing functions from canonical services.authority_router module.
"""
import warnings
from services.authority_router import calculate_distance, calculate_eta, get_route

warnings.warn("routing_service is deprecated; use authority_router", DeprecationWarning, stacklevel=2)

__all__ = ["calculate_distance", "calculate_eta", "get_route"]
