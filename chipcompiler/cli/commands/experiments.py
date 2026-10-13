import json
import tarfile
import time
from pathlib import Path
from typing import Annotated

import typer

from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.experiments.operations import (
    compare_sweep,
    diagnose_workspace,
    create_sweep,
    export_package,
    export_sweep,
    load_json,
    parse_parameters,
    project_path,
    package_report,
    package_file_matches,
    read_package,
    run_sweep,
    sweep_matrix,
    verify_sweep,
    verify_package,
)

reproducible_app = create_app(help="Export and verify reproducible ECC evidence packages")
sweep_app = create_app(help="Run deterministic parameter sweeps")
explore_app = create_app(help="Rank and select sweep candidates")
diagnose_app = create_app(help="Diagnose workspace flow, checklist, QoR, and recovery actions")


@diagnose_app.command("run")
def diagnose_run(*, project: Annotated[str | None, typer.Option("--project")] = None, workspace: Annotated[str, typer.Option("--workspace")] = "default", json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    result = diagnose_workspace(project_path(project), workspace)
    if json_output:
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        typer.echo(f"status: {result['status']}")
        typer.echo(f"workspace: {result['workspace']}")
        typer.echo(f"flow: {result['flow']['status']} failed_steps={','.join(result['flow']['failed_steps']) or '-'}")
        typer.echo(f"checklist: {result['checklist']['status']} blocked={result['checklist']['blocked_count']}")
        typer.echo(f"qor: {result['qor']['score']} available={result['qor']['available']}")
        typer.echo(f"next_actions: {'; '.join(result['next_actions']) or '-'}")
    if result["status"] in {"failed", "blocked"}:
        raise typer.Exit(6)


@reproducible_app.command("export")
def reproducible_export(
    *, project: Annotated[str | None, typer.Option("--project")] = None,
    workspace: Annotated[str, typer.Option("--workspace")] = "default",
    output: Annotated[str, typer.Option("--output")],
) -> None:
    try:
        root = project_path(project)
        output_path = Path(output).expanduser()
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        result = export_package(root, (root / workspace).resolve(), output_path.resolve())
        typer.echo(json.dumps(result, sort_keys=True))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


@reproducible_app.command("inspect")
def reproducible_inspect(*, package: Annotated[str, typer.Option("--package")], json_output: Annotated[bool, typer.Option("--json")] = False, files: Annotated[bool, typer.Option("--files")] = False, file_type: Annotated[str, typer.Option("--type", help="all, rtl, config, flow, checklist, or signoff")] = "all") -> None:
    try:
        archive, manifest = read_package(Path(package))
        archive.close()
        if files:
            payload = [entry.get("path") for entry in manifest.get("files", []) if package_file_matches(entry.get("path", ""), file_type)]
        else:
            payload = manifest
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    except (OSError, ValueError, tarfile.TarError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


@reproducible_app.command("verify")
def reproducible_verify(*, package: Annotated[str, typer.Option("--package")], json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    try:
        result = verify_package(Path(package))
    except (OSError, ValueError, tarfile.TarError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, sort_keys=True))
    if result["status"] != "pass":
        raise typer.Exit(6)


@reproducible_app.command("report")
def reproducible_report(*, package: Annotated[str, typer.Option("--package")], json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    try:
        result = package_report(Path(package))
    except (OSError, ValueError, tarfile.TarError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    if json_output:
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        typer.echo(f"package: {result['kind']} schema={result['schema_version']}")
        typer.echo(f"files: {result['file_count']} total_bytes={result['total_bytes']}")
        typer.echo(f"fingerprint: {result['file_fingerprint']}")
        typer.echo(f"verification: {result['verification']['status']}")
        runtime = result.get("runtime", {})
        typer.echo(f"ecc: {runtime.get('ecc', 'unknown')} pdk: {runtime.get('pdk', {}).get('name', 'unknown')}")
        summary = result.get("summary", {})
        typer.echo(f"flow: {summary.get('flow_status', 'unknown')} checklist: {summary.get('checklist_status', 'unknown')} qor: {summary.get('qor', 'unknown')} violations: {summary.get('violation_count', 'unknown')}")
    if result["verification"]["status"] != "pass":
        raise typer.Exit(6)


@sweep_app.command("create")
def sweep_create(
    *, project: Annotated[str | None, typer.Option("--project")] = None,
    name: Annotated[str, typer.Option("--name")],
    param: Annotated[list[str], typer.Option("--param")],
) -> None:
    try:
        result = create_sweep(project_path(project), name, parse_parameters(param))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


@sweep_app.command("show")
def sweep_show(*, project: Annotated[str | None, typer.Option("--project")] = None, name: Annotated[str, typer.Option("--name")], json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    payload = load_json(project_path(project) / "experiments" / name / "sweep.json")
    if payload is None:
        raise typer.BadParameter(f"sweep does not exist: {name}")
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@sweep_app.command("list")
def sweep_list(*, project: Annotated[str | None, typer.Option("--project")] = None) -> None:
    root = project_path(project) / "experiments"
    result = [item.name for item in sorted(root.iterdir()) if (item / "sweep.json").exists()] if root.exists() else []
    typer.echo(json.dumps(result))


@sweep_app.command("run")
def sweep_run(*, project: Annotated[str | None, typer.Option("--project")] = None, name: Annotated[str, typer.Option("--name")], max_candidates: Annotated[int | None, typer.Option("--max-candidates", min=1)] = None) -> None:
    try:
        result = run_sweep(project_path(project), name, max_candidates)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


@sweep_app.command("compare")
def sweep_compare(*, project: Annotated[str | None, typer.Option("--project")] = None, name: Annotated[str, typer.Option("--name")], json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    rows = compare_sweep(project_path(project), name)
    if json_output:
        typer.echo(json.dumps(sweep_matrix(rows), indent=2, sort_keys=True))
        return
    typer.echo("candidate | flow | steps | checklist | violations | qor | exit | parameters")
    typer.echo("----------|------|-------|-----------|-------------|-----|------|-----------")
    for row in sweep_matrix(rows):
        parameters = ",".join(f"{key}={value}" for key, value in row["parameters"].items())
        typer.echo(f"{row['candidate']} | {row['flow']} | {row['steps'] or '-'} | {row['checklist'] or '-'} | {row['violations']} | {row['qor']} | {row['exit_code']} | {parameters}")


@sweep_app.command("verify")
def sweep_verify(*, project: Annotated[str | None, typer.Option("--project")] = None, name: Annotated[str, typer.Option("--name")]) -> None:
    result = verify_sweep(project_path(project), name)
    typer.echo(json.dumps(result, indent=2, sort_keys=True))
    if result["status"] != "pass":
        raise typer.Exit(6)


@explore_app.command("rank")
def explore_rank(*, project: Annotated[str | None, typer.Option("--project")] = None, name: Annotated[str, typer.Option("--name")]) -> None:
    typer.echo(json.dumps(compare_sweep(project_path(project), name), indent=2, sort_keys=True))


@explore_app.command("export")
def explore_export(*, project: Annotated[str | None, typer.Option("--project")] = None, name: Annotated[str, typer.Option("--name")], format_name: Annotated[str, typer.Option("--format", help="json, csv, or markdown")] = "json", output: Annotated[str | None, typer.Option("--output")] = None) -> None:
    try:
        content = export_sweep(compare_sweep(project_path(project), name), format_name)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if output:
        Path(output).write_text(content)
        typer.echo(json.dumps({"status": "success", "format": format_name, "output": str(Path(output).resolve())}))
    else:
        typer.echo(content, nl=False)


@explore_app.command("promote")
def explore_promote(*, project: Annotated[str | None, typer.Option("--project")] = None, name: Annotated[str, typer.Option("--name")], candidate: Annotated[str, typer.Option("--candidate")]) -> None:
    root = project_path(project) / "experiments" / name
    if not (root / "sweep.json").exists():
        raise typer.BadParameter(f"sweep does not exist: {name}")
    results = load_json(root / "results.json", {"results": []}).get("results", [])
    selected = next((row for row in results if row.get("id") == candidate), None)
    if selected is None:
        raise typer.BadParameter(f"candidate does not exist or has not run: {candidate}")
    if selected.get("status") != "passed":
        raise typer.BadParameter(f"only passed candidates can be promoted: {candidate}")
    payload = {"schema_version": 1, "candidate": candidate, "selected_at": time.time()}
    (root / "winner.json").write_text(json.dumps(payload, indent=2) + "\n")
    typer.echo(json.dumps(payload, sort_keys=True))
