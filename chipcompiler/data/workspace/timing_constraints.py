"""Workspace-owned pre/post-CTS scenario files, created before flow execution."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from chipcompiler.utility import json_read

from .sdc import custom_step_sdc_path, is_generated_sdc, signoff_sdc_path
from .sdc_inputs import SdcInputs

if TYPE_CHECKING:
    from . import Workspace


@dataclass(frozen=True)
class TimingScenario:
    corner: str
    temperature: str
    rc: str


def _config_scenarios(config: dict) -> list[TimingScenario]:
    libraries = {entry["corner"]: entry for entry in config.get("liberty", [])}
    return [
        TimingScenario(corner, str(libraries[corner]["temperature"]), rc)
        for group in config.get("signoff", [])
        for corner, rc_corners in group.items()
        if corner in libraries
        for rc in rc_corners
    ]


def timing_scenarios(workspace: "Workspace") -> list[TimingScenario]:
    """The scenarios the workspace's own STA configuration declares.

    An existing workspace reads only its persisted config: re-reading the
    installation's defaults or the PDK's `ecc-configs/` here would drag corners
    an installation update introduced into a workspace that never asked for
    them. The merged baseline is used only when no config exists yet, which is
    how a workspace being created (or one built directly in a test) gets its
    initial scenario set.
    """
    from . import workspace_config_key_path
    from .tool_configs import tool_config

    path = workspace_config_key_path(workspace.directory, "sta")
    if path is not None and path.is_file():
        return _config_scenarios(json_read(path))
    configs_dir = Path(__file__).resolve().parents[2] / "tools/ecc/configs"
    return _config_scenarios(tool_config(configs_dir, "sta_ecc.json", workspace.pdk))


def scenario_tcl_path(directory: Path, scenario: TimingScenario, *, post_cts: bool) -> Path:
    temperature = scenario.temperature.replace("-", "m").replace(".", "p")
    phase_dir = "post_CTS" if post_cts else "pre_CTS"
    return directory / "origin" / phase_dir / f"{scenario.corner}_{temperature}_{scenario.rc}.tcl"


def generate_timing_scripts(workspace: "Workspace", *, has_io_cells: bool | None = None) -> None:
    """Generate both sets and use pre-CTS TYP/TYPICAL as the default entry point."""
    if workspace.pdk.sdc is not None and not is_generated_sdc(workspace.pdk.sdc):
        for post_cts in (False, True):
            custom_step_sdc_path(workspace.pdk.sdc, workspace.directory, post_cts=post_cts)
        return
    scenarios = timing_scenarios(workspace)
    if not scenarios:
        return
    inputs = SdcInputs.from_parameters(workspace.parameters.data)
    for corner in dict.fromkeys(scenario.corner for scenario in scenarios):
        inputs.clocks(workspace.parameters.data, corner)
    for post_cts in (False, True):
        for scenario in scenarios:
            signoff_sdc_path(
                workspace,
                scenario_tcl_path(workspace.directory, scenario, post_cts=post_cts),
                post_cts=post_cts,
                corner=scenario.corner,
                rc_para=scenario.rc,
                has_io_cells=has_io_cells,
            )
    # TYP/TYPICAL when the workspace declares it, otherwise its own first
    # scenario. Corner names are PDK-defined, so the default entry point is
    # whatever this workspace's config actually generates, never a hard-coded
    # corner that may not exist in it.
    default = next(
        (item for item in scenarios if (item.corner, item.rc) == ("TYP", "TYPICAL")),
        scenarios[0],
    )
    workspace.pdk.sdc = scenario_tcl_path(workspace.directory, default, post_cts=False)
