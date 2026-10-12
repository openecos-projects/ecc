from dataclasses import dataclass

from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions


@dataclass(frozen=True)
class ReportSnapshotInput:
    output_path: str
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
    workspace: str | None = None
