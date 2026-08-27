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
from typing_extensions import deprecated

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


@deprecated(
    "legacy parameters.json -> ecc.toml migration; slated for removal once "
    "legacy workspaces are phased out",
    category=None,
)
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


def _contiguous_range(chain: list[str], first: str, last: str) -> list[str]:
    """Chain names from *first* to *last* inclusive."""
    return chain[chain.index(first) : chain.index(last) + 1]


def flow_steps_in_range(start: str, end: str) -> list[str]:
    """Canonical step names from *start* to *end* inclusive."""
    chain = canonical_flow_chain()
    try:
        return _contiguous_range(chain, start, end)
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

    from chipcompiler.data.workspace import _canonical_harden_flow_entries

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
    """Inverse of _split_payload: flatten TOML sections back to one dict.

    The merged payload is normalized to the canonical flat vocabulary:
    a hand-written ecc.toml with legacy long keys (or GUI geometry
    aliases) never leaks non-canonical keys into a loaded Parameters
    payload.
    """
    for name in ("params", "design", "pdk"):
        section = sections.get(name)
        if section is not None and not isinstance(section, dict):
            raise WorkspaceConfigError(f"[{name}] must be a table, not {type(section).__name__}")
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

    from .parameter_keys import normalize_parameter_dict

    return normalize_parameter_dict(params)


def _decode_workspace_config(path: Path, workspace_dir: str | Path) -> dict:
    """Decode and validate one workspace config document.

    Shared by load_workspace_config (canonical location) and the staged
    migration candidate: TOML parse, [flow] validation with ledger
    fallback, payload merge, and workspace-relative pdk_config resolution.
    Raises WorkspaceConfigError on TOML parse failure and
    WorkspaceFlowTargetError on [flow] rule violations.
    """
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise WorkspaceConfigError(f"workspace config parse failure: {path}: {exc}") from exc

    flow = validate_flow_config(raw.get("flow"))
    if not flow:
        # A hand-broken file without [flow] derives its target from the
        # persisted execution ledger (first and last step names).
        flow = _derive_flow_from_ledger(workspace_dir)
    payload = _merge_payload(raw)

    pdk_config = payload.get("pdk_config")
    if isinstance(pdk_config, str) and pdk_config and not os.path.isabs(pdk_config):
        payload["pdk_config"] = str(Path(workspace_dir) / pdk_config)

    payload["_flow"] = flow
    return payload


def load_workspace_config(workspace_dir: str | Path) -> dict:
    """Load ``home/ecc.toml`` as a canonical flat parameter payload.

    The returned dict always carries a ``_flow`` entry with the validated
    ``[flow]`` section (empty dict when absent). ``pdk_config`` is resolved
    against the workspace directory when stored workspace-relative.

    Raises WorkspaceConfigError on TOML parse failure and
    WorkspaceFlowTargetError on ``[flow]`` rule violations.
    """
    return _decode_workspace_config(workspace_config_path(workspace_dir), workspace_dir)


def _derive_flow_from_ledger(workspace_dir: str | Path) -> dict[str, str]:
    """The [flow] section implied by the persisted flow.json, or {}."""
    from chipcompiler.utility import json_read

    data = json_read(Path(workspace_dir) / "home" / "flow.json")
    if not isinstance(data, dict):
        return {}
    steps = data.get("steps", [])
    if not isinstance(steps, list):
        return {}
    names = [
        step["name"]
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("name"), str) and step["name"]
    ]
    if not names:
        return {}
    try:
        return validate_flow_config({"start": names[0], "end": names[-1]})
    except WorkspaceFlowTargetError:
        return {}


def _drop_null_values(value: Any, *, _path: str = "") -> Any:
    """Drop JSON null values TOML cannot serialize, logging each removal.

    Legacy ``parameters.json`` payloads may carry ``null``; a migration
    blocked on it must not leave the workspace permanently unwritable —
    absent beats null here (a parameter that cannot round-trip would
    otherwise read back as a different value anyway).
    """
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if item is None:
                logger.warning("dropping null value at %s%s during TOML render", _path, key)
                continue
            result[key] = _drop_null_values(item, _path=f"{_path}{key}.")
        return result
    if isinstance(value, list):
        result = []
        for index, item in enumerate(value):
            if item is None:
                logger.warning("dropping null element at %s[%d] during TOML render", _path, index)
                continue
            result.append(_drop_null_values(item, _path=f"{_path}[{index}]."))
        return result
    return value


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

    payload = _drop_null_values(dict(data))
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


def _unlink_best_effort(path: Path) -> None:
    """Remove a temporary config candidate, best-effort.

    A failed cleanup must never abort the caller: the fallback contract
    (normalized in-memory copy, retry on next open) does not depend on
    the temp file being gone.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("failed to remove temporary config candidate %s: %s", path, exc)


def _stage_config_bytes(target: Path, content: bytes) -> Path | None:
    """Write and fsync content at a temp path next to target (not installed)."""
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
        return tmp_path
    except OSError:
        logger.warning("failed to write workspace config: %s", target)
        if tmp_path is not None:
            _unlink_best_effort(tmp_path)
        return None


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

    workspace_real = Path(workspace_dir).resolve()
    home_spelled = workspace_real / "home"
    if home_spelled.is_symlink() or (home_spelled / WORKSPACE_CONFIG_FILENAME).is_symlink():
        # A symlinked config target (leaf or its home parent) would redirect
        # the staged replace onto whatever it points at (potentially outside
        # the workspace): refuse instead of overwriting a file we do not own.
        logger.warning(
            "refusing to write workspace config through a symlinked path: %s",
            home_spelled / WORKSPACE_CONFIG_FILENAME,
        )
        return False
    target = (home_spelled / WORKSPACE_CONFIG_FILENAME).resolve()
    tmp_path = _stage_config_bytes(target, content)
    if tmp_path is None:
        return False
    try:
        os.replace(tmp_path, target)
        return True
    except OSError:
        logger.warning("failed to write workspace config: %s", target)
        _unlink_best_effort(tmp_path)
        return False


def resolve_flow_selection(
    flow_config: dict,
    canonical_steps: list[tuple[str, str, str]],
) -> tuple[list[str], bool]:
    """Canonical step names selected by *flow_config*, widened to a range.

    Returns (names, degraded): an explicit non-contiguous selection degrades
    to the contiguous first..last range with a log note, so the execution
    ledger and the persisted flow target can never contradict each other.
    """
    from chipcompiler.data.workspace import _selected_dynamic_flow_step_names

    selected_names = _selected_dynamic_flow_step_names(flow_config, canonical_steps)
    if not selected_names:
        return ([], False)

    canonical_names = [name for name, _tool, _state in canonical_steps]
    contiguous = _contiguous_range(canonical_names, selected_names[0], selected_names[-1])
    if contiguous == selected_names:
        return (contiguous, False)

    logger.warning(
        "non-contiguous flow steps %s degraded to contiguous range %s..%s",
        selected_names,
        selected_names[0],
        selected_names[-1],
    )
    return (contiguous, True)


@deprecated(
    "legacy parameters.json -> ecc.toml migration; slated for removal once "
    "legacy workspaces are phased out",
    category=None,
)
def migrate_legacy_parameters(workspace_dir: Path) -> None:
    """Rewrite a legacy ``home/parameters.json`` into ``home/ecc.toml``.

    Runs at workspace open, the single choke point for loading workspaces.
    When both files exist the TOML wins and the JSON is left untouched. The
    candidate is staged and validated before its atomic install, so any
    failure (render, write, validation, install) leaves no final TOML:
    the workspace loads via the normalized in-memory copy and the next
    open retries.
    """
    from .parameter_keys import normalize_parameter_dict

    home_spelled = Path(workspace_dir).resolve() / "home"
    if home_spelled.is_symlink():
        # A symlinked home redirects the migration's write AND the legacy
        # delete onto an external directory: never mutate through it.
        logger.warning(
            "legacy parameters migration refused through a symlinked home: %s",
            home_spelled,
        )
        return
    config_path = workspace_config_path(workspace_dir)
    legacy_path = legacy_parameters_path(workspace_dir)
    if config_path.exists():
        if legacy_path.exists():
            logger.warning(
                "workspace_config_shadowed: both %s and %s exist; using the TOML",
                config_path,
                legacy_path,
            )
        return
    if legacy_path.is_symlink():
        # A symlinked legacy parameters file would let the migration copy
        # external content into the workspace and then delete the link:
        # refuse and leave the file untouched.
        logger.warning(
            "legacy parameters migration refused through a symlinked file: %s",
            legacy_path,
        )
        return
    if not legacy_path.exists():
        return

    from chipcompiler.utility import JsonReadError, json_read_strict

    try:
        legacy_data = json_read_strict(legacy_path)
    except (JsonReadError, OSError) as exc:
        logger.warning("legacy parameters unreadable, skipping migration: %s: %s", legacy_path, exc)
        return
    if not isinstance(legacy_data, dict):
        logger.warning(
            "legacy parameters unreadable, skipping migration: %s: not a JSON object", legacy_path
        )
        return

    normalized = normalize_parameter_dict(legacy_data)
    # Derive the flow target from the persisted flow's first/last steps so
    # the migrated workspace stays self-describing.
    flow_section = _derive_flow_from_ledger(workspace_dir)
    try:
        content = render_workspace_config(workspace_dir, normalized, flow_section or None)
    except (TypeError, ValueError) as exc:
        # Payload values tomli_w cannot serialize (e.g. a legacy null).
        logger.warning(
            "legacy parameters migration deferred (render failed): %s: %s", legacy_path, exc
        )
        return

    # Stage the candidate, validate it against the workspace root, and only
    # then atomically install it. A failed candidate validation leaves NO
    # final config behind, so the next open retries without any cleanup of
    # an installed unverified file.
    candidate = _stage_config_bytes(config_path, content)
    if candidate is None:
        logger.warning("legacy parameters migration deferred (rewrite failed): %s", legacy_path)
        return
    try:
        _decode_workspace_config(candidate, workspace_dir)
    except Exception as exc:
        logger.warning(
            "legacy parameters migration deferred (verify failed): %s: %s", config_path, exc
        )
        _unlink_best_effort(candidate)
        return
    try:
        os.replace(candidate, config_path)
    except OSError as exc:
        logger.warning(
            "legacy parameters migration deferred (install failed): %s: %s", config_path, exc
        )
        _unlink_best_effort(candidate)
        return
    try:
        legacy_path.unlink()
    except OSError as exc:
        # The TOML is verified; a leftover JSON only re-enters the shadowed
        # branch on the next open — warn, but the workspace is migrated.
        logger.warning(
            "legacy parameters migrated but the original file could not be removed: %s: %s",
            legacy_path,
            exc,
        )


@deprecated(
    "legacy parameters.json -> ecc.toml migration; slated for removal once "
    "legacy workspaces are phased out",
    category=None,
)
def legacy_parameters_fallback(workspace_dir: str | Path) -> dict:
    """Normalized in-memory copy of a legacy parameters.json, or {}.

    Used when the rewrite was deferred (e.g. read-only dir) so the
    workspace still opens; the next open retries the migration.
    """
    from chipcompiler.utility import json_read

    from .parameter_keys import normalize_parameter_dict

    data = json_read(legacy_parameters_path(workspace_dir))
    if not isinstance(data, dict):
        return {}
    return normalize_parameter_dict(data)
