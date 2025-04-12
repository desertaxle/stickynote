from .memoize import memoize

__all__ = ["memoize"]

"""
StickyNote - A Python library for memoization with flexible storage backends.

The main decorator is `memoize`, which can be used to cache the results of functions.
It supports various storage backends, key strategies, and serializers.

Example:
    >>> from stickynote import memoize
    >>> from stickynote.storage import MemoryStorage
    >>> 
    >>> # Basic usage
    >>> @memoize
    >>> def add(a, b):
    >>>     return a + b
    >>> 
    >>> # With a custom storage backend
    >>> storage = MemoryStorage()
    >>> @memoize(storage=storage)
    >>> def multiply(a, b):
    >>>     return a * b
    >>> 
    >>> # With a cache hit callback
    >>> cache_hit_count = 0
    >>> def on_cache_hit():
    >>>     nonlocal cache_hit_count
    >>>     cache_hit_count += 1
    >>> 
    >>> @memoize(storage=storage, on_cache_hit=on_cache_hit)
    >>> def subtract(a, b):
    >>>     return a - b
"""
