from pathlib import Path

from ecc_experience.files import digest, read_json
from ecc_experience.knowledge.release import create_release, verify_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError
from ecc_experience.study.evaluate import evaluate_study
from ecc_experience.study.spec import check_output, invalid, load_spec, resolve


def publish_study(report_path: str | Path, store: str | Path, output: str | Path) -> dict:
    report = read_json(Path(report_path).expanduser())
    identity = {
        key: value
        for key, value in report.items()
        if key not in {"evaluated_at", "evaluation_fingerprint"}
    }
    if (
        report.get("schema") != "ecc-experience-study-evaluation/1"
        or report.get("evaluation_fingerprint") != digest(identity)
        or not isinstance(report.get("spec"), str)
    ):
        raise invalid("Study evaluation report is invalid or changed")
    current = evaluate_study(report["spec"], store)
    if report["evaluation_fingerprint"] != current["evaluation_fingerprint"]:
        raise ExperienceError("Study evidence changed", code="experience_source_changed")
    if current["status"] != "pass" or not current["feedback"]:
        raise ExperienceError(
            "Verified, isolated feedback and a passing evaluation are required",
            code="experience_release_unverified",
        )
    spec, root, _fingerprint = load_spec(report["spec"])
    frozen = verify_release(resolve(root, spec.release), store)
    destination = Path(output).expanduser().absolute()
    if (
        destination == resolve(root, spec.release)
        or destination == Path(report_path).expanduser().absolute()
        or destination.exists()
        or destination.is_symlink()
    ):
        raise invalid("K+1 release must be a new file outside K and the evaluation report")
    if destination.resolve().is_relative_to(Path(store).expanduser().resolve()):
        raise invalid("K+1 release must be outside the evidence store")
    selected = sorted(
        {item["case_id"] for item in frozen["cases"]}
        | {item["case_id"] for item in current["feedback"]}
    )
    check_output(
        destination,
        ExperienceStore(store),
        set(selected)
        | {
            case_id
            for pair in spec.pairs
            for case_id in (pair.baseline_case_id, pair.candidate_case_id)
        },
    )
    result = create_release(selected, store, destination)
    return {
        **result,
        "previous_release_id": frozen["release_id"],
        "evaluation_fingerprint": current["evaluation_fingerprint"],
        "scope": "verified_observations_only",
        "heldout_cases_included": False,
    }
