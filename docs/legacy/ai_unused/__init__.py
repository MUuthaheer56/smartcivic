"""
================================================================================
DEPRECATED / LEGACY AI MODULES — docs/legacy/ai_unused/
================================================================================

This package contains DETACHED, UNMAINTAINED AI modules from earlier SmartCivic
prototypes.  They are intentionally NOT wired into:

  * app.py registered blueprints
  * services/ai_pipeline.py canonical pipeline
  * routes/api/* active REST endpoints
  * any MongoDB collection or service layer

Do NOT import these modules in production code.  If any feature here is needed,
re-implement it cleanly against the current services/ contract and models/
schemas rather than trying to revive the old prototypes.

Contents (archived for audit trail only):
  - drain/drain_predictor.py, drain_scheduler.py
  - animals/animal_detector.py, hotspot_clusterer.py
  - trust/civic_trust_scorer.py
  - dump/dump_age_estimator.py
  - construction/permit_checker.py, safety_detector.py
  - streetlight/darkness_detector.py
  - lakes/lake_boundary_checker.py
  - footpath/encroachment_detector.py
  - specialised/repair_verify.py, road.py
  - coordination/coordination_analyzer.py
  - top-level: anomaly_detector, image_analyzer, nlp_classifier,
    noise_validator, pipeline, trust_scorer, drain_predictor
================================================================================
"""
import warnings

_DEPRECATION_MSG = (
    "docs.legacy.ai_unused is an archived package of detached prototype modules. "
    "It is NOT wired into the active SmartCivic+ services, routes, or database "
    "models.  Importing from here is almost certainly a mistake; see the package "
    "__init__.py docstring for the module list and the correct migration path."
)

warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)

__all__ = []  # prevent star-import leakage
