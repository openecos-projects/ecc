"""Executable constraints for the single-owner hardcode rules.

The guard scans first-party sources (``chipcompiler/``, excluding
``thirdparty/``) for three regressions:

* a frozen ``<step>_<tool>`` directory literal outside its owner table,
* a builder-owned artifact file name outside a builder or a listed consumer,
* a direct ``.tool == "<literal>"`` comparison instead of ``ToolName``.

Every allowlist entry names its reason. Adding one requires editing this file,
so the list grows only deliberately and shrinks as consumers migrate.
"""

import ast
from pathlib import Path

import chipcompiler
from chipcompiler.data.step import (
    DUAL_STEP_DIRECTORIES,
    LEGACY_STEP_DIRECTORIES,
    STEP_DIRECTORIES,
    step_storage_name,
)
from chipcompiler.data.types import SkippableStepEnum, ToolName

_PACKAGE_ROOT = Path(chipcompiler.__file__).resolve().parent

_STEP_DIRECTORY_LITERALS = frozenset(
    {
        *STEP_DIRECTORIES.values(),
        *LEGACY_STEP_DIRECTORIES.values(),
        *DUAL_STEP_DIRECTORIES.values(),
        f"{step_storage_name(SkippableStepEnum.TIMING_OPT.value, ToolName.SIZER.value)}"
        f"_{ToolName.SIZER.value}",
    }
)

_ARTIFACT_NAMES = frozenset(
    {
        "qor_hotspots.json",
        "sta_timing_issues.json",
        "geometry.manifest",
        "subflow.json",
    }
)

_TOOL_NAMES = frozenset(member.value for member in ToolName)
# `lec_dual` is both a directory name and an engine/tool name; the engine
# vocabularies own that spelling, so it is not a directory violation.
_STEP_DIRECTORY_LITERALS = _STEP_DIRECTORY_LITERALS - _TOOL_NAMES

# Directory literals: the table in data/step.py owns them; the design-report
# display table is a contract vocabulary, not directory resolution.
_STEP_DIR_ALLOWLIST = {
    "engine/signoff/report_data.py": "design-report display-name canonicalization table",
}

# Artifact names: tools/*/builder.py produce them. Consumers that read the
# files without a WorkspaceStep are listed with their reason.
_ARTIFACT_ALLOWLIST = {
    "engine/analysis.py": "snapshot artifact index reads builder-owned leaves without steps",
    "cli/command_handlers/chipview.py": "CLI reads the exported geometry manifest directly",
}


def _is_builder(relative_path: str) -> bool:
    return relative_path.startswith("tools/") and relative_path.endswith("/builder.py")


def _tool_attribute(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "tool"


def _tool_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if node.value in _TOOL_NAMES else None
    return None


def scan(root: Path) -> list[tuple[str, int, str, str]]:
    """Return ``(module, line, rule, literal)`` violations under *root*."""
    violations: list[tuple[str, int, str, str]] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("thirdparty/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if relative not in {"data/step.py", *_STEP_DIR_ALLOWLIST}:
                    for name in _STEP_DIRECTORY_LITERALS:
                        if value == name or value.startswith(f"{name}/"):
                            violations.append((relative, node.lineno, "step-directory", value))
                            break
                if (
                    value in _ARTIFACT_NAMES
                    and not _is_builder(relative)
                    and relative not in _ARTIFACT_ALLOWLIST
                ):
                    violations.append((relative, node.lineno, "artifact-name", value))
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                for left, right in zip(operands[:-1], operands[1:], strict=True):
                    literal = _tool_literal(right if _tool_attribute(left) else left)
                    if literal is not None and (_tool_attribute(left) or _tool_attribute(right)):
                        violations.append((relative, node.lineno, "tool-comparison", literal))
    return violations


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_first_party_sources_follow_the_guard():
    assert scan(_PACKAGE_ROOT) == []


def test_guard_rejects_a_directory_literal_outside_the_owner(tmp_path):
    _write(tmp_path, "engine/consumer.py", 'DIR = "Harden_ecc"\n')

    assert scan(tmp_path) == [("engine/consumer.py", 1, "step-directory", "Harden_ecc")]


def test_guard_accepts_the_same_literal_in_the_owner_table(tmp_path):
    _write(tmp_path, "data/step.py", 'DIR = "Harden_ecc"\n')

    assert scan(tmp_path) == []


def test_guard_rejects_an_artifact_name_outside_a_builder(tmp_path):
    _write(tmp_path, "engine/consumer.py", 'NAME = "qor_hotspots.json"\n')
    _write(tmp_path, "tools/ecc/builder.py", 'NAME = "qor_hotspots.json"\n')

    assert scan(tmp_path) == [("engine/consumer.py", 1, "artifact-name", "qor_hotspots.json")]


def test_guard_rejects_a_tool_attribute_compared_with_a_string(tmp_path):
    _write(tmp_path, "engine/consumer.py", 'if step.tool == "ecc":\n    pass\n')

    assert scan(tmp_path) == [("engine/consumer.py", 1, "tool-comparison", "ecc")]


def test_guard_ignores_unrelated_strings(tmp_path):
    _write(
        tmp_path,
        "engine/consumer.py",
        'logger.info("output written to %s", path)\nNAME = "spindle"\n',
    )

    assert scan(tmp_path) == []


def test_guard_excludes_thirdparty(tmp_path):
    _write(tmp_path, "thirdparty/vendor.py", 'DIR = "Harden_ecc"\nNAME = "subflow.json"\n')

    assert scan(tmp_path) == []


def test_allowlists_stay_explicit_and_reasoned():
    assert set(_STEP_DIR_ALLOWLIST) == {"engine/signoff/report_data.py"}
    assert set(_ARTIFACT_ALLOWLIST) == {
        "engine/analysis.py",
        "cli/command_handlers/chipview.py",
    }
    assert all(reason for reason in _STEP_DIR_ALLOWLIST.values())
    assert all(reason for reason in _ARTIFACT_ALLOWLIST.values())
