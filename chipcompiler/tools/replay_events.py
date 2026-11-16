"""Optional phase events for report/export operations with no physical mutations."""

import itertools
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path

from chipcompiler.tools.replay_storage import atomic_json

_sequence = itertools.count()
logger = logging.getLogger(__name__)


def analysis_event(phase: str, subflow: str, metrics: dict | None = None) -> None:
    directory = os.environ.get("ECC_REPLAY_CAPTURE_DIR")
    if not directory:
        return
    try:
        sequence = next(_sequence)
        producer = f"ecc-{os.getpid()}"
        stamp = time.monotonic_ns()
        atomic_json(
            Path(directory) / f"{producer}-{stamp}-{sequence}.json",
            {
                "sequence": sequence,
                "producer": producer,
                "elapsed_ns": stamp - int(os.environ["ECC_REPLAY_START_NS"]),
                "phase": phase,
                "subflow": subflow,
                "state_domain": "analysis_state",
                "scope": "patch",
                "objects": {},
                "metrics": metrics or {},
            },
        )
    except (OSError, ValueError, KeyError):
        logger.warning("Cannot record Replay phase %s", phase, exc_info=True)


@contextmanager
def export_phase(kind: str, path: str):
    """Observe an existing export without changing its execution or validation."""
    enabled = bool(os.environ.get("ECC_REPLAY_CAPTURE_DIR"))
    if enabled:
        analysis_event(f"{kind}_export_started", "run harden")
    try:
        yield
    except Exception:
        if enabled:
            analysis_event(f"{kind}_export_failed", "run harden")
        raise
    else:
        if enabled:
            artifact = Path(path)
            try:
                size = artifact.stat().st_size
            except OSError:
                size = None
            analysis_event(f"{kind}_export_completed", "run harden", {"artifact_bytes": size})
