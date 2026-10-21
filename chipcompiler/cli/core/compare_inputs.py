from dataclasses import dataclass

from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions


@dataclass(frozen=True)
class CompareRunInput:
    baseline: str
    current: str
    output: OutputOptions
    project: ProjectOptions = ProjectOptions()
