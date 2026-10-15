"""Equal-budget paired receipts without inferring cross-design effectiveness."""

from pathlib import Path

from ecc_experience.dse.plan import invalid, read_dse_plan
from ecc_experience.dse.report2 import summarize_version2
from ecc_experience.files import file_digest, read_json
from ecc_experience.optimization.plan import write_plan


def compare_runs(plan, result, other_plan, other_result, output) -> dict:
    plans = [read_dse_plan(path)[0] for path in (plan, other_plan)]
    if any(item["schema"] != "ecc-experience-stage-dse-plan/2" for item in plans):
        raise invalid("Equal-budget comparison requires version 2 DSE plans")
    keys = (
        "snapshot_digest",
        "input_content_fingerprint",
        "process",
        "runtime",
        "project_configuration",
        "space",
        "objectives",
        "rungs",
        "limits",
    )
    if any(plans[0][key] != plans[1][key] for key in keys):
        raise invalid(
            "Paired runs require identical source, environment, space, objectives, "
            "rungs and budgets"
        )
    paths = [Path(path).expanduser().resolve() for path in (result, other_result)]
    if paths[0] == paths[1]:
        raise invalid("Paired comparison requires two different executions")
    summaries = [
        summarize_version2(frozen, read_json(path))
        for frozen, path in zip(plans, paths, strict=True)
    ]
    identities = [{row["run_id"] for row in summary["trials"]} for summary in summaries]
    if identities[0] & identities[1]:
        raise invalid("Paired runs reuse execution evidence")
    payload = {
        "schema": "ecc-experience-dse-comparison/1",
        "status": "observed_only",
        "exit_code": 0,
        "pairs": [
            {
                "plan_fingerprint": frozen["plan_fingerprint"],
                "result_sha256": file_digest(path)[0],
                "strategy": frozen["strategy"],
                "warm_start_status": frozen["warm_start"]["status"],
                "status": summary["status"],
                "budget": summary["budget"],
                "score_delta": summary["score_delta"],
                "pareto_front": summary["pareto_front"],
            }
            for frozen, path, summary in zip(plans, paths, summaries, strict=True)
        ],
        "generalization_status": "unproven",
        "benefit_status": "not_established",
        "safe_to_apply": False,
        "limitations": [
            "Equal caps do not imply equal completed trials or measured runtime",
            "This receipt does not establish statistical benefit or family independence",
        ],
    }
    destination = Path(output).expanduser().absolute()
    if (
        destination.exists()
        or destination.is_symlink()
        or any(
            destination.resolve().is_relative_to(Path(frozen[key]))
            for frozen in plans
            for key in ("store", "baseline_workspace")
        )
    ):
        raise invalid("Comparison output must be new and outside source and store")
    return write_plan(destination, payload)
