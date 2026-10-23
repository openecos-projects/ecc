from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from chipcompiler.cli.experiments.candidate_evidence import normalized_step_statuses
from chipcompiler.cli.inspection.evidence_summary import (
    checklist_items,
    checklist_status,
    flow_status,
    item_blocked,
    qor_score,
    step_status,
)
from chipcompiler.data import ADVISORY_FLOW_STEPS
from chipcompiler.project.manifest import CONFIG_FILENAME, MANIFEST_FILENAME

SCHEMA_VERSION = 1


def payload_fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_versions(project: Path) -> dict[str, Any]:
    versions: dict[str, Any] = {}
    command_line = (
        [sys.argv[0], "version", "--json"]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "chipcompiler.cli.main", "version", "--json"]
    )
    try:
        completed = subprocess.run(command_line, capture_output=True, text=True, check=False)
        payload = json.loads(completed.stdout)
        versions["ecc"] = str(payload.get("version", payload.get("ecc", "unknown")))
    except (OSError, json.JSONDecodeError):
        versions["ecc"] = "unknown"
    try:
        from chipcompiler.cli.core.version_info import version_payload
        from chipcompiler.cli.inspection.tool_versions import tool_versions

        versions.update(
            {
                key: str(value)
                for key, value in version_payload().items()
                if key in {"ecc", "dreamplace", "ecc_tools"}
            }
        )
        versions["tools"] = tool_versions()
    except (ImportError, OSError):
        versions["tools"] = {}
    config_path = project / CONFIG_FILENAME
    try:
        config = tomllib.loads(config_path.read_text())
        pdk = config.get("pdk", {})
        versions["pdk"] = {"name": pdk.get("name", "unknown"), "root": pdk.get("root", "unknown")}
        if pdk.get("root"):
            versions["pdk"]["root_exists"] = Path(pdk["root"]).is_dir()
    except (OSError, tomllib.TOMLDecodeError):
        versions["pdk"] = {"name": "unknown", "root": "unknown", "root_exists": False}
    return versions


def project_path(value: str | None) -> Path:
    path = Path(value or os.getcwd()).expanduser().resolve()
    if path.is_file():
        path = path.parent
    for candidate in (path, *path.parents):
        if (candidate / MANIFEST_FILENAME).exists() or (candidate / CONFIG_FILENAME).exists():
            return candidate
    return path


def diagnose_workspace(project: Path, workspace_name: str) -> dict[str, Any]:
    workspace = workspace_path(project, workspace_name)
    flow_value = load_json(workspace / "home" / "flow.json", {})
    checklist_value = load_json(workspace / "home" / "checklist.json", {})
    qor_value = load_json(workspace / "home" / "qor_report.json", {})
    flow = flow_value if isinstance(flow_value, dict) else {}
    checklist = checklist_value if isinstance(checklist_value, dict) else {}
    qor = qor_value if isinstance(qor_value, dict) else {}
    steps = flow.get("steps", [])
    failed_steps = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        state = step_status(step)
        if state not in {"failed", "blocked", "error", "incomplete", "invalid"}:
            continue
        if state == "incomplete" and step.get("name") in ADVISORY_FLOW_STEPS:
            continue
        failed_steps.append(step.get("name", step.get("id", "unknown")))
    flow_state = flow_status(flow)
    items = checklist_items(checklist)
    blocked_items = [item.get("id", "unknown") for item in items if item_blocked(item)]
    checks_state = checklist_status(checklist)
    score = qor_score(qor)
    missing = [
        str(path.relative_to(workspace))
        for path in (workspace / "home" / "flow.json", workspace / "home" / "checklist.json")
        if not path.is_file()
    ]
    status = (
        "failed"
        if failed_steps or flow_state == "failed"
        else "blocked"
        if blocked_items or checks_state == "blocked"
        else "attention"
        if missing or not qor or flow_state != "success" or checks_state != "passed"
        else "passed"
    )
    actions = []
    if failed_steps or blocked_items:
        actions.extend(
            [
                f"ecc report checklist --project {project} --workspace {workspace_name}",
                f"ecc run --project {project} --workspace {workspace_name} --resume",
            ]
        )
    return {
        "status": status,
        "project": str(project),
        "workspace": str(workspace),
        "flow": {
            "status": flow_state,
            "failed_steps": failed_steps,
        },
        "checklist": {
            "status": checks_state,
            "blocked_count": len(blocked_items),
            "blocked_items": blocked_items,
        },
        "qor": {
            "available": bool(qor),
            "score": score if score is not None else "unknown",
        },
        "missing_artifacts": missing,
        "next_actions": actions,
    }


def workspace_path(project: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project / value).resolve()


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def safe_relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def export_package(project: Path, workspace: Path, output: Path) -> dict[str, Any]:
    if not workspace.is_dir():
        raise ValueError(f"workspace does not exist: {workspace}")
    files: list[Path] = []
    roots = [project / MANIFEST_FILENAME, project / CONFIG_FILENAME]
    for relative in ("home", "config", "reports", "results"):
        candidate = workspace / relative
        if candidate.exists():
            roots.append(candidate)
    roots.extend(workspace.glob("*.json"))
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(item for item in root.rglob("*") if item.is_file())
    files = sorted(
        path for path in files if not any(part in {".git", "__pycache__"} for part in path.parts)
    )
    staging = output.parent / f".{output.stem}.staging-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    entries = []
    try:
        for source in files:
            relative = safe_relative(project, source)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            entries.append({"path": relative, "size": target.stat().st_size, "sha256": digest})
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "kind": "ecc-reproducible-export",
            "project": str(project),
            "workspace": str(workspace),
            "created_at": int(time.time()),
            "files": entries,
            "file_fingerprint": payload_fingerprint(entries),
            "runtime": runtime_versions(project),
            "inputs": {
                entry["path"]: entry["sha256"]
                for entry in entries
                if entry["path"] in {"ecc.toml", "project.json"} or "/rtl/" in f"/{entry['path']}"
            },
        }
        dump_json(staging / "manifest.json", manifest)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, "w:gz") as archive:
            archive.add(staging, arcname=".")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"status": "success", "package": str(output), "file_count": len(entries)}


@contextmanager
def read_package(package: Path) -> Iterator[tuple[tarfile.TarFile, dict[str, Any]]]:
    with tarfile.open(package, "r:gz") as archive:
        try:
            member = archive.getmember("./manifest.json")
        except KeyError:
            raise ValueError("package does not contain manifest.json") from None
        with archive.extractfile(member) as stream:
            manifest = json.load(stream)
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")
        yield archive, manifest


def verify_package(package: Path) -> dict[str, Any]:
    errors: list[str] = []
    with read_package(package) as (archive, manifest):
        if manifest.get("kind") != "ecc-reproducible-export":
            errors.append("manifest: invalid kind")
        if manifest.get("schema_version") != SCHEMA_VERSION:
            errors.append("manifest: unsupported schema_version")
        entries = manifest.get("files")
        if not isinstance(entries, list):
            errors.append("manifest: files must be a list")
            entries = []
        paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
        if len(paths) != len(set(paths)):
            errors.append("manifest: duplicate file path")
        if manifest.get("file_fingerprint") != payload_fingerprint(entries):
            errors.append("manifest: file_fingerprint mismatch")
        names = {member.name for member in archive.getmembers()}
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("path"), str)
                or not isinstance(entry.get("sha256"), str)
                or not isinstance(entry.get("size"), int)
            ):
                errors.append("manifest: invalid file entry")
                continue
            name = f"./{entry['path']}"
            if name not in names:
                errors.append(f"missing: {entry['path']}")
                continue
            member = archive.getmember(name)
            content = archive.extractfile(member).read()
            digest = hashlib.sha256(content).hexdigest()
            if len(content) != entry["size"]:
                errors.append(f"size: {entry['path']}")
            if digest != entry.get("sha256"):
                errors.append(f"checksum: {entry['path']}")
        expected_inputs = {
            entry["path"]: entry["sha256"]
            for entry in entries
            if isinstance(entry, dict)
            and entry.get("path") in {"ecc.toml", "project.json"}
            or isinstance(entry, dict)
            and "/rtl/" in f"/{entry.get('path', '')}"
        }
        if manifest.get("inputs") != expected_inputs:
            errors.append("manifest: inputs fingerprint mismatch")
        for member in archive.getmembers():
            if Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                errors.append(f"unsafe path: {member.name}")
    return {"status": "pass" if not errors else "fail", "package": str(package), "errors": errors}


def package_report(package: Path) -> dict[str, Any]:
    with read_package(package) as (archive, manifest):
        files = manifest.get("files", [])
        payloads: dict[str, Any] = {}
        invalid_json: list[str] = []
        for member in archive.getmembers():
            if member.isfile() and member.name.endswith(".json"):
                try:
                    payloads[member.name] = json.load(archive.extractfile(member))
                except (json.JSONDecodeError, OSError):
                    invalid_json.append(member.name)
                    continue
        flow_name, flow = next(
            (
                (name, value)
                for name, value in payloads.items()
                if name.endswith("flow.json") and isinstance(value, dict)
            ),
            (None, {}),
        )
        checklist_name, checklist = next(
            (
                (name, value)
                for name, value in payloads.items()
                if "checklist" in name and isinstance(value, dict)
            ),
            (None, {}),
        )
        qor_name, qor = next(
            (
                (name, value)
                for name, value in payloads.items()
                if "qor" in name and isinstance(value, dict)
            ),
            (None, {}),
        )
        summary = summarize_evidence(flow, checklist, qor, payloads)
        return {
            "kind": manifest.get("kind"),
            "schema_version": manifest.get("schema_version"),
            "workspace": manifest.get("workspace"),
            "created_at": manifest.get("created_at"),
            "file_count": len(files),
            "total_bytes": sum(entry.get("size", 0) for entry in files if isinstance(entry, dict)),
            "file_fingerprint": manifest.get("file_fingerprint"),
            "runtime": manifest.get("runtime", {}),
            "inputs": manifest.get("inputs", {}),
            "summary": {
                **summary,
                "sources": {
                    "flow": flow_name,
                    "checklist": checklist_name,
                    "qor": qor_name,
                    "violations": "embedded-json"
                    if summary["violation_count"] != "unknown"
                    else None,
                },
                "reasons": {
                    "flow": "ok" if flow_name else "missing",
                    "checklist": "invalid"
                    if any("checklist" in name for name in invalid_json)
                    else "ok"
                    if checklist_name
                    else "missing",
                    "qor": "ok" if qor_name else "missing",
                    "violations": "ok" if summary["violation_count"] != "unknown" else "missing",
                },
            },
            "verification": verify_package(package),
        }


def package_file_matches(path: str, kind: str) -> bool:
    if kind == "all":
        return True
    if kind == "rtl":
        return path.endswith((".v", ".sv", ".vh", ".svh")) or "/rtl/" in f"/{path}"
    if kind == "config":
        return path.endswith((".toml", ".tcl", ".yaml", ".yml")) or "/config/" in f"/{path}"
    if kind == "flow":
        return path.endswith("flow.json") or "/flow" in path
    if kind == "checklist":
        return "checklist" in path
    if kind == "signoff":
        return "signoff" in path or "/reports/" in path
    raise ValueError(f"unknown package file type: {kind}")


def parse_parameters(values: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"parameter must be KEY=VALUE[,VALUE]: {value}")
        key, raw = value.split("=", 1)
        choices = [item for item in raw.split(",") if item]
        if not key or not choices:
            raise ValueError(f"parameter must have a key and values: {value}")
        result[key] = choices
    if not result:
        raise ValueError("at least one --param is required")
    return result


def create_sweep(project: Path, name: str, parameters: dict[str, list[str]]) -> dict[str, Any]:
    root = project / "experiments" / name
    if root.exists():
        raise ValueError(f"sweep already exists: {name}")
    keys = sorted(parameters)
    candidates = [
        {"id": f"candidate_{index:04d}", "parameters": dict(zip(keys, values, strict=True))}
        for index, values in enumerate(itertools.product(*(parameters[key] for key in keys)), 1)
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "parameters": parameters,
        "candidates": candidates,
        "created_at": int(time.time()),
    }
    payload["plan_fingerprint"] = payload_fingerprint(
        {key: value for key, value in payload.items() if key != "created_at"}
    )
    dump_json(root / "sweep.json", payload)
    return payload


def sweep_result(project: Path, name: str) -> Path:
    return project / "experiments" / name / "results.json"


def verify_sweep(project: Path, name: str) -> dict[str, Any]:
    root = project / "experiments" / name
    plan = load_json(root / "sweep.json")
    errors: list[str] = []
    if not isinstance(plan, dict):
        return {"status": "fail", "sweep": name, "errors": ["missing or invalid sweep.json"]}
    expected_fingerprint = payload_fingerprint(
        {key: value for key, value in plan.items() if key not in {"created_at", "plan_fingerprint"}}
    )
    if plan.get("plan_fingerprint") != expected_fingerprint:
        errors.append("plan_fingerprint mismatch")
    candidates = {
        item.get("id"): item
        for item in plan.get("candidates", [])
        if isinstance(item, dict) and item.get("id")
    }
    results_payload = load_json(root / "results.json")
    results = results_payload.get("results", []) if isinstance(results_payload, dict) else []
    result_ids: set[str] = set()
    for result in results:
        candidate_id = result.get("id") if isinstance(result, dict) else None
        if not candidate_id or candidate_id in result_ids:
            errors.append(f"invalid or duplicate result: {candidate_id or 'unknown'}")
            continue
        result_ids.add(candidate_id)
        candidate = candidates.get(candidate_id)
        if candidate is None:
            errors.append(f"result not in plan: {candidate_id}")
            continue
        if result.get("parameters") != candidate.get("parameters"):
            errors.append(f"parameters mismatch: {candidate_id}")
        workspace = Path(result.get("workspace", ""))
        if not workspace.is_dir():
            errors.append(f"workspace missing: {candidate_id}")
    for candidate_id in candidates:
        if candidate_id not in result_ids:
            errors.append(f"result missing: {candidate_id}")
    return {
        "status": "pass" if not errors else "fail",
        "sweep": name,
        "candidate_count": len(candidates),
        "result_count": len(results),
        "errors": errors,
    }


def compare_sweep(project: Path, name: str) -> list[dict[str, Any]]:
    payload = load_json(sweep_result(project, name), {"results": []})
    rows = payload.get("results", [])
    order = {"passed": 0, "success": 0, "blocked": 1, "failed": 2, "unknown": 3}
    return sorted(
        rows,
        key=lambda row: (
            order.get(row.get("status", "unknown"), 3),
            -(
                row.get("qor_score")
                if isinstance(row.get("qor_score"), (int, float))
                else float("-inf")
            ),
        ),
    )


def sweep_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matrix = []
    for row in rows:
        steps = row.get("step_statuses", [])
        matrix.append(
            {
                "candidate": row.get("id", "unknown"),
                "parameters": row.get("parameters", {}),
                "flow": row.get("status", "unknown"),
                "steps": ";".join(
                    f"{step.get('name')}={step.get('status', 'unknown')}" for step in steps
                ),
                "checklist": ";".join(
                    f"{step.get('name')}={step.get('checklist', 'unknown')}" for step in steps
                ),
                "violations": row.get("violation_count", "unknown"),
                "qor": row.get("qor_score", "unknown"),
                "exit_code": row.get("exit_code", "unknown"),
            }
        )
    return matrix


def export_sweep(rows: list[dict[str, Any]], fmt: str) -> str:
    matrix = sweep_matrix(rows)
    if fmt == "json":
        return json.dumps(matrix, indent=2, sort_keys=True)
    columns = (
        "candidate",
        "flow",
        "steps",
        "checklist",
        "violations",
        "qor",
        "exit_code",
        "parameters",
    )
    if fmt == "csv":
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in matrix:
            writer.writerow(
                {
                    **row,
                    "parameters": ",".join(
                        f"{key}={value}" for key, value in row["parameters"].items()
                    ),
                }
            )
        return stream.getvalue()
    if fmt == "markdown":
        lines = [
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ]
        for row in matrix:
            values = {
                **row,
                "parameters": ", ".join(
                    f"{key}={value}" for key, value in row["parameters"].items()
                ),
            }
            lines.append("| " + " | ".join(str(values[column]) for column in columns) + " |")
        return "\n".join(lines) + "\n"
    raise ValueError(f"unsupported export format: {fmt}")


def _json_command(project: Path, workspace: Path, command: str) -> tuple[int, Any]:
    command_line = (
        [sys.argv[0]]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "chipcompiler.cli.main"]
    )
    completed = subprocess.run(
        [
            *command_line,
            *command.split(),
            "--project",
            str(project),
            "--workspace",
            str(workspace),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return completed.returncode, json.loads(completed.stdout)
    except json.JSONDecodeError:
        return completed.returncode, None


def _first_number(value: Any, keys: set[str]) -> float | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys and isinstance(child, (int, float)):
                return float(child)
            result = _first_number(child, keys)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _first_number(child, keys)
            if result is not None:
                return result
    return None


def summarize_evidence(
    flow: dict[str, Any], checklist: dict[str, Any], qor: dict[str, Any], payloads: Any
) -> dict[str, Any]:
    status_values = [
        item.get("status") for item in checklist.get("items", []) if isinstance(item, dict)
    ]
    violation_count = _first_number(payloads, {"violation_count", "violations", "error_count"})
    return {
        "flow_status": flow.get("status", "unknown"),
        "checklist_status": "blocked"
        if "blocked" in status_values
        else "attention"
        if "warning" in status_values
        else "passed"
        if status_values and all(value == "passed" for value in status_values)
        else "unknown",
        "qor": qor.get("qor_score", qor.get("score", "unknown")),
        "violation_count": int(violation_count) if violation_count is not None else "unknown",
    }


def collect_candidate_evidence(project: Path, workspace: Path, exit_code: int) -> dict[str, Any]:
    flow = load_json(workspace / "home" / "flow.json", {}) or {}
    status_code, status_payload = _json_command(project, workspace, "status")
    signoff_code, signoff_payload = _json_command(project, workspace, "signoff check")
    step_statuses = normalized_step_statuses(flow, status_payload)
    blocked = any(
        step["status"] == "blocked" or step["checklist"] == "blocked" for step in step_statuses
    )
    failed = exit_code != 0 or signoff_code not in {0, 7}
    status = (
        "blocked"
        if blocked
        else "failed"
        if failed
        else "passed"
        if step_statuses or status_code == 0
        else "unknown"
    )
    qor_score = None
    for report in workspace.rglob("*.json"):
        qor_score = _first_number(load_json(report), {"qor_score", "score", "ppa_score"})
        if qor_score is not None:
            break
    violation_count = _first_number(
        signoff_payload, {"violation_count", "violations", "error_count"}
    )
    return {
        "status": status,
        "step_statuses": step_statuses,
        "qor_score": qor_score,
        "violation_count": int(violation_count) if violation_count is not None else "unknown",
        "signoff_exit_code": signoff_code,
        "workspace_status_exit_code": status_code,
    }


def run_sweep(project: Path, name: str, max_candidates: int | None) -> dict[str, Any]:
    plan = load_json(project / "experiments" / name / "sweep.json")
    if not plan:
        raise ValueError(f"sweep does not exist: {name}")
    candidates = plan["candidates"][:max_candidates]
    previous = load_json(sweep_result(project, name), {"results": []}) or {}
    previous_results = {
        row.get("id"): row for row in previous.get("results", []) if isinstance(row, dict)
    }
    results = []
    for candidate in candidates:
        candidate_root = project / "experiments" / name / "candidates" / candidate["id"]
        candidate_project = candidate_root / "project"
        if not candidate_project.exists():

            def ignore(source: str, names: list[str]) -> set[str]:
                return {
                    item
                    for item in names
                    if item in {"experiments", ".git"}
                    or item.endswith(".lock")
                    or item.startswith("ws_")
                }

            shutil.copytree(project, candidate_project, ignore=ignore)
            manifest_path = candidate_project / MANIFEST_FILENAME
            manifest = load_json(manifest_path, {})
            if isinstance(manifest, dict):
                manifest["root_path"] = str(candidate_project)
                manifest["workspaces"] = []
                manifest["runtime_processes"] = []
                dump_json(manifest_path, manifest)
        workspace = candidate_project / candidate["id"]
        existing = previous_results.get(candidate["id"])
        if (
            existing
            and existing.get("status") in {"passed", "blocked", "failed", "unknown"}
            and workspace.exists()
        ):
            results.append(existing)
            continue
        command_line = (
            [sys.argv[0]]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "chipcompiler.cli.main"]
        )
        command = [
            *command_line,
            "run",
            "--project",
            str(candidate_project),
            "--workspace",
            str(workspace),
        ]
        for key, value in candidate["parameters"].items():
            command.extend(["--set", f"{key}={value}"])
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        evidence = collect_candidate_evidence(candidate_project, workspace, completed.returncode)
        results.append(
            {
                "id": candidate["id"],
                "workspace": str(workspace),
                "parameters": candidate["parameters"],
                "exit_code": completed.returncode,
                **evidence,
            }
        )
    payload = {"schema_version": SCHEMA_VERSION, "results": results}
    dump_json(sweep_result(project, name), payload)
    return payload
