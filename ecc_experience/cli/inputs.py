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
    through_step: str | None = None


@dataclass(frozen=True)
class MatchInput:
    output: OutputOptions
    store: str
    case_id: str
    release: str
    through_step: str
    limit: int = 10
    experimental_cross_design: bool = False
    groups: str | None = None
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
    retry_failed: bool = False


@dataclass(frozen=True)
class CampaignAnalysisInput:
    output: OutputOptions
    source: str
    output_path: str
    secondary: str | None = None
    auxiliary: str | None = None
    min_independent_designs: int = 3
    min_families: int = 2
    min_candidate_configurations: int = 2
    project: ProjectOptions = ProjectOptions()


@dataclass(frozen=True)
class BenchmarkSpecInput:
    output: OutputOptions
    spec: str
    project: ProjectOptions = ProjectOptions()


@dataclass(frozen=True)
class BenchmarkPlanInput:
    output: OutputOptions
    spec: str
    output_path: str
    project: ProjectOptions = ProjectOptions()


@dataclass(frozen=True)
class BenchmarkSummaryInput:
    output: OutputOptions
    plan: str
    matrix: str
    readiness: str
    output_path: str
    effect: str | None = None
    project: ProjectOptions = ProjectOptions()


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
    optimization: dict | None = None


@dataclass(frozen=True)
class OptimizeInput:
    output: OutputOptions
    project: ProjectOptions
    store: str
    plan_path: str
    output_path: str


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


@dataclass(frozen=True)
class TransferInput:
    output: OutputOptions
    store: str
    output_path: str | None = None
    package_path: str | None = None
    case_ids: list[str] | None = None
    release_path: str | None = None
    project: ProjectOptions = ProjectOptions()
