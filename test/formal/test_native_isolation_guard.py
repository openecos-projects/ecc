"""Keep native ECC initialization inside worker-side call sites."""

import ast
import subprocess
from pathlib import Path
from typing import NamedTuple

_ROOT = Path(__file__).parents[2]
_TARGETS = frozenset(
    {
        "ECCToolsModule",
        "create_db_engine",
        "init_db_engine",
        "init_db_engine_for_step",
        "init_db_engine_for_workspace_step",
    }
)

_ALLOWLIST = {
    ("chipcompiler.engine.step_subprocess", "run_step_worker"): "one-shot step handler",
    ("chipcompiler.engine.db", "create_db_engine"): "worker-side DB wrapper",
    ("chipcompiler.engine.flow", "init_db_engine_for_step"): "worker rebuilds one step DB",
    (
        "chipcompiler.engine.workspace_flow",
        "init_db_engine_for_workspace_step",
    ): "worker-side workspace DB helper",
    ("chipcompiler.tools.ecc.runner", "create_db_engine.load_data"): "worker DB snapshot load",
    ("chipcompiler.tools.ecc.runner", "create_db_engine.load_design"): "worker DB design load",
    ("chipcompiler.tools.ecc.runner", "get_eda_instance"): "tool execution inside worker",
    ("chipcompiler.tools.ecc.runner", "run_sta_without_spef"): "post-synthesis STA in worker",
    ("chipcompiler.tools.ecc.sta_parallel", "_run_corner"): "multiprocessing STA corner child",
    (
        "chipcompiler.tools.ecc.timing_constraints",
        "prepare_timing_context",
    ): "timing IO-cell context inside a tool's run_step",
    (
        "chipcompiler.tools.ecc_dreamplace.runner",
        "_run_placement_mode",
    ): "DreamPlace execution inside worker",
    (
        "chipcompiler.tools.ecc_dreamplace.runner",
        "legalize_layout",
    ): "Sizer legalization inside worker",
}


class NativeCall(NamedTuple):
    module: str
    function: str
    symbol: str
    line: int


class _Visitor(ast.NodeVisitor):
    def __init__(self, module):
        self.module = module
        self.scopes = []
        self.calls = []
        self.aliases = {}

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name in _TARGETS:
                self.aliases[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name in _TARGETS:
                self.aliases[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def _nested(self, node):
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        arguments = [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
            node.args.vararg,
            node.args.kwarg,
        ]
        for argument in arguments:
            if argument is not None and argument.annotation is not None:
                self.visit(argument.annotation)
        if node.returns is not None:
            self.visit(node.returns)
        self.scopes.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    visit_FunctionDef = _nested
    visit_AsyncFunctionDef = _nested

    def visit_Lambda(self, node):
        self.scopes.append("<lambda>")
        self.generic_visit(node)
        self.scopes.pop()

    def visit_Call(self, node):
        function = ".".join(self.scopes) or "<module>"
        if isinstance(node.func, ast.Name):
            symbol = self.aliases.get(node.func.id, node.func.id)
        elif isinstance(node.func, ast.Attribute):
            symbol = node.func.attr
        else:
            symbol = ""
        if symbol in _TARGETS:
            self.calls.append(NativeCall(self.module, function, symbol, node.lineno))
        self.generic_visit(node)


def _scan_paths(paths, root=_ROOT):
    calls = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        module = relative.removesuffix(".py").replace("/", ".")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _Visitor(module)
        visitor.visit(tree)
        calls.extend(visitor.calls)
    return calls


def _production_sources():
    completed = subprocess.run(
        ["git", "ls-files", "--", "*.py"],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        _ROOT / relative
        for relative in completed.stdout.splitlines()
        if not relative.startswith("test/")
        and not relative.startswith("agent/test/")
        and not relative.startswith("chipcompiler/thirdparty/")
    ]


def _scan(root):
    paths = [
        path
        for path in root.rglob("*.py")
        if "thirdparty" not in path.parts and "test" not in path.parts
    ]
    return _scan_paths(paths, root)


def _unexpected(calls):
    return sorted(call for call in calls if (call.module, call.function) not in _ALLOWLIST)


def _write(root, relative, source):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_native_initialization_is_limited_to_worker_call_sites():
    calls = _scan_paths(_production_sources())

    assert _unexpected(calls) == []
    assert {(call.module, call.function) for call in calls} == set(_ALLOWLIST)


def test_guard_rejects_new_function_in_allowlisted_module(tmp_path):
    _write(
        tmp_path,
        "chipcompiler/engine/flow.py",
        "def helper():\n    return create_db_engine(None, None)\n",
    )

    assert _unexpected(_scan(tmp_path)) == [
        NativeCall("chipcompiler.engine.flow", "helper", "create_db_engine", 2)
    ]


def test_guard_scans_other_first_party_packages(tmp_path):
    _write(
        tmp_path,
        "packaging/run_ecc.py",
        "def helper():\n    return create_db_engine(None, None)\n",
    )

    assert _unexpected(_scan(tmp_path)) == [
        NativeCall("packaging.run_ecc", "helper", "create_db_engine", 2)
    ]


def test_guard_rejects_import_time_initialization_in_default_argument(tmp_path):
    _write(
        tmp_path,
        "chipcompiler/tools/ecc/runner.py",
        "def get_eda_instance(ecc_module=ECCToolsModule()):\n    return ecc_module\n",
    )

    assert _unexpected(_scan(tmp_path)) == [
        NativeCall("chipcompiler.tools.ecc.runner", "<module>", "ECCToolsModule", 1)
    ]


def test_guard_rejects_parent_backtrack_initialization(tmp_path):
    _write(
        tmp_path,
        "chipcompiler/engine/rerun.py",
        "def _run_selected(flow, step):\n    flow.init_db_engine_for_step(step)\n",
    )

    assert _unexpected(_scan(tmp_path)) == [
        NativeCall("chipcompiler.engine.rerun", "_run_selected", "init_db_engine_for_step", 2)
    ]


def test_guard_resolves_agent_import_aliases(tmp_path):
    _write(
        tmp_path,
        "agent/workspace_api.py",
        "from chipcompiler.engine.workspace_flow import (\n"
        "    init_db_engine_for_workspace_step as _init_db,\n"
        ")\n"
        "def candidate(flow, step):\n"
        "    _init_db(flow, step)\n",
    )

    assert _unexpected(_scan(tmp_path)) == [
        NativeCall(
            "agent.workspace_api",
            "candidate",
            "init_db_engine_for_workspace_step",
            5,
        )
    ]
