"""Versioned, declarative PDK boundary. No process-family defaults live here."""

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DESCRIPTOR_FILENAME = "ecc-pdk.json"


class DescriptorError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def release_version(root: Path) -> str | None:
    path = root / "VERSION"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise DescriptorError("invalid_version", "VERSION must be a regular file")
    if not path.exists():
        return None
    with path.open("rb") as stream:
        raw = stream.read(131)
    match = re.fullmatch(rb"([A-Za-z0-9][A-Za-z0-9._+-]{0,127})(?:\r?\n)?", raw)
    if not match:
        raise DescriptorError("invalid_version", "VERSION must contain one release number")
    return match[1].decode("ascii")


def check_release(root: Path, release: str) -> str | None:
    version = release_version(root)
    if version is not None and version != release:
        raise DescriptorError(
            "release_mismatch", f"PDK VERSION {version} differs from configured release {release}"
        )
    return version


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Resource(StrictModel):
    path: str
    role: Literal["tech", "lef", "liberty", "verilog", "gds", "mapping", "rc", "em", "model"]
    sha256: str | None = None

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("resource paths must be relative to the PDK root")
        return value

    @field_validator("sha256")
    @classmethod
    def valid_digest(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("sha256 must contain 64 lowercase hexadecimal characters")
        return value


class CellRoles(StrictModel):
    site_core: str = ""
    site_io: str = ""
    site_corner: str = ""
    tap_cell: str = ""
    end_cap: str = ""
    buffers: list[str] = Field(default_factory=list)
    fillers: list[str] = Field(default_factory=list)
    tie_high_cell: str = ""
    tie_high_port: str = ""
    tie_low_cell: str = ""
    tie_low_port: str = ""
    abc_driver_cell: str = ""
    abc_load: float = 0.0  # fF at the Yosys boundary
    sdc_load: float = 0.0  # pF at the SDC boundary
    dont_use: list[str] = Field(default_factory=list)


class LibraryView(StrictModel):
    libraries: list[str]
    process: str
    voltage: float
    temperature: float
    rc_corner: str = ""


class CellVariant(StrictModel):
    master: str
    vt: str
    family: str
    drive_rank: float
    pins: dict[str, str] = Field(default_factory=dict)


class Descriptor(StrictModel):
    schema_version: Literal[1] = 1
    family_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    release: str = ""
    profile_revision: str = "1"
    resources: dict[str, Resource] = Field(default_factory=dict)
    cells: CellRoles = Field(default_factory=CellRoles)
    cell_catalog: list[CellVariant] = Field(default_factory=list)
    views: dict[str, LibraryView] = Field(default_factory=dict)
    synthesis_libraries: list[str] = Field(default_factory=list)
    # Tool-owned schemas validate these namespaces before execution.
    tools: dict[str, dict] = Field(default_factory=dict)
    parameters: dict = Field(default_factory=dict)

    @field_validator("tools")
    @classmethod
    def validate_tool_settings(cls, value: dict) -> dict:
        from .tool_settings import ToolSettings

        ToolSettings.model_validate(value)
        json.dumps(value, allow_nan=False)
        return value

    @field_validator("parameters")
    @classmethod
    def validate_finite_parameters(cls, value: dict) -> dict:
        json.dumps(value, allow_nan=False)
        return value

    @model_validator(mode="after")
    def validate_references(self):
        for name in [
            *self.synthesis_libraries,
            *(r for v in self.views.values() for r in v.libraries),
        ]:
            if name not in self.resources or self.resources[name].role != "liberty":
                raise ValueError(f"library reference must identify a liberty resource: {name}")
        if sum(r.role == "tech" for r in self.resources.values()) > 1:
            raise ValueError("a profile may select only one technology LEF")
        masters = [cell.master for cell in self.cell_catalog]
        if len(masters) != len(set(masters)):
            raise ValueError("duplicate master in cell_catalog")
        return self


def load_descriptor(root: Path, path: Path | None = None) -> Descriptor:
    from .managed import read_configuration, source_path

    if path is None and not source_path(root).exists():
        from .profiles import detect_release

        return detect_release(root).resolved()
    descriptor = read_configuration(source_path(root, path)).resolved()
    check_release(root, descriptor.release)
    return descriptor


def resource_path(root: Path, resource: Resource) -> Path:
    resolved_root = root.resolve()
    path = (resolved_root / resource.path).resolve()
    if not path.is_relative_to(resolved_root):
        raise DescriptorError(
            "resource_outside_root", f"resource escapes PDK root: {resource.path}"
        )
    return path


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def content_identity(root: Path, descriptor: Descriptor) -> tuple[str, dict[str, str]]:
    version = check_release(root, descriptor.release)
    hashes = {}
    for name, resource in sorted(descriptor.resources.items()):
        path = resource_path(root, resource)
        if not path.is_file():
            raise DescriptorError("resource_missing", f"missing resource {name}: {path}")
        if version is not None:
            continue
        actual = file_digest(path)
        if resource.sha256 is not None and actual != resource.sha256:
            raise DescriptorError("content_mismatch", f"resource checksum differs: {name}")
        hashes[name] = actual
    return execution_identity(descriptor, hashes), hashes


def execution_identity(descriptor: Descriptor, hashes: dict[str, str]) -> str:
    payload = {"descriptor": descriptor.model_dump(), "resources": hashes}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
