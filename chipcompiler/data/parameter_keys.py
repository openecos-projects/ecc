#!/usr/bin/env python

"""Conversion between legacy long parameter keys and canonical flat names.

The canonical parameter vocabulary is flat snake_case (``frequency_max``,
``top_module``, ``die``/``core`` subtrees, ...). Older workspaces persisted
display-oriented keys (``"Frequency max [MHz]"``, ``"Top module"``, ...) and
the GUI sends flat keys plus a handful of positional geometry aliases at the
project/RPC boundary. This module is the only place that knows the legacy
vocabulary; everything else consumes the canonical form.
"""

import logging
import re
from copy import deepcopy

logger = logging.getLogger(__name__)

_UNIT_SUFFIX = re.compile(r"\[[^\]]*\]")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Positional GUI geometry aliases and where they live in the canonical tree.
# (alias, subtree, key, list index or None)
_GEOMETRY_TO_PARAMETERS = {
    "die_width": ("die", "size", 0),
    "die_height": ("die", "size", 1),
    "utilitization": ("core", "utilitization", None),
    "margin": ("core", "margin", 0),
}


def normalize_key(key: object) -> str:
    """Map one legacy/display key to its canonical snake_case form."""
    without_units = _UNIT_SUFFIX.sub("", str(key))
    normalized = _NON_ALNUM.sub("_", without_units.strip().lower())
    return normalized.strip("_")


def normalize_keys(data: object, _path: str = "") -> object:
    """Recursively normalize every dict key in *data*.

    Returns a new structure; the input is not mutated. When a long key and
    its already-canonical form collide, the long-key value wins (the
    workspace's artifacts were produced with it) and the dropped flat value
    is logged.
    """
    if isinstance(data, dict):
        result = {}
        collisions = []
        for key, value in data.items():
            canonical = normalize_key(key)
            normalized_value = normalize_keys(value, f"{_path}{canonical}.")
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
                f"{_path}{canonical}",
            )
        return result
    if isinstance(data, list):
        return [normalize_keys(item, _path) for item in data]
    return data


def geometry_to_parameters(flat: dict) -> dict:
    """Convert a GUI flat payload (geometry aliases included) to canonical form.

    Returns a new dict: mechanical normalization first, then the positional
    aliases folded into the ``die``/``core`` subtrees, and the GUI-only
    ``die_area_mode`` dropped. Unknown flat keys are kept as-is.
    """
    normalized = normalize_keys(flat)
    assert isinstance(normalized, dict)
    normalized.pop("die_area_mode", None)
    for alias, (subtree, key, index) in _GEOMETRY_TO_PARAMETERS.items():
        if alias not in normalized:
            continue
        value = normalized.pop(alias)
        subtree_data = normalized.setdefault(subtree, {})
        if not isinstance(subtree_data, dict):
            logger.warning("geometry alias %s dropped: %s is not a mapping", alias, subtree)
            continue
        if index is None:
            subtree_data[key] = value
            continue
        entries = subtree_data.get(key)
        if not isinstance(entries, list):
            entries = []
        while len(entries) <= index:
            entries.append(0)
        entries[index] = value
        subtree_data[key] = entries
    return normalized


def parameters_to_geometry(parameters: dict) -> dict:
    """Project canonical parameters back to the GUI flat vocabulary.

    The inverse of :func:`geometry_to_parameters`: subtree values surface as
    the positional aliases, and ``die_area_mode`` is derived
    (``width_height`` when a die size is present, else
    ``utilitization_margin``).
    """
    flat = deepcopy(parameters)
    for alias, (subtree, key, index) in _GEOMETRY_TO_PARAMETERS.items():
        subtree_data = flat.get(subtree)
        if not isinstance(subtree_data, dict):
            continue
        if index is None:
            if key in subtree_data:
                flat[alias] = subtree_data[key]
            continue
        entries = subtree_data.get(key)
        if isinstance(entries, list) and len(entries) > index:
            flat[alias] = entries[index]
    die = flat.get("die")
    die_size = die.get("size") if isinstance(die, dict) else None
    flat["die_area_mode"] = "width_height" if die_size else "utilitization_margin"
    return flat
