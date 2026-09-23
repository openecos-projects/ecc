"""Structural contract every flow-step tool module satisfies.

A tool module is a package under ``chipcompiler/tools/`` exposing the five
module-level functions below. The protocol is structural: modules satisfy
it with zero annotation changes, and the formal conformance test
(``test/formal/test_tool_module_contract.py``) is the executable teeth —
CI runs no pyright over these boundaries.
"""

import inspect
from pathlib import Path
from typing import Protocol, TypeVar, runtime_checkable

from chipcompiler.data import Workspace, WorkspaceStepBase

StepT = TypeVar("StepT", bound=WorkspaceStepBase)


@runtime_checkable
class ToolModule(Protocol[StepT]):
    """The five-function surface of a flow-step tool module.

    StepT binds the step type produced by ``build_step`` to the one
    consumed by ``build_step_space``/``build_step_config``/``run_step``:
    each tool module is ``ToolModule[ItsStep]``, so the per-tool narrowing
    never fights contravariance; orchestrating consumers use
    ``ToolModule[Any]``.
    """

    @staticmethod
    def is_eda_exist() -> bool: ...

    @staticmethod
    def build_step(
        workspace: Workspace,
        step_name: str,
        input_def: Path | None,
        input_verilog: Path | None,
        input_db: Path | str | None = None,
        output_def: Path | None = None,
        output_verilog: Path | None = None,
        output_gds: Path | None = None,
    ) -> StepT: ...

    @staticmethod
    def build_step_space(step: StepT) -> None: ...

    @staticmethod
    def build_step_config(workspace: Workspace, step: StepT) -> None: ...

    @staticmethod
    def run_step(workspace: Workspace, step: StepT, ecc_module: object | None = None) -> bool: ...


def tool_module_functions() -> dict[str, inspect.Signature]:
    """The contract's member functions and their declared signatures."""
    return {
        name: inspect.signature(member)
        for name, member in inspect.getmembers(ToolModule, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
