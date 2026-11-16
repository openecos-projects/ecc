"""Compact v2 translations preserve exact geometry and pin positions."""

from pathlib import Path


def translations(previous, upsert):
    remaining, moved = {}, {}
    for key, current in upsert.items():
        old = previous.get(key)
        offset = translation(old, current)
        if offset is None:
            remaining[key] = current
        else:
            moved[key] = offset
    return remaining, moved


def translation(old, new):
    if not old or old["kind"] not in {"instance", "macro"}:
        return None
    a, b = old["bbox"], new["bbox"]
    dx, dy = b[0] - a[0], b[1] - a[1]
    if b != [a[0] + dx, a[1] + dy, a[2] + dx, a[3] + dy]:
        return None
    if {k: v for k, v in old.items() if k not in {"bbox", "pins"}} != {
        k: v for k, v in new.items() if k not in {"bbox", "pins"}
    }:
        return None
    old_pins, new_pins = old.get("pins", {}), new.get("pins", {})
    if old_pins.keys() != new_pins.keys():
        return None
    for name, pin in old_pins.items():
        position = pin.get("position")
        if not position or new_pins[name] != {
            **pin,
            "position": [position[0] + dx, position[1] + dy],
        }:
            return None
    return [dx, dy]


def write_frame(directory, relative, payload):
    """Compression is explicit in the v2 index; small debug frames stay plain JSON."""
    import gzip
    import json
    import tempfile

    data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    encoding = "json"
    if len(data) >= 1024 * 1024:
        data = gzip.compress(data, compresslevel=1, mtime=0)
        relative += ".gz"
        encoding = "gzip+json"
    if payload.get("base_checkpoint") is not None:
        # Older v2 readers reject the explicit encoding instead of silently
        # treating this compact checkpoint as the complete physical scene.
        encoding += "+base"
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return relative, encoding
