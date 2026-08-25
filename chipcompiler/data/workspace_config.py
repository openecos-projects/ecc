#!/usr/bin/env python

"""Workspace configuration persistence: ``home/ecc.toml``.

The workspace's resolved configuration snapshot lives in TOML so a workspace
is self-describing in the same vocabulary as the project-level ``ecc.toml``.
JSON remains the format for machine state (``flow.json``, checklist,
metrics); this module owns the human-facing configuration file only.

Layout::

    [design]   name / top / clock_port / frequency_mhz
    [pdk]      name / root (absolute) / config (workspace-relative)
    [flow]     preset = "rtl2gds"  OR  start = "...", end = "..."
    [params]   flat snake_case parameters; nested dicts map to subtables
"""

import logging
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomli_w

logger = logging.getLogger(__name__)

WORKSPACE_CONFIG_FILENAME = "ecc.toml"
LEGACY_PARAMETERS_FILENAME = "parameters.json"

_IDENTITY_FIELDS = ("pdk", "design", "top_module", "clock")

# param key -> TOML section key, for [design] and [pdk]. Splitting mirrors a
# non-empty section value back under the param key; frequency is copied (not
# moved) so the params copy stays authoritative on load.
_DESIGN_SECTION_KEYS = {
    "design": "name",
    "top_module": "top",
    "clock": "clock_port",
    "frequency_max": "frequency_mhz",
}
_PDK_SECTION_KEYS = {
    "pdk": "name",
    "pdk_root": "root",
    "pdk_config": "config",
}


class WorkspaceConfigError(ValueError):
    """Invalid ``home/ecc.toml`` content (parse failure or rule violation)."""


class WorkspaceFlowTargetError(ValueError):
    """Invalid ``[flow]`` section in a workspace configuration."""


def workspace_config_path(workspace_dir: str | Path) -> Path:
    return Path(workspace_dir) / "home" / WORKSPACE_CONFIG_FILENAME


def legacy_parameters_path(workspace_dir: str | Path) -> Path:
    return Path(workspace_dir) / "home" / LEGACY_PARAMETERS_FILENAME


def is_workspace_config(path: str | Path) -> bool:
    """True when *path* names a workspace config file (TOML or legacy JSON)."""
    return Path(path).name in (WORKSPACE_CONFIG_FILENAME, LEGACY_PARAMETERS_FILENAME)


def parameters_have_chip_identity(data: object) -> bool:
    """Return True when parameters still carry chip identity fields."""
    if not isinstance(data, dict):
        return False
    # Rewrap to a plain dict: isinstance narrowing alone leaves dict[Never]
    # keys under ty, which rejects every .get call below.
    payload: dict = dict(data)
    for key in _IDENTITY_FIELDS:
        if str(payload.get(key, "")).strip():
            return True
    die = payload.get("die")
    if isinstance(die, dict):
        try:
            area = float(die.get("area") or 0)
        except (TypeError, ValueError):
            area = 0.0
        if area > 0:
            return True
    return False


def validate_flow_config(flow: object) -> dict[str, str]:
    """Validate a ``[flow]`` section; return it as a plain string dict.

    Raises WorkspaceFlowTargetError on any rule violation: ``preset`` mixed
    with ``start``/``end``, only one of ``start``/``end``, unknown step
    names, or ``start`` positioned after ``end`` in the canonical chain.
    """
    if flow is None:
        return {}
    if not isinstance(flow, dict):
        raise WorkspaceFlowTargetError(f"[flow] must be a table, not {type(flow).__name__}")
    section: dict = dict(flow)
    preset = section.get("preset")
    start = section.get("start")
    end = section.get("end")
    if preset is not None and (start is not None or end is not None):
        raise WorkspaceFlowTargetError("[flow] preset cannot be combined with start/end")
    if (start is None) != (end is None):
        raise WorkspaceFlowTargetError("[flow] start and end must be set together")
    if preset is None and start is None:
        return {}

    result: dict[str, str] = {}
    if preset is not None:
        if not isinstance(preset, str) or not preset.strip():
            raise WorkspaceFlowTargetError(f"[flow] preset must be a non-empty string: {preset!r}")
        flow_range_for_preset(preset)  # raises on unknown presets
        result["preset"] = preset
        return result

    from chipcompiler.data.workspace import _canonical_harden_flow_entries

    canonical_names = [name for name, _tool, _state in _canonical_harden_flow_entries()]
    normalized: dict[str, str] = {}
    for key, value in (("start", start), ("end", end)):
        if not isinstance(value, str):
            raise WorkspaceFlowTargetError(f"[flow] {key} must be a string: {value!r}")
        # Workspace files carry canonical step names only; display-name
        # aliases are translated at the manifest/RPC boundary, never here.
        if value not in canonical_names:
            raise WorkspaceFlowTargetError(f"[flow] unknown step name: {value!r}")
        normalized[key] = value
    if canonical_names.index(normalized["start"]) > canonical_names.index(normalized["end"]):
        raise WorkspaceFlowTargetError(
            f"[flow] start {normalized['start']!r} is after end {normalized['end']!r}"
        )
    return normalized


def canonical_flow_chain() -> list[str]:
    """The canonical harden chain's step names, in order."""
    from chipcompiler.data.workspace import _canonical_harden_flow_entries

    return [name for name, _tool, _state in _canonical_harden_flow_entries()]


def flow_range_for_preset(preset: str) -> tuple[str, str]:
    """(first, last) canonical step names of a named preset."""
    from chipcompiler import rtl2gds as rtl2gds_api

    builder = rtl2gds_api.get_flow_builders().get(preset)
    if builder is None:
        raise WorkspaceFlowTargetError(f"unknown flow preset: {preset}")
    steps = builder()
    if not steps:
        raise WorkspaceFlowTargetError(f"flow preset has no steps: {preset}")
    first, last = steps[0][0], steps[-1][0]
    return (
        first.value if hasattr(first, "value") else str(first),
        last.value if hasattr(last, "value") else str(last),
    )


def flow_range_of(flow: dict) -> tuple[str, str] | None:
    """(start, end) canonical names for a validated [flow] section."""
    flow = validate_flow_config(flow)
    if not flow:
        return None
    if "preset" in flow:
        return flow_range_for_preset(flow["preset"])
    return (flow["start"], flow["end"])


def flow_steps_in_range(start: str, end: str) -> list[str]:
    """Canonical step names from *start* to *end* inclusive."""
    chain = canonical_flow_chain()
    try:
        return chain[chain.index(start) : chain.index(end) + 1]
    except ValueError as exc:
        raise WorkspaceFlowTargetError(f"flow range outside the canonical chain: {exc}") from exc


def flow_section_from_flow_config(flow_config: dict | None) -> dict[str, str]:
    """Derive the [flow] section (start/end canonical form) from a flow_config.

    Uses the same selection resolution as the flow.json seeding, so both
    stores always describe the same contiguous range. Returns {} when the
    flow_config does not select steps.
    """
    if not isinstance(flow_config, dict) or not flow_config:
        return {}

    from chipcompiler.data.workspace import (
        _canonical_harden_flow_entries,
        resolve_flow_selection,
    )

    selected, _degraded = resolve_flow_selection(flow_config, _canonical_harden_flow_entries())
    if not selected:
        return {}

    # Names are already canonical here; validate to keep the contract explicit.
    return validate_flow_config({"start": selected[0], "end": selected[-1]})


def _split_payload(data: dict) -> dict[str, Any]:
    """Split a canonical flat parameter payload into the TOML section shape."""
    params = dict(data)
    design = {
        section_key: params.pop(section_key)
        for section_key in _DESIGN_SECTION_KEYS.values()
        if section_key in params
    }
    # Sync identity keys into the [design] section; the params copies are the
    # authoritative store read back into Parameters.data.
    for param_key, section_key in _DESIGN_SECTION_KEYS.items():
        value = params.get(param_key)
        if section_key not in design and value is not None:
            if isinstance(value, str) and not value.strip():
                continue
            design[section_key] = value

    pdk = {
        section_key: params[param_key]
        for param_key, section_key in _PDK_SECTION_KEYS.items()
        if str(params.get(param_key, "")).strip()
    }
    return {"design": design, "pdk": pdk, "params": params}


def _merge_payload(sections: dict[str, Any]) -> dict:
    """Inverse of _split_payload: flatten TOML sections back to one dict."""
    params = dict(sections.get("params") or {})
    design = sections.get("design") or {}
    pdk = sections.get("pdk") or {}

    for param_key, section_key in _DESIGN_SECTION_KEYS.items():
        value = design.get(section_key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        params[param_key] = value

    for param_key, section_key in _PDK_SECTION_KEYS.items():
        value = pdk.get(section_key)
        if str(value or "").strip():
            params[param_key] = value
    return params


def load_workspace_config(workspace_dir: str | Path) -> dict:
    """Load ``home/ecc.toml`` as a canonical flat parameter payload.

    The returned dict always carries a ``_flow`` entry with the validated
    ``[flow]`` section (empty dict when absent). ``pdk_config`` is resolved
    against the workspace directory when stored workspace-relative.

    Raises WorkspaceConfigError on TOML parse failure and
    WorkspaceFlowTargetError on ``[flow]`` rule violations.
    """
    path = workspace_config_path(workspace_dir)
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise WorkspaceConfigError(f"workspace config parse failure: {path}: {exc}") from exc

    flow = validate_flow_config(raw.get("flow"))
    payload = _merge_payload(raw)

    pdk_config = payload.get("pdk_config")
    if isinstance(pdk_config, str) and pdk_config and not os.path.isabs(pdk_config):
        payload["pdk_config"] = str(Path(workspace_dir) / pdk_config)

    payload["_flow"] = flow
    return payload


def render_workspace_config(
    workspace_dir: str | Path,
    data: dict,
    flow: dict | None = None,
) -> bytes:
    """Render the workspace configuration TOML document.

    ``pdk_config`` values inside the workspace are stored
    workspace-relative; *flow* is validated before rendering.
    """
    if flow:
        validate_flow_config(flow)
    workspace_root = Path(workspace_dir).resolve()

    payload = dict(data)
    pdk_config = payload.get("pdk_config")
    if isinstance(pdk_config, str) and pdk_config and os.path.isabs(pdk_config):
        resolved = Path(pdk_config).resolve()
        if resolved.is_relative_to(workspace_root):
            payload["pdk_config"] = str(resolved.relative_to(workspace_root))

    sections = _split_payload(payload)
    document: dict[str, Any] = {
        "design": sections["design"],
        "pdk": sections["pdk"],
    }
    if flow:
        document["flow"] = dict(flow)
    document["params"] = sections["params"]
    return tomli_w.dumps(document).encode("utf-8")


def save_workspace_config(
    workspace_dir: str | Path,
    data: dict,
    flow: dict | None = None,
) -> bool:
    """Write the workspace configuration atomically (tmp + rename).

    Invalid [flow] sections raise WorkspaceFlowTargetError before anything
    is written; unserializable payloads and filesystem failures return
    False so migration fallback paths stay reachable.
    """
    if flow:
        validate_flow_config(flow)
    try:
        content = render_workspace_config(workspace_dir, data, flow)
    except (TypeError, ValueError) as exc:
        # Payload values tomli_w cannot serialize (e.g. a legacy null).
        logger.warning("failed to render workspace config for %s: %s", workspace_dir, exc)
        return False

    target = workspace_config_path(workspace_dir).expanduser().resolve()
    tmp_path = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=target.parent,
            delete=False,
            prefix=f".{target.name}.",
            suffix=".tmp",
        ) as f:
            tmp_path = Path(f.name)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
        return True
    except OSError:
        logger.warning("failed to write workspace config: %s", target)
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        return False
