#!/usr/bin/env python

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Final

from chipcompiler.utility import Logger, create_logger, dict_to_str
from chipcompiler.utility.filelist import parse_filelist, parse_incdir_directives, resolve_path
from chipcompiler.utility.path import path_is_within, path_text

from ..home import HomeData
from ..parameter import (
    Parameters,
    get_parameters,
    load_parameter,
    reload_parameter,
    save_parameter,
    update_parameters,
)
from ..pdk import PDK, get_pdk
from ..step import StateEnum, StepEnum
from .layout import EccData, WorkspaceStepBase

# The shared step type used as the annotation/constructor across the codebase.
WorkspaceStep = WorkspaceStepBase


@dataclass
class OriginDesign:
    """
    Dataclass for original design information
    """

    name: str = ""  # design name
    top_module: str = ""  # top module name
    origin_def: Path | None = None  # original def file path
    origin_verilog: Path | None = None  # original verilog file path
    input_filelist: Path | None = None  # input filelist for synthesis


@dataclass
class Flow:
    """
    Dataclass for design flow
    """

    path: Path | None = None  # flow file path
    data: dict = field(default_factory=dict)  # flow steps

    def steps(self) -> list[dict]:
        data = self.data if isinstance(self.data, dict) else {}
        if not data and self.path is not None:
            from chipcompiler.utility import json_read

            loaded = json_read(self.path)
            if isinstance(loaded, dict):
                self.data = loaded
                data = loaded
        raw_steps = data.get("steps", [])
        if not isinstance(raw_steps, list):
            return []
        return [step for step in raw_steps if isinstance(step, dict)]

    def get_step(self, name: str | StepEnum, tool: str | None = None) -> dict | None:
        step_name = name.value if isinstance(name, StepEnum) else name
        for step in self.steps():
            if step.get("name") != step_name:
                continue
            if tool is None or step.get("tool") == tool:
                return step
        return None

    def has_step(self, name: str | StepEnum, tool: str | None = None) -> bool:
        return self.get_step(name, tool) is not None


@dataclass
class Workspace:
    """
    Dataclass for workspace information
    """

    directory: Path | None = None  # workspace directory
    design: OriginDesign = field(default_factory=OriginDesign)  # original design info
    pdk: PDK = field(default_factory=PDK)  # pdk information
    parameters: Parameters = field(default_factory=Parameters)  # design parameters
    flow: Flow = field(default_factory=Flow)  # design flow for this workspace
    home: HomeData = field(default_factory=HomeData)  # home data for this workspace
    config: dict[str, Path] = field(default_factory=dict)  # workspace-level config paths

    # logger
    logger: Logger = field(default_factory=Logger)  # logger for this workspace


def step_group_to_dict(group: Any) -> dict:
    """Project a typed path group back to its legacy-key dict for logging.

    Reproduces the pre-migration per-builder key set: a scalar/path field is
    emitted only when populated (so a variant's inherited-but-unset fields — e.g.
    ``db`` on a synthesis output, or ``sizer_env`` on a non-sizer script — do not
    appear), while list/mapping payloads (``spef``/``steps``/``checklist``) are
    always emitted as the builders always initialized them. Renames ``def_`` to
    ``"def"``, flattens ``EccData.steps`` into its dynamic per-step keys, and
    recurses into nested groups (e.g. ``report.sta``).
    """
    result: dict = {}
    for f in fields(group):
        if f.name == "steps" and isinstance(group, EccData):
            result.update(group.steps)
            continue
        if f.name == "requires_slang":
            # typed-model gate flag, not a legacy path key; never projected.
            continue
        value = getattr(group, f.name)
        if is_dataclass(value) and not isinstance(value, type):
            value = step_group_to_dict(value)
        elif value is None:
            # A field this builder never populated (inherited from the base or a
            # sibling variant); it was not in the legacy dict, so skip it.
            continue
        key = "def" if f.name == "def_" else f.name
        result[key] = value
    return result


def log_workspace_step(step: WorkspaceStep, logger: Logger):
    logger.log_section(f"step {step.name} info")
    logger.info(f"step name         : {step.name}")
    logger.info(f"step eda          : {step.tool}")
    logger.info(f"step eda version  : {step.version}")
    logger.info(f"step subworkspace : {step.directory}")

    logger.info("\ninput - \n%s", dict_to_str(step_group_to_dict(step.input)))
    logger.info("\noutput - \n%s", dict_to_str(step_group_to_dict(step.output)))
    logger.info("\ndata - \n%s", dict_to_str(step_group_to_dict(step.data)))
    logger.info("\nfeature - \n%s", dict_to_str(step_group_to_dict(step.feature)))
    logger.info("\nreport - \n%s", dict_to_str(step_group_to_dict(step.report)))
    logger.info("\nlog - \n%s", dict_to_str(step_group_to_dict(step.log)))
    logger.info("\nscript - \n%s", dict_to_str(step_group_to_dict(step.script)))
    logger.info("\nanalysis - \n%s", dict_to_str(step_group_to_dict(step.analysis)))
    logger.info("\nsubflow - \n%s", dict_to_str(step_group_to_dict(step.subflow)))
    logger.info("\nchecklist - \n%s", dict_to_str(step_group_to_dict(step.checklist)))
    logger.log_separator()


_WORKSPACE_CONFIG_FILENAMES: Final[dict[str, str]] = {
    "db": "db_ecc.json",
    StepEnum.CTS.value: "cts_ecc.json",
    StepEnum.DRC.value: "drc_ecc.json",
    StepEnum.FLOORPLAN.value: "floorplan_ecc.json",
    StepEnum.ROUTING.value: "route_ecc.json",
    StepEnum.FILLER.value: "filler_ecc.json",
    StepEnum.RCX.value: "rcx_ecc.json",
    StepEnum.STA.value: "sta_ecc.json",
    "dreamplace": "dreamplace_ecc.json",
}

_LEGACY_WORKSPACE_CONFIG_FILENAMES: Final[dict[str, str]] = {
    "db": "db_default_config.json",
    StepEnum.CTS.value: "cts_default_config.json",
    StepEnum.DRC.value: "drc_default_config.json",
    StepEnum.FLOORPLAN.value: "fp_default_config.json",
    StepEnum.ROUTING.value: "rt_default_config.json",
    StepEnum.FILLER.value: "pl_default_config.json",
    StepEnum.RCX.value: "rcx.json",
    StepEnum.STA.value: "sta.json",
    "dreamplace": "dreamplace.json",
}

_STEP_BY_VALUE: Final[dict[str, StepEnum]] = {step.value: step for step in StepEnum}

_STEP_CONFIG_KEYS: Final[dict[tuple[StepEnum, str], tuple[str, ...]]] = {
    (StepEnum.FLOORPLAN, "ecc"): ("db", StepEnum.FLOORPLAN.value),
    (StepEnum.PLACEMENT, "ecc"): ("db",),
    (StepEnum.CTS, "ecc"): ("db", StepEnum.CTS.value),
    (StepEnum.ROUTING, "ecc"): ("db", StepEnum.ROUTING.value),
    (StepEnum.DRC, "ecc"): ("db", StepEnum.DRC.value),
    (StepEnum.LEGALIZATION, "ecc"): ("db",),
    (StepEnum.FILLER, "ecc"): ("db", StepEnum.FILLER.value),
    (StepEnum.RCX, "ecc"): ("db", StepEnum.RCX.value),
    (StepEnum.STA, "ecc"): ("db", StepEnum.RCX.value, StepEnum.STA.value),
    (StepEnum.PLACEMENT, "dreamplace"): ("dreamplace",),
    (StepEnum.LEGALIZATION, "dreamplace"): ("dreamplace",),
    (StepEnum.TIMING_OPT, "sizer"): ("db", "dreamplace"),
}


def _workspace_step_enum(step: str | StepEnum) -> StepEnum | None:
    if isinstance(step, StepEnum):
        return step
    return _STEP_BY_VALUE.get(step)


def workspace_config_paths(workspace_dir: str | Path) -> dict[str, Path]:
    config_dir = Path(workspace_dir) / "config"
    return {
        "dir": config_dir,
        **{
            config_key: config_dir / filename
            for config_key, filename in _WORKSPACE_CONFIG_FILENAMES.items()
        },
    }


def migrate_workspace_config_filenames(workspace_dir: str | Path) -> None:
    """Rename legacy workspace configs before resolving their canonical paths."""
    config_dir = Path(workspace_dir) / "config"
    if not config_dir.is_dir():
        return

    for config_key, legacy_filename in _LEGACY_WORKSPACE_CONFIG_FILENAMES.items():
        legacy_path = config_dir / legacy_filename
        canonical_path = config_dir / _WORKSPACE_CONFIG_FILENAMES[config_key]
        if legacy_path.is_file() and not canonical_path.exists():
            legacy_path.rename(canonical_path)


def workspace_config_path(workspace_dir: str | Path, config_key: str) -> Path | None:
    return workspace_config_paths(workspace_dir).get(config_key)


def step_config_keys(step: str | StepEnum, tool: str | None) -> tuple[str, ...]:
    step_enum = _workspace_step_enum(step)
    if step_enum is None or tool is None:
        return ()
    return _STEP_CONFIG_KEYS.get((step_enum, tool), ())


def step_config_paths(
    workspace_dir: str | Path,
    step: str | StepEnum,
    tool: str | None,
    *,
    existing_only: bool = False,
) -> tuple[Path, ...]:
    paths = workspace_config_paths(workspace_dir)
    result = []
    for config_key in step_config_keys(step, tool):
        path = paths.get(config_key)
        if path is None:
            continue
        if existing_only and not path.is_file():
            continue
        result.append(path)
    return tuple(result)


def build_workspace_config_paths(workspace: Workspace) -> dict[str, Path]:
    """Build workspace-level config file paths."""
    workspace_dir = Path(workspace.directory) if workspace.directory is not None else Path("")
    return workspace_config_paths(workspace_dir)


def build_dynamic_flow_data(flow_config: dict | None) -> dict:
    """Build initial flow.json data from GUI-provided flow_config."""
    if not isinstance(flow_config, dict) or not flow_config:
        return {}

    canonical_steps = _canonical_harden_flow_entries()
    selected_names = _selected_dynamic_flow_step_names(flow_config, canonical_steps)
    if not selected_names:
        return {}

    selected = set(selected_names)
    return {
        "steps": [
            _flow_step_template(name, tool, state)
            for name, tool, state in canonical_steps
            if name in selected
        ]
    }


def _canonical_harden_flow_entries() -> list[tuple[str, str, str]]:
    import chipcompiler.rtl2gds as rtl2gds_api

    return [
        (
            step.value if isinstance(step, StepEnum) else str(step),
            str(tool),
            state.value if isinstance(state, StateEnum) else str(state),
        )
        for step, tool, state in rtl2gds_api.build_harden_flow()
    ]


def _selected_dynamic_flow_step_names(
    flow_config: dict,
    canonical_steps: list[tuple[str, str, str]],
) -> list[str]:
    canonical_names = [name for name, _tool, _state in canonical_steps]
    canonical_name_set = set(canonical_names)

    raw_steps = flow_config.get("steps", [])
    if isinstance(raw_steps, str):
        raw_steps = [raw_steps]
    if isinstance(raw_steps, (list, tuple)):
        requested = {
            name
            for name in (_normalize_flow_step_name(item) for item in raw_steps)
            if name in canonical_name_set
        }
        if requested:
            return [name for name in canonical_names if name in requested]

    start_step = _normalize_flow_step_name(flow_config.get("start_step"))
    end_step = _normalize_flow_step_name(flow_config.get("end_step"))
    if start_step not in canonical_name_set or end_step not in canonical_name_set:
        return []

    start_index = canonical_names.index(start_step)
    end_index = canonical_names.index(end_step)
    start = min(start_index, end_index)
    end = max(start_index, end_index)
    return canonical_names[start : end + 1]


def _normalize_flow_step_name(value) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    alias_key = token.lower().replace("_", "").replace("-", "").replace(" ", "")
    aliases = {
        "synth": StepEnum.SYNTHESIS.value,
        "synthesis": StepEnum.SYNTHESIS.value,
        "floor": StepEnum.FLOORPLAN.value,
        "floorplan": StepEnum.FLOORPLAN.value,
        "place": StepEnum.PLACEMENT.value,
        "placement": StepEnum.PLACEMENT.value,
        "cts": StepEnum.CTS.value,
        "legal": StepEnum.LEGALIZATION.value,
        "legalization": StepEnum.LEGALIZATION.value,
        "route": StepEnum.ROUTING.value,
        "routing": StepEnum.ROUTING.value,
        "drc": StepEnum.DRC.value,
        "lvs": StepEnum.LVS.value,
        "filler": StepEnum.FILLER.value,
        "rcx": StepEnum.RCX.value,
        "sta": StepEnum.STA.value,
        "harden": StepEnum.HARDEN.value,
    }
    return aliases.get(alias_key, token)


def _flow_step_template(name: str, tool: str, state: str) -> dict:
    return {
        "name": name,
        "tool": tool,
        "state": state,
        "runtime": "",
        "peak memory (mb)": 0,
        "info": {},
    }


@dataclass(frozen=True)
class WorkspaceConfigParameterMapping:
    parameter_key: str
    config_key: str
    json_path: tuple[str, ...]
    to_config: Callable[[Any], Any] | None = None
    to_parameter: Callable[[Any], Any] | None = None


def _flag_to_int(value: Any) -> int:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on"}:
            return 1
        if normalized in {"false", "no", "off", ""}:
            return 0
        try:
            return int(float(normalized))
        except ValueError:
            return 1
    return int(bool(value))


PARAMETER_CONFIG_FIELD_MAPPINGS = (
    WorkspaceConfigParameterMapping(
        "max_fanout",
        StepEnum.NETLIST_OPT.value,
        ("max_fanout",),
    ),
    WorkspaceConfigParameterMapping(
        "max_fanout",
        StepEnum.CTS.value,
        ("max_fanout",),
    ),
    WorkspaceConfigParameterMapping(
        "bottom_layer",
        "db",
        ("LayerSettings", "routing_layer_1st"),
    ),
    WorkspaceConfigParameterMapping(
        "bottom_layer",
        StepEnum.ROUTING.value,
        ("RT", "-bottom_routing_layer"),
    ),
    WorkspaceConfigParameterMapping(
        "top_layer",
        StepEnum.ROUTING.value,
        ("RT", "-top_routing_layer"),
    ),
    WorkspaceConfigParameterMapping(
        "target_density",
        "dreamplace",
        ("target_density",),
    ),
    WorkspaceConfigParameterMapping(
        "target_overflow",
        "dreamplace",
        ("stop_overflow",),
    ),
    WorkspaceConfigParameterMapping(
        "cell_padding_x",
        "dreamplace",
        ("cell_padding_x",),
    ),
    WorkspaceConfigParameterMapping(
        "routability_opt_flag",
        "dreamplace",
        ("routability_opt_flag",),
        to_config=_flag_to_int,
        to_parameter=_flag_to_int,
    ),
)


_MISSING = object()


def _get_nested_value(data: dict, path: tuple[str, ...]):
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _set_nested_value(data: dict, path: tuple[str, ...], value) -> None:
    current = data
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[path[-1]] = value


def _mapping_config_path(
    workspace: Workspace,
    mapping: WorkspaceConfigParameterMapping,
) -> Path | None:
    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)
    return workspace.config.get(mapping.config_key)


def _reload_workspace_parameters(workspace: Workspace) -> None:
    parameter_path = workspace.parameters.path
    if parameter_path is None:
        return
    workspace.parameters = reload_parameter(parameter_path, workspace.parameters)


def _apply_parameter_mappings_to_workspace_config(workspace: Workspace) -> None:
    from chipcompiler.utility import json_read, json_write

    configs: dict[str, dict] = {}
    for mapping in PARAMETER_CONFIG_FIELD_MAPPINGS:
        if mapping.parameter_key not in workspace.parameters.data:
            continue

        path = _mapping_config_path(workspace, mapping)
        if not path:
            continue

        config = configs.setdefault(path, json_read(path))
        value = workspace.parameters.data[mapping.parameter_key]
        if mapping.to_config is not None:
            value = mapping.to_config(value)
        _set_nested_value(config, mapping.json_path, value)

    for path, config in configs.items():
        json_write(path, config)


def _coerce_legacy_dreamplace_routability_flag(workspace: Workspace, dreamplace: dict) -> None:
    dreamplace_overrides = workspace.parameters.data.get("dreamplace", {})
    if isinstance(dreamplace_overrides, dict) and "routability_opt_flag" in dreamplace_overrides:
        return
    if "routability_opt_flag" in workspace.parameters.data:
        dreamplace["routability_opt_flag"] = _flag_to_int(
            workspace.parameters.data["routability_opt_flag"]
        )


def _load_default_floorplan_config() -> dict:
    from chipcompiler.utility import json_read

    root_dir = Path(__file__).resolve().parent.parent.parent
    return json_read(root_dir / "tools" / "ecc" / "configs" / "floorplan_ecc.json")


def _has_new_floorplan_schema(config: dict) -> bool:
    die_builder = config.get("die_builder")
    return (
        all(
            key in config
            for key in (
                "ifp",
                "macro_placer",
                "die_builder",
                "io_placer",
                "phy_placer",
                "pdn_generator",
            )
        )
        and isinstance(die_builder, dict)
        and all(key in die_builder for key in ("mode", "margin", "die_util", "die_size"))
    )


def _macro_location_file(config_path: Path, floorplan: dict) -> Path:
    macro_placer = floorplan.setdefault("macro_placer", {})
    macro_path_text = str(macro_placer.get("macro_location_path") or "macro_locations.txt")
    macro_placer["macro_location_path"] = macro_path_text
    macro_path = Path(macro_path_text)
    if not macro_path.is_absolute():
        macro_path = config_path.parent / macro_path
    macro_path.parent.mkdir(parents=True, exist_ok=True)
    if not macro_path.exists():
        macro_path.write_text("", encoding="utf-8")
    return macro_path


def _refresh_floorplan_config(workspace: Workspace, step: WorkspaceStep | None = None) -> None:
    from chipcompiler.utility import json_read, json_write

    config_path = workspace.config.get(StepEnum.FLOORPLAN.value)
    if not config_path:
        return

    default_floorplan = _load_default_floorplan_config()
    floorplan = json_read(config_path) if Path(config_path).exists() else {}
    if not _has_new_floorplan_schema(floorplan):
        floorplan = default_floorplan

    ifp = floorplan.setdefault("ifp", {})
    default_ifp = default_floorplan.get("ifp", {})
    ifp.setdefault("thread_number", default_ifp.get("thread_number", 16))
    if step is not None:
        workdir = step.data.workdir_for(StepEnum.FLOORPLAN.value)
        if workdir:
            ifp["temp_directory_path"] = path_text(workdir)

    default_die_builder = default_floorplan.get("die_builder", {})
    die_builder = floorplan.setdefault("die_builder", {})
    die_builder.setdefault("mode", default_die_builder.get("mode", "die_util"))
    die_builder["site_name"] = workspace.pdk.site_core or die_builder.get(
        "site_name", default_die_builder.get("site_name", "")
    )

    default_margin = default_die_builder.get("margin", {})
    margin_config = die_builder.setdefault("margin", {})
    core = workspace.parameters.data.get("core", {})
    margin = core.get("margin", [])
    if len(margin) < 2:
        margin = [
            margin_config.get("left_micron", default_margin.get("left_micron", 10.0)),
            margin_config.get("bottom_micron", default_margin.get("bottom_micron", 10.0)),
        ]
    margin_config["left_micron"] = margin[0]
    margin_config["right_micron"] = margin[0]
    margin_config["top_micron"] = margin[1]
    margin_config["bottom_micron"] = margin[1]

    default_die_util = default_die_builder.get("die_util", {})
    die_util = die_builder.setdefault("die_util", {})
    die_util["aspect_ratio"] = core.get(
        "aspect_ratio", die_util.get("aspect_ratio", default_die_util.get("aspect_ratio", 1.0))
    )
    die_util["utilization"] = core.get(
        "utilitization", die_util.get("utilization", default_die_util.get("utilization", 0.5))
    )

    default_die_size = default_die_builder.get("die_size", {})
    die_size = die_builder.setdefault("die_size", {})
    die_size.setdefault("width_micron", default_die_size.get("width_micron", 100.1))
    die_size.setdefault("height_micron", default_die_size.get("height_micron", 246.6))
    die = workspace.parameters.data.get("die", {})
    die_dimensions = die.get("size") if isinstance(die, dict) else None
    if isinstance(die_dimensions, list) and len(die_dimensions) >= 2:
        die_size["width_micron"] = die_dimensions[0]
        die_size["height_micron"] = die_dimensions[1]
        die_builder["mode"] = "die_size"
    for legacy_key in (
        "core_width_to_height_ratio",
        "core_utilization",
        "left_margin_micron",
        "right_margin_micron",
        "top_margin_micron",
        "bottom_margin_micron",
    ):
        die_builder.pop(legacy_key, None)

    phy_placer = floorplan.setdefault("phy_placer", {})
    well_tap = phy_placer.setdefault("well_tap", {})
    well_tap["cell_name"] = workspace.pdk.tap_cell or well_tap.get("cell_name", "")
    well_tap.setdefault("distance_micron", 58.0)

    side_endcap = phy_placer.setdefault("side_endcap", {})
    side_endcap["left_cell_name"] = workspace.pdk.end_cap or side_endcap.get("left_cell_name", "")
    side_endcap["right_cell_name"] = workspace.pdk.end_cap or side_endcap.get("right_cell_name", "")

    _macro_location_file(Path(config_path), floorplan)
    json_write(config_path, floorplan)


def _ensure_writable(path: str):
    import os
    import stat
    from contextlib import suppress

    with suppress(OSError):
        os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR | stat.S_IXUSR)

    for root, dirs, files in os.walk(path):
        for name in dirs:
            target = os.path.join(root, name)
            with suppress(OSError):
                os.chmod(target, os.stat(target).st_mode | stat.S_IWUSR | stat.S_IXUSR)
        for name in files:
            target = os.path.join(root, name)
            with suppress(OSError):
                os.chmod(target, os.stat(target).st_mode | stat.S_IWUSR)


def _copy_missing_files(src_dir: str, dst_dir: str):
    import os
    import shutil

    os.makedirs(dst_dir, exist_ok=True)
    for name in os.listdir(src_dir):
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)


def _rcx_temperature_key(temperature) -> str:
    try:
        numeric = float(temperature)
        return str(int(numeric)) if numeric.is_integer() else f"{numeric:.12g}"
    except (TypeError, ValueError):
        return str(temperature)


def _rcx_temperature_token(temperature) -> str:
    return _rcx_temperature_key(temperature).replace(".", "p").replace("-", "m") + "C"


def init_workspace_config(workspace: Workspace) -> None:
    """Create workspace-level configs, then refresh parameter/PDK-derived fields."""
    import shutil

    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)

    config_dir = workspace.config["dir"]
    root_dir = Path(__file__).resolve().parent.parent.parent
    ecc_config_dir = root_dir / "tools" / "ecc" / "configs"
    dreamplace_config = root_dir / "tools" / "ecc_dreamplace" / "configs" / "dreamplace_ecc.json"

    _copy_missing_files(ecc_config_dir, config_dir)
    if not workspace.config["dreamplace"].exists():
        shutil.copy2(dreamplace_config, workspace.config["dreamplace"])
    _ensure_writable(config_dir)

    refresh_workspace_config(workspace)


def refresh_workspace_config(workspace: Workspace) -> None:
    """Reload the workspace configuration and refresh configs derived from parameters/PDK."""
    import os

    from chipcompiler.tools.ecc_dreamplace.parameter_overrides import apply_parameter_overrides
    from chipcompiler.utility import json_read, json_write

    _reload_workspace_parameters(workspace)

    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)

    db = json_read(workspace.config["db"])
    if "INPUT" not in db or "LayerSettings" not in db:
        raise FileNotFoundError(
            f"DB config missing or corrupt (no 'INPUT' or 'LayerSettings' key): "
            f"{workspace.config['db']}"
        )
    db["INPUT"]["tech_lef_path"] = str(workspace.pdk.tech or "")
    db["INPUT"]["lef_paths"] = [str(path) for path in workspace.pdk.lefs]
    db["INPUT"]["lib_path"] = [str(path) for path in workspace.pdk.libs]
    db["INPUT"]["sdc_path"] = str(workspace.pdk.sdc or "")
    db["INPUT"]["spef"] = str(workspace.pdk.spef or "")
    db["LayerSettings"]["routing_layer_1st"] = workspace.parameters.data.get("bottom_layer", "")
    if not json_write(workspace.config["db"], db):
        raise OSError(f"Failed to write DB config: {workspace.config['db']}")

    fixfanout = json_read(workspace.config[f"{StepEnum.NETLIST_OPT.value}"])
    if not fixfanout:
        raise FileNotFoundError(
            f"Netlist opt config missing or corrupt: "
            f"{workspace.config[f'{StepEnum.NETLIST_OPT.value}']}"
        )
    max_fanout = workspace.parameters.data.get("max_fanout", 32)
    fixfanout["insert_buffer"] = workspace.pdk.buffers[0] if len(workspace.pdk.buffers) > 0 else ""
    fixfanout["max_fanout"] = max_fanout
    json_write(workspace.config[f"{StepEnum.NETLIST_OPT.value}"], fixfanout)

    filler_path = workspace.config[f"{StepEnum.FILLER.value}"]
    filler = json_read(filler_path)
    if not isinstance(filler, dict):
        raise FileNotFoundError(f"Filler config missing or corrupt: {filler_path}")
    min_filler_width = filler.get("-min_filler_width")
    if min_filler_width is None:
        nested = filler.get("PL", {})
        nested = nested.get("Filler", {}) if isinstance(nested, dict) else {}
        min_filler_width = nested.get("min_filler_width", 1) if isinstance(nested, dict) else 1
    json_write(filler_path, {"-min_filler_width": min_filler_width})

    cts = json_read(workspace.config[f"{StepEnum.CTS.value}"])
    if not cts:
        raise FileNotFoundError(
            f"CTS config missing or corrupt: {workspace.config[f'{StepEnum.CTS.value}']}"
        )
    cts["buffer_type"] = workspace.pdk.buffers
    cts["max_fanout"] = max_fanout
    json_write(workspace.config[f"{StepEnum.CTS.value}"], cts)

    router = json_read(workspace.config[f"{StepEnum.ROUTING.value}"])
    if "RT" not in router:
        raise FileNotFoundError(
            f"Routing config missing or corrupt (no 'RT' key): "
            f"{workspace.config[f'{StepEnum.ROUTING.value}']}"
        )
    router["RT"]["-bottom_routing_layer"] = workspace.parameters.data.get("bottom_layer", "")
    router["RT"]["-top_routing_layer"] = workspace.parameters.data.get("top_layer", "")
    json_write(workspace.config[f"{StepEnum.ROUTING.value}"], router)

    _refresh_floorplan_config(workspace)

    _apply_parameter_mappings_to_workspace_config(workspace)

    # rcx = json_read(workspace.config[f"{StepEnum.RCX.value}"])
    # rcx["pdk"] = "ics55" if workspace.pdk.name == "ics55" else ""
    # rcx["mapping_file"] = workspace.pdk.mapping_file
    # corners = deepcopy(workspace.pdk.corners)
    # rcx["corners"] = corners
    # json_write(workspace.config[f"{StepEnum.RCX.value}"], rcx)

    sta = json_read(workspace.config[f"{StepEnum.STA.value}"])
    pdk_root = str(workspace.pdk.root or "").rstrip(os.sep)
    for liberty in sta.get("liberty", []):
        liberty["path"] = [
            path
            if path == pdk_root or path.startswith(f"{pdk_root}{os.sep}")
            else str((workspace.pdk.root or Path("")) / path.lstrip(os.sep))
            for path in liberty.get("path", [])
        ]

    json_write(workspace.config[f"{StepEnum.STA.value}"], sta)

    dreamplace = json_read(workspace.config["dreamplace"])
    if not dreamplace:
        raise FileNotFoundError(
            f"DreamPlace config missing or corrupt: {workspace.config['dreamplace']}"
        )
    dreamplace["lef_input"] = [
        str(path) for path in [workspace.pdk.tech, *workspace.pdk.lefs] if path
    ]
    dreamplace["base_design_name"] = workspace.design.name
    dreamplace = apply_parameter_overrides(dreamplace, workspace.parameters.data)
    _coerce_legacy_dreamplace_routability_flag(workspace, dreamplace)
    json_write(workspace.config["dreamplace"], dreamplace)


def sync_workspace_config_to_parameters(workspace: Workspace, config_path: Path) -> bool:
    """Sync managed fields from one workspace config file back into the workspace configuration."""
    from chipcompiler.utility import json_read

    _reload_workspace_parameters(workspace)

    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)

    resolved_config_path = Path(config_path).expanduser().resolve()
    changed = False
    for mapping in PARAMETER_CONFIG_FIELD_MAPPINGS:
        mapped_path = _mapping_config_path(workspace, mapping)
        if mapped_path is None or mapped_path.expanduser().resolve() != resolved_config_path:
            continue

        config = json_read(mapped_path)
        value = _get_nested_value(config, mapping.json_path)
        if value is _MISSING:
            continue

        if mapping.to_parameter is not None:
            value = mapping.to_parameter(value)

        if workspace.parameters.data.get(mapping.parameter_key) != value:
            workspace.parameters.data[mapping.parameter_key] = value
            changed = True

    if changed and not save_parameter(workspace.parameters):
        import logging

        logging.getLogger(__name__).warning(
            "Failed to persist parameter sync changes; changes exist only in memory"
        )

    return changed


def _reset_workspace_checklist(workspace: Workspace) -> None:
    from chipcompiler.utility import json_write

    checklist_path_text = workspace.home.data.get("checklist", "")
    if checklist_path_text:
        checklist_path = Path(checklist_path_text)
    else:
        checklist_path = Path(workspace.directory) / "home" / "checklist.json"
    json_write(
        checklist_path,
        {
            "path": str(checklist_path),
            "checklist": [],
        },
    )


def _reset_workspace_runtime_parameters(workspace: Workspace) -> None:
    from copy import deepcopy

    current_data = workspace.parameters.data or {}
    pdk_name = str(current_data.get("pdk", "")).lower()
    template_parameters = get_parameters(pdk_name)
    template_data = deepcopy(template_parameters.data)

    die_template = template_data.get("die")
    if isinstance(die_template, dict) and isinstance(current_data.get("die"), dict):
        current_data["die"] = deepcopy(die_template)

    core_template = template_data.get("core")
    if isinstance(core_template, dict) and isinstance(current_data.get("core"), dict):
        current_core = current_data["core"]
        current_data["core"] = {
            **deepcopy(core_template),
            "utilitization": current_core.get("utilitization", core_template.get("utilitization")),
            "margin": deepcopy(current_core.get("margin", core_template.get("margin"))),
            "aspect_ratio": current_core.get("aspect_ratio", core_template.get("aspect_ratio")),
        }

    if not save_parameter(workspace.parameters):
        import logging

        logging.getLogger(__name__).warning(
            "Failed to persist workspace parameters after template refresh"
        )


def prepare_workspace_for_rerun(
    workspace: Workspace,
    engine_flow,
    *,
    preserve_user_inputs: bool = False,
) -> None:
    """Delete old run artifacts and restore runtime files before a full-flow rerun.

    GUI reruns retain the user's current configuration and parameter values. CLI
    keeps the established runtime-parameter reset behavior.
    """
    import shutil

    workspace_root = Path(workspace.directory).resolve()
    step_directories = []
    for workspace_step in getattr(engine_flow, "workspace_steps", []):
        step_directory = getattr(workspace_step, "directory", "")
        if not step_directory:
            continue
        resolved_step_directory = Path(step_directory).resolve()
        if resolved_step_directory == workspace_root or not path_is_within(
            resolved_step_directory, workspace_root
        ):
            raise ValueError(
                f"refusing to delete step directory outside workspace: {step_directory}"
            )
        step_directories.append(resolved_step_directory)

    for step_directory in sorted(
        set(step_directories), key=lambda path: len(str(path)), reverse=True
    ):
        if not step_directory.exists():
            continue
        if step_directory.is_symlink() or step_directory.is_file():
            step_directory.unlink()
        else:
            shutil.rmtree(step_directory)

    if hasattr(engine_flow, "clear_states"):
        engine_flow.clear_states()

    workspace.home.reset()
    workspace.home.set_flow(workspace.flow.path)
    workspace.home.set_checklist(workspace_root / "home" / "checklist.json")
    parameter_path = workspace.parameters.path or (workspace_root / "home" / "ecc.toml")
    workspace.parameters.path = Path(parameter_path)
    workspace.home.set_parameters(workspace.parameters.path)
    _reset_workspace_checklist(workspace)
    if not preserve_user_inputs:
        _reset_workspace_runtime_parameters(workspace)
        refresh_workspace_config(workspace)

    if hasattr(engine_flow, "engine_db"):
        engine_flow.engine_db = None
    if hasattr(engine_flow, "workspace_steps"):
        engine_flow.workspace_steps.clear()
    if hasattr(engine_flow, "create_step_workspaces"):
        engine_flow.create_step_workspaces()


def update_step_config(workspace: Workspace, step: WorkspaceStep) -> None:
    """Update only step-dependent workspace config fields."""
    from chipcompiler.utility import json_read, json_write

    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)

    db = json_read(workspace.config["db"])
    if "INPUT" not in db or "OUTPUT" not in db:
        raise FileNotFoundError(
            f"DB config missing or corrupt (no 'INPUT' or 'OUTPUT' key): {workspace.config['db']}"
        )
    db["INPUT"]["def_path"] = path_text(step.input.def_)
    db["INPUT"]["verilog_path"] = path_text(step.input.verilog)
    db["OUTPUT"]["output_dir_path"] = path_text(step.output.dir)
    json_write(workspace.config["db"], db)

    if step.name == StepEnum.FLOORPLAN.value:
        _refresh_floorplan_config(workspace, step=step)

    if step.name == StepEnum.ROUTING.value and isinstance(step.data, EccData):
        router = json_read(workspace.config[f"{StepEnum.ROUTING.value}"])
        if "RT" not in router:
            raise FileNotFoundError(
                f"Routing config missing or corrupt (no 'RT' key): "
                f"{workspace.config[f'{StepEnum.ROUTING.value}']}"
            )
        router["RT"]["-temp_directory_path"] = path_text(
            step.data.steps.get(StepEnum.ROUTING.value)
        )
        json_write(workspace.config[f"{StepEnum.ROUTING.value}"], router)

    if step.name == StepEnum.RCX.value:
        rcx = json_read(workspace.config[f"{StepEnum.RCX.value}"])
        if not rcx:
            raise FileNotFoundError(
                f"RCX config missing or corrupt: {workspace.config[f'{StepEnum.RCX.value}']}"
            )
        rcx_output_dir = path_text(step.data.dir)
        spef_design_name = workspace.design.top_module or workspace.design.name
        rcx["output"] = rcx_output_dir
        for corner in rcx.get("corners", []):
            corner_name = corner.get("name", "")
            if corner_name:
                temperatures = corner.get("temperature", [25]) or [25]
                corner["spef_file"] = [
                    {
                        _rcx_temperature_key(temperature): (
                            f"{rcx_output_dir}/"
                            f"{spef_design_name}_{corner_name}_"
                            f"{_rcx_temperature_token(temperature)}.spef"
                        )
                    }
                    for temperature in temperatures
                ]
        json_write(workspace.config[f"{StepEnum.RCX.value}"], rcx)


def copy_filelist_with_sources(input_filelist: str, workspace_dir: str, logger=None) -> str:
    """
    Copy filelist and all referenced source files + include directories to workspace/origin/.

    Maintains the original directory structure of source files relative to the filelist location.
    Supports +incdir directives with smart deduplication.

    Args:
        input_filelist: Path to the filelist file
        workspace_dir: Target workspace directory
        logger: Optional logger instance for logging operations

    Returns:
        Path to the copied filelist in workspace/origin/

    Raises:
        FileNotFoundError: If filelist file doesn't exist
        IOError: If file copy operations fail

    Example:
        >>> new_filelist_path = copy_filelist_with_sources(
        ...     "/project/design.f",
        ...     "/workspace/gcd"
        ... )
        >>> print(new_filelist_path)
        '/workspace/gcd/origin/design.f'
    """
    import os
    import shutil

    origin_dir = os.path.join(workspace_dir, "origin")
    os.makedirs(origin_dir, exist_ok=True)

    filelist_dir = os.path.dirname(os.path.abspath(input_filelist))
    copied_files = set()
    stats = {"copied": 0, "missing": 0, "incdir_copied": 0, "incdir_skipped": 0}

    # Copy files listed in filelist
    try:
        source_files = parse_filelist(input_filelist)
    except Exception as e:
        if logger:
            logger.error(f"Failed to parse filelist {input_filelist}: {e}")
        raise

    for src_path in source_files:
        abs_src = resolve_path(src_path, filelist_dir)

        if not os.path.exists(abs_src):
            if logger:
                logger.warning(f"File not found (skipping): {abs_src}")
            stats["missing"] += 1
            continue

        rel_path = os.path.basename(src_path) if os.path.isabs(src_path) else src_path

        if rel_path in copied_files:
            if logger:
                logger.debug(f"Skipping duplicate: {rel_path}")
            continue

        if _copy_file_safely(abs_src, os.path.join(origin_dir, rel_path), logger, src_path):
            copied_files.add(rel_path)
            stats["copied"] += 1

    # Copy +incdir directories
    try:
        incdir_paths = parse_incdir_directives(input_filelist)
    except Exception as e:
        if logger:
            logger.warning(f"Failed to parse +incdir directives: {e}")
        incdir_paths = []

    for incdir_path in incdir_paths:
        abs_incdir = resolve_path(incdir_path, filelist_dir)

        if not os.path.exists(abs_incdir):
            if logger:
                logger.warning(f"Include directory not found: {abs_incdir}")
            continue

        if not os.path.isdir(abs_incdir):
            if logger:
                logger.warning(f"Include path is not a directory: {abs_incdir}")
            continue

        for root, _dirs, files in os.walk(abs_incdir):
            for filename in files:
                src_file = os.path.join(root, filename)
                rel_from_filelist = os.path.relpath(src_file, filelist_dir)

                if rel_from_filelist in copied_files:
                    stats["incdir_skipped"] += 1
                    if logger:
                        logger.debug(f"Skipping duplicate from +incdir: {rel_from_filelist}")
                    continue

                dst_file = os.path.join(origin_dir, rel_from_filelist)
                if _copy_file_safely(src_file, dst_file, logger, f"+incdir/{src_file}"):
                    copied_files.add(rel_from_filelist)
                    stats["incdir_copied"] += 1

    # Copy filelist file itself
    new_filelist = os.path.join(origin_dir, os.path.basename(input_filelist))
    try:
        shutil.copy2(input_filelist, new_filelist)
    except Exception as e:
        if logger:
            logger.error(f"Failed to copy filelist: {e}")
        raise

    if logger:
        logger.info(
            f"Copied filelist and sources: "
            f"{stats['copied']} files from filelist, "
            f"{stats['incdir_copied']} files from +incdir, "
            f"{stats['missing']} missing, "
            f"{stats['incdir_skipped']} duplicates skipped"
        )

    return new_filelist


def _copy_file_safely(src: str, dst: str, logger, context: str) -> bool:
    """Copy a file with error handling and logging."""
    import os
    import shutil

    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if logger:
            logger.debug(f"Copied: {src} -> {dst}")
        return True
    except Exception as e:
        if logger:
            logger.error(f"Error copying {context}: {e}")
        return False


def _workspace_directory_has_existing_data(workspace_dir: Path) -> bool:
    if not workspace_dir.exists():
        return False
    if not workspace_dir.is_dir():
        return True

    try:
        next(workspace_dir.iterdir())
    except StopIteration:
        return False
    except OSError:
        return True
    return True


def create_workspace(
    directory: str | Path,
    origin_def: str | Path,
    origin_verilog: str | Path,
    pdk: PDK | str,
    parameters: Parameters | dict,
    input_filelist: str | Path = "",
    pdk_root: str | Path = "",
    pdk_json: str | Path = "",
    flow_config: dict | None = None,
    sdc: str | Path = "",
    pdk_overrides: dict | None = None,
) -> Workspace:
    """
    Create a workspace for chip design flow.

    Args:
        directory: Workspace directory path
        origin_def: Original DEF file path (for physical design)
        origin_verilog: Original verilog file path (RTL or synthesized netlist)
        pdk: PDK information (LEF, Liberty, SDC, etc.)
        parameters: Design parameters (clock, frequency, etc.)
        sdc: Optional timing constraints file copied into workspace/origin/
        input_filelist: Optional filelist for synthesis (SystemVerilog sources)

    Returns:
        Workspace instance with all paths configured

    Note:
        - origin_verilog can be either RTL (requires SYNTHESIS step) or
          pre-synthesized netlist (skips SYNTHESIS)
        - input_filelist takes priority over origin_verilog for synthesis when both exist
        - All input files are copied to workspace/origin/ directory
    """
    # create workspace directory
    import shutil

    workspace_dir = Path(directory).expanduser().resolve()
    origin_dir = workspace_dir / "origin"
    home_dir = workspace_dir / "home"
    log_dir = workspace_dir / "log"
    if _workspace_directory_has_existing_data(workspace_dir):
        return None

    try:
        workspace_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    # create workspace instance
    workspace = Workspace()

    # pdk
    if isinstance(pdk, PDK):
        workspace.pdk = pdk

    if isinstance(pdk, str):
        workspace.pdk = get_pdk(
            pdk_name=pdk, pdk_root=pdk_root, pdk_config=pdk_json, overrides=pdk_overrides
        )

    explicit_sdc_path = Path(sdc).expanduser().resolve() if sdc else None
    if explicit_sdc_path is not None:
        workspace.pdk.sdc = explicit_sdc_path

    # update config
    if isinstance(parameters, Parameters):
        workspace.design.name = parameters.data["design"]
        workspace.design.top_module = parameters.data["top_module"]
        workspace.parameters = parameters

    if isinstance(parameters, dict):
        # format parameters
        pdk_name = workspace.pdk.name or (pdk if isinstance(pdk, str) else "")
        workspace.parameters = get_parameters(pdk_name)
        update_parameters(parameters_src=parameters, parameters_target=workspace.parameters.data)

        workspace.design.name = workspace.parameters.data["design"]
        workspace.design.top_module = workspace.parameters.data["top_module"]

    # update path
    workspace.directory = workspace_dir
    workspace.config = build_workspace_config_paths(workspace)

    # create logger first (needed for copy operations)
    log_dir.mkdir(parents=True, exist_ok=True)
    workspace.logger = create_logger(name=workspace.parameters.data["design"], log_dir=log_dir)

    # update orign files to workspace origin folder
    origin_dir.mkdir(parents=True, exist_ok=True)
    workspace.config["dir"].mkdir(parents=True, exist_ok=True)
    origin_def_path = Path(origin_def) if origin_def else None
    if origin_def_path and origin_def_path.exists():
        target = origin_dir / origin_def_path.name
        shutil.copy(origin_def_path, target)
        workspace.design.origin_def = target
    else:
        workspace.design.origin_def = origin_dir / f"{workspace.design.name}.def"

    origin_verilog_path = Path(origin_verilog) if origin_verilog else None
    if origin_verilog_path and origin_verilog_path.exists():
        target = origin_dir / origin_verilog_path.name
        shutil.copy(origin_verilog_path, target)
        workspace.design.origin_verilog = target
    else:
        workspace.design.origin_verilog = origin_dir / f"{workspace.design.name}.v"

    # Copy filelist and all referenced source files
    input_filelist_path = Path(input_filelist) if input_filelist else None
    if input_filelist_path and input_filelist_path.exists():
        try:
            # Use new copy_filelist_with_sources to copy filelist + all RTL files
            workspace.design.input_filelist = Path(
                copy_filelist_with_sources(
                    input_filelist=str(input_filelist_path),
                    workspace_dir=str(workspace_dir),
                    logger=workspace.logger,
                )
            )
        except Exception as e:
            workspace.logger.error(f"Failed to copy filelist sources: {e}")
            workspace.logger.warning("Falling back to copying only filelist file")
            # Fallback: copy only filelist file (backward compatibility)
            target = origin_dir / input_filelist_path.name
            shutil.copy(input_filelist_path, target)
            workspace.design.input_filelist = target

    if workspace.pdk.sdc and workspace.pdk.sdc.exists():
        sdc_target = origin_dir / workspace.pdk.sdc.name
        shutil.copy(workspace.pdk.sdc, sdc_target)
        workspace.pdk.sdc = sdc_target
    else:
        # create default sdc file
        workspace.pdk.sdc = origin_dir / f"{workspace.design.name}.sdc"
        create_default_sdc(workspace)

    if workspace.pdk.spef and workspace.pdk.spef.exists():
        spef_target = origin_dir / workspace.pdk.spef.name
        shutil.copy(workspace.pdk.spef, spef_target)
        workspace.pdk.spef = spef_target

    init_workspace_config(workspace)

    # set home data
    home_dir.mkdir(parents=True, exist_ok=True)
    workspace.flow.path = home_dir / "flow.json"
    workspace.parameters.path = home_dir / "ecc.toml"
    workspace.home.init(path=home_dir / "home.json")
    workspace.home.set_flow(workspace.flow.path)
    workspace.home.set_checklist(home_dir / "checklist.json")
    workspace.home.set_parameters(workspace.parameters.path)
    dynamic_flow_data = build_dynamic_flow_data(flow_config)
    if dynamic_flow_data:
        from chipcompiler.utility import json_write

        workspace.flow.data = dynamic_flow_data
        if not json_write(workspace.flow.path, workspace.flow.data):
            raise OSError(f"Failed to write initial flow.json: {workspace.flow.path}")

        from ..workspace_config import flow_section_from_flow_config

        flow_section = flow_section_from_flow_config(flow_config)
        if flow_section:
            workspace.parameters.data["_flow"] = flow_section

    if workspace.pdk.root:
        workspace.parameters.data["pdk_root"] = str(workspace.pdk.root)
    if pdk_json:
        pdk_config_path = home_dir / "pdk.json"
        shutil.copy(pdk_json, pdk_config_path)
        workspace.parameters.data["pdk_config"] = str(pdk_config_path)

    # save parameter
    if not save_parameter(workspace.parameters):
        raise OSError(f"Failed to save parameters: {workspace.parameters.path}")

    log_workspace(workspace)
    log_parameters(workspace)

    return workspace


def _migrate_legacy_parameters_file(workspace_dir: Path) -> None:
    """Rewrite a legacy ``home/parameters.json`` into ``home/ecc.toml``.

    Runs at workspace open, the single choke point for loading workspaces.
    When both files exist the TOML wins and the JSON is left untouched. A
    failed rewrite (permissions, read-only fs) leaves the workspace loadable
    via the normalized in-memory copy; the next open retries.
    """
    from ..parameter_keys import normalize_parameter_dict
    from ..workspace_config import (
        legacy_parameters_path,
        load_workspace_config,
        save_workspace_config,
        workspace_config_path,
    )

    config_path = workspace_config_path(workspace_dir)
    legacy_path = legacy_parameters_path(workspace_dir)
    if config_path.exists():
        if legacy_path.exists():
            logging.getLogger(__name__).warning(
                "workspace_config_shadowed: both %s and %s exist; using the TOML",
                config_path,
                legacy_path,
            )
        return
    if not legacy_path.exists():
        return

    from chipcompiler.utility import JsonReadError, json_read_strict

    try:
        legacy_data = json_read_strict(legacy_path)
    except (JsonReadError, OSError) as exc:
        logging.getLogger(__name__).warning(
            "legacy parameters unreadable, skipping migration: %s: %s", legacy_path, exc
        )
        return

    normalized = normalize_parameter_dict(legacy_data)
    flow_section: dict = {}
    flow_path = workspace_dir / "home" / "flow.json"
    if flow_path.exists():
        # Derive the flow target from the persisted flow's first/last steps
        # so the migrated workspace stays self-describing.
        from chipcompiler.utility import json_read

        flow_data = json_read(flow_path)
        step_names = [
            step["name"]
            for step in flow_data.get("steps", [])
            if isinstance(step, dict) and step.get("name")
        ]
        if step_names:
            from ..workspace_config import WorkspaceFlowTargetError, validate_flow_config

            try:
                flow_section = validate_flow_config({"start": step_names[0], "end": step_names[-1]})
            except WorkspaceFlowTargetError:
                flow_section = {}
    if not save_workspace_config(workspace_dir, normalized, flow_section or None):
        logging.getLogger(__name__).warning(
            "legacy parameters migration deferred (rewrite failed): %s", legacy_path
        )
        return
    try:
        load_workspace_config(workspace_dir)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "legacy parameters migration deferred (verify failed): %s: %s", config_path, exc
        )
        return
    legacy_path.unlink(missing_ok=True)


def load_workspace(directory: str | Path) -> Workspace:
    workspace_dir = Path(directory).expanduser().resolve()
    origin_dir = workspace_dir / "origin"
    home_dir = workspace_dir / "home"
    if not workspace_dir.exists():
        return None

    _migrate_legacy_parameters_file(workspace_dir)

    # create workspace instance
    workspace = Workspace()
    workspace.directory = workspace_dir
    migrate_workspace_config_filenames(workspace_dir)
    workspace.config = build_workspace_config_paths(workspace)

    parameters = load_parameter(home_dir / "ecc.toml")
    config_path = home_dir / "ecc.toml"
    legacy_path = home_dir / "parameters.json"
    if len(parameters.data) <= 0 and not config_path.exists() and legacy_path.exists():
        # Migration was deferred (e.g. read-only dir): fall back to the
        # normalized in-memory copy so the workspace still opens. When the
        # TOML exists it wins unconditionally — a malformed config never
        # silently falls back to stale JSON.
        from chipcompiler.utility import json_read

        from ..parameter_keys import normalize_parameter_dict

        fallback = normalize_parameter_dict(json_read(legacy_path))
        if fallback:
            parameters.data = fallback
    if len(parameters.data) <= 0:
        return None

    workspace.parameters = parameters

    pdk = get_pdk(
        pdk_name=parameters.data.get("pdk", ""),
        pdk_root=parameters.data.get("pdk_root", ""),
        pdk_config=parameters.data.get("pdk_config", ""),
    )
    sdc_path = list(origin_dir.rglob("*.sdc"))
    if len(sdc_path) > 0:
        pdk.sdc = sdc_path[0]
    spef_path = list(origin_dir.rglob("*.spef"))
    if len(spef_path) > 0:
        pdk.spef = spef_path[0]

    # update lef and lib paths based on config
    from chipcompiler.utility import json_read

    db_json = json_read(workspace.config.get("db", ""))
    if db_json.get("INPUT", {}).get("tech_lef_path", "") != "":
        pdk.tech = Path(db_json.get("INPUT", {}).get("tech_lef_path", ""))
    if db_json.get("INPUT", {}).get("lef_paths", []) != []:
        pdk.lefs = [Path(path) for path in db_json.get("INPUT", {}).get("lef_paths", [])]
    if db_json.get("INPUT", {}).get("lib_path", []) != []:
        pdk.libs = [Path(path) for path in db_json.get("INPUT", {}).get("lib_path", [])]
    workspace.pdk = pdk

    # update config
    workspace.design.name = parameters.data.get("design", "")
    workspace.design.top_module = parameters.data.get("top_module", "")
    def_path = list(origin_dir.rglob("*.def"))
    def_gz_path = list(origin_dir.rglob("*.def.gz"))
    if len(def_path) > 0:
        workspace.design.origin_def = def_path[0]
    if len(def_gz_path) > 0:
        workspace.design.origin_def = def_gz_path[0]

    verilog_path = list(origin_dir.rglob("*.v"))
    verilog_gz_path = list(origin_dir.rglob("*.v.gz"))
    if len(verilog_path) > 0:
        workspace.design.origin_verilog = verilog_path[0]
    if len(verilog_gz_path) > 0:
        workspace.design.origin_verilog = verilog_gz_path[0]

    filelist_path = origin_dir / "filelist"
    if filelist_path.exists():
        workspace.design.input_filelist = filelist_path

    # set home data
    home_dir.mkdir(parents=True, exist_ok=True)
    workspace.config["dir"].mkdir(parents=True, exist_ok=True)
    workspace.flow.path = home_dir / "flow.json"
    workspace.home.init(path=home_dir / "home.json")
    workspace.home.set_flow(workspace.flow.path)
    workspace.home.set_checklist(home_dir / "checklist.json")
    workspace.home.set_parameters(workspace.parameters.path)

    # create logger first (needed for copy operations)
    workspace.logger = create_logger(name=parameters.data["design"], log_dir=workspace_dir / "log")

    log_workspace(workspace)
    log_parameters(workspace)

    return workspace


def log_workspace(workspace: Workspace):
    def format_string(text: str, len=20) -> str:
        return text.ljust(len, " ")

    workspace.logger.log_section("workspace info")
    workspace.logger.info("workspace      : %s", workspace.directory)
    workspace.logger.info("config         : %s", workspace.config.get("dir", ""))
    workspace.logger.info("PDK            : %s", workspace.pdk.name)
    workspace.logger.info("design         : %s", workspace.design.name)
    workspace.logger.info("top module     : %s", workspace.design.top_module)
    workspace.logger.info("origin def     : %s", workspace.design.origin_def)
    workspace.logger.info("origin verilog : %s", workspace.design.origin_verilog)
    workspace.logger.info("input filelist : %s", workspace.design.input_filelist)
    workspace.logger.info("sdc            : %s", workspace.pdk.sdc)
    workspace.logger.info("spef           : %s", workspace.pdk.spef)


def log_parameters(workspace: Workspace):
    workspace.logger.log_section("parameters info")
    workspace.logger.info("parameters     : %s", workspace.parameters.path)
    workspace.logger.info("\n%s", dict_to_str(workspace.parameters.data))


def log_flow(workspace: Workspace):
    def format_string(text: str, len=20) -> str:
        return text.ljust(len, " ")

    workspace.logger.log_section("flow info")
    workspace.logger.info("flow           : %s", workspace.flow.path)
    workspace.logger.info(
        "%s | %s | %s | %s",
        format_string("name"),
        format_string("tool"),
        format_string("state"),
        format_string("runtime"),
    )
    for step in workspace.flow.data.get("steps", []):
        workspace.logger.info(
            "%s | %s | %s | %s",
            format_string(step.get("name", "")),
            format_string(step.get("tool", "")),
            format_string(step.get("state", "")),
            format_string(step.get("runtime", "")),
        )


def create_default_sdc(workspace: Workspace):
    """
    Create SDC file based on PDK and workspace parameters.
    """
    sdc_content = []
    sdc_content.append("# Auto-generated SDC file\n")
    sdc_content.append("\n")
    sdc_content.append("set clk_name {} \n".format(workspace.parameters.data.get("clock", "")))
    sdc_content.append("set clk_port_name {}\n".format(workspace.parameters.data.get("clock", "")))
    sdc_content.append(
        "set clk_freq_mhz {}\n".format(workspace.parameters.data.get("frequency_max", 100))
    )
    sdc_content.append("set clk_period [expr 1000.0 / $clk_freq_mhz]\n")
    sdc_content.append("set clk_io_pct 0.2\n")
    sdc_content.append("set clk_port [get_ports $clk_port_name]\n")
    sdc_content.append("create_clock -name $clk_name -period $clk_period $clk_port\n")

    with open(workspace.pdk.sdc, "w") as file:
        file.writelines(sdc_content)
