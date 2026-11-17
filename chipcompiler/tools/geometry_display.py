"""Publish native display assets as immutable members of the current geometry snapshot."""

import filecmp
import json
import shutil
import struct
import uuid
from pathlib import Path

from chipcompiler.tools.replay_storage import within

HEADER = struct.Struct("<8sIIIIQQ")
MAX_METADATA = 1024 * 1024


def metadata(path: Path, *, validate_index: bool = False) -> dict:
    """Read only the small catalog; sample/marker/path data stays native binary."""
    with path.open("rb") as stream:
        header = stream.read(HEADER.size)
        if len(header) != HEADER.size:
            raise ValueError("Truncated geometry display header")
        magic, version, encoding, size, record_size, count, index = HEADER.unpack(header)
        if magic != b"ECOSDSP1" or version != 1 or size > MAX_METADATA:
            raise ValueError("Unsupported geometry display header")
        length = path.stat().st_size
        start = HEADER.size + size
        if encoding == 1:
            valid = record_size == 32 and index == 0 and length == start + count * 32
        elif encoding == 2:
            valid = record_size == 0 and index >= start and length == index + (count + 1) * 8
        else:
            valid = False
        if not valid:
            raise ValueError("Invalid geometry display size/index")
        document = json.loads(stream.read(size))
        if not isinstance(document, dict) or any(
            not isinstance(document.get(key), str) or not document[key]
            for key in ("kind", "key", "label")
        ):
            raise ValueError("Missing geometry display identity")
        if encoding == 2 and validate_index:
            stream.seek(index)
            previous = struct.unpack("<Q", stream.read(8))[0]
            if previous != 0:
                raise ValueError("Invalid first geometry display offset")
            remaining = count
            while remaining:
                size = min(remaining, 8192)
                for (offset,) in struct.iter_unpack("<Q", stream.read(size * 8)):
                    if (
                        offset <= previous
                        or offset > index - start
                        or offset - previous > 64 * 1024 * 1024
                    ):
                        raise ValueError("Invalid geometry display record offset")
                    previous = offset
                remaining -= size
            if previous != index - start:
                raise ValueError("Invalid final geometry display offset")
        return document


def _manifest(step) -> Path | None:
    path = getattr(getattr(step, "output", None), "geometry_manifest", None)
    return Path(path) if path else None


def invalidate(step) -> None:
    """Detach old analyses before an attempt; leave immutable files for existing readers."""
    path = _manifest(step)
    if path is None or not path.is_file():
        return
    content = path.read_text()
    filtered = "".join(
        line
        for line in content.splitlines(keepends=True)
        if not line.startswith(("display.", "drc="))
    )
    if filtered != content:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(filtered)
        temporary.replace(path)


def begin(step) -> int:
    """Invalidate old bindings and anchor freshness to the output filesystem clock."""
    invalidate(step)
    if _manifest(step) is None:
        return 0
    directory = Path(step.directory) / "data"
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / f".display-start-{uuid.uuid4().hex}"
    try:
        marker.touch(exist_ok=False)
        return marker.stat().st_mtime_ns
    finally:
        marker.unlink(missing_ok=True)


def publish(step, started_ns: int) -> None:
    """Bind fresh native assets after the tool succeeds and before Replay finalizes."""
    manifest = _manifest(step)
    if manifest is None or not manifest.is_file():
        return
    root = Path(step.directory).resolve()
    candidates = []
    # Native reporters own data/feature; published geometry is deliberately excluded.
    for name in ("data", "feature"):
        directory = root / name
        if directory.is_dir():
            candidates.extend(directory.rglob("*.gdisplay"))
    sources = []
    keys = {}
    fields = {}
    for line in manifest.read_text().splitlines():
        if "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key in fields:
            raise ValueError(f"Duplicate geometry manifest key: {key}")
        fields[key] = value
    for path in sorted(candidates):
        source = within(root, path)
        if source.stat().st_mtime_ns < started_ns:
            continue
        info = metadata(source, validate_index=True)
        key = info["key"]
        if key in keys:
            if filecmp.cmp(keys[key], source, shallow=False):
                continue
            raise ValueError(f"Duplicate geometry display dataset: {key}")
        if info.get("coordinate_unit", "dbu") != "dbu":
            raise ValueError(f"Unsupported geometry display coordinates: {key}")
        dbu = info.get("dbu_per_micron")
        if dbu is not None and dbu != int(fields["dbu_per_micron"]):
            raise ValueError(f"Geometry display unit mismatch: {key}")
        keys[key] = source
        sources.append(source)
    if not sources:
        return
    # A unique directory avoids overwriting mapped bytes in another open viewer.
    relative = Path("display") / uuid.uuid4().hex
    destination = manifest.parent / relative
    destination.mkdir(parents=True)
    before = manifest.read_bytes()
    temporary = manifest.with_name(f".{manifest.name}.{uuid.uuid4().hex}.tmp")
    try:
        entries = []
        for index, source in enumerate(sources):
            filename = f"{index:04}.gdisplay"
            shutil.copyfile(source, destination / filename)
            metadata(destination / filename, validate_index=True)
            entries.append(f"display.{index:04}={(relative / filename).as_posix()}\n")
        text = "".join(
            line
            for line in before.decode().splitlines(keepends=True)
            if not line.startswith("display.")
        )
        temporary.write_text(text.rstrip("\n") + "\n" + "".join(entries))
        if manifest.read_bytes() != before:
            raise ValueError("Geometry changed while publishing display data")
        temporary.replace(manifest)
    except BaseException:
        temporary.unlink(missing_ok=True)
        shutil.rmtree(destination)
        raise
