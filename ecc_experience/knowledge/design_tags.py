"""Normalize explicitly sourced design tags; names alone never confirm structure."""

from ecc_experience.models import DesignTag


def design_tags(facts: dict) -> list[DesignTag]:
    specification = facts.get("workspaceSpec", {})
    design = specification.get("design", {}) if isinstance(specification, dict) else {}
    values = design.get("tags", []) if isinstance(design, dict) else []
    explicit = facts.get("designTags")
    if isinstance(explicit, list):
        values = [*values, *explicit] if isinstance(values, list) else explicit
    if not isinstance(values, list):
        return []
    result: list[DesignTag] = []
    seen: set[str] = set()
    for value in values[:128]:
        if isinstance(value, str):
            name = value.strip()
            source, confidence = "spec", "low"
        elif isinstance(value, dict):
            name = value.get("name")
            source = value.get("source", "spec")
            confidence = value.get("confidence", "low")
        else:
            continue
        if (
            not isinstance(name, str)
            or not name.strip()
            or source not in {"user", "spec", "synthesis", "ai"}
            or confidence not in {"high", "medium", "low"}
        ):
            continue
        name = name.strip()[:128]
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        result.append(DesignTag(name=name, source=source, confidence=confidence))
    return result


def memory_identity(facts: dict) -> dict:
    specification = facts.get("workspaceSpec", {})
    design = specification.get("design", {}) if isinstance(specification, dict) else {}
    value = design if isinstance(design, dict) else {}
    memory = value.get("memory", {})
    memory = memory if isinstance(memory, dict) else {}
    implementation = memory.get("implementation", value.get("memoryImplementation", "unknown"))
    if implementation not in {"register", "mapped_macro", "mixed", "unknown"}:
        implementation = "unknown"
    return {
        "memory_implementation": implementation,
        "memory_bits": _nonnegative_int(memory.get("bits", value.get("memoryBits"))),
        "macro_count": _nonnegative_int(memory.get("macroCount", value.get("macroCount"))),
    }


def _nonnegative_int(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None
