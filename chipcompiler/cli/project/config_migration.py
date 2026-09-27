"""Compatibility repair for manifest projects with legacy ``ecc.toml`` files."""

import os
import tomllib
from math import isfinite
from pathlib import Path

from chipcompiler.cli.project.toml_edit import set_scoped_key
from chipcompiler.utility.file import write_text_atomic


class ConfigMigrationError(ValueError):
    """The existing config cannot be repaired without risking user data."""


def repair_manifest_project_config(project_dir: str, manifest) -> tuple[str, ...]:
    """Fill missing project identity fields from a validated manifest.

    Existing values and formatting are preserved.  The migration intentionally
    leaves ``pdk.root`` empty when the manifest has no binding so a newly
    initialized project can still be opened before the GUI's PDK selection.
    """
    path = Path(project_dir) / "ecc.toml"
    text = _read_existing(path)
    document = _parse_existing(path, text)
    base = manifest.base_design
    parameters = base.get("parameters") if isinstance(base.get("parameters"), dict) else {}

    design_name = manifest.design_name
    top = _nonempty(base.get("top_module")) or _nonempty(parameters.get("top_module"))
    clock = _nonempty(base.get("clock")) or _nonempty(parameters.get("clock"))
    pdk = _nonempty(base.get("pdk")) or _nonempty(parameters.get("pdk"))
    pdk_root = _nonempty(base.get("pdk_root")) or _nonempty(parameters.get("pdk_root"))
    frequency = _positive_number(parameters.get("frequency_max"))
    rtl = _rtl_sources(base)

    defaults: tuple[tuple[str, str, object], ...] = (
        ("design.name", "design", design_name),
        ("design.top", "design", top or design_name),
        ("design.rtl", "design", rtl),
        ("design.netlist", "design", _nonempty(base.get("netlist"))),
        (
            "design.golden_netlist",
            "design",
            _nonempty(base.get("golden_netlist")),
        ),
        ("design.def", "design", _nonempty(base.get("origin_def"))),
        ("design.sdc", "design", _nonempty(base.get("sdc"))),
        ("design.spef", "design", _nonempty(base.get("spef"))),
        ("design.clock_port", "design", clock or "clk"),
        ("design.frequency_mhz", "design", frequency or 100.0),
        ("pdk.name", "pdk", pdk or "ics55"),
        ("pdk.root", "pdk", pdk_root),
        ("flow.preset", "flow", "rtl2gds"),
    )

    updated = text
    repaired: list[str] = []
    for dotted_key, table, value in defaults:
        if value in ("", []):
            continue
        name = dotted_key.removeprefix(f"{table}.")
        if _has_value(document, table, name, dotted_key):
            continue
        updated = set_scoped_key(updated, table, name, value)
        repaired.append(dotted_key)

    if not repaired:
        return ()
    try:
        tomllib.loads(updated)
        write_text_atomic(str(path), updated)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigMigrationError(f"cannot update {path}: {exc}") from exc
    return tuple(repaired)


def _read_existing(path: Path) -> str:
    if not os.path.lexists(path):
        return ""
    if path.is_symlink() or not path.is_file():
        raise ConfigMigrationError(f"{path} must be a regular file")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigMigrationError(f"cannot read {path}: {exc}") from exc


def _parse_existing(path: Path, text: str) -> dict:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigMigrationError(f"malformed {path}: {exc}") from exc
    for table in ("design", "pdk", "flow"):
        value = document.get(table)
        if value is not None and not isinstance(value, dict):
            raise ConfigMigrationError(f"{path}: [{table}] must be a table")
    return document


def _has_value(document: dict, table: str, name: str, dotted_key: str) -> bool:
    section = document.get(table)
    if not isinstance(section, dict):
        return False
    if name not in section:
        return False
    value = section.get(name)
    if name == "frequency_mhz":
        if _positive_number(value) is None:
            raise ConfigMigrationError(f"{dotted_key} must be a positive finite number")
        return True
    if name == "rtl":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ConfigMigrationError(f"{dotted_key} must be an array of strings")
        return any(_nonempty(item) for item in value)
    if not isinstance(value, str):
        raise ConfigMigrationError(f"{dotted_key} must be a string")
    return bool(value.strip())


def _rtl_sources(base: dict) -> list[str]:
    rtl = base.get("rtl_list")
    if isinstance(rtl, list):
        values = [value.strip() for value in rtl if _nonempty(value)]
        if values:
            return values
    origin = _nonempty(base.get("origin_verilog"))
    return [origin] if origin else []


def _nonempty(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _positive_number(value: object) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value <= 0
    ):
        return None
    return float(value)
