"""Executable constraints for the single-owner hardcode rules.

The guard scans first-party sources (``chipcompiler/``, excluding
``thirdparty/``) for three regressions:

* a frozen ``<step>_<tool>`` directory literal outside its owner table,
* a builder-owned artifact file name outside its owning builder or a listed
  consumer,
* a direct ``.tool == "<literal>"`` comparison instead of ``ToolName``.

Every allowlist entry names its reason. The ceiling below is the set that
existed when the guard shipped; entries may be removed as consumers migrate but
the guard fails if one is added.
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

_ARTIFACT_OWNERS = {
    "qor_hotspots.json": {"tools/ecc/builder.py", "tools/yosys/builder.py"},
    "sta_timing_issues.json": {"tools/ecc/builder.py"},
    "geometry.manifest": {"tools/ecc/builder.py"},
    "subflow.json": {
        "tools/ecc/builder.py",
        "tools/yosys/builder.py",
        "tools/lec_dual/builder.py",
        "tools/kepler_formal/builder.py",
        "tools/yosys_lec/builder.py",
    },
}

_ARTIFACT_NAMES = frozenset(_ARTIFACT_OWNERS)

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

# Writers of home/flow.json. The ledger module is the one first-party writer;
# the other three are recovery/migration paths that intentionally do not load
# a Workspace (the plan's explicit exceptions).
_FLOW_WRITE_OWNERS = {
    "data/workspace/flow_ledger.py": "the schema-aware ledger writer",
    "engine/reconcile.py": "recovery path without a loaded Workspace",
    "engine/interrupted_run.py": "recovery path without a loaded Workspace",
    "cli/project/migrate_fs.py": "filesystem migration without a loaded Workspace",
}


def _tool_attribute(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "tool"


def _writes_the_ledger(call: ast.Call) -> bool:
    """Whether a ``json_write`` call targets the flow ledger."""
    if not isinstance(call.func, ast.Name) or call.func.id != "json_write":
        return False
    for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
        for child in ast.walk(argument):
            if isinstance(child, ast.Constant) and child.value == "flow.json":
                return True
            if isinstance(child, ast.Attribute) and child.attr == "path":
                target = child.value
                if isinstance(target, ast.Attribute) and target.attr == "flow":
                    return True
                if isinstance(target, ast.Name) and target.id == "flow":
                    return True
    return False


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
                    and relative not in _ARTIFACT_OWNERS[value]
                    and relative not in _ARTIFACT_ALLOWLIST
                ):
                    violations.append((relative, node.lineno, "artifact-name", value))
            if (
                isinstance(node, ast.Call)
                and _writes_the_ledger(node)
                and relative not in _FLOW_WRITE_OWNERS
            ):
                violations.append((relative, node.lineno, "ledger-write", "flow.json"))
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


def test_guard_rejects_an_artifact_name_outside_its_owner(tmp_path):
    _write(tmp_path, "engine/consumer.py", 'NAME = "qor_hotspots.json"\n')
    _write(tmp_path, "tools/ecc/builder.py", 'NAME = "qor_hotspots.json"\n')
    _write(tmp_path, "tools/lec_dual/builder.py", 'NAME = "qor_hotspots.json"\n')

    assert scan(tmp_path) == [
        ("engine/consumer.py", 1, "artifact-name", "qor_hotspots.json"),
        ("tools/lec_dual/builder.py", 1, "artifact-name", "qor_hotspots.json"),
    ]


def test_guard_rejects_a_direct_ledger_write_outside_the_owners(tmp_path):
    _write(
        tmp_path,
        "tools/example/module.py",
        "from chipcompiler.utility import json_write\n"
        "def reset(workspace):\n"
        "    json_write(workspace.flow.path, workspace.flow.data)\n",
    )
    _write(
        tmp_path,
        "engine/reconcile.py",
        "from chipcompiler.utility import json_write\n"
        'json_write(workspace_dir / "home" / "flow.json", data)\n',
    )

    assert scan(tmp_path) == [("tools/example/module.py", 3, "ledger-write", "flow.json")]


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


# Rule membership is part of the contract: an entry may move out of a list,
# never into a different rule's list.
_STEP_DIR_ALLOWLIST_CEILING = frozenset({"engine/signoff/report_data.py"})
_ARTIFACT_ALLOWLIST_CEILING = frozenset({"engine/analysis.py", "cli/command_handlers/chipview.py"})
_FLOW_WRITE_OWNERS_CEILING = frozenset(
    {
        "data/workspace/flow_ledger.py",
        "engine/reconcile.py",
        "engine/interrupted_run.py",
        "cli/project/migrate_fs.py",
    }
)


def test_allowlists_only_shrink_from_the_shipped_ceilings():
    assert set(_STEP_DIR_ALLOWLIST) <= _STEP_DIR_ALLOWLIST_CEILING
    assert set(_ARTIFACT_ALLOWLIST) <= _ARTIFACT_ALLOWLIST_CEILING
    assert set(_FLOW_WRITE_OWNERS) <= _FLOW_WRITE_OWNERS_CEILING
    assert all(reason for reason in _STEP_DIR_ALLOWLIST.values())
    assert all(reason for reason in _ARTIFACT_ALLOWLIST.values())
    assert all(reason for reason in _FLOW_WRITE_OWNERS.values())
