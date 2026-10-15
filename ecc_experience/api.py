from pathlib import Path

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.benchmark.execute import run_campaign as execute_campaign
from ecc_experience.benchmark.ledger import initialize as initialize_campaign
from ecc_experience.benchmark.ledger import record_trial as record_campaign_trial
from ecc_experience.benchmark.ledger import status as read_campaign_status
from ecc_experience.benchmark.manifest import load_manifest
from ecc_experience.benchmark.quality import campaign_quality as read_campaign_quality
from ecc_experience.benchmark.recovery import recover_campaign as recover_campaign_attempt
from ecc_experience.benchmark.summary import summarize as summarize_campaign
from ecc_experience.collection.collect import CollectionResult, collect_committed_case
from ecc_experience.collection.drain import drain as drain_recording
from ecc_experience.dse.execute import run_dse
from ecc_experience.dse.plan import plan_dse
from ecc_experience.dse.report import report_dse
from ecc_experience.knowledge.features import case_features
from ecc_experience.knowledge.matching import match_cases
from ecc_experience.knowledge.recommend import recommend as recommend_cases
from ecc_experience.knowledge.release import create_release, verify_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.transfer import export_package, import_package
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.modeling.dataset import build_dataset
from ecc_experience.modeling.model import evaluate_model, publish_model, train_model
from ecc_experience.modeling.predict import advise_dataset, predict_case
from ecc_experience.modeling.registry import promote as promote_model_release
from ecc_experience.modeling.registry import rollback as rollback_model_release
from ecc_experience.modeling.registry import status as model_registry_status
from ecc_experience.modeling.split import split_dataset
from ecc_experience.modeling.sweep import seed_sweep
from ecc_experience.modeling.validation import validate_matrix
from ecc_experience.models import ExperienceCase, Verification
from ecc_experience.optimization.evaluate import evaluate as evaluate_cases
from ecc_experience.optimization.execute import optimize as execute_optimization
from ecc_experience.optimization.plan import build_plan, write_plan
from ecc_experience.optimization.policy import OptimizationLimits
from ecc_experience.recording import disable as disable_recording
from ecc_experience.recording import set_enabled
from ecc_experience.recording import status as recording_status
from ecc_experience.study.evaluate import evaluate_study
from ecc_experience.study.publish import publish_study


def study_evaluate(spec: str | Path, store: str | Path, output: str | Path) -> dict:
    return evaluate_study(spec, store, output)


def study_publish(evaluation: str | Path, store: str | Path, output: str | Path) -> dict:
    return publish_study(evaluation, store, output)


def dataset_build(
    release: str | Path,
    store: str | Path,
    output: str | Path,
    *,
    target: str,
    through_step: str,
    groups: str | Path | None = None,
) -> dict:
    return build_dataset(
        release,
        store,
        output,
        target=target,
        through_step=through_step,
        groups=groups,
    )


def model_train(dataset: str | Path, output: str | Path, *, ridge: float = 1.0) -> dict:
    return train_model(dataset, output, ridge=ridge)


def model_evaluate(
    model: str | Path,
    dataset: str | Path,
    output: str | Path,
    *,
    min_independent_designs: int = 3,
    min_families: int = 2,
    max_mae: float = 10.0,
    min_interval_coverage: float = 0.5,
) -> dict:
    return evaluate_model(
        model,
        dataset,
        output,
        min_independent_designs=min_independent_designs,
        min_families=min_families,
        max_mae=max_mae,
        min_interval_coverage=min_interval_coverage,
    )


def model_publish(model: str | Path, evaluation: str | Path, output: str | Path) -> dict:
    return publish_model(model, evaluation, output)


def model_predict(
    model_release: str | Path,
    case_id: str,
    store: str | Path,
    *,
    through_step: str | None = None,
) -> dict:
    return predict_case(model_release, case_id, store, through_step=through_step)


def model_advise(
    model_release: str | Path,
    dataset: str | Path,
    output: str | Path,
    *,
    limit: int = 10,
) -> dict:
    return advise_dataset(model_release, dataset, output, limit=limit)


def model_validate(
    model: str | Path,
    matrix: str | Path,
    output: str | Path,
    *,
    min_independent_designs: int = 3,
    min_families: int = 2,
    max_mae: float = 10.0,
    min_interval_coverage: float = 0.5,
    min_rank_accuracy: float = 0.5,
    family_holdout: bool = False,
) -> dict:
    return validate_matrix(
        model,
        matrix,
        output,
        min_independent_designs=min_independent_designs,
        min_families=min_families,
        max_mae=max_mae,
        min_interval_coverage=min_interval_coverage,
        min_rank_accuracy=min_rank_accuracy,
        family_holdout=family_holdout,
    )


def model_promote(model_release: str | Path, registry: str | Path) -> dict:
    return promote_model_release(model_release, registry)


def model_rollback(registry: str | Path, release_id: str | None = None) -> dict:
    return rollback_model_release(registry, release_id)


def model_registry(registry: str | Path) -> dict:
    return model_registry_status(registry)


def model_seed_sweep(
    project: str | Path, advice: str | Path, model_release: str | Path, name: str
) -> dict:
    return seed_sweep(project, advice, model_release, name)


def dataset_split(
    dataset: str | Path,
    output: str | Path,
    *,
    by: str = "design",
    seed: str = "0",
    validation_fraction: float = 0.2,
    test_fraction: float = 0.2,
) -> dict:
    return split_dataset(
        dataset,
        output,
        by=by,
        seed=seed,
        validation_fraction=validation_fraction,
        test_fraction=test_fraction,
    )


def dse_report(plan: str | Path, result: str | Path, output: str | Path) -> dict:
    return report_dse(plan, result, output)


def dse_compare(
    plan: str | Path,
    result: str | Path,
    other_plan: str | Path,
    other_result: str | Path,
    output: str | Path,
) -> dict:
    from ecc_experience.dse.compare import compare_runs

    return compare_runs(plan, result, other_plan, other_result, output)


def collect(workspace: str | Path, store: str | Path) -> CollectionResult:
    return collect_committed_case(workspace, ExperienceStore(store), read_workspace_observation)


def list_cases(store: str | Path) -> list[ExperienceCase]:
    repository = ExperienceStore(store)
    return [repository.read(case_id) for case_id in repository.list_ids()]


def show(case_id: str, store: str | Path) -> ExperienceCase:
    return ExperienceStore(store).read(case_id)


def features(case_id: str, store: str | Path, *, through_step: str | None = None) -> dict:
    return case_features(case_id, store, through_step=through_step)


def match(
    case_id: str,
    store: str | Path,
    *,
    release: str | Path,
    through_step: str,
    limit: int = 10,
    experimental_cross_design: bool = False,
    groups: str | Path | None = None,
) -> dict:
    return match_cases(
        case_id,
        store,
        release=release,
        through_step=through_step,
        limit=limit,
        experimental_cross_design=experimental_cross_design,
        groups=groups,
    )


def verify(case_id: str, store: str | Path) -> Verification:
    repository = ExperienceStore(store)
    return verify_case(repository.read(case_id), repository.case_directory(case_id))


def enable(project: str | Path, store: str | Path):
    return set_enabled(project, store=store, enabled=True)


def disable(project: str | Path):
    return disable_recording(project)


def status(project: str | Path) -> dict:
    return recording_status(project)


def drain(project: str | Path, *, limit: int = 32) -> list[dict]:
    return drain_recording(project, limit=limit)


def validate_campaign(manifest: str | Path) -> dict:
    _validated, summary = load_manifest(manifest)
    return summary


def campaign_create(spec: str | Path, output: str | Path) -> dict:
    from ecc_experience.benchmark.create import create_campaign

    return create_campaign(spec, output)


def campaign_report(
    manifest: str | Path, output: str | Path, *, ledger: str | Path | None = None
) -> dict:
    from ecc_experience.benchmark.report import report_campaign

    return report_campaign(manifest, output, ledger)


def benchmark_matrix(
    inputs: str | Path,
    expected: list[str],
    output: str | Path,
    families: dict[str, str] | None = None,
) -> dict:
    from ecc_experience.benchmark.matrix import aggregate

    return aggregate(inputs, expected, output, families)


def benchmark_readiness(
    matrix: str | Path,
    output: str | Path,
    *,
    min_independent_designs: int = 3,
    min_families: int = 2,
    min_candidate_configurations: int = 2,
) -> dict:
    from ecc_experience.benchmark.readiness import check

    return check(
        matrix,
        output,
        min_independent_designs=min_independent_designs,
        min_families=min_families,
        min_candidate_configurations=min_candidate_configurations,
    )


def campaign_archive(manifest: str | Path, report: str | Path, output: str | Path) -> dict:
    from ecc_experience.benchmark.archive import create

    return create(manifest, report, output)


def campaign_effect(
    report: str | Path,
    output: str | Path,
    baselines: dict[str, str] | None = None,
) -> dict:
    from ecc_experience.benchmark.effect import compare

    return compare(report, output, baselines)


def validate_benchmark_spec(spec: str | Path) -> dict:
    from ecc_experience.benchmark.spec import validate

    return validate(spec)


def prepare_benchmark(spec: str | Path, output: str | Path) -> dict:
    from ecc_experience.benchmark.plan import materialize

    return materialize(spec, output)


def run_campaign(manifest: str | Path, *, retry_failed: bool = False) -> dict:
    return execute_campaign(manifest, retry_failed=retry_failed)


def init_campaign(manifest: str | Path, ledger: str | Path | None = None) -> dict:
    return initialize_campaign(manifest, ledger)


def record_trial(
    ledger: str | Path,
    *,
    design_id: str,
    workspace: str,
    status: str,
    trial_id: str | None = None,
    case_id: str | None = None,
    reason: str | None = None,
) -> dict:
    return record_campaign_trial(
        ledger,
        design_id=design_id,
        workspace=workspace,
        status=status,
        trial_id=trial_id,
        case_id=case_id,
        reason=reason,
    )


def campaign_status(manifest: str | Path, ledger: str | Path | None = None) -> dict:
    return read_campaign_status(manifest, ledger)


def recommend(
    workspace: str | Path,
    store: str | Path,
    *,
    limit: int = 10,
    release: str | Path | None = None,
) -> dict:
    return recommend_cases(workspace, store, limit=limit, release=release)


def campaign_summary(manifest: str | Path, ledger: str | Path | None = None) -> dict:
    return summarize_campaign(manifest, ledger)


def campaign_quality(manifest: str | Path, ledger: str | Path | None = None) -> dict:
    return read_campaign_quality(manifest, ledger)


def recover_campaign(manifest: str | Path, *, trial_id: str) -> dict:
    return recover_campaign_attempt(manifest, trial_id=trial_id)


def dse_plan(
    project: str | Path,
    workspace: str | Path,
    store: str | Path,
    output: str | Path,
    *,
    parameters: list[str] | None = None,
    through_step: str = "",
    metric: str = "",
    unit: str = "",
    direction: str = "minimize",
    limits: dict | None = None,
    release: str | Path | None = None,
    spec: str | Path | None = None,
) -> dict:
    if spec is not None:
        from ecc_experience.dse.plan import invalid
        from ecc_experience.dse.version2 import plan_version2

        if (
            parameters
            or through_step
            or metric
            or unit
            or limits
            or release
            or direction != "minimize"
        ):
            raise invalid("Use either a version 2 spec or legacy grid arguments")
        return plan_version2(project, workspace, store, output, spec=spec)
    return plan_dse(
        project,
        workspace,
        store,
        output,
        parameters=parameters or [],
        through_step=through_step,
        metric=metric,
        unit=unit,
        direction=direction,
        limits=limits or {},
        release=release,
    )


def dse_run(
    plan: str | Path,
    output: str | Path,
    *,
    model_release: str | Path | None = None,
    resume: bool = False,
    select: str | None = None,
) -> dict:
    return run_dse(plan, output, model_release=model_release, resume=resume, select=select)


def plan(
    workspace: str | Path,
    store: str | Path,
    output: str | Path,
    *,
    limit: int = 10,
    release: str | Path | None = None,
    optimization: OptimizationLimits | None = None,
) -> dict:
    return write_plan(
        output,
        build_plan(workspace, store, limit=limit, release=release, optimization=optimization),
    )


def optimize(
    project: str | Path, plan_path: str | Path, store: str | Path, output: str | Path
) -> dict:
    return execute_optimization(project, plan_path, store, output)


def evaluate(baseline: str, candidate: str, store: str | Path) -> dict:
    return evaluate_cases(baseline, candidate, store)


def release_create(case_ids: list[str], store: str | Path, output: str | Path) -> dict:
    return create_release(case_ids, store, output)


def release_verify(release: str | Path, store: str | Path) -> dict:
    return verify_release(release, store)


def package_export(
    store: str | Path,
    output: str | Path,
    *,
    case_ids: list[str] | None = None,
    release: str | Path | None = None,
) -> dict:
    return export_package(store, output, case_ids=case_ids, release=release)


def package_import(package: str | Path, store: str | Path) -> dict:
    return import_package(package, store)
