import json
import tarfile
import time
from pathlib import Path
from typing import Annotated

import typer

from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.experiments.operations import (
    compare_sweep,
    create_sweep,
    export_package,
    load_json,
    parse_parameters,
    project_path,
    read_package,
    run_sweep,
    verify_package,
)

reproducible_app = create_app(help="Export and verify reproducible ECC evidence packages")
sweep_app = create_app(help="Run deterministic parameter sweeps")
explore_app = create_app(help="Rank and select sweep candidates")


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
def reproducible_inspect(*, package: Annotated[str, typer.Option("--package")], json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    try:
        archive, manifest = read_package(Path(package))
        archive.close()
        typer.echo(json.dumps(manifest, indent=2, sort_keys=True))
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
def sweep_compare(*, project: Annotated[str | None, typer.Option("--project")] = None, name: Annotated[str, typer.Option("--name")]) -> None:
    typer.echo(json.dumps(compare_sweep(project_path(project), name), indent=2, sort_keys=True))


@explore_app.command("rank")
def explore_rank(*, project: Annotated[str | None, typer.Option("--project")] = None, name: Annotated[str, typer.Option("--name")]) -> None:
    typer.echo(json.dumps(compare_sweep(project_path(project), name), indent=2, sort_keys=True))


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
