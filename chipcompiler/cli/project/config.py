import logging
import os
import tomllib
from dataclasses import dataclass, field

from chipcompiler.utility.filelist import FILELIST_SUFFIXES, RTL_SUFFIXES

SUPPORTED_PDK_NAMES = {"ics55"}


class InvalidFlowRun:
    """config_run_id result for a [flow] run value that cannot name a run directory."""

    def __init__(self, problem: str) -> None:
        self.problem = problem


def _flow_run_problem(value: object) -> str | None:
    """Return the rejection reason for a present [flow] run value, or None."""
    if isinstance(value, str):
        if value == "default":
            return None
        if value and value == value.strip() and "\x00" not in value:
            return None
    return f"unsupported flow.run: {value}"


# TODO: Move ecc.toml parsing and validation into chipcompiler.data.project_config
# as EccTomlConfig; then delete this module or keep only thin CLI glue here.
@dataclass
class ProjectConfig:
    design_name: str = ""
    design_top: str = ""
    design_rtl: list[str] = field(default_factory=list)
    design_clock_port: str = ""
    design_frequency_mhz: float = 0.0

    pdk_name: str = ""
    pdk_root: str = ""
    pdk_overrides: dict[str, object] = field(default_factory=dict)

    flow_preset: str = ""
    flow_run: str = ""

    config_path: str = ""
    project_dir: str = ""

    params_overrides: dict[str, object] = field(default_factory=dict)

    _toml_error: str | None = field(default=None, init=False, repr=False)
    _param_errors: list[str] = field(default_factory=list, init=False, repr=False)
    _pdk_config_errors: list[str] = field(default_factory=list, init=False, repr=False)
    _flow_run_error: str | None = field(default=None, init=False, repr=False)


def load_project_config(config_path: str) -> ProjectConfig:
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        cfg = ProjectConfig(config_path=config_path)
        cfg._toml_error = str(exc)
        return cfg
    return _parse_config(data, config_path)


def _parse_config(data: dict, config_path: str) -> ProjectConfig:
    design = data.get("design", {})
    pdk = data.get("pdk", {})
    flow = data.get("flow", {})

    if not isinstance(design, dict):
        design = {}
    if not isinstance(pdk, dict):
        pdk = {}
    if not isinstance(flow, dict):
        flow = {}

    project_dir = os.path.dirname(os.path.abspath(config_path))

    try:
        freq = float(design.get("frequency_mhz", 0))
    except (TypeError, ValueError):
        freq = 0.0

    rtl_raw = design.get("rtl", [])
    if not isinstance(rtl_raw, list):
        rtl_raw = []
    design_rtl = [v for v in rtl_raw if isinstance(v, str)]

    def _str(val, default=""):
        return val if isinstance(val, str) else default

    pdk_overrides_raw = pdk.get("overrides", {})
    pdk_overrides = {} if not isinstance(pdk_overrides_raw, dict) else pdk_overrides_raw

    raw_run = flow.get("run", "default")

    cfg = ProjectConfig(
        design_name=_str(design.get("name", "")),
        design_top=_str(design.get("top", "")),
        design_rtl=design_rtl,
        design_clock_port=_str(design.get("clock_port", "")),
        design_frequency_mhz=freq,
        pdk_name=_str(pdk.get("name", "")),
        pdk_root=_str(pdk.get("root", "")),
        pdk_overrides=pdk_overrides,
        flow_preset=_str(flow.get("preset", "")),
        flow_run=_str(raw_run, "default"),
        config_path=config_path,
        project_dir=project_dir,
    )

    cfg._flow_run_error = _flow_run_problem(raw_run)

    if not isinstance(pdk_overrides_raw, dict):
        cfg._pdk_config_errors = [
            "[pdk.overrides] must be a table (mapping), not " + type(pdk_overrides_raw).__name__
        ]

    params_raw = data.get("params")
    if isinstance(params_raw, dict):
        from chipcompiler.cli.project.params import parse_toml_params

        flat, param_errors = parse_toml_params(params_raw)
        cfg.params_overrides = resolve_path_params(flat, project_dir)
        if param_errors:
            cfg._param_errors = param_errors

    return cfg


def resolve_project_dir(project: str | None) -> str:
    if project:
        return os.path.abspath(project)
    return os.getcwd()


def find_config_path(project_dir: str) -> str | None:
    path = os.path.join(project_dir, "ecc.toml")
    return path if os.path.isfile(path) else None


def load_run_config(project_dir: str) -> ProjectConfig | None:
    """Parse the project's ecc.toml; None when it is missing or unreadable."""
    config_path = find_config_path(project_dir)
    if config_path is None:
        return None
    try:
        return load_project_config(config_path)
    except (OSError, UnicodeDecodeError):
        return None


def config_run_id_from(cfg: ProjectConfig | None) -> str | InvalidFlowRun | None:
    """Apply the canonical [flow] run rule to an already-parsed config."""
    if cfg is None or cfg._toml_error:
        return None
    if cfg._flow_run_error is not None:
        return InvalidFlowRun(cfg._flow_run_error)
    if cfg.flow_run == "default":
        return None
    return cfg.flow_run


def config_run_id(project_dir: str) -> str | InvalidFlowRun | None:
    """Return the [flow] run id configured in the project's ecc.toml.

    None when the key is absent, is "default", or the config cannot be read;
    InvalidFlowRun when the key is present but cannot name a run directory;
    otherwise the run id string.
    """
    return config_run_id_from(load_run_config(project_dir))


def _supported_flow_presets() -> set[str]:
    from chipcompiler import rtl2gds as rtl2gds_api

    return set(rtl2gds_api.get_flow_builders())


def validate_project_config(
    cfg: ProjectConfig, skip_path_params: set[str] | None = None
) -> list[str]:
    """Validate ecc.toml; skip_path_params names CLI-replaced params exempt from path checks."""
    if cfg._toml_error:
        return [f"malformed ecc.toml: {cfg._toml_error}"]

    errors = []

    for pe in cfg._pdk_config_errors:
        errors.append(f"invalid PDK configuration: {pe}")

    for pe in cfg._param_errors:
        errors.append(f"invalid params: {pe}")

    skipped = skip_path_params or set()
    effective_paths = {k: v for k, v in cfg.params_overrides.items() if k not in skipped}
    errors.extend(path_param_errors(effective_paths))

    if not cfg.design_name:
        errors.append("design.name is required")
    if not cfg.design_top:
        errors.append("design.top is required")
    if not cfg.design_clock_port:
        errors.append("design.clock_port is required")
    if cfg.design_frequency_mhz <= 0:
        errors.append("design.frequency_mhz must be greater than 0")
    if not cfg.design_rtl:
        errors.append("design.rtl must have at least one entry")
    elif len(cfg.design_rtl) > 1:
        errors.append("design.rtl must have exactly one entry; use a filelist for multiple sources")

    if not cfg.pdk_name:
        errors.append("pdk.name is required")
    elif cfg.pdk_name not in SUPPORTED_PDK_NAMES:
        errors.append(f"unsupported pdk.name: {cfg.pdk_name}")

    pdk_root = _resolve_pdk_root(cfg)
    if pdk_root:
        if not os.path.isdir(pdk_root):
            errors.append(f"pdk.root is not a directory: {cfg.pdk_root or '$(env)'}")
        else:
            pdk_err = _validate_pdk_contents(cfg.pdk_name, pdk_root, resolve_pdk_overrides(cfg))
            if pdk_err:
                errors.append(pdk_err)
    else:
        errors.append("pdk.root is required")

    if not cfg.flow_preset:
        errors.append("flow.preset is required")
    elif cfg.flow_preset not in _supported_flow_presets():
        errors.append(f"unsupported flow.preset: {cfg.flow_preset}")

    if cfg._flow_run_error:
        errors.append(cfg._flow_run_error)

    if len(cfg.design_rtl) == 1:
        rtl_path = _resolve_path(cfg.project_dir, cfg.design_rtl[0])
        if not os.path.exists(rtl_path):
            errors.append(f"rtl path does not exist: {cfg.design_rtl[0]}")
        elif os.path.isdir(rtl_path):
            errors.append(f"rtl path must be a file, not a directory: {cfg.design_rtl[0]}")
        else:
            suffix = os.path.splitext(rtl_path)[1].lower()
            if suffix in FILELIST_SUFFIXES:
                from chipcompiler.utility.filelist import validate_filelist

                try:
                    _, missing = validate_filelist(rtl_path)
                    if missing:
                        errors.append(f"filelist references missing files: {', '.join(missing)}")
                except (ValueError, OSError) as e:
                    errors.append(f"invalid filelist {cfg.design_rtl[0]}: {e}")

    return errors


def to_parameters(cfg: ProjectConfig) -> dict:
    return {
        "PDK": cfg.pdk_name,
        "Design": cfg.design_name,
        "Top module": cfg.design_top,
        "Clock": cfg.design_clock_port,
        "Frequency max [MHz]": cfg.design_frequency_mhz,
    }


def resolve_rtl(cfg: ProjectConfig) -> tuple[str, str, str]:
    if not cfg.design_rtl:
        return ("", "", "")

    rtl_path = _resolve_path(cfg.project_dir, cfg.design_rtl[0])
    suffix = os.path.splitext(rtl_path)[1].lower()

    if suffix in FILELIST_SUFFIXES:
        return ("filelist", "", rtl_path)
    if suffix in RTL_SUFFIXES:
        return ("rtl", rtl_path, "")

    if os.path.isfile(rtl_path):
        try:
            from chipcompiler.utility.filelist import parse_filelist, validate_filelist

            parse_filelist(rtl_path)
            _, missing = validate_filelist(rtl_path)
            if not missing:
                return ("filelist", "", rtl_path)
        except (OSError, ValueError) as e:
            logging.debug("File %s is not a valid filelist: %s", rtl_path, e)

    return ("rtl", rtl_path, "")


def _resolve_path(project_dir: str, path: str) -> str:
    path = os.path.expandvars(os.path.expanduser(path))
    if os.path.isabs(path):
        return path
    return os.path.join(project_dir, path)


def resolve_path_params(flat: dict[str, object], base_dir: str) -> dict[str, object]:
    """Resolve relative values of path-type params against base_dir."""
    from chipcompiler.cli.project.params import lookup_schema

    resolved = dict(flat)
    for key, value in resolved.items():
        schema = lookup_schema(key)
        if schema and schema.type == "path" and isinstance(value, str) and value:
            resolved[key] = _resolve_path(base_dir, value)
    return resolved


def path_param_errors(flat: dict[str, object]) -> list[str]:
    """Return an error for each path-type param value that is not an existing file."""
    from chipcompiler.cli.project.params import lookup_schema

    errors = []
    for key, value in flat.items():
        schema = lookup_schema(key)
        if (
            schema
            and schema.type == "path"
            and isinstance(value, str)
            and value
            and not os.path.isfile(value)
        ):
            errors.append(f"{key} path does not exist: {value}")
    return errors


def resolve_pdk_root(cfg: ProjectConfig) -> str:
    return _resolve_pdk_root(cfg)


def _resolve_pdk_root(cfg: ProjectConfig) -> str:
    if not cfg.pdk_root:
        return _pdk_root_from_env()
    return _resolve_path(cfg.project_dir, cfg.pdk_root)


def resolve_pdk_overrides(cfg: ProjectConfig) -> dict[str, object]:
    """Return pdk_overrides with path-field values resolved to absolute paths.

    PDK-content paths (PDK_CONTENT_PATH_FIELDS) resolve against the PDK root;
    design-data paths (sdc/spef) resolve against the project dir. Non-path
    values such as dont_use glob patterns pass through untouched.
    """
    from chipcompiler.data.pdk import PATH_LIST_FIELDS, PATH_SCALAR_FIELDS, PDK_CONTENT_PATH_FIELDS

    resolved = dict(cfg.pdk_overrides)
    pdk_root = _resolve_pdk_root(cfg)
    for key, value in resolved.items():
        base = pdk_root if key in PDK_CONTENT_PATH_FIELDS else cfg.project_dir
        if key in PATH_SCALAR_FIELDS and isinstance(value, str):
            resolved[key] = _resolve_path(base, value)
        elif key in PATH_LIST_FIELDS and isinstance(value, list):
            resolved[key] = [
                _resolve_path(base, element) if isinstance(element, str) else element
                for element in value
            ]
    return resolved


def _validate_pdk_contents(
    pdk_name: str, pdk_root: str, pdk_overrides: dict | None = None
) -> str | None:
    if not pdk_root:
        return None
    try:
        from chipcompiler.data.pdk import get_pdk

        get_pdk(pdk_name, pdk_root, overrides=pdk_overrides)
        return None
    except ValueError as exc:
        return str(exc)


def _pdk_root_from_env() -> str:
    for key in ("CHIPCOMPILER_ICS55_PDK_ROOT", "ICS55_PDK_ROOT"):
        val = os.environ.get(key, "").strip()
        if not val:
            continue
        # Absolute: the value becomes the join base for serialized override
        # paths consumed from step working directories.
        val = os.path.abspath(val)
        if os.path.isdir(val):
            return val
    return ""
