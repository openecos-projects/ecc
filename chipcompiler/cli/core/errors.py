"""Handler-level command errors and their result conversion."""

from collections.abc import Callable
from functools import wraps

from chipcompiler.cli.core.types import CommandResult


class CommandError(Exception):
    """An error record set that a public handler returns as a failed result."""

    def __init__(self, records: list[dict], exit_code: int = 1):
        self.records = tuple(records)
        self.exit_code = exit_code
        super().__init__(f"command failed with exit code {exit_code}")

    @classmethod
    def from_result(cls, result: CommandResult) -> "CommandError":
        return cls(list(result.records), result.exit_code)


def command_handler(handler: Callable[..., CommandResult]) -> Callable[..., CommandResult]:
    """Convert a raised :class:`CommandError` into a failed handler result."""

    @wraps(handler)
    def wrapped(*args, **kwargs) -> CommandResult:
        try:
            return handler(*args, **kwargs)
        except CommandError as error:
            return CommandResult.err(list(error.records), error.exit_code)

    return wrapped
