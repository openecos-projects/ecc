"""Structural contract every flow-step tool module satisfies.

A tool module is a package under ``chipcompiler/tools/`` exposing the five
module-level functions below. The protocol is structural: modules satisfy
it with zero annotation changes, and the formal conformance test
(``test/formal/test_tool_module_contract.py``) is the executable teeth —
the type checker does not enforce the structural protocol.
"""

import inspect
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, TypeVar, runtime_checkable

from chipcompiler.data import Workspace, WorkspaceStepBase
from chipcompiler.data.step_config_reads import ConfigRead

StepT = TypeVar("StepT", bound=WorkspaceStepBase)


@runtime_checkable
class ToolModule(Protocol[StepT]):
    """The surface of a flow-step tool module: five functions and its config reads.

    StepT binds the step type produced by ``build_step`` to the one
    consumed by ``build_step_space``/``build_step_config``/``run_step``:
    each tool module is ``ToolModule[ItsStep]``, so the per-tool narrowing
    never fights contravariance; orchestrating consumers use
    ``ToolModule[Any]``.
    """

    #: Step name -> the workspace configs (and fields) the step reads; see
    #: :mod:`chipcompiler.data.step_config_reads`.
    STEP_CONFIG_READS: Mapping[str, tuple[ConfigRead, ...]]

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
        *,
        step_directory: Path | None = None,
    ) -> StepT: ...

    @staticmethod
    def build_step_space(step: StepT) -> None: ...

    @staticmethod
    def build_step_config(workspace: Workspace, step: StepT) -> None: ...

    @staticmethod
    def run_step(workspace: Workspace, step: StepT, ecc_module: object | None = None) -> bool: ...


def tool_module_members() -> list[str]:
    """Every member a tool module must define: the functions and its config reads."""
    return [*tool_module_functions(), "STEP_CONFIG_READS"]


def tool_module_functions() -> dict[str, inspect.Signature]:
    """The contract's member functions and their declared signatures."""
    return {
        name: inspect.signature(member)
        for name, member in inspect.getmembers(ToolModule, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
