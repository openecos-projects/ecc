"""Resolve bounded RTL, filelist, include and timing-constraint inputs.

The resolver is intentionally conservative.  It only hashes files it can read
and parse itself; unsupported frontend behaviour lowers the closure state to
``partial`` instead of silently treating the top-level file as complete.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ecc_experience.files import digest, file_digest
from ecc_experience.models import InputDigest

MAX_CLOSURE_FILES = 2048
MAX_PARSE_BYTES = 8 * 1024 * 1024
_FILELIST_SUFFIXES = {".f", ".lst", ".filelist"}
_HDL_SUFFIXES = {".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl"}
_TEXT_SUFFIXES = _FILELIST_SUFFIXES | _HDL_SUFFIXES | {".sdc", ".tcl"}
_INCLUDE = re.compile(r"^\s*`include\s+[<\"]([^>\"]+)[>\"]", re.MULTILINE)
_CLOCK_PERIOD = re.compile(r"\bcreate_clock\b[^\n]*?-period\s+([0-9]*\.?[0-9]+)", re.I)
_OPERATING_CONDITION = re.compile(
    r"\bset_operating_conditions\b[^\n]*?([A-Za-z][A-Za-z0-9_.-]*)", re.I
)
_VARIABLE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")


@dataclass
class ClosureResult:
    inputs: list[InputDigest]
    design: dict
    constraints: dict
    files: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


@dataclass
class _Resolver:
    root: Path
    input_id: str
    role: str
    files: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    include_dirs: list[Path] = field(default_factory=list)
    seen_paths: set[Path] = field(default_factory=set)
    seen_content: set[str] = field(default_factory=set)
    complete: bool = True

    def resolve(self, reference: str, *, kind: str, base: Path | None = None) -> None:
        if len(self.files) >= MAX_CLOSURE_FILES:
            self._partial("input_closure_file_limit")
            return
        resolved = _resolve_path(reference, base or self.root, self.root)
        if resolved is None:
            self._partial("input_closure_unresolved_reference")
            return
        try:
            resolved = resolved.resolve(strict=True)
        except OSError:
            self._partial("input_closure_unresolved_reference")
            return
        if not resolved.is_file():
            self._partial("input_closure_non_file_reference")
            return
        try:
            checksum, size = file_digest(resolved)
        except OSError:
            self._partial("input_closure_unreadable_file")
            return
        if resolved not in self.seen_paths:
            self.seen_paths.add(resolved)
            self.files.append(
                {
                    "logical_id": f"{self.input_id}:{len(self.files):04d}",
                    "role": self.role,
                    "kind": kind,
                    "sha256": checksum,
                    "bytes": size,
                }
            )
        if self.role.casefold() not in {"rtl", "verilog", "systemverilog"}:
            return
        suffix = resolved.suffix.casefold()
        if suffix not in _TEXT_SUFFIXES or size > MAX_PARSE_BYTES:
            if suffix in _HDL_SUFFIXES or suffix in _FILELIST_SUFFIXES:
                self._partial("input_closure_parse_limit")
            return
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self._partial("input_closure_unreadable_file")
            return
        content_key = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        if content_key in self.seen_content:
            return
        self.seen_content.add(content_key)
        if suffix in _FILELIST_SUFFIXES or kind == "filelist":
            self._parse_filelist(text, resolved.parent)
        if suffix in _HDL_SUFFIXES:
            self._parse_includes(text, resolved.parent)

    def _parse_filelist(self, text: str, base: Path) -> None:
        for raw in text.splitlines():
            line = _strip_comment(raw).strip()
            if not line:
                continue
            tokens = line.split()
            index = 0
            while index < len(tokens):
                token = tokens[index]
                if token.startswith("+incdir+"):
                    value = token[len("+incdir+") :]
                    if value:
                        for directory in value.split("+"):
                            self._add_include_dir(directory, base)
                    index += 1
                elif token in {"-I", "-y", "-Y"}:
                    if index + 1 >= len(tokens):
                        self._partial("input_closure_filelist_directive_incomplete")
                        break
                    if token == "-I":
                        self._add_include_dir(tokens[index + 1], base)
                    else:
                        self._partial("input_closure_library_directory_unsupported")
                    index += 2
                elif token in {"-f", "-F"}:
                    if index + 1 >= len(tokens):
                        self._partial("input_closure_filelist_directive_incomplete")
                        break
                    self.resolve(tokens[index + 1], kind="filelist", base=base)
                    index += 2
                elif token in {"-v"}:
                    if index + 1 >= len(tokens):
                        self._partial("input_closure_filelist_directive_incomplete")
                        break
                    self.resolve(tokens[index + 1], kind="hdl", base=base)
                    index += 2
                elif token.startswith("-") or token.startswith("+"):
                    self._partial("input_closure_filelist_directive_unsupported")
                    index += 1
                else:
                    self.resolve(token, kind="hdl", base=base)
                    index += 1

    def _parse_includes(self, text: str, base: Path) -> None:
        for match in _INCLUDE.finditer(text):
            name = match.group(1)
            if _VARIABLE.search(name):
                self._partial("input_closure_include_variable_unresolved")
                continue
            search = [base, *self.include_dirs]
            resolved = next(
                (
                    candidate
                    for directory in search
                    for candidate in (directory / name,)
                    if candidate.is_file()
                ),
                None,
            )
            if resolved is None:
                self._partial("input_closure_include_unresolved")
                continue
            self.resolve(str(resolved), kind="include", base=base)

    def _add_include_dir(self, value: str, base: Path) -> None:
        if _VARIABLE.search(value):
            self._partial("input_closure_include_directory_variable_unresolved")
            return
        directory = _resolve_path(value, base, self.root)
        if directory is None or not directory.is_dir():
            self._partial("input_closure_include_directory_unresolved")
            return
        resolved = directory.resolve()
        if resolved not in self.include_dirs:
            self.include_dirs.append(resolved)

    def _partial(self, reason: str) -> None:
        self.complete = False
        if reason not in self.limitations:
            self.limitations.append(reason)


def capture_input_closure(
    workspace: str | Path,
    facts: dict,
    inputs: list[InputDigest],
) -> ClosureResult:
    root = Path(workspace).expanduser().resolve()
    specification = facts.get("workspaceSpec", {})
    bindings = facts.get("workspaceBindings", {}).get("inputs", {})
    if not isinstance(specification, dict) or not isinstance(bindings, dict):
        return _unknown(inputs, "input_closure_metadata_invalid")

    all_files: list[dict] = []
    limitations: list[str] = []
    updated: list[InputDigest] = []
    for item in inputs:
        reference = bindings.get(item.input_id)
        if not isinstance(reference, str) or not reference:
            updated.append(item.model_copy(update={"closure": "unknown", "resolved_files": 0}))
            limitations.append(f"input_closure_binding_missing:{item.input_id}")
            continue
        resolver = _Resolver(root=root, input_id=item.input_id, role=item.role)
        resolver.resolve(reference, kind=_kind(reference, item.role))
        closure = (
            "complete"
            if item.status == "available" and resolver.complete and resolver.files
            else "partial"
            if item.status == "available"
            else "unknown"
        )
        for value in resolver.limitations:
            message = f"{item.input_id}:{value}"
            if message not in limitations:
                limitations.append(message)
        all_files.extend(resolver.files)
        closure_sha = (
            digest(
                [
                    {key: value[key] for key in ("logical_id", "role", "kind", "sha256", "bytes")}
                    for value in resolver.files
                ]
            )
            if resolver.files
            else None
        )
        updated.append(
            item.model_copy(
                update={
                    "closure": closure,
                    "closure_sha256": closure_sha,
                    "resolved_files": len(resolver.files),
                }
            )
        )

    top = specification.get("design", {}).get("topModule")
    closure_status = _closure_status(updated)
    design_fingerprint = (
        digest(
            {
                "top": top,
                "design": specification.get("design"),
                "files": all_files,
                "inputs": [
                    {key: item[key] for key in ("input_id", "role", "sha256", "closure_sha256")}
                    for item in (value.model_dump() for value in updated)
                ],
            }
        )
        if closure_status == "complete"
        else None
    )
    constraints = capture_constraints(root, facts)
    return ClosureResult(
        inputs=updated,
        design={
            "fingerprint": design_fingerprint,
            "top_module": top if isinstance(top, str) else None,
            "tags": [],
            "memory_implementation": "unknown",
            "memory_bits": None,
            "macro_count": None,
            "closure": closure_status,
        },
        constraints=constraints,
        files=all_files,
        limitations=limitations,
    )


def capture_constraints(workspace: str | Path, facts: dict) -> dict:
    root = Path(workspace).expanduser().resolve()
    outputs = facts.get("stepOutputs")
    sdc = outputs.get("sdc") if isinstance(outputs, dict) else None
    reference = sdc.get("path") if isinstance(sdc, dict) else None
    if not isinstance(reference, str) or not reference:
        return {
            "fingerprint": None,
            "sdc_sha256": None,
            "clock_periods": [],
            "corners": [],
            "timing_constraints_status": "unknown",
        }
    path = _resolve_path(reference, root, root)
    if path is None:
        return {
            "fingerprint": None,
            "sdc_sha256": None,
            "clock_periods": [],
            "corners": [],
            "timing_constraints_status": "unknown",
        }
    try:
        checksum, size = file_digest(path)
    except OSError:
        return {
            "fingerprint": None,
            "sdc_sha256": None,
            "clock_periods": [],
            "corners": [],
            "timing_constraints_status": "unknown",
        }
    periods: list[float] = []
    corners: list[str] = []
    status = "available"
    if size <= MAX_PARSE_BYTES:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            periods = sorted({float(value) for value in _CLOCK_PERIOD.findall(text)})
            corners = sorted({value for value in _OPERATING_CONDITION.findall(text)})
            if not periods:
                status = "partial"
        except OSError:
            status = "unknown"
    else:
        status = "partial"
    return {
        "fingerprint": digest(
            {
                "sdc_sha256": checksum,
                "clock_periods": periods,
                "corners": corners,
                "status": status,
            }
        ),
        "sdc_sha256": checksum,
        "clock_periods": periods,
        "corners": corners,
        "timing_constraints_status": status,
    }


def content_fingerprint(facts: dict, inputs: list[InputDigest]) -> str | None:
    specification = facts.get("workspaceSpec", {})
    if (
        not isinstance(specification, dict)
        or not inputs
        or any(item.sha256 is None or item.closure != "complete" for item in inputs)
    ):
        return None
    return digest(
        {
            "top": specification.get("design", {}).get("topModule"),
            "inputs": [
                {
                    key: value
                    for key, value in item.model_dump().items()
                    if key in {"input_id", "role", "sha256", "closure", "closure_sha256"}
                }
                for item in inputs
            ],
        }
    )


def _kind(reference: str, role: str) -> str:
    suffix = Path(reference).suffix.casefold()
    if role.casefold() == "sdc" or suffix == ".sdc":
        return "sdc"
    if suffix in _FILELIST_SUFFIXES:
        return "filelist"
    if suffix in _HDL_SUFFIXES:
        return "hdl"
    return "input"


def _resolve_path(reference: str, base: Path, root: Path) -> Path | None:
    if not reference or _VARIABLE.search(reference):
        return None
    candidate = Path(reference).expanduser()
    if candidate.is_absolute():
        return candidate
    for parent in (base, root):
        value = (parent / candidate).resolve()
        if value.exists():
            return value
    return (base / candidate).resolve()


def _strip_comment(line: str) -> str:
    for marker in ("//", "#"):
        index = line.find(marker)
        if index >= 0:
            line = line[:index]
    return line


def _closure_status(inputs: list[InputDigest]) -> str:
    states = {item.closure for item in inputs}
    if states and states == {"complete"}:
        return "complete"
    if states == {"unknown"} or not states:
        return "unknown"
    return "partial"


def _unknown(inputs: list[InputDigest], reason: str) -> ClosureResult:
    return ClosureResult(
        inputs=[item.model_copy(update={"closure": "unknown"}) for item in inputs],
        design={
            "fingerprint": None,
            "top_module": None,
            "tags": [],
            "memory_implementation": "unknown",
            "memory_bits": None,
            "macro_count": None,
            "closure": "unknown",
        },
        constraints=capture_constraints(".", {"stepOutputs": {}}),
        limitations=[reason],
    )
