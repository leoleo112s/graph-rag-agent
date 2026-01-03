from .backends import (
    CacheStorageBackend,
    DiskCacheBackend,
    HybridCacheBackend,
    MemoryCacheBackend,
    ThreadSafeCacheBackend,
)
from .manager import CacheManager
from .model_cache import ensure_model_cache_dir, initialize_model_cache
from .models import CacheItem
from .strategies import (
    CacheKeyStrategy,
    ContextAndKeywordAwareCacheKeyStrategy,
    ContextAwareCacheKeyStrategy,
    SimpleCacheKeyStrategy,
)
from .vector_similarity import VectorSimilarityMatcher

__all__ = [
    # Key strategies
    "CacheKeyStrategy",
    "SimpleCacheKeyStrategy",
    "ContextAwareCacheKeyStrategy",
    "ContextAndKeywordAwareCacheKeyStrategy",
    # Storage backends
    "CacheStorageBackend",
    "MemoryCacheBackend",
    "DiskCacheBackend",
    "HybridCacheBackend",
    "ThreadSafeCacheBackend",
    # Models
    "CacheItem",
    # Main manager
    "CacheManager",
    # Vector similarity
    "VectorSimilarityMatcher",
    # Model cache
    "initialize_model_cache",
    "ensure_model_cache_dir",
]
