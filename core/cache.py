"""Caching layer for Wilco - caches tool results and LLM responses for faster, cheaper operation.

This module provides transparent caching with TTL support, so repeated queries return cached results
instead of hitting APIs or re-executing tools. Cache entries are stored on disk for persistence
across sessions, with automatic cleanup of expired entries.

Optimization: in-memory snapshot avoids reading JSON file on every get/set inside
the Agentic Loop (Gather->Act->Verify). File loaded once, kept in RAM, flushed on write.
"""
import hashlib
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

CACHE_DIR = Path.home() / ".wilco" / "cache"
CACHE_FILE = CACHE_DIR / "cache.json"
DEFAULT_TTL = 3600  # 1 hour in seconds

_lock = threading.RLock()
_mem_cache: dict | None = None
_mem_mtime: float = 0.0


def _load_cache() -> dict:
    """Load cache from disk, or return empty dict if missing/corrupt.

    Optimized: reuses in-memory snapshot when file mtime unchanged, so hot
    path inside tool loop never touches filesystem.
    """
    global _mem_cache, _mem_mtime
    with _lock:
        try:
            mtime = CACHE_FILE.stat().st_mtime if CACHE_FILE.exists() else 0.0
        except OSError:
            mtime = 0.0
        if _mem_cache is not None and mtime == _mem_mtime:
            return _mem_cache
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (json.JSONDecodeError, OSError):
            data = {}
        _mem_cache = data
        _mem_mtime = mtime
        return _mem_cache


def _save_cache(data: dict):
    """Persist cache to disk and update in-memory snapshot."""
    global _mem_cache, _mem_mtime
    with _lock:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            try:
                _mem_mtime = CACHE_FILE.stat().st_mtime
            except OSError:
                _mem_mtime = 0.0
            _mem_cache = data
        except OSError:
            pass


def _make_key(prefix: str, *args, **kwargs) -> str:
    """Create a cache key from arguments."""
    key_data = f"{prefix}:{args}:{sorted(kwargs.items())}"
    return hashlib.md5(key_data.encode(), usedforsecurity=False).hexdigest()  # S4790 safe: non-crypto cache key


def get(prefix: str, *args, **kwargs) -> Optional[Any]:
    """Get a cached value if it exists and hasn't expired."""
    key = _make_key(prefix, *args, **kwargs)
    cache = _load_cache()
    entry = cache.get(key)
    if entry is None:
        return None
    if "expires_at" in entry:
        try:
            expires_at = datetime.fromisoformat(entry["expires_at"])
        except (ValueError, TypeError):
            return entry.get("value")
        if datetime.now() > expires_at:
            with _lock:
                cache.pop(key, None)
            _save_cache(cache)
            return None
    return entry.get("value")


def set(prefix: str, value: Any, ttl: int = DEFAULT_TTL, *args, **kwargs):
    """Cache a value with the given TTL in seconds."""
    key = _make_key(prefix, *args, **kwargs)
    cache = _load_cache()
    now = datetime.now()
    cache[key] = {
        "value": value,
        "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
        "created_at": now.isoformat(),
    }
    _save_cache(cache)


def invalidate(prefix: str = None, *args, **kwargs):
    """Invalidate cache entries. If prefix is None, clears all cache."""
    cache = _load_cache()
    with _lock:
        if prefix is None:
            cache.clear()
        else:
            key = _make_key(prefix, *args, **kwargs)
            cache.pop(key, None)
    _save_cache(cache)


def cleanup_expired():
    """Remove all expired cache entries."""
    cache = _load_cache()
    now = datetime.now()
    expired_keys = []
    for key, entry in cache.items():
        if "expires_at" in entry:
            try:
                expires_at = datetime.fromisoformat(entry["expires_at"])
            except (ValueError, TypeError):
                continue
            if now > expires_at:
                expired_keys.append(key)
    if not expired_keys:
        return 0
    with _lock:
        for key in expired_keys:
            cache.pop(key, None)
    _save_cache(cache)
    return len(expired_keys)


def get_stats() -> dict:
    """Get cache statistics."""
    cache = _load_cache()
    now = datetime.now()
    total = len(cache)
    expired = 0
    for entry in cache.values():
        if "expires_at" in entry:
            try:
                expires_at = datetime.fromisoformat(entry["expires_at"])
            except (ValueError, TypeError):
                continue
            if now > expires_at:
                expired += 1
    return {
        "total_entries": total,
        "expired_entries": expired,
        "active_entries": total - expired,
    }


def cached(ttl: int = DEFAULT_TTL):
    """Decorator for caching function results.

    Usage:
        @cached(ttl=3600)
        def get_weather(city):
            # ... API call ...
            return result
    """
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cached_value = get(func.__name__, *args, **kwargs)
            if cached_value is not None:
                return cached_value
            result = func(*args, **kwargs)
            set(func.__name__, result, ttl, *args, **kwargs)
            return result
        return wrapper
    return decorator
