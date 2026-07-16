"""Data provider module with caching support."""

from stock_scanner.data.provider import DataProvider
from stock_scanner.data.cache import (
    get_cached,
    set_cached,
    cached,
    get_fundamental_cache,
    set_fundamental_cache,
    get_price_cache,
    set_price_cache,
    get_benchmark_cache,
    set_benchmark_cache,
    get_scan_cache,
    set_scan_cache,
    CacheTransaction,
    BatchCache,
    clear_expired,
    invalidate_prefix,
)

__all__ = [
    "DataProvider",
    "get_cached",
    "set_cached",
    "cached",
    "get_fundamental_cache",
    "set_fundamental_cache",
    "get_price_cache",
    "set_price_cache",
    "get_benchmark_cache",
    "set_benchmark_cache",
    "get_scan_cache",
    "set_scan_cache",
    "CacheTransaction",
    "BatchCache",
    "clear_expired",
    "invalidate_prefix",
]
