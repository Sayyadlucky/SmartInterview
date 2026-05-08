from __future__ import annotations

import hashlib
import importlib.util
import logging
import math
import re
from threading import Lock

from django.conf import settings
from django.core.cache import cache


logger = logging.getLogger(__name__)

REQUIRED_EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'
EMBEDDING_DIMENSION = 384
EMBEDDING_CACHE_PREFIX = 'ai-talent-pool:embedding:'

_embedding_cache: dict[str, list[float]] = {}
_model_instance = None
_model_checked = False
_model_lock = Lock()


class EmbeddingProviderUnavailable(RuntimeError):
    pass


def _cache_key(text: str) -> str:
    digest = hashlib.sha1(text.encode('utf-8')).hexdigest()
    return f'{EMBEDDING_CACHE_PREFIX}{digest}'


def _tokenize(text: str) -> list[str]:
    return re.findall(r'[a-z0-9+#.-]+', (text or '').lower())


def _fallback_embedding(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSION
    tokens = _tokenize(text)
    if not tokens:
        return vector

    for token in tokens:
        token_hash = hashlib.sha256(token.encode('utf-8')).digest()
        for offset in range(0, len(token_hash), 2):
            bucket = token_hash[offset] % EMBEDDING_DIMENSION
            sign = 1.0 if token_hash[offset + 1] % 2 == 0 else -1.0
            vector[bucket] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _hashed_fallback_allowed() -> bool:
    return bool(getattr(settings, 'AI_TALENT_POOL_ENABLE_HASHED_EMBEDDING_FALLBACK', False)) and not bool(
        getattr(settings, 'AI_TALENT_POOL_REQUIRE_REAL_EMBEDDINGS', True)
    )


def _log_embedding_configuration_warning() -> None:
    sentence_transformers_available = importlib.util.find_spec('sentence_transformers') is not None
    if sentence_transformers_available:
        return

    if getattr(settings, 'AI_TALENT_POOL_REQUIRE_REAL_EMBEDDINGS', True):
        logger.warning(
            'AI Talent Pool is configured to require real embeddings, but sentence-transformers is not currently importable. '
            'Requests will fail until the dependency and model are available.'
        )
        return

    if _hashed_fallback_allowed():
        logger.warning(
            'AI Talent Pool is running in local/dev fallback mode because sentence-transformers is unavailable. '
            'Hashed embeddings are enabled only because AI_TALENT_POOL_ENABLE_HASHED_EMBEDDING_FALLBACK is true '
            'and AI_TALENT_POOL_REQUIRE_REAL_EMBEDDINGS is false.'
        )


def _get_model():
    global _model_instance, _model_checked
    with _model_lock:
        if _model_checked:
            if _model_instance is None and not _hashed_fallback_allowed():
                raise EmbeddingProviderUnavailable(
                    'AI Talent Pool embeddings are unavailable. Install sentence-transformers and make '
                    f'{REQUIRED_EMBEDDING_MODEL_NAME} available in this environment.'
                )
            return _model_instance
        _model_checked = True

        configured_model = getattr(settings, 'AI_TALENT_POOL_EMBEDDING_MODEL', REQUIRED_EMBEDDING_MODEL_NAME)
        if configured_model != REQUIRED_EMBEDDING_MODEL_NAME:
            raise EmbeddingProviderUnavailable(
                'AI Talent Pool is pinned to the required embedding model '
                f'{REQUIRED_EMBEDDING_MODEL_NAME}, but the configured model is {configured_model}.'
            )

        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            cache_folder = getattr(settings, 'AI_TALENT_POOL_SENTENCE_TRANSFORMERS_CACHE_DIR', None) or None
            _model_instance = SentenceTransformer(REQUIRED_EMBEDDING_MODEL_NAME, cache_folder=cache_folder)
            logger.info('Loaded sentence-transformers model for AI talent pool: %s', REQUIRED_EMBEDDING_MODEL_NAME)
        except Exception as exc:
            _model_instance = None
            if _hashed_fallback_allowed():
                logger.warning(
                    'sentence-transformers unavailable for AI talent pool. Dev hashed embedding fallback is enabled. Error: %s',
                    exc,
                )
            else:
                raise EmbeddingProviderUnavailable(
                    'AI Talent Pool embeddings are unavailable in production mode. Install sentence-transformers '
                    f'and ensure {REQUIRED_EMBEDDING_MODEL_NAME} can be loaded. Original error: {exc}'
                ) from exc
        return _model_instance


def get_embedding(text: str) -> list[float]:
    normalized = (text or '').strip()
    if not normalized:
        return [0.0] * EMBEDDING_DIMENSION

    key = _cache_key(normalized)
    if key in _embedding_cache:
        return _embedding_cache[key]

    cached_value = cache.get(key)
    if isinstance(cached_value, list):
        _embedding_cache[key] = cached_value
        return cached_value

    model = _get_model()
    if model is None:
        if not _hashed_fallback_allowed():
            raise EmbeddingProviderUnavailable(
                'AI Talent Pool embeddings are unavailable and hashed fallback is disabled.'
            )
        embedding = _fallback_embedding(normalized)
    else:
        try:
            vector = model.encode(normalized, normalize_embeddings=True)
            embedding = [float(value) for value in vector]
        except Exception as exc:
            if _hashed_fallback_allowed():
                logger.exception(
                    'Embedding generation failed. Dev hashed embedding fallback is enabled. Error: %s',
                    exc,
                )
                embedding = _fallback_embedding(normalized)
            else:
                raise EmbeddingProviderUnavailable(
                    'AI Talent Pool embedding generation failed in production mode. '
                    'Hashed fallback is disabled.'
                ) from exc

    _embedding_cache[key] = embedding
    cache.set(key, embedding, timeout=60 * 60 * 24)
    return embedding


def cosine_similarity(left: list[float], right: list[float]) -> float:
    raw = raw_cosine_similarity(left, right)
    return max(0.0, min(1.0, raw))


def raw_cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))


_log_embedding_configuration_warning()
