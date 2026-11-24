"""Import a design that ECC-FE handed off into a manifest project.

``ecc-fe handoff`` describes a design that passed the frontend flow in one
file, ``handoff.json``. That file is all this module reads of ECC-FE: the
sources and headers it lists are copied below ``rtl/`` and a filelist that
carries its include directories, defines and parameter overrides is written
beside them.
"""

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from chipcompiler.cli.core.records import warning_record
from chipcompiler.cli.project.config import load_project_config
from chipcompiler.cli.project.rtl_import import (
    RtlImportError,
    contained_target,
    ensure_targets_available,
    project_root,
    register_rtl,
)
from chipcompiler.project.manifest import CONFIG_FILENAME

HANDOFF_KIND = "ecc-fe-handoff"
HANDOFF_SCHEMA_VERSION = 1
MANIFEST_NAME = "handoff.json"
FILELIST_NAME = "design.f"


@dataclass(frozen=True)
class Handoff:
    """What a version 1 handoff manifest says about the design."""

    path: Path
    generator: str
    run: str
    top: str
    clock_port: str | None
    files: tuple[Path, ...]
    headers: tuple[Path, ...]
    incdirs: tuple[Path, ...]
    defines: tuple[str, ...]
    parameters: tuple[str, ...]


def read_handoff(manifest: str) -> Handoff:
    path = Path(manifest).expanduser().resolve()
    if path.is_dir():
        path = path / MANIFEST_NAME
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RtlImportError(
            "fe_handoff_not_found", "handoff manifest was not found", str(path)
        ) from exc
    except (OSError, ValueError) as exc:
        raise RtlImportError("fe_handoff_invalid", str(exc), str(path)) from exc
    if not isinstance(document, dict) or document.get("kind") != HANDOFF_KIND:
        raise RtlImportError(
            "fe_handoff_invalid", "not a handoff manifest written by ecc-fe", str(path)
        )
    version = document.get("schema_version")
    if version != HANDOFF_SCHEMA_VERSION:
        raise RtlImportError(
            "fe_handoff_unsupported_version",
            f"handoff schema version {version} is not supported "
            f"(this ecc reads version {HANDOFF_SCHEMA_VERSION})",
            str(path),
        )
    try:
        design, rtl, flow = document["design"], document["rtl"], document["flow"]
        if flow["status"] != "complete":
            reasons = ", ".join(f"{item['step']}: {item['reason']}" for item in flow["blockers"])
            raise RtlImportError(
                "fe_handoff_incomplete",
                f"the frontend flow did not complete ({reasons})",
                str(path),
            )
        if rtl["libdirs"]:
            raise RtlImportError(
                "fe_handoff_unsupported",
                "library directories (-y) cannot be imported; list the library files instead",
                str(rtl["libdirs"][0]),
            )
        return Handoff(
            path=path,
            generator=f"{document['generator']['name']} {document['generator']['version']}",
            run=str(document["source"]["run"]),
            top=design["top"],
            clock_port=design["clock_port"],
            files=_verified(path.parent, rtl["files"]),
            headers=_verified(path.parent, rtl["headers"]),
            incdirs=tuple((path.parent / entry).resolve() for entry in rtl["incdirs"]),
            defines=tuple(rtl["defines"]),
            parameters=tuple(design["parameters"]),
        )
    except (KeyError, TypeError) as exc:
        raise RtlImportError(
            "fe_handoff_invalid", f"handoff manifest is missing a field: {exc}", str(path)
        ) from exc


def _verified(base: Path, entries: list[dict[str, str]]) -> tuple[Path, ...]:
    """The listed files, each still the content the frontend checked."""
    paths = []
    for entry in entries:
        path = (base / entry["path"]).resolve()
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise RtlImportError(
                "fe_handoff_file_missing", "a file of the handoff was not found", str(path)
            ) from exc
        if digest != entry["sha256"]:
            raise RtlImportError(
                "fe_handoff_file_changed",
                "a file changed after the handoff was written; run ecc-fe handoff again",
                str(path),
            )
        paths.append(path)
    return tuple(paths)


def import_fe_handoff(project_dir: str, manifest: str, *, force: bool = False) -> list[dict]:
    """Import the design of *manifest*; the records of the import, the result last."""
    root = project_root(project_dir)
    handoff = read_handoff(manifest)
    if not handoff.files:
        raise RtlImportError(
            "fe_handoff_invalid", "handoff manifest lists no source files", str(handoff.path)
        )

    rtl_root = root / "rtl"
    rtl_root.mkdir(exist_ok=True)
    inputs = handoff.files + handoff.headers
    # An include directory above the inputs keeps its place: the layout starts there.
    holding = [
        directory
        for directory in handoff.incdirs
        if any(directory in path.parents for path in inputs)
    ]
    base = Path(os.path.commonpath([*(path.parent for path in inputs), *holding]))

    def target(path: Path) -> Path:
        return contained_target(rtl_root / path.relative_to(base), rtl_root, path)

    filelist = contained_target(rtl_root / FILELIST_NAME, rtl_root, handoff.path)
    copied = [(path, target(path)) for path in inputs]
    ensure_targets_available([(handoff.path, filelist), *copied], force=force)
    include_dirs = [
        target(directory)
        for directory in handoff.incdirs
        if directory == base or base in directory.parents
    ]

    for source, destination in copied:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for directory in include_dirs:
        directory.mkdir(parents=True, exist_ok=True)
    sources = copied[: len(handoff.files)]
    lines = [
        f"# Imported from an ECC-FE handoff ({handoff.generator}, run {handoff.run}).",
        *(f"+incdir+{os.path.relpath(directory, rtl_root)}" for directory in include_dirs),
        *(f"+define+{define}" for define in handoff.defines),
        *(f"-G {parameter}" for parameter in handoff.parameters),
        *(os.path.relpath(destination, rtl_root) for _, destination in sources),
    ]
    filelist.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rtl_entries = [str(destination.relative_to(root)) for _, destination in sources]
    design: dict[str, object] = {"rtl": [str(filelist.relative_to(root))], "top": handoff.top}
    if handoff.clock_port:
        design["clock_port"] = handoff.clock_port
    register_rtl(root, design, rtl_entries, origin_filelist=str(filelist.relative_to(root)))
    result = {
        "project": str(root),
        "status": "rtl_imported",
        "filelist": str(filelist.relative_to(root)),
        "rtl": rtl_entries,
        "include_dirs": [str(path.relative_to(root)) for path in include_dirs] or None,
        "top": handoff.top,
        "clock_port": handoff.clock_port,
        "handoff": str(handoff.path),
        "frontend": handoff.generator,
    }
    return [*_clock_warnings(root, handoff.clock_port), result]


def _clock_warnings(root: Path, clock_port: str | None) -> list[dict]:
    """Warn when the project constrains another port than the design's clock.

    A project whose ``design.sdc`` timing input declares the primary clock
    takes the clock port from there, not from ``[design] clock_port``.
    """
    cfg = load_project_config(str(root / CONFIG_FILENAME))
    if not clock_port or cfg._timing_input_error or cfg.design_clock_port == clock_port:
        return []
    return [
        warning_record(
            "clock_port_mismatch",
            clock_port=clock_port,
            constrained_port=cfg.design_clock_port,
            timing_input=cfg.design_sdc,
            reason="the timing input declares the primary clock on another port "
            "than the clock of the imported design; edit its primary_clocks",
        )
    ]
