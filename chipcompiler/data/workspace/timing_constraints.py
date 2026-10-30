"""Workspace-owned pre/post-CTS scenario files, created before flow execution."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from chipcompiler.utility import json_read
from chipcompiler.utility.file import write_text_atomic

from .sdc import is_generated_sdc, signoff_sdc_path

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
    """Keep the complete default script set, with configured scenarios taking precedence."""
    from . import workspace_config_key_path

    template = Path(__file__).resolve().parents[2] / "tools/ecc/configs/sta_ecc.json"
    path = workspace_config_key_path(workspace.directory, "sta")
    configs = (json_read(template), json_read(path) if path else {})
    scenarios = {
        (scenario.corner, scenario.rc): scenario
        for config in configs
        for scenario in _config_scenarios(config)
    }
    return list(scenarios.values())


def scenario_tcl_path(directory: Path, scenario: TimingScenario, *, post_cts: bool) -> Path:
    temperature = scenario.temperature.replace("-", "m").replace(".", "p")
    phase_dir = "post_CTS" if post_cts else "pre_CTS"
    return directory / "origin" / phase_dir / f"{scenario.corner}_{temperature}_{scenario.rc}.tcl"


def write_timing_io_context(workspace: "Workspace", *, has_io_cells: bool) -> None:
    if not is_generated_sdc(workspace.pdk.sdc):
        return
    path = workspace.directory / "home" / "timing_io.tcl"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, f"set has_io_cells {int(has_io_cells)}\n")


def generate_timing_scripts(workspace: "Workspace") -> None:
    """Generate both complete sets without loading RTL or a native database."""
    if not is_generated_sdc(workspace.pdk.sdc):
        return
    scenarios = timing_scenarios(workspace)
    if not scenarios:
        raise ValueError("Generated timing constraints require configured STA scenarios")
    context = workspace.directory / "home" / "timing_io.tcl"
    if not context.exists():
        context.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(
            context, 'error "ECC must load the design before selecting timing IO constraints"\n'
        )
    for post_cts in (False, True):
        for scenario in scenarios:
            signoff_sdc_path(
                workspace,
                scenario_tcl_path(workspace.directory, scenario, post_cts=post_cts),
                post_cts=post_cts,
                corner=scenario.corner,
                rc_para=scenario.rc,
            )
