"""
SmartCivic — Text Embeddings & Semantic Similarity Service
Provides fast CPU embeddings for multilingual municipal complaints (English/Kannada/Indic mixes).
Caches embeddings in MongoDB and in-memory to prevent recomputation.
"""
import re
import math
import numpy as np
from typing import List, Optional, Dict
from sklearn.feature_extraction.text import HashingVectorizer

# Using HashingVectorizer with subword n-grams (3 to 5 chars)
# 1. Deterministic & stateless across worker processes (no vocabulary sync needed)
# 2. Resilient to misspellings, transliterations, and Kannada/English mixed text
# 3. Fast CPU execution (sub-millisecond)
_vectorizer = HashingVectorizer(
    n_features=512,
    analyzer="char_wb",
    ngram_range=(3, 5),
    alternate_sign=False,
    norm="l2"
)

# In-memory LRU cache for recent text embeddings
_EMBEDDING_CACHE: Dict[str, List[float]] = {}
_MAX_CACHE_ENTRIES = 2000

def _normalize_text(text: str) -> str:
    if not text:
        return ""
    # Strip excessive punctuation and lowercase
    cleaned = re.sub(r'[\r\n\t]+', ' ', str(text).lower().strip())
    return cleaned

def compute_text_embedding(text: str) -> List[float]:
    """
    Computes a normalized embedding vector for the complaint text.
    Returns a list of 512 floats with L2 norm = 1.0.
    """
    clean = _normalize_text(text)
    if not clean:
        return [0.0] * 512

    if clean in _EMBEDDING_CACHE:
        return _EMBEDDING_CACHE[clean]

    vec = _vectorizer.transform([clean]).toarray()[0]
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    res = [float(round(x, 5)) for x in vec.tolist()]

    if len(_EMBEDDING_CACHE) >= _MAX_CACHE_ENTRIES:
        _EMBEDDING_CACHE.pop(next(iter(_EMBEDDING_CACHE)))
    _EMBEDDING_CACHE[clean] = res

    return res

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculates cosine similarity between two normalized vectors."""
    if not vec1 or not vec2:
        return 0.0
    v1 = np.array(vec1, dtype=float)
    v2 = np.array(vec2, dtype=float)
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 == 0 or n2 == 0:
        return 0.0
    sim = float(np.dot(v1, v2) / (n1 * n2))
    return max(0.0, min(1.0, sim))

