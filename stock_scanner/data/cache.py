"""Incremental caching layer with TTL support."""

from __future__ import annotations

import hashlib
import pickle
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

from stock_scanner.engine.typing import Ticker

# Cache configuration
CACHE_DIR = Path("reports/.cache")
DEFAULT_TTL = 86400  # 24 hours in seconds

# Type variables for generic decorators
P = ParamSpec("P")
R = TypeVar("R")


def _ensure_cache_dir() -> None:
    """Ensure cache directory exists."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_key(prefix: str, *args, **kwargs) -> str:
    """Generate a deterministic cache key from function arguments."""
    # Create a stable string representation
    key_parts = [prefix]
    key_parts.extend(str(arg) for arg in args)
    key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    key_string = "|".join(key_parts)
    return hashlib.sha256(key_string.encode()).hexdigest()[:16]


def _cache_path(key: str) -> Path:
    """Get the full path for a cache key."""
    return CACHE_DIR / f"{key}.pkl"


def get_cached(key: str, ttl: int = DEFAULT_TTL) -> Any | None:
    """Retrieve a cached value if it exists and hasn't expired.

    Args:
        key: Cache key
        ttl: Time-to-live in seconds

    Returns:
        Cached value or None if not found/expired
    """
    _ensure_cache_dir()
    path = _cache_path(key)

    if not path.exists():
        return None

    # Check TTL
    mtime = path.stat().st_mtime
    if time.time() - mtime > ttl:
        # Expired - remove and return None
        path.unlink(missing_ok=True)
        return None

    try:
        return pickle.loads(path.read_bytes())
    except (pickle.PickleError, EOFError, OSError):
        # Corrupted cache - remove and return None
        path.unlink(missing_ok=True)
        return None


def set_cached(key: str, value: Any) -> None:
    """Store a value in the cache.

    Args:
        key: Cache key
        value: Value to cache (must be picklable)
    """
    _ensure_cache_dir()
    path = _cache_path(key)
    try:
        path.write_bytes(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
    except (pickle.PickleError, OSError) as e:
        # Log error but don't fail the operation
        import logging

        logging.getLogger(__name__).warning(f"Failed to write cache {key}: {e}")


def cached(ttl: int = DEFAULT_TTL, prefix: str = "") -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to cache function results with TTL.

    Args:
        ttl: Time-to-live in seconds
        prefix: Optional prefix for cache keys

    Example:
        @cached(ttl=3600, prefix="fundamentals")
        def fetch_fundamentals(ticker: str, year: int) -> dict:
            ...
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Generate cache key
            cache_prefix = prefix or func.__module__.split(".")[-1]
            key = _cache_key(f"{cache_prefix}.{func.__name__}", *args, **kwargs)

            # Try to get from cache
            cached = get_cached(key, ttl)
            if cached is not None:
                return cached

            # Call function and cache result
            result = func(*args, **kwargs)
            set_cached(key, result)
            return result

        return wrapper

    return decorator


# Specialized cache functions for common operations
def get_price_cache_key(tickers: list[Ticker], period: str = "1y") -> str:
    """Generate cache key for price data."""
    tickers_sorted = sorted(tickers)
    return _cache_key(f"prices.{period}", *tickers_sorted)


def get_fundamental_cache_key(ticker: Ticker, as_of_year: int | None = None) -> str:
    """Generate cache key for fundamental data."""
    return _cache_key("fundamentals", ticker, as_of_year or "latest")


def get_benchmark_cache_key(symbol: str, period: str = "2y") -> str:
    """Generate cache key for benchmark data."""
    return _cache_key(f"benchmark.{period}", symbol)


def get_sentiment_cache_key(ticker: Ticker) -> str:
    """Generate cache key for sentiment data."""
    return _cache_key("sentiment", ticker)


def clear_cache(pattern: str = "*") -> int:
    """Clear cache entries matching pattern.

    Args:
        pattern: Glob pattern for cache files to remove

    Returns:
        Number of files removed
    """
    _ensure_cache_dir()
    count = 0
    for path in CACHE_DIR.glob(f"{pattern}.pkl"):
        try:
            path.unlink()
            count += 1
        except OSError:
            pass
    return count


def get_cache_stats() -> dict:
    """Get cache statistics.

    Returns:
        Dict with cache size, file count, oldest/newest entries
    """
    _ensure_cache_dir()
    files = list(CACHE_DIR.glob("*.pkl"))

    if not files:
        return {
            "total_files": 0,
            "total_size_bytes": 0,
            "oldest_entry": None,
            "newest_entry": None,
        }

    total_size = sum(f.stat().st_size for f in files)
    mtimess = [f.stat().st_mtime for f in files]

    return {
        "total_files": len(files),
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "oldest_entry": min(mtimess) if mtimess else None,
        "newest_entry": max(mtimess) if mtimess else None,
    }


# Context manager for batch cache operations
class CacheBatch:
    """Batch multiple cache writes for efficiency."""

    def __init__(self):
        self._pending: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        """Add to batch."""
        self._pending[key] = value

    def commit(self) -> int:
        """Write all pending entries."""
        count = 0
        for key, value in self._pending.items():
            set_cached(key, value)
            count += 1
        self._pending.clear()
        return count

    def __enter__(self) -> CacheBatch:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.commit()


# Specialized cache functions for common operations
def get_price_cache(tickers: list[str], period: str = "1y") -> dict | None:
    """Get cached price data for tickers."""
    key = get_price_cache_key(tickers, period)
    return get_cached(key, ttl=3600)  # 1 hour TTL


def set_price_cache(tickers: list[str], data: dict, period: str = "1y") -> None:
    """Cache price data for tickers."""
    key = get_price_cache_key(tickers, period)
    set_cached(key, data)


def get_benchmark_cache(symbol: str, period: str = "2y") -> dict | None:
    """Get cached benchmark data."""
    key = get_benchmark_cache_key(symbol, period)
    return get_cached(key, ttl=86400)  # 24 hour TTL


def set_benchmark_cache(symbol: str, data: dict, period: str = "2y") -> None:
    """Cache benchmark data."""
    key = get_benchmark_cache_key(symbol, period)
    set_cached(key, data)


def get_fundamental_cache(ticker: str, as_of_year: int | None = None) -> dict | None:
    """Get cached fundamental data for a ticker."""
    key = get_fundamental_cache_key(ticker, as_of_year)
    return get_cached(key, ttl=86400 * 30)  # 30 days TTL


def set_fundamental_cache(ticker: str, data: dict, as_of_year: int | None = None) -> None:
    """Cache fundamental data for a ticker."""
    key = get_fundamental_cache_key(ticker, as_of_year)
    set_cached(key, data)


def get_scan_cache(scan_name: str, **filters) -> dict | None:
    """Get cached scan results."""
    key = f"scan_{scan_name}"
    for k, v in sorted(filters.items()):
        key += f"_{k}={v}"
    return get_cached(key, ttl=86400)


def set_scan_cache(scan_name: str, data: dict, **filters) -> None:
    """Cache scan results."""
    key = f"scan_{scan_name}"
    for k, v in sorted(filters.items()):
        key += f"_{k}={v}"
    set_cached(key, data)


# Context manager for cache transactions
class CacheTransaction:
    """Context manager for atomic cache updates."""

    def __init__(self, prefix: str, **params):
        self.prefix = prefix
        self.params = params
        self._temp_data = None

    def __enter__(self) -> CacheTransaction:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None and self._temp_data is not None:
            set_cached(self.prefix, self._temp_data, **self.params)
        return False

    def set(self, data):
        self._temp_data = data


# Batch cache operations for performance
class BatchCache:
    """Batch multiple cache operations for efficiency."""

    def __init__(self):
        self._gets = []
        self._sets = []

    def get(self, prefix: str, **params):
        """Queue a get operation."""
        key = _cache_key(prefix, **params)
        self._gets.append((prefix, params, key))
        return (key, None)

    def set(self, prefix: str, value, **params):
        """Queue a set operation."""
        self._sets.append((prefix, value, params))

    def execute(self):
        """Execute all queued operations."""
        results = {}

        # Execute gets
        for prefix, params, key in self._gets:
            path = _cache_path(key)
            if path.exists():
                try:
                    results[key] = pickle.loads(path.read_bytes())
                except (pickle.PickleError, EOFError, OSError):
                    results[key] = None
            else:
                results[key] = None

        # Execute sets
        for prefix, value, params in self._sets:
            key = _cache_key(prefix, **params)
            path = _cache_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL))
            results[key] = value

        return results

    def __enter__(self) -> BatchCache:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.execute()
        return False


def clear_expired(ttl: int = DEFAULT_TTL) -> int:
    """Remove all expired cache entries.

    Returns:
        Number of files removed
    """
    _ensure_cache_dir()
    count = 0
    now = time.time()
    for path in CACHE_DIR.glob("*.pkl"):
        try:
            mtime = path.stat().st_mtime
            if now - mtime > ttl:
                path.unlink()
                count += 1
        except OSError:
            pass
    return count


def invalidate_prefix(prefix: str) -> int:
    """Invalidate all cache entries matching prefix.

    Returns:
        Number of files removed
    """
    _ensure_cache_dir()
    count = 0
    for path in CACHE_DIR.glob(f"{prefix}_*.pkl"):
        try:
            path.unlink()
            count += 1
        except OSError:
            pass
    return count
