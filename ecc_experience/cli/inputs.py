from dataclasses import dataclass

from chipcompiler.cli.core.inputs import OutputOptions, ProjectOptions


@dataclass(frozen=True)
class CollectInput:
    output: OutputOptions
    project: ProjectOptions
    store: str
    workspace: str | None = None


@dataclass(frozen=True)
class StoreInput:
    output: OutputOptions
    store: str
    case_id: str | None = None
    project: ProjectOptions = ProjectOptions()
