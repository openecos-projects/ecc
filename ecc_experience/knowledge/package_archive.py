"""Bounded, deterministic archives for immutable experience evidence."""

import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
import zlib
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, ValidationError

from ecc_experience.files import canonical_bytes, digest
from ecc_experience.models import ExperienceError, Model

MAX_FILES = 20000
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024


class PackageFile(Model):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0, le=MAX_FILE_BYTES)


class PackageManifest(Model):
    schema_version: Literal[1] = 1
    kind: Literal["ecc_experience_package"] = "ecc_experience_package"
    package_id: str
    case_ids: list[str] = Field(min_length=1, max_length=10000)
    release_path: Literal["release.json"] | None = None
    files: list[PackageFile] = Field(min_length=1, max_length=MAX_FILES)


def invalid(message: str) -> ExperienceError:
    return ExperienceError(message, code="experience_package_invalid")


def build_manifest(files: dict[str, bytes], case_ids: list[str]) -> PackageManifest:
    records = [
        PackageFile(path=name, sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))
        for name, content in sorted(files.items())
    ]
    manifest = PackageManifest(
        package_id="",
        case_ids=sorted(case_ids),
        release_path="release.json" if "release.json" in files else None,
        files=records,
    )
    return manifest.model_copy(
        update={"package_id": f"package-{digest(manifest.model_dump(exclude={'package_id'}))}"}
    )


def read_archive(path: str | Path) -> tuple[PackageManifest, dict[str, bytes]]:
    source = Path(path).expanduser()
    if source.is_symlink() or not source.is_file():
        raise invalid("Package must be a regular file")
    if source.stat().st_size > MAX_ARCHIVE_BYTES:
        raise invalid("Package exceeds the compressed size limit")
    files: dict[str, bytes] = {}
    total = 0
    try:
        with _open_archive(source) as archive:
            for member in archive:
                _validate_path(member.name)
                if not member.isfile() or member.issparse():
                    raise invalid("Package members must be regular, non-sparse files")
                if member.name in files:
                    raise invalid(f"Duplicate package member: {member.name}")
                if member.size < 0 or member.size > MAX_FILE_BYTES:
                    raise invalid("Package member exceeds the file size limit")
                total += member.size
                if total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES + 1:
                    raise invalid("Package exceeds the expanded size or member limit")
                stream = archive.extractfile(member)
                if stream is None:
                    raise invalid("Package member cannot be read")
                content = stream.read(member.size + 1)
                if len(content) != member.size:
                    raise invalid("Package member size mismatch")
                files[member.name] = content
    except (tarfile.TarError, EOFError, gzip.BadGzipFile, zlib.error) as exc:
        raise invalid("Unable to decode experience package") from exc
    manifest = _manifest(files.pop("manifest.json", None))
    expected = {item.path: item for item in manifest.files}
    if len(expected) != len(manifest.files) or set(expected) != set(files):
        raise invalid("Package manifest file membership mismatch")
    for name, content in files.items():
        record = expected[name]
        if (len(content), hashlib.sha256(content).hexdigest()) != (record.bytes, record.sha256):
            raise invalid(f"Package file checksum mismatch: {name}")
    return manifest, files


@contextmanager
def _open_archive(source: Path):
    with tempfile.TemporaryFile() as expanded:
        size = 0
        with gzip.open(source, "rb") as compressed:
            while chunk := compressed.read(64 * 1024):
                size += len(chunk)
                if size > MAX_TOTAL_BYTES:
                    raise invalid("Package exceeds the expanded archive size limit")
                expanded.write(chunk)
        expanded.seek(0)
        with tarfile.open(fileobj=expanded, mode="r|") as archive:
            yield archive


def write_archive(path: str | Path, manifest: PackageManifest, files: dict[str, bytes]) -> str:
    destination = Path(path).expanduser().absolute()
    if destination.is_symlink():
        raise invalid("Package output must not be a symlink")
    if destination.exists():
        existing, _files = read_archive(destination)
        if existing == manifest:
            return "already_present"
        raise ExperienceError(
            "Package output already contains different data", code="experience_package_conflict"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".package-", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            with (
                gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed,
                tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive,
            ):
                contents = {**files, "manifest.json": canonical_bytes(manifest.model_dump())}
                for name, content in sorted(contents.items()):
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    member.mode = 0o600
                    archive.addfile(member, io.BytesIO(content))
            output.flush()
            os.fsync(output.fileno())
        read_archive(temporary)
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise ExperienceError(
                "Package output appeared during export", code="experience_package_conflict"
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return "created"


def _manifest(content: bytes | None) -> PackageManifest:
    if content is None:
        raise invalid("Package manifest is missing")
    try:
        payload = json.loads(content)
        if not isinstance(payload, dict) or set(payload) != set(PackageManifest.model_fields):
            raise invalid("Package manifest fields do not match the schema")
        if type(payload["schema_version"]) is not int:
            raise invalid("Invalid package schema version")
        manifest = PackageManifest.model_validate(payload)
        expected = f"package-{digest(manifest.model_dump(exclude={'package_id'}))}"
        if manifest.package_id != expected:
            raise invalid("Package identity mismatch")
        if len(set(manifest.case_ids)) != len(manifest.case_ids):
            raise invalid("Package contains duplicate case IDs")
        return manifest
    except (ValueError, UnicodeError, RecursionError, ValidationError) as exc:
        raise invalid("Invalid package manifest") from exc


def _validate_path(name: str) -> None:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != name
        or "\\" in name
        or ":" in name
        or any(ord(character) < 32 for character in name)
    ):
        raise invalid(f"Unsafe package member path: {name!r}")
