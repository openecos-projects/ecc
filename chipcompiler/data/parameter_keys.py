#!/usr/bin/env python

"""Conversion between legacy long parameter keys and canonical flat names.

The canonical parameter vocabulary is flat snake_case (``frequency_max``,
``top_module``, ``die``/``core`` subtrees, ...). Older workspaces persisted
display-oriented keys (``"Frequency max [MHz]"``, ``"Top module"``, ...).
This module is the only place that knows the legacy vocabulary; everything
else consumes the canonical form.
"""

import logging
import re
from copy import deepcopy

logger = logging.getLogger(__name__)

_UNIT_SUFFIX = re.compile(r"\[[^\]]*\]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Machine-state payloads whose dict keys are literal identifiers from tool
# config files (JSON paths, tool config keys, cell names). Normalizing them
# would redirect config_override patches onto bogus keys (e.g. "RT" -> "rt",
# "-thread_number" -> "thread_number") and rewrite JSON values such as
# sta.signoff corner names, so their subtrees round-trip untouched.
_RESERVED_PAYLOAD_KEYS = frozenset(
    {"config_overrides", "workspace_param_overrides", "pdk_overrides"}
)

# Internal workspace controls are canonical identifiers too. They are kept
# out of the user-facing schema, but must survive params.toml round-trips.
_INTERNAL_PARAMETER_KEYS = frozenset({"_input_mode", "_flow"})


def normalize_key(key: object) -> str:
    """Map one legacy/display key to its canonical snake_case form."""
    without_units = _UNIT_SUFFIX.sub("", str(key))
    normalized = _NON_ALNUM.sub("_", without_units.strip().lower())
    return normalized.strip("_")


def normalize_keys(data, _path: str = "") -> object:
    """Recursively normalize every dict key in *data*.

    Returns a new structure; the input is not mutated. When a long key and
    its already-canonical form collide, the long-key value wins (the
    workspace's artifacts were produced with it) and the dropped flat value
    is logged.
    """
    if isinstance(data, dict):
        return _normalize_dict(data, _path)
    if isinstance(data, list):
        return [normalize_keys(item, _path) for item in data]
    return data


def normalize_parameter_dict(data: dict) -> dict:
    """Normalize a parameter payload, preserving the plain ``dict`` type."""
    return _normalize_dict(data, "")


def _normalize_dict(data: dict, path: str) -> dict:
    result: dict = {}
    collisions = []
    for key, value in data.items():
        canonical = str(key) if str(key) in _INTERNAL_PARAMETER_KEYS else normalize_key(key)
        if canonical in _RESERVED_PAYLOAD_KEYS:
            # Literal tool-config identifiers must survive the round-trip.
            result[canonical] = deepcopy(value)
            continue
        normalized_value = normalize_keys(value, f"{path}{canonical}.")
        if canonical in result:
            collisions.append(canonical)
            if str(key) == canonical:
                # Inert flat duplicate of a long key already seen: the
                # long-key value wins, the flat one is dropped.
                continue
        result[canonical] = normalized_value
    for canonical in collisions:
        logger.warning(
            "parameter key collision at %s: keeping long-key value, dropping flat duplicate",
            f"{path}{canonical}",
        )
    return result
