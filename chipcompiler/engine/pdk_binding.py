import hashlib
import json
from pathlib import Path
from typing import Any


def pdk_binding_content_hash(
    spec: dict[str, Any],
    bindings: dict[str, Any],
) -> str:
    digest = hashlib.sha256()
    digest.update(str(spec.get("familyId", "")).encode())
    digest.update(str(spec.get("version") or bindings.get("version") or "").encode())
    digest.update(json.dumps(spec.get("overrides", {}), sort_keys=True).encode())
    for path in _selected_paths(spec, bindings):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _selected_paths(spec: dict[str, Any], bindings: dict[str, Any]) -> list[Path]:
    if spec.get("mode") == "manual":
        files = bindings.get("files")
        if not isinstance(files, dict):
            return []
        return [
            Path(files[ref["fileId"]])
            for ref in spec.get("files", [])
            if isinstance(ref, dict)
            and isinstance(ref.get("fileId"), str)
            and ref["fileId"] in files
            and Path(files[ref["fileId"]]).is_file()
        ]

    try:
        from chipcompiler.data import get_pdk

        pdk = get_pdk(
            spec.get("familyId", ""),
            pdk_root=bindings.get("root", ""),
            overrides=pdk_overrides_from_binding(spec, bindings),
        )
    except (OSError, ValueError):
        return []
    candidates = [pdk.tech, *pdk.lefs, *pdk.libs, pdk.mapping_file]
    return [Path(path) for path in candidates if path is not None and Path(path).is_file()]


def pdk_overrides_from_binding(spec: dict[str, Any], bindings: dict[str, Any]) -> dict[str, Any]:
    overrides = dict(spec.get("overrides", {}))
    files = bindings.get("files", {})
    by_role: dict[str, list[str]] = {}
    for ref in spec.get("files", []):
        path = files.get(ref.get("fileId")) if isinstance(files, dict) else None
        if isinstance(path, str):
            by_role.setdefault(ref["role"], []).append(path)
    if by_role.get("tech"):
        overrides["tech"] = by_role["tech"][0]
    if by_role.get("lef"):
        overrides["lefs"] = by_role["lef"]
    if by_role.get("liberty"):
        overrides["libs"] = by_role["liberty"]
    if by_role.get("mapping"):
        overrides["mapping_file"] = by_role["mapping"][0]
    return overrides
