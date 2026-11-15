"""Create an RTL project on another PDK without inheriting physical results."""

import json
import shutil
import tempfile
from pathlib import Path

import tomli_w

from chipcompiler.cli.project.config import load_project_config
from chipcompiler.cli.project.project_init import (
    _fsync_directory,
    _populate,
    _publish_without_renameat2,
)
from chipcompiler.cli.project.rtl_import import import_project_rtl
from chipcompiler.utility.filelist import FILELIST_SUFFIXES
from chipcompiler.utility.workspace_lock import workspace_lock

from .manifest import DescriptorError
from .project_defaults import selected_pdk


def clone_with_pdk(source: Path, target: Path, root: Path) -> Path:
    source = source.expanduser().resolve(strict=True)
    target = target.expanduser().resolve()
    if target == source or target.is_relative_to(source):
        raise DescriptorError("invalid_target", "new project must be outside the source project")
    selected = selected_pdk(str(root), "ecc")
    target.parent.mkdir(parents=True, exist_ok=True)
    with workspace_lock(source), workspace_lock(target):
        if target.exists():
            raise DescriptorError("already_exists", "clone target must not exist")
        cfg = load_project_config(str(source / "ecc.toml"))
        if cfg is None or not cfg.design_rtl:
            raise DescriptorError(
                "rtl_required", "clone-with-pdk requires a project with RTL inputs"
            )
        inputs = [str((source / path).resolve()) for path in cfg.design_rtl]
        filelists = [path for path in inputs if Path(path).suffix in FILELIST_SUFFIXES]
        if filelists and (len(filelists) != 1 or len(inputs) != 1):
            raise DescriptorError("unsupported_inputs", "use one filelist or a list of RTL sources")
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
        try:
            _populate(staging, target, target.name, cfg.design_name, None, selected)
            import_project_rtl(
                str(staging),
                filelist=filelists[0] if filelists else None,
                verilog=tuple(inputs) if not filelists else (),
            )
            import tomllib

            config = tomllib.loads((staging / "ecc.toml").read_text())
            config["design"].update(
                top=cfg.design_top,
                clock_port=cfg.design_clock_port,
                frequency_mhz=cfg.design_frequency_mhz,
            )
            config["params"]["sdc"]["clock_list"] = ""
            if cfg.design_sdc:
                sdc = (source / cfg.design_sdc).resolve(strict=True)
                destination = staging / "constraints" / sdc.name
                destination.parent.mkdir(exist_ok=True)
                shutil.copyfile(sdc, destination)
                config["design"]["sdc"] = destination.relative_to(staging).as_posix()
            (staging / "ecc.toml").write_text(tomli_w.dumps(config))
            manifest_path = staging / "project.json"
            manifest = json.loads(manifest_path.read_text())
            base = manifest["base_design"]
            base.update(top_module=cfg.design_top, clock=cfg.design_clock_port)
            base["parameters"].update(
                top_module=cfg.design_top,
                clock=cfg.design_clock_port,
                frequency_max=cfg.design_frequency_mhz,
            )
            if cfg.design_sdc:
                base["sdc"] = str(target / config["design"]["sdc"])
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

            provenance = {"source_project": str(source), "copied": "RTL and design constraints"}
            (staging / "clone-source.json").write_text(json.dumps(provenance, indent=2) + "\n")
            _publish_without_renameat2(staging, target, None)
            _fsync_directory(target.parent)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return target.resolve()
