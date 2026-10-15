"""Bind DSE decisions and measurements to frozen plans and immutable cases."""

import re
from pathlib import Path

from ecc_experience.dse.evidence import stage_acceptance
from ecc_experience.dse.multiobjective import measure_objectives, rank_trials
from ecc_experience.dse.optimizer import propose
from ecc_experience.dse.plan import invalid
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.verify import verify_case
from ecc_experience.study.evidence import acceptance


def baseline_score(plan: dict, observed: dict) -> float | None:
    store = ExperienceStore(plan["store"])
    case = store.read(plan["baseline_case_id"])
    context = case.facts.get("experienceExecutionContext")
    if not isinstance(context, dict) or context.get("runtime") != plan["runtime"]:
        return None
    accepted = acceptance(case, store.case_directory(case.case_id))
    if observed["status"] != "passed" or accepted["status"] != "pass":
        return None
    if accepted["qor_score"] != observed.get("qor_score"):
        raise invalid("DSE baseline score differs from immutable evidence")
    return accepted["qor_score"]


def audit_trial(plan: dict, trial: dict, rung: dict | None) -> dict:
    workspace_id = trial.get("workspace_id", "")
    if not re.fullmatch(r"dse_[0-9a-f]{16}", workspace_id) or trial.get("workspace") != str(
        Path(plan["project"]) / workspace_id
    ):
        raise invalid("DSE trial workspace binding is invalid")
    parameters = trial["parameters"]
    if set(parameters) != set(plan["space"]) or any(
        value not in plan["space"][key] for key, value in parameters.items()
    ):
        raise invalid("DSE trial configuration is outside frozen space")
    case_id = trial.get("case_id")
    if not case_id:
        if trial.get("status") in {"stage_passed", "passed"}:
            raise invalid("Successful DSE trial requires immutable evidence")
        return {"status": "unknown", "case_id": None, "resources": []}
    store = ExperienceStore(plan["store"])
    case = store.read(case_id)
    checked = verify_case(case, store.case_directory(case_id))
    context = case.facts.get("experienceExecutionContext")
    specification = case.facts.get("workspaceSpec")
    flow = case.facts.get("flow")
    if (
        not isinstance(context, dict)
        or not isinstance(specification, dict)
        or not isinstance(flow, dict)
    ):
        raise invalid("DSE case lacks execution context, configuration or flow")
    observed = specification.get("parameters")
    if not isinstance(observed, dict):
        raise invalid("DSE case configuration is invalid")
    if checked.integrity != "pass" or (
        case.source.attempt_id != trial.get("run_id")
        or case.input_content_fingerprint != plan["input_content_fingerprint"]
        or case.process_fingerprint != plan["process"].get("fingerprint")
        or context.get("runtime") != plan["runtime"]
        or any(observed.get(key) != value for key, value in parameters.items())
    ):
        raise invalid("DSE evidence does not match frozen configuration and execution")
    if rung and trial["status"] == "stage_passed":
        first = rung["objectives"][0]
        accepted = stage_acceptance(
            case_id,
            plan["store"],
            {
                "through_step": rung["through_step"],
                "objective": {key: first[key] for key in ("id", "unit", "scope", "corner")},
            },
            exit_code=trial.get("exit_code", 1),
        )
        if accepted["status"] != "stage_passed":
            raise invalid("DSE stage acceptance does not match immutable evidence")
        measured = measure_objectives(
            case_id, plan["store"], rung["through_step"], rung["objectives"]
        )
        if measured["status"] != "available" or measured["values"] != trial.get("objective_values"):
            raise invalid("DSE objective values differ from immutable case evidence")
    if rung is None and trial["status"] == "passed":
        accepted = acceptance(case, store.case_directory(case_id))
        if accepted["status"] != "pass" or accepted["qor_score"] != trial.get("qor_score"):
            raise invalid("DSE full validation does not match immutable signoff and QoR")
    return {
        "status": checked.status,
        "case_id": case_id,
        "resources": [
            {"step": step["name"], "observation": step.get("resource_observation")}
            for step in flow.get("steps", [])
        ],
        "feedback_eligible": checked.status == "pass",
    }


def audit_history(plan: dict, result: dict) -> dict:
    if (
        result.get("schema") != "ecc-experience-stage-dse-result/2"
        or result.get("plan_fingerprint") != plan["plan_fingerprint"]
    ):
        raise invalid("DSE result is not bound to the frozen version 2 plan")
    history = []
    candidates = {}
    evidence = {}
    seen = set()
    previous_rung = 0
    for index, trial in enumerate(result["trials"]):
        rung_index = trial.get("rung")
        if (
            type(rung_index) is not int
            or not previous_rung <= rung_index < len(plan["rungs"])
            or trial.get("mode") != "screen"
        ):
            raise invalid("Invalid DSE rung identity")
        previous_rung = rung_index
        identity = (rung_index, trial.get("candidate_id"))
        if identity in seen:
            raise invalid("Duplicate DSE candidate within rung")
        seen.add(identity)
        if rung_index == 0:
            proposed, decision = propose(plan, history)
            if (
                proposed is None
                or trial.get("candidate_id") != proposed["candidate_id"]
                or trial.get("parameters") != proposed["parameters"]
                or trial.get("decision") != decision
            ):
                raise invalid("DSE optimizer history does not replay")
            candidates[proposed["candidate_id"]] = proposed
            history.append(trial)
        elif (
            trial.get("candidate_id") not in candidates
            or trial["parameters"] != candidates[trial["candidate_id"]]["parameters"]
        ):
            raise invalid("DSE rung candidate is not bound to the proposal history")
        if rung_index > 0:
            previous = [item for item in result["trials"][:index] if item["rung"] == rung_index - 1]
            ranking = rank_trials(previous, plan["rungs"][rung_index - 1]["objectives"])
            allowed = {
                row["id"] for row in ranking[: plan["rungs"][rung_index - 1]["promote_count"]]
            }
            if trial["candidate_id"] not in allowed:
                raise invalid("DSE candidate was not eligible for rung promotion")
        evidence[str(index)] = audit_trial(plan, trial, plan["rungs"][rung_index])
    for index, promotion in enumerate(result["promotions"]):
        if index >= len(plan["rungs"]) - 1:
            raise invalid("Invalid DSE promotion history")
        ranking = rank_trials(
            [trial for trial in result["trials"] if trial["rung"] == index],
            plan["rungs"][index]["objectives"],
        )
        if promotion != {
            "from_rung": index,
            "to_rung": index + 1,
            "candidate_ids": [
                row["id"] for row in ranking[: plan["rungs"][index]["promote_count"]]
            ],
            "ranking": ranking,
        }:
            raise invalid("DSE promotions differ from measured evidence")
    final = [trial for trial in result["trials"] if trial["rung"] == len(plan["rungs"]) - 1]
    front = [row["id"] for row in rank_trials(final, plan["objectives"]) if row["rank"] == 0]
    if "pareto_front" in result and result["pareto_front"] != front:
        raise invalid("DSE Pareto front differs from measured evidence")
    selection = result.get("selection")
    if selection and (
        selection.get("candidate") not in front
        or result.get("stage_winner")
        != next(trial for trial in final if trial["candidate_id"] == selection["candidate"])
        or len(result["promotions"]) != len(plan["rungs"]) - 1
    ):
        raise invalid("DSE selection is not bound to its measured final-stage winner")
    for field, mode in (("full_validation", "full"), ("fresh_validation", "fresh")):
        trial = result.get(field)
        if trial:
            if (
                not selection
                or trial.get("mode") != mode
                or trial.get("candidate_id") != selection["candidate"]
                or trial.get("candidate_id") not in candidates
                or trial["parameters"] != candidates[trial["candidate_id"]]["parameters"]
            ):
                raise invalid("DSE validation candidate differs from proposal history")
            evidence[field] = audit_trial(plan, trial, None)
    validations = [
        result[field] for field in ("full_validation", "fresh_validation") if result.get(field)
    ]
    records = [*result["trials"], *validations]
    if len(records) > plan["limits"]["max_trials"] or len(history) > plan["screening_trials"]:
        raise invalid("DSE result exceeds the frozen execution budget")
    if len({record["workspace_id"] for record in records}) != len(records) or len(
        {record["run_id"] for record in records}
    ) != len(records):
        raise invalid("DSE attempts require independent workspace and run identities")
    if (result["status"] == "complete") != (result.get("exit_code") == 0):
        raise invalid("DSE success status and exit code disagree")
    if result["status"] == "complete":
        if len(validations) != 2 or any(trial["status"] != "passed" for trial in validations):
            raise invalid("DSE completion requires full and independent fresh acceptance")
        score = baseline_score(plan, result["baseline_evidence"])
        delta = result["fresh_validation"]["qor_score"] - score if score is not None else None
        if result.get("score_delta") != delta or result.get("improved") != (
            delta > 0 if delta is not None else None
        ):
            raise invalid("DSE improvement claim differs from verified evidence")
    return {"candidates": candidates, "evidence": evidence}
