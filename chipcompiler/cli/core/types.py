from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from chipcompiler.cli.project.config import ProjectConfig


class OutputMode(Enum):
    TEXT = "text"
    PLAIN = "plain"
    JSON = "json"


@dataclass(frozen=True)
class CommandContext:
    project_dir: str
    project: str | None
    run_dir: str
    run_id: str | None
    output_mode: OutputMode
    config_error: str | None = None
    config: ProjectConfig | None = None
    # project.json manifest state: "manifest" | "legacy" | "virgin" | None
    project_state: str | None = None
    manifest_error: str | None = None
    # ``--workspace`` may be either a managed ID or an absolute external path.
    workspace_path_explicit: bool = False


@dataclass(frozen=True)
class CommandResult:
    records: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    exit_code: int = 0

    @staticmethod
    def ok(records: list[dict[str, Any]]) -> "CommandResult":
        return CommandResult(records=tuple(records), exit_code=0)

    @staticmethod
    def err(records: list[dict[str, Any]], exit_code: int = 1) -> "CommandResult":
        return CommandResult(records=tuple(records), exit_code=exit_code)
