from dataclasses import dataclass


@dataclass(frozen=True)
class OutputOptions:
    plain: bool = False


@dataclass(frozen=True)
class ProjectOptions:
    project: str | None = None


@dataclass(frozen=True)
class InitInput:
    name: str
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
    project_name: str | None = None
    design_name: str | None = None
    mpc_resource_id: str | None = None
    mpc_display_name: str | None = None
    mpc_version: str | None = None
    mpc_root: str | None = None
    mpc_design_index: int | None = None


@dataclass(frozen=True)
class CheckInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str | None = None


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
    to_step: str | None = None
    only: str | None = None
    force: bool = False
    preset: str | None = None
    keep_backup: bool = False
    expected_revision: int | None = None
    command_id: str = ""
    no_wait: bool = False
    run_id: str = ""
    runtime_id: str = ""
    log_file: str = ""


@dataclass(frozen=True)
class ProcessInspectInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str
    run_id: str | None = None


@dataclass(frozen=True)
class ProcessCancelInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str
    run_id: str
    force: bool = False


@dataclass(frozen=True)
class ProcessReconcileInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str
    run_id: str | None = None
    no_wait: bool = False


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
    expected_revision: int | None = None
    no_wait: bool = False
    additional_files: str | None = None


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
    workspace: str | None = None


@dataclass(frozen=True)
class FlowListInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()


@dataclass(frozen=True)
class ParamShowInput:
    output: OutputOptions
    project: ProjectOptions
    key: str
    workspace: str | None = None


@dataclass(frozen=True)
class ParamSetInput:
    output: OutputOptions
    project: ProjectOptions
    key: str
    value: str
    workspace: str | None = None


@dataclass(frozen=True)
class ParamUnsetInput:
    output: OutputOptions
    project: ProjectOptions
    key: str
    workspace: str | None = None


@dataclass(frozen=True)
class ParamDiffInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str | None = None


@dataclass(frozen=True)
class ParamApplyInput:
    output: OutputOptions
    project: ProjectOptions
    sets: tuple[str, ...] = ()
    unsets: tuple[str, ...] = ()
    workspace: str | None = None
    step: str | None = None
    expected_revision: int | None = None
    command_id: str = ""
    no_wait: bool = False


@dataclass(frozen=True)
class ProjectSetInput:
    output: OutputOptions
    project: ProjectOptions
    key: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class ProjectUnsetInput:
    output: OutputOptions
    project: ProjectOptions
    key: str


@dataclass(frozen=True)
class ProjectAddInput:
    output: OutputOptions
    project: ProjectOptions
    key: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class ProjectShowInput:
    output: OutputOptions
    project: ProjectOptions
    key: str | None = None


@dataclass(frozen=True)
class ProjectApplyInput:
    output: OutputOptions
    project: ProjectOptions
    sets: tuple[str, ...] = ()
    unsets: tuple[str, ...] = ()
    add_rtl: tuple[str, ...] = ()
    remove_rtl: tuple[str, ...] = ()
    no_wait: bool = False


@dataclass(frozen=True)
class ProjectBaselineInput:
    output: OutputOptions
    project: ProjectOptions
    workspace_id: str
    reason: str = ""


@dataclass(frozen=True)
class ProjectReconcileInput:
    output: OutputOptions
    project: ProjectOptions
    no_wait: bool = False


@dataclass(frozen=True)
class ProjectDoctorInput:
    output: OutputOptions
    project: ProjectOptions
    fix: bool = False


@dataclass(frozen=True)
class WorkspaceRefreshInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str
    force: bool = False
    keep_backup: bool = False
    expected_revision: int | None = None
    command_id: str = ""
    no_wait: bool = False


@dataclass(frozen=True)
class WorkspaceImportInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str
    path: str
    no_wait: bool = False


@dataclass(frozen=True)
class WorkspaceDeriveInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str
    target_workspace: str
    from_step: str | None = None
    command_id: str = ""
    no_wait: bool = False


@dataclass(frozen=True)
class WorkspaceArchiveInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str
    expected_revision: int | None = None
    command_id: str = ""
    no_wait: bool = False


@dataclass(frozen=True)
class WorkspaceDeleteInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str
    expected_revision: int | None = None
    command_id: str = ""
    no_wait: bool = False
    delete_directory: bool = False


@dataclass(frozen=True)
class WorkspaceResetFlowInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str
    expected_revision: int | None = None
    command_id: str = ""
    no_wait: bool = False


@dataclass(frozen=True)
class WorkspaceReconcileDeletesInput:
    output: OutputOptions
    project: ProjectOptions
    no_wait: bool = False


@dataclass(frozen=True)
class WorkspaceCreateInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str
    path: str | None = None
    from_step: str | None = None
    to_step: str | None = None
    param_set: tuple[str, ...] = ()
    command_id: str = ""
    no_wait: bool = False


@dataclass(frozen=True)
class MacroSetInput:
    output: OutputOptions
    project: ProjectOptions
    instance: str
    x: float
    y: float
    orientation: str
    workspace: str | None = None


@dataclass(frozen=True)
class MacroRemoveInput:
    output: OutputOptions
    project: ProjectOptions
    instance: str
    workspace: str | None = None


@dataclass(frozen=True)
class MacroShowInput:
    output: OutputOptions
    project: ProjectOptions
    workspace: str | None = None


@dataclass(frozen=True)
class MacroImportInput:
    output: OutputOptions
    project: ProjectOptions
    path: str
    workspace: str | None = None
    expected_revision: int | None = None
    command_id: str = ""
    no_wait: bool = False


def output_options(*, plain: bool) -> OutputOptions:
    return OutputOptions(plain=plain)


def project_options(project: str | None) -> ProjectOptions:
    return ProjectOptions(project=project)
