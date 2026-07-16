"""Incremental caching layer with TTL support."""

from __future__ import annotations
import hashlib
import pickle
import time
from pathlib import Path
from typing import Any, Callable, TypeVar, ParamSpec
from functools import wraps

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
    
    def __enter__(self) -> "CacheBatch":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.commit()
