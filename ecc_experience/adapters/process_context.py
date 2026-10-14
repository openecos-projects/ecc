"""Fingerprint selected ECC PDK bindings without running EDA or reading private metadata."""

from pathlib import Path

from chipcompiler.data import get_pdk
from chipcompiler.engine.pdk_binding import pdk_overrides_from_binding
from ecc_experience.files import digest, file_digest


def process_context(facts: dict) -> dict:
    specification = facts.get("workspaceSpec", {})
    bindings = facts.get("workspaceBindings", {}).get("pdk", {})
    pdk = specification.get("pdk", {})
    unknown = {
        "status": "unknown",
        "fingerprint": None,
        "scope": "selected_tech_lef_liberty_mapping_not_complete_pdk_closure",
    }
    if not pdk or not isinstance(bindings, dict):
        return {**unknown, "reason": "No PDK binding"}
    try:
        if pdk.get("mode") == "manual":
            declarations = pdk.get("files", [])
            files = bindings.get("files", {})
            selected = [(item["role"], Path(files[item["fileId"]])) for item in declarations]
        else:
            if not isinstance(bindings.get("root"), str) or not bindings["root"]:
                return {**unknown, "reason": "PDK root is not explicitly bound"}
            bound = get_pdk(
                pdk.get("familyId", ""),
                pdk_root=bindings["root"],
                overrides=pdk_overrides_from_binding(pdk, bindings),
            )
            if bound.tech is None:
                return {**unknown, "reason": "Technology binding is unavailable"}
            selected = [
                ("tech", Path(bound.tech)),
                *[("lef", Path(path)) for path in bound.lefs],
                *[("liberty", Path(path)) for path in bound.libs],
            ]
            if bound.mapping_file:
                selected.append(("mapping", Path(bound.mapping_file)))
        if not {"tech", "lef", "liberty"} <= {role for role, _path in selected}:
            return {**unknown, "reason": "Incomplete selected PDK bindings"}
        records = [
            {"role": role, "sha256": checksum, "bytes": size}
            for role, path in selected
            for checksum, size in [file_digest(path)]
        ]
        identity = {
            "profile": {key: pdk.get(key) for key in ("familyId", "version", "mode", "overrides")},
            "files": records,
        }
        return {**unknown, "status": "available", "fingerprint": digest(identity), "files": records}
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return {**unknown, "reason": f"Selected PDK content unavailable: {type(exc).__name__}"}
