"""Select the chip/core PDN baseline without replacing explicit user meshes."""

from chipcompiler.data.config_params.floorplan import pdn_defaults
from chipcompiler.data.pdk import PDK


def refresh_pdn_defaults(floorplan: dict, parameters: dict, pdk: PDK) -> None:
    patch = parameters.get("config_overrides", {}).get("floorplan", {})
    mode = patch.get("io_placer", {}).get("mode", floorplan["io_placer"]["mode"])
    core = pdn_defaults(pdk, "auto")
    chip = pdn_defaults(pdk, "io_cell")
    selected = chip if mode == "io_cell" else core
    pdn = floorplan["pdn_generator"]
    explicit = patch.get("pdn_generator", {})
    for name, value in selected.items():
        # Only replace a shipped baseline; retain custom imported configs too.
        if name not in explicit and (name not in pdn or pdn[name] in (core[name], chip[name])):
            pdn[name] = value
