"""Small helpers for measuring elapsed time in connection tests."""
import time


def elapsed_ms_since(start: float) -> int:
    """Return whole milliseconds since perf_counter() value start."""
    return int((time.perf_counter() - start) * 1000)
