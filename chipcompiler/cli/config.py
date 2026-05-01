import os
import tomllib
from dataclasses import dataclass, field

SUPPORTED_PDK_NAMES = {"ics55"}
SUPPORTED_FLOW_PRESETS = {"rtl2gds"}
SUPPORTED_FLOW_RUNS = {"default"}


@dataclass
class ProjectConfig:
    design_name: str = ""
    design_top: str = ""
    design_rtl: list[str] = field(default_factory=list)
    design_clock_port: str = ""
    design_frequency_mhz: float = 0.0

    pdk_name: str = ""
    pdk_root: str = ""

    flow_preset: str = ""
    flow_run: str = ""

    config_path: str = ""
    project_dir: str = ""


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

    cfg = ProjectConfig(
        design_name=design.get("name", ""),
        design_top=design.get("top", ""),
        design_rtl=design_rtl,
        design_clock_port=design.get("clock_port", ""),
        design_frequency_mhz=freq,
        pdk_name=pdk.get("name", ""),
        pdk_root=pdk.get("root", ""),
        flow_preset=flow.get("preset", ""),
        flow_run=flow.get("run", "default"),
        config_path=config_path,
        project_dir=project_dir,
    )
    return cfg


def resolve_project_dir(project: str | None) -> str:
    if project:
        return os.path.abspath(project)
    return os.getcwd()


def find_config_path(project_dir: str) -> str | None:
    path = os.path.join(project_dir, "ecc.toml")
    return path if os.path.isfile(path) else None


def validate_project_config(cfg: ProjectConfig) -> list[str]:
    toml_error = getattr(cfg, "_toml_error", None)
    if toml_error:
        return [f"malformed ecc.toml: {toml_error}"]

    errors = []

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

    if cfg.pdk_root:
        resolved_root = _resolve_path(cfg.project_dir, cfg.pdk_root)
        if not os.path.isdir(resolved_root):
            errors.append(f"pdk.root is not a directory: {cfg.pdk_root}")
    elif not _pdk_root_from_env():
        errors.append("pdk.root is required")

    if not cfg.flow_preset:
        errors.append("flow.preset is required")
    elif cfg.flow_preset not in SUPPORTED_FLOW_PRESETS:
        errors.append(f"unsupported flow.preset: {cfg.flow_preset}")

    if cfg.flow_run and cfg.flow_run not in SUPPORTED_FLOW_RUNS:
        errors.append(f"unsupported flow.run: {cfg.flow_run}")

    if len(cfg.design_rtl) == 1:
        rtl_path = _resolve_path(cfg.project_dir, cfg.design_rtl[0])
        if not os.path.exists(rtl_path):
            errors.append(f"rtl path does not exist: {cfg.design_rtl[0]}")
        elif os.path.isdir(rtl_path):
            errors.append(f"rtl path must be a file, not a directory: {cfg.design_rtl[0]}")

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

    FILELIST_SUFFIXES = {".f", ".fl", ".filelist"}
    RTL_SUFFIXES = {".v", ".sv", ".svh", ".vh"}

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
        except Exception:
            pass

    return ("rtl", rtl_path, "")


def _resolve_path(project_dir: str, path: str) -> str:
    path = os.path.expandvars(os.path.expanduser(path))
    if os.path.isabs(path):
        return path
    return os.path.join(project_dir, path)


def resolve_pdk_root(cfg: ProjectConfig) -> str:
    if not cfg.pdk_root:
        return _pdk_root_from_env()
    return _resolve_path(cfg.project_dir, cfg.pdk_root)


def _pdk_root_from_env() -> str:
    for key in ("CHIPCOMPILER_ICS55_PDK_ROOT", "ICS55_PDK_ROOT"):
        val = os.environ.get(key, "").strip()
        if not val:
            continue
        val = os.path.normpath(val)
        if os.path.isdir(val):
            return val
    return ""
