"""Staging of schema-declared snapshot params into a run workspace.

Params whose schema declares `snapshot` name a design input file. At run
creation the file is copied into `<run>/scripts/` under the declared name and
the workspace parameters record the workspace-relative path, so
`ecc run --workspace` resumes do not depend on the original file or on the
run directory's absolute location.
"""

import os
from dataclasses import dataclass, field

from chipcompiler.cli.project.params import lookup_schema


@dataclass(frozen=True)
class SnapshotPlan:
    files: dict[str, tuple[str, bytes]] = field(default_factory=dict)
    # param key -> (absolute snapshot target, file content)
    overrides: dict[str, str] = field(default_factory=dict)
    # param key -> workspace-relative snapshot path recorded in parameters


def plan_snapshots(overrides: dict[str, object], run_dir: str) -> tuple[SnapshotPlan, list[str]]:
    """Read declared snapshot files and plan their workspace copies."""
    files: dict[str, tuple[str, bytes]] = {}
    planned_overrides: dict[str, str] = {}
    errors: list[str] = []
    for key, value in overrides.items():
        schema = lookup_schema(key)
        if schema is None or schema.snapshot is None:
            continue
        if not (isinstance(value, str) and value):
            continue
        try:
            with open(value, "rb") as f:
                content = f.read()
        except OSError as exc:
            errors.append(f"cannot read {key} path {value}: {exc}")
            continue
        relative = os.path.join("scripts", schema.snapshot)
        files[key] = (os.path.join(run_dir, relative), content)
        planned_overrides[key] = relative
    return SnapshotPlan(files=files, overrides=planned_overrides), errors


def write_snapshots(plan: SnapshotPlan) -> None:
    """Materialize planned snapshots; raises OSError on failure."""
    for target, content in plan.files.values():
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(content)
