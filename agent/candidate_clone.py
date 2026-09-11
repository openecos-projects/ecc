import json
from pathlib import Path

from chipcompiler.runtime.workspace_api import RuntimeApiError

_ARTIFACT_DIR_NAMES = frozenset({"output", "data", "feature", "analysis", "report", "log"})


def candidate_clone_ignore(source_root: Path, target_step: str | None):
    skipped_step_roots: set[Path] = set()
    if target_step is not None:
        try:
            flow = json.loads((source_root / "home" / "flow.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeApiError("command_failed", "candidate flow state is invalid") from exc
        if not isinstance(flow, dict) or not isinstance(flow.get("steps"), list):
            raise RuntimeApiError("command_failed", "candidate flow state is invalid")
        rerun = False
        for step in flow.get("steps", []):
            if not isinstance(step, dict):
                continue
            name, tool = step.get("name"), step.get("tool")
            rerun = rerun or name == target_step
            if rerun and isinstance(name, str) and isinstance(tool, str):
                skipped_step_roots.add(source_root / f"{name}_{tool}")
                skipped_step_roots.add(source_root / f"{'_'.join(name.split()).lower()}_{tool}")

    def ignore(directory, names):
        current = Path(directory).resolve()
        if current == source_root:
            return {".agent"}.intersection(names)
        if current in skipped_step_roots:
            return _ARTIFACT_DIR_NAMES.intersection(names)
        return set()

    return ignore
