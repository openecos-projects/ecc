"""Conservative configuration identity for comparing collected observations."""

from ecc_experience.files import digest
from ecc_experience.models import ExperienceCase


def configuration_identity(case: ExperienceCase) -> dict:
    specification = case.facts.get("workspaceSpec")
    parameters = specification.get("parameters") if isinstance(specification, dict) else None
    steps = _flow_identity(case.facts)
    context = case.facts.get("experienceExecutionContext")
    runtime = None
    if (
        isinstance(context, dict)
        and context.get("schema") == "ecc-experience-execution-context/1"
        and case.source.attempt_id
        and context.get("attempt_id") == case.source.attempt_id
        and isinstance(context.get("runtime"), dict)
    ):
        runtime = context["runtime"]
    identity = {
        "input_content_fingerprint": case.input_content_fingerprint,
        "process_fingerprint": case.process_fingerprint,
        "parameters": parameters if isinstance(parameters, dict) else None,
        "runtime": runtime,
        "flow": steps,
    }
    missing = [
        name
        for name, available in (
            ("input_content_fingerprint", bool(case.input_content_fingerprint)),
            ("process_fingerprint", bool(case.process_fingerprint)),
            ("parameters", isinstance(parameters, dict)),
            ("flow", bool(steps)),
        )
        if not available
    ]
    missing.extend(_runtime_gaps(runtime, steps or []))
    complete = not missing
    return {
        "key": digest(identity) if complete else case.case_id,
        "complete": complete,
        "missing_identity": missing,
        "identity": identity,
    }


def _flow_identity(facts: dict) -> list[dict[str, str]] | None:
    flow = facts.get("flow")
    steps = flow.get("steps") if isinstance(flow, dict) else None
    if not isinstance(steps, list) or not steps:
        return None
    result = []
    for step in steps:
        if not isinstance(step, dict):
            return None
        name = step.get("name")
        tool = step.get("tool")
        if not isinstance(name, str) or not name or not isinstance(tool, str) or not tool:
            return None
        result.append({"name": name, "tool": tool})
    return result


def _runtime_gaps(runtime: object, steps: list[dict[str, str]]) -> list[str]:
    if not isinstance(runtime, dict):
        return ["runtime"]
    missing = []
    if not isinstance(runtime.get("sources"), dict) or not runtime["sources"]:
        missing.append("runtime.sources")
    versions = runtime.get("tools")
    native = runtime.get("native_packages")
    if not isinstance(versions, dict) or not isinstance(native, dict):
        return [*missing, "runtime.tool_versions"]
    for tool in sorted({step["tool"] for step in steps}):
        distribution = {"ecc": "ecc-tools-bin", "dreamplace": "ecc-dreamplace"}.get(tool)
        version = native.get(distribution) if distribution else versions.get(tool)
        if not isinstance(version, str) or version.strip().casefold() in {
            "",
            "unknown",
            "not installed",
        }:
            missing.append(f"runtime.tool:{tool}")
    return missing
