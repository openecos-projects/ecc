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
class DoctorInput:
    output: OutputOptions
    project: ProjectOptions


@dataclass(frozen=True)
class RunInput:
    output: OutputOptions
    project: ProjectOptions
    overwrite: bool = False
    param_set: tuple[str, ...] = ()
    workspace: str | None = None
    resume: bool = False
    from_step: str | None = None
    only: str | None = None
    force: bool = False
    preset: str | None = None


@dataclass(frozen=True)
class MigrateInput:
    output: OutputOptions
    project: ProjectOptions
    yes: bool = False


@dataclass(frozen=True)
class StatusInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str | None = None


@dataclass(frozen=True)
class LogInput:
    output: OutputOptions
    project: ProjectOptions
    step: str | None = None
    workspace: str | None = None


@dataclass(frozen=True)
class ConfigInput:
    output: OutputOptions
    project: ProjectOptions
    step: str | None = None
    workspace: str | None = None


@dataclass(frozen=True)
class PdkSetRootInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
    path: str = ""


@dataclass(frozen=True)
class PdkSetupInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
    path: str | None = None


@dataclass(frozen=True)
class PdkShowInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()


@dataclass(frozen=True)
class PdkUnsetInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()


@dataclass(frozen=True)
class ReportQorInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
    workspace: str | None = None
    output_path: str | None = None


@dataclass(frozen=True)
class ReportChecklistInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
    workspace: str | None = None
    output_path: str | None = None


@dataclass(frozen=True)
class ReportStepInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
    workspace: str | None = None
    step: str | None = None
    sections: tuple[str, ...] = ()


@dataclass(frozen=True)
class SignoffInspectInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
    workspace: str | None = None


@dataclass(frozen=True)
class SignoffExportInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
    workspace: str | None = None
    output_path: str = ""
    include_debug: bool = False


@dataclass(frozen=True)
class ReportSummaryInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
    workspace: str | None = None
    output_path: str | None = None


@dataclass(frozen=True)
class ParamListInput:
    output: OutputOptions
    project: ProjectOptions
    step: str | None = None
    all: bool = False


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


def output_options(*, json_output: bool, jsonl: bool, plain: bool) -> OutputOptions:
    return OutputOptions(json=json_output, jsonl=jsonl, plain=plain)


def project_options(project: str | None, run_id: str | None = None) -> ProjectOptions:
    return ProjectOptions(project=project, run_id=run_id)
