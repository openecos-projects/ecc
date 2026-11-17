"""Freeze completion-only artifacts belonging to the current capture attempt."""

import json
import shutil
from pathlib import Path

from chipcompiler.tools.replay_analysis import collect_analysis
from chipcompiler.tools.replay_artifacts import reference_geometry
from chipcompiler.tools.replay_storage import within


def current_metrics(step, started_unix_ns: int) -> list:
    path = getattr(getattr(step, "analysis", None), "qor_metrics", None)
    if not path or not Path(path).is_file() or Path(path).stat().st_mtime_ns < started_unix_ns:
        return []
    # Runtime entries may still belong to the previous attempt at tool completion.
    return [
        metric
        for metric in json.loads(Path(path).read_text()).get("metrics", [])
        if metric.get("category") != "runtime"
    ]


def completion_checklist(
    workspace, step, started_unix_ns: int, *, freshly_written: bool = False
) -> dict:
    path = getattr(getattr(step, "checklist", None), "path", None)
    if (
        not path
        or not Path(path).is_file()
        or (not freshly_written and Path(path).stat().st_mtime_ns < started_unix_ns)
    ):
        return {
            "status": "unavailable",
            "checklist": [],
            "reason": "No checklist produced for this attempt",
        }
    document = json.loads(within(Path(workspace.directory), Path(path)).read_text())
    document["checklist"] = [
        item
        for item in document.get("checklist", [])
        if not item.get("step") or item["step"] == step.name
    ]
    return document


def collect_results(step, directory: Path, started_unix_ns: int, workspace_dir=None) -> dict:
    metrics = current_metrics(step, started_unix_ns)
    result: dict[str, object] = {"result_metrics": metrics}
    result.update(collect_analysis(step, directory, started_unix_ns))
    if step.name in {"lec", "postRouteLec"}:
        output_json = getattr(getattr(step, "output", None), "json", None)
        if (
            output_json
            and Path(output_json).is_file()
            and Path(output_json).stat().st_mtime_ns >= started_unix_ns
        ):
            try:
                verdict = json.loads(Path(output_json).read_text()).get("status", "unknown")
            except (OSError, ValueError):
                verdict = "unavailable"
            metrics.append({"id": "equivalence", "display_name": "Equivalence", "value": verdict})
    feature = getattr(getattr(step, "feature", None), "dir", None)
    if feature:
        frozen_features = []
        for suffix in ("db.json", "step.json"):
            source = Path(feature) / f"{step.name}.{suffix}"
            if source.is_file() and source.stat().st_mtime_ns >= started_unix_ns:
                if workspace_dir:
                    source = within(Path(workspace_dir), source)
                if source.stat().st_size > 16 * 1024 * 1024:
                    continue
                relative = f"subflows/results/features/{suffix}"
                target = directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                frozen_features.append(relative)
        if frozen_features:
            result["result_feature_files"] = frozen_features
    if workspace_dir:
        geometry_manifest = getattr(getattr(step, "output", None), "geometry_manifest", None)
        if geometry_manifest:
            manifest_path = Path(geometry_manifest)
            workspace_path = Path(workspace_dir).resolve()
            try:
                resolved = manifest_path.resolve()
                if resolved.is_file() and resolved.stat().st_mtime_ns >= started_unix_ns:
                    within(workspace_path, resolved)
                    result.update(reference_geometry(resolved))
            except (OSError, ValueError) as error:
                result["geometry_unavailable"] = str(error)
    if step.name != "place" or not feature:
        return result
    manifest = getattr(getattr(step, "output", None), "geometry_manifest", None)
    if (
        manifest
        and Path(manifest).is_file()
        and any(line.startswith("display.") for line in Path(manifest).read_text().splitlines())
    ):
        return result
    # Existing map CSVs carry a layout.csv with explicit DBU rectangles. Never
    # infer grid coordinates from the image size or reuse stale maps on rerun.
    relative = "subflows/run-placement/overlays/maps"
    copied = False
    for category in sorted(Path(feature).glob("*_map")):
        layout = category / "layout.csv"
        if not layout.is_file() or layout.stat().st_mtime_ns < started_unix_ns:
            continue
        for path in category.glob("*.csv"):
            if path.is_file() and path.stat().st_mtime_ns >= started_unix_ns:
                target = directory / relative / category.name / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                copied = True
    if copied:
        result["maps"] = relative
    return result
