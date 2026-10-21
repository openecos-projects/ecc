from dataclasses import dataclass

from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions


@dataclass(frozen=True)
class ReportProjectInput:
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
