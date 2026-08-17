"""Retry utilities with exponential backoff for transient failures."""
import time
import random
from functools import wraps


def with_retry(max_retries=3, base_delay=0.5, max_delay=30.0, exceptions=(Exception,)):
    """Decorator for retrying a function with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts (0 = no retries)
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        exceptions: Tuple of exception types to catch and retry
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        break
                    # Exponential backoff with jitter
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    delay *= (0.5 + random.random() * 0.5)  # Add jitter
                    time.sleep(delay)
            # If we get here, all retries failed
            raise last_exception
        return wrapper
    return decorator


def retry_call(func, *args, max_retries=2, base_delay=0.5, **kwargs):
    """Call a function with retry logic, returning error message on failure instead of raising.
    
    This is useful for tool calls where we want to return a meaningful error rather than crash.
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt == max_retries:
                break
            delay = min(base_delay * (2 ** attempt), 10.0)
            delay *= (0.5 + random.random() * 0.5)
            time.sleep(delay)
    
    # All retries failed - return error message
    return f"{func.__name__} failed after {max_retries + 1} attempts: {type(last_error).__name__}: {last_error}"
