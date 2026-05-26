from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutputOptions:
    json: bool = False
    jsonl: bool = False
    plain: bool = False


@dataclass(frozen=True)
class ProjectOptions:
    project: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class InitInput:
    name: str
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()


@dataclass(frozen=True)
class CheckInput:
    output: OutputOptions
    project: ProjectOptions


@dataclass(frozen=True)
class RunInput:
    output: OutputOptions
    project: ProjectOptions
    overwrite: bool = False
    param_set: tuple[str, ...] = ()


@dataclass(frozen=True)
class StatusInput:
    output: OutputOptions
    project: ProjectOptions


@dataclass(frozen=True)
class StepInspectInput:
    output: OutputOptions
    project: ProjectOptions
    step: str | None = None


@dataclass(frozen=True)
class LogInput:
    output: OutputOptions
    project: ProjectOptions
    step: str | None = None
    errors: bool = False


@dataclass(frozen=True)
class ConfigInput:
    output: OutputOptions
    project: ProjectOptions
    step: str | None = None
    resolved: bool = False


@dataclass(frozen=True)
class DiagnoseInput:
    output: OutputOptions
    project: ProjectOptions
    step: str | None = None


@dataclass(frozen=True)
class ParamListInput:
    output: OutputOptions
    project: ProjectOptions


@dataclass(frozen=True)
class ParamShowInput:
    output: OutputOptions
    project: ProjectOptions
    key: str


@dataclass(frozen=True)
class ParamSetInput:
    output: OutputOptions
    project: ProjectOptions
    key: str
    value: str


@dataclass(frozen=True)
class ParamUnsetInput:
    output: OutputOptions
    project: ProjectOptions
    key: str


@dataclass(frozen=True)
class ParamDiffInput:
    output: OutputOptions
    project: ProjectOptions


def output_options(json_output: bool, jsonl: bool, plain: bool) -> OutputOptions:
    return OutputOptions(json=json_output, jsonl=jsonl, plain=plain)


def project_options(project: str | None, run_id: str | None = None) -> ProjectOptions:
    return ProjectOptions(project=project, run_id=run_id)
