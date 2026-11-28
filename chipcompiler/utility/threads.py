"""Single CPU budget shared by every tool that takes a thread count."""

import logging
import os

ENV_THREADS = "ECC_THREADS"
_LOG = logging.getLogger(__name__)


def env_thread_budget() -> int | None:
    """Validated positive integer from ``ECC_THREADS``, or None when unset/invalid."""
    raw = os.environ.get(ENV_THREADS, "").strip()
    if not raw:
        return None
    if raw.isascii() and raw.isdigit() and int(raw) > 0:
        return int(raw)
    _LOG.warning("Ignoring invalid %s=%r; using process CPU affinity", ENV_THREADS, raw)
    return None


def _available_cpus() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def _validate_positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def thread_budget(default: int | None = None) -> int:
    """``ECC_THREADS`` when set cleanly, else CPUs available capped by ``default``."""
    if default is not None:
        _validate_positive_int(default, "default")
    configured = env_thread_budget()
    if configured is not None:
        return configured
    available = _available_cpus()
    return available if default is None else min(default, available)


def resolve_thread_count(thread_number: int | None = None, *, default: int | None = None) -> int:
    """Resolve an explicit thread count or fall back to ``thread_budget(default=default)``."""
    if thread_number is None:
        return thread_budget(default=default)
    return _validate_positive_int(thread_number, "thread_number")
