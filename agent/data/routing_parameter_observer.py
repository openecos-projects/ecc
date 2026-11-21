"""Read the configuration iRT reports after native initialization."""

import re
from contextlib import suppress
from itertools import pairwise
from pathlib import Path

from chipcompiler.utility.log import flush_cstdio

from .candidate_artifacts import sha256_path
from .parameter_runtime_observer import _invoke_and_record

ROUTING_TOOL = "ECC-Routing"
_KEYS = {
    "route.thread_number": "thread_number",
    "route.bottom_layer": "bottom_routing_layer",
    "route.top_layer": "top_routing_layer",
    "route.enable_timing": "enable_timing",
}
_NATIVE_CONFIG = re.compile(r"^\[RT [^\n]* printConfig\]\s+(.*)$", re.MULTILINE)


def run_with_routing_observation(workspace, step, patch, invoke):
    raw_path = step.log.file
    log_path = Path(raw_path) if raw_path else None
    offset = 0
    if log_path is not None:
        with suppress(OSError):
            offset = log_path.stat().st_size
    return _invoke_and_record(
        workspace,
        invoke,
        lambda succeeded: _build_routing_report(
            patch, log_path, offset, engine_succeeded=succeeded
        ),
    )


def _build_routing_report(patch, log_path: Path | None, offset: int, *, engine_succeeded):
    knob_id = patch["knob_id"]
    observed = None
    if log_path is not None:
        try:
            flush_cstdio()
            with log_path.open(encoding="utf-8", errors="replace") as stream:
                stream.seek(offset)
                fields = []
                for line in stream:
                    match = _NATIVE_CONFIG.match(line)
                    if match:
                        fields.append(match[1].strip())
            for key, value in pairwise(fields):
                if key == _KEYS[knob_id]:
                    observed = value
        except OSError:
            pass
    actual = None
    if engine_succeeded and observed is not None:
        if knob_id == "route.thread_number" and observed.isdecimal():
            actual = int(observed)
        elif knob_id == "route.enable_timing" and observed in {"0", "1"}:
            actual = observed == "1"
    return {
        "schema_version": "tool.parameter_runtime_report.v2",
        "knob_id": knob_id,
        "written_value": patch["value"],
        "tool": {
            "name": ROUTING_TOOL,
            "revision": "ecc.agent.routing_parameter_observer.v1",
            "source_sha256": sha256_path(Path(__file__)),
        },
        "actual_value": actual,
        "status": "effective" if actual is not None else "unknown",
        "reason": None if actual is not None else "iRT did not report a verified scalar value.",
        "observation": {"native_config_value": observed, "routing_completed": engine_succeeded},
    }
