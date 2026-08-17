"""Caching layer for Wilco - caches tool results and LLM responses for faster, cheaper operation.

This module provides transparent caching with TTL support, so repeated queries return cached results
instead of hitting APIs or re-executing tools. Cache entries are stored on disk for persistence
across sessions, with automatic cleanup of expired entries.
"""
import hashlib
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

CACHE_DIR = Path.home() / ".wilco" / "cache"
CACHE_FILE = CACHE_DIR / "cache.json"
DEFAULT_TTL = 3600  # 1 hour in seconds


def _load_cache() -> dict:
    """Load cache from disk, or return empty dict if missing/corrupt."""
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_cache(data: dict):
    """Persist cache to disk."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


def _make_key(prefix: str, *args, **kwargs) -> str:
    """Create a cache key from arguments."""
    key_data = f"{prefix}:{args}:{sorted(kwargs.items())}"
    return hashlib.md5(key_data.encode()).hexdigest()


def get(prefix: str, *args, **kwargs) -> Optional[Any]:
    """Get a cached value if it exists and hasn't expired."""
    key = _make_key(prefix, *args, **kwargs)
    cache = _load_cache()
    
    if key in cache:
        entry = cache[key]
        # Check if expired
        if "expires_at" in entry:
            expires_at = datetime.fromisoformat(entry["expires_at"])
            if datetime.now() > expires_at:
                # Expired, remove it
                del cache[key]
                _save_cache(cache)
                return None
        return entry.get("value")
    return None


def set(prefix: str, value: Any, ttl: int = DEFAULT_TTL, *args, **kwargs):
    """Cache a value with the given TTL in seconds."""
    key = _make_key(prefix, *args, **kwargs)
    cache = _load_cache()
    
    expires_at = (datetime.now() + timedelta(seconds=ttl)).isoformat()
    cache[key] = {
        "value": value,
        "expires_at": expires_at,
        "created_at": datetime.now().isoformat(),
    }
    
    _save_cache(cache)


def invalidate(prefix: str = None, *args, **kwargs):
    """Invalidate cache entries. If prefix is None, clears all cache."""
    cache = _load_cache()
    
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
            expires_at = datetime.fromisoformat(entry["expires_at"])
            if now > expires_at:
                expired_keys.append(key)
    
    for key in expired_keys:
        del cache[key]
    
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
            expires_at = datetime.fromisoformat(entry["expires_at"])
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
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Try to get from cache
            cached_value = get(func.__name__, *args, **kwargs)
            if cached_value is not None:
                return cached_value
            
            # Call function and cache result
            result = func(*args, **kwargs)
            set(func.__name__, result, ttl, *args, **kwargs)
            return result
        return wrapper
    return decorator