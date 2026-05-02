from dataclasses import dataclass, field
from enum import Enum


class OutputMode(Enum):
    TEXT = "text"
    JSON = "json"
    JSONL = "jsonl"


@dataclass(frozen=True)
class CommandContext:
    project_dir: str
    project: str | None
    run_dir: str
    run_id: str | None
    output_mode: OutputMode


@dataclass(frozen=True)
class CommandResult:
    records: tuple[dict, ...] = field(default_factory=tuple)
    exit_code: int = 0

    @staticmethod
    def ok(records: list[dict]) -> "CommandResult":
        return CommandResult(records=tuple(records), exit_code=0)

    @staticmethod
    def err(records: list[dict], exit_code: int = 1) -> "CommandResult":
        return CommandResult(records=tuple(records), exit_code=exit_code)
