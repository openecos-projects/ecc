"""CLI commands for the P4 dataset and explainable-model lifecycle."""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from chipcompiler.cli.core.apps import create_app
from chipcompiler.cli.core.inputs import (
    OutputOptions,
    ProjectOptions,
    output_options,
    project_options,
)
from chipcompiler.cli.core.invocation import execute_command
from chipcompiler.cli.core.options import JsonOption, PlainOption
from chipcompiler.cli.core.types import CommandContext, CommandResult
from ecc_experience.cli.handlers import _guard

dataset_app = create_app(help="Build immutable modeling datasets from verified experience releases")
model_app = create_app(help="Train, verify, publish and query explainable experience models")


@dataclass(frozen=True)
class DatasetInput:
    output: OutputOptions
    project: ProjectOptions
    release: str
    store: str
    output_path: str
    target: str
    through_step: str
    groups: str | None = None


@dataclass(frozen=True)
class ModelInput:
    output: OutputOptions
    project: ProjectOptions
    action: str
    output_path: str | None = None
    dataset: str | None = None
    model: str | None = None
    evaluation: str | None = None
    model_release: str | None = None
    case_id: str | None = None
    store: str | None = None
    through_step: str | None = None
    ridge: float = 1.0
    min_independent_designs: int = 3
    min_families: int = 2
    max_mae: float = 10.0
    min_interval_coverage: float = 0.5
    limit: int = 10


def _dataset_build(command: DatasetInput, _context: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import dataset_build

        result = dataset_build(
            command.release,
            command.store,
            command.output_path,
            target=command.target,
            through_step=command.through_step,
            groups=command.groups,
        )
        return CommandResult.ok(
            [
                {
                    "experience": "dataset_build",
                    "dataset_id": result["dataset_id"],
                    "output": str(Path(command.output_path).expanduser().absolute()),
                    "summary": result["summary"],
                    "excluded": result["excluded"],
                }
            ]
        )

    return _guard(operation)


def _model_command(command: ModelInput, _context: CommandContext) -> CommandResult:
    def operation() -> CommandResult:
        from ecc_experience.api import (
            model_advise,
            model_evaluate,
            model_predict,
            model_publish,
            model_train,
        )

        if command.action == "train":
            result = model_train(
                command.dataset or "", command.output_path or "", ridge=command.ridge
            )
            record = {
                "experience": "model_train",
                "model_id": result["model_id"],
                "output": str(Path(command.output_path or "").expanduser().absolute()),
                "training_summary": result["training_summary"],
            }
            return CommandResult.ok([record])
        if command.action == "evaluate":
            result = model_evaluate(
                command.model or "",
                command.dataset or "",
                command.output_path or "",
                min_independent_designs=command.min_independent_designs,
                min_families=command.min_families,
                max_mae=command.max_mae,
                min_interval_coverage=command.min_interval_coverage,
            )
            return CommandResult(
                records=(
                    {
                        "experience": "model_evaluate",
                        "status": result["status"],
                        "output": str(Path(command.output_path or "").expanduser().absolute()),
                        "metrics": result["metrics"],
                        "summary": result["summary"],
                        "generalization_status": result["generalization_status"],
                    },
                ),
                exit_code=result["exit_code"],
            )
        if command.action == "publish":
            result = model_publish(
                command.model or "",
                command.evaluation or "",
                command.output_path or "",
            )
            return CommandResult.ok([{"experience": "model_publish", **result}])
        if command.action == "predict":
            result = model_predict(
                command.model_release or "",
                command.case_id or "",
                command.store or "",
                through_step=command.through_step,
            )
            return CommandResult.ok([{"experience": "model_predict", **result}])
        if command.action == "advise":
            result = model_advise(
                command.model_release or "",
                command.dataset or "",
                command.output_path or "",
                limit=command.limit,
            )
            return CommandResult.ok(
                [
                    {
                        "experience": "model_advise",
                        "advice_id": result["advice_id"],
                        "output": str(Path(command.output_path or "").expanduser().absolute()),
                        "candidate_count": len(result["candidates"]),
                        "safe_to_apply": result["safe_to_apply"],
                    }
                ]
            )
        raise ValueError(f"Unsupported model action: {command.action}")

    return _guard(operation)


@dataset_app.command("build", help="Build a leakage-auditable dataset from a verified release")
def dataset_build_cmd(
    *,
    release: Annotated[str, typer.Option("--release", help="Verified experience release JSON")],
    store: Annotated[str, typer.Option("--store", help="Experience store directory")],
    output: Annotated[str, typer.Option("--output", help="New dataset JSON")],
    target: Annotated[
        str,
        typer.Option("--target", help="final_qor, feasibility, metric:ID or resource:STEP:FIELD"),
    ],
    through_step: Annotated[str, typer.Option("--through-step", help="Feature prefix boundary")],
    groups: Annotated[
        str | None, typer.Option("--groups", help="Optional case-to-family JSON")
    ] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    execute_command(
        "experience",
        DatasetInput(
            output_options(plain=plain, json_output=json_output),
            project_options(None),
            release,
            store,
            output,
            target,
            through_step,
            groups,
        ),
        _dataset_build,
    )


@model_app.command("train", help="Train a deterministic explainable ridge baseline")
def model_train_cmd(
    *,
    dataset: Annotated[str, typer.Option("--dataset")],
    output: Annotated[str, typer.Option("--output")],
    ridge: Annotated[float, typer.Option("--ridge", min=0.000001)] = 1.0,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    execute_command(
        "experience",
        ModelInput(
            output_options(plain=plain, json_output=json_output),
            project_options(None),
            "train",
            output,
            dataset,
            ridge=ridge,
        ),
        _model_command,
    )


@model_app.command("evaluate", help="Evaluate a model on an independent held-out dataset")
def model_evaluate_cmd(
    *,
    model: Annotated[str, typer.Option("--model")],
    dataset: Annotated[str, typer.Option("--dataset")],
    output: Annotated[str, typer.Option("--output")],
    min_independent_designs: Annotated[int, typer.Option("--min-independent-designs", min=1)] = 3,
    min_families: Annotated[int, typer.Option("--min-families", min=1)] = 2,
    max_mae: Annotated[float, typer.Option("--max-mae", min=0)] = 10.0,
    min_interval_coverage: Annotated[
        float, typer.Option("--min-interval-coverage", min=0, max=1)
    ] = 0.5,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    execute_command(
        "experience",
        ModelInput(
            output_options(plain=plain, json_output=json_output),
            project_options(None),
            "evaluate",
            output,
            dataset,
            model=model,
            min_independent_designs=min_independent_designs,
            min_families=min_families,
            max_mae=max_mae,
            min_interval_coverage=min_interval_coverage,
        ),
        _model_command,
    )


@model_app.command("publish", help="Publish only a passing, rechecked model evaluation")
def model_publish_cmd(
    *,
    model: Annotated[str, typer.Option("--model")],
    evaluation: Annotated[str, typer.Option("--evaluation")],
    output: Annotated[str, typer.Option("--output")],
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    execute_command(
        "experience",
        ModelInput(
            output_options(plain=plain, json_output=json_output),
            project_options(None),
            "publish",
            output,
            model=model,
            evaluation=evaluation,
        ),
        _model_command,
    )


@model_app.command("predict", help="Predict a verified case without modifying its workspace")
def model_predict_cmd(
    *,
    model_release: Annotated[str, typer.Option("--model-release")],
    case_id: Annotated[str, typer.Option("--case-id")],
    store: Annotated[str, typer.Option("--store")],
    through_step: Annotated[str | None, typer.Option("--through-step")] = None,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    execute_command(
        "experience",
        ModelInput(
            output_options(plain=plain, json_output=json_output),
            project_options(None),
            "predict",
            model_release=model_release,
            case_id=case_id,
            store=store,
            through_step=through_step,
        ),
        _model_command,
    )


@model_app.command("advise", help="Rank candidate rows without automatically applying parameters")
def model_advise_cmd(
    *,
    model_release: Annotated[str, typer.Option("--model-release")],
    dataset: Annotated[str, typer.Option("--dataset")],
    output: Annotated[str, typer.Option("--output")],
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 10,
    plain: PlainOption = False,
    json_output: JsonOption = False,
) -> None:
    execute_command(
        "experience",
        ModelInput(
            output_options(plain=plain, json_output=json_output),
            project_options(None),
            "advise",
            output,
            dataset,
            model_release=model_release,
            limit=limit,
        ),
        _model_command,
    )
