"""Materialize the existing test process as a portable description."""

import json
from pathlib import Path

from chipcompiler.data.parameter import ICS55_PARAMETERS_TEMPLATE, SG13G2_PARAMETERS_TEMPLATE
from chipcompiler.data.pdk import PDK_ICS55, PDK_SG13G2
from chipcompiler.pdk.manifest import CellRoles, Descriptor, LibraryView, Resource


def write_fixture_description(root: Path, family: str = "ics55") -> None:
    pdk = PDK_ICS55(root) if family == "ics55" else PDK_SG13G2(root)
    assert pdk.tech is not None
    resources = {"tech": Resource(path=pdk.tech.relative_to(root).as_posix(), role="tech")}
    for role, paths in (("lef", pdk.lefs), ("liberty", pdk.libs)):
        for index, path in enumerate(paths):
            resources[f"{role}-{index}"] = Resource.model_validate(
                {"path": path.relative_to(root).as_posix(), "role": role}
            )
    configs = json.loads((Path(__file__).parent / "fixtures/tool_defaults.json").read_text())
    for index, view in enumerate(configs.get("sta", {}).get("liberty", [])):
        for lib_index, value in enumerate(view["path"]):
            path = root / value.lstrip("/")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text("library(fixture) {}\n")
            resources[f"sta-{index}-{lib_index}"] = Resource(
                path=path.relative_to(root).as_posix(), role="liberty"
            )
    descriptor = Descriptor(
        family_id=family,
        release=pdk.version,
        resources=resources,
        cells=CellRoles.model_validate({key: getattr(pdk, key) for key in CellRoles.model_fields}),
        views={
            "TYP": LibraryView(
                libraries=[key for key in resources if key.startswith("liberty-")],
                process="test",
                voltage=1.0,
                temperature=25.0,
            )
        },
        parameters=ICS55_PARAMETERS_TEMPLATE if family == "ics55" else SG13G2_PARAMETERS_TEMPLATE,
        synthesis_libraries=[
            name for name, resource in resources.items() if resource.role == "liberty"
        ][:2],
        tools={
            "configs": configs,
            "timing": {"default_view": "TYP"},
            "extraction": {"corners": pdk.corners},
        },
    )
    (root / "ecc-pdk.json").write_text(descriptor.model_dump_json(indent=2))
