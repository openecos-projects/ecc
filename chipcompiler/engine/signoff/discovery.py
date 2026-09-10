"""Artifact discovery and workspace-read helpers for the signoff collector.

Split from the collector core: these mixin methods locate per-step
artifacts, read workspace configuration, and resolve step state
contracts. Shared through composition, so ``self`` is the composed
``SignoffPackageCollector``.
"""

import json
from pathlib import Path

from chipcompiler.data import StepEnum


class CollectorDiscoveryMixin:
    def _read_json(self, path: Path) -> dict:
        try:
            with open(path, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _read_parameters(self, path: Path) -> dict:
        """Read the workspace configuration's [params] section; {} when unreadable."""
        import tomllib

        try:
            with open(path, "rb") as file:
                data = tomllib.load(file)
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            return {}
        params = data.get("params", {})
        return params if isinstance(params, dict) else {}

    def _path_from_config(self, workspace_dir: Path, path_text: str) -> Path | None:
        if not path_text:
            return None
        path = Path(path_text)
        if not path.is_absolute():
            path = workspace_dir / path
        return path if path.is_file() else None

    def _source_path(self, workspace_dir: Path, source: Path) -> str:
        try:
            return source.relative_to(workspace_dir).as_posix()
        except ValueError:
            return str(source)

    def _review_source_path(
        self,
        workspace_dir: Path,
        source: Path | None,
        fallback: str,
    ) -> str:
        if source is None:
            return fallback
        try:
            return source.relative_to(workspace_dir).as_posix()
        except ValueError:
            return source.name

    def _find_one(
        self,
        directory: Path,
        preferred_name: str,
        pattern: str,
    ) -> tuple[Path | None, str]:
        preferred = directory / preferred_name
        if preferred.is_file():
            return preferred, ""
        matches = sorted(directory.glob(pattern)) if directory.is_dir() else []
        if len(matches) == 1:
            return matches[0], ""
        if len(matches) > 1:
            return None, "Multiple matching files found"
        return None, "Required file is missing or empty"

    def _design_from_outputs(self, workspace_dir: Path) -> str:
        for pattern, suffix in (
            ("Harden_ecc/output/*_Harden.gds", "_Harden.gds"),
            ("filler_ecc/output/*_filler.v.gz", "_filler.v.gz"),
        ):
            matches = sorted(workspace_dir.glob(pattern))
            if matches:
                name = matches[0].name
                if name.endswith(suffix):
                    return name[: -len(suffix)]
        return ""

    def _synthesis_output_verilog(self) -> Path | None:
        """Resolve the netlist from the Yosys step's declared output contract."""
        synthesis_step = self._build_workspace_step(
            {"name": StepEnum.SYNTHESIS.value, "tool": "yosys"},
            previous_step=None,
        )
        output = getattr(synthesis_step, "output", None)
        verilog = getattr(output, "verilog", None)
        return Path(verilog) if verilog else None

    def _required_step_states(self, *, require_lec: bool) -> dict:
        required = [
            StepEnum.HARDEN.value,
            StepEnum.RCX.value,
            StepEnum.STA.value,
            StepEnum.DRC.value,
            StepEnum.LVS.value,
            StepEnum.FILLER.value,
            StepEnum.ROUTING.value,
        ]
        if require_lec:
            required.append(StepEnum.POST_ROUTE_LEC.value)
        states = {}
        for step in required:
            entry = self.workspace.flow.get_step(step)
            states[step] = entry.get("state", "") if entry else ""
        return states

    def _requires_post_route_lec(
        self,
        golden_verilog: Path | None,
        gate_verilog: Path | None,
    ) -> bool:
        if golden_verilog is None or not Path(golden_verilog).is_file():
            return False
        return bool(gate_verilog and Path(gate_verilog).is_file())
