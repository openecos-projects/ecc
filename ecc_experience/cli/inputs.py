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


@dataclass(frozen=True)
class RecordingInput:
    output: OutputOptions
    project: ProjectOptions
    store: str | None = None
    limit: int = 32


@dataclass(frozen=True)
class CampaignInput:
    output: OutputOptions
    project: ProjectOptions
    manifest: str
    ledger: str | None = None
    design_id: str | None = None
    workspace: str | None = None
    status: str | None = None
    trial_id: str | None = None
    case_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RecommendInput:
    output: OutputOptions
    project: ProjectOptions
    store: str
    workspace: str | None = None
    limit: int = 10
    release: str | None = None


@dataclass(frozen=True)
class PlanInput:
    output: OutputOptions
    project: ProjectOptions
    store: str
    output_path: str
    workspace: str | None = None
    limit: int = 10
    release: str | None = None


@dataclass(frozen=True)
class EvaluationInput:
    output: OutputOptions
    project: ProjectOptions
    store: str
    baseline: str
    candidate: str


@dataclass(frozen=True)
class ReleaseInput:
    output: OutputOptions
    project: ProjectOptions
    store: str
    case_ids: list[str] | None = None
    output_path: str | None = None
    release_path: str | None = None
