"""Which workspace configs a flow step reads, as each tool declares them.

Every flow-step tool package declares ``STEP_CONFIG_READS`` (see
:class:`chipcompiler.tools.protocol.ToolModule`): for each step it runs, the
workspace configs (``config/<key>_ecc.json``) the step reads, each narrowed to
the fields it reads when it reads only part of a shared config. Run preflight
and ``ecc config`` use the config keys; parameter invalidation also matches
the fields, so a parameter reruns only the steps that read what it writes.
"""

import importlib
from collections.abc import Sequence
from typing import NamedTuple


class ConfigRead(NamedTuple):
    """A workspace config a step reads; an empty *path* reads the whole file."""

    key: str
    path: tuple[str, ...] = ()

    def overlaps(self, key: str, path: Sequence[str]) -> bool:
        """Whether a write to *key* at JSON *path* changes what this read sees."""
        shared = min(len(self.path), len(path))
        return key == self.key and tuple(path[:shared]) == self.path[:shared]


def step_config_reads(step: str, tool: str | None) -> tuple[ConfigRead, ...]:
    """The configs *step* reads when *tool* runs it; none for an unknown pair."""
    from chipcompiler.tools.registry import FLOW_TOOLS, tool_spec

    spec = tool_spec(tool)
    if spec is None or tool not in FLOW_TOOLS:
        return ()
    package = importlib.import_module(f"chipcompiler.tools.{spec.module}")
    return tuple(package.STEP_CONFIG_READS.get(step, ()))


def step_config_keys(step: str, tool: str | None) -> tuple[str, ...]:
    """The config keys *step* reads when *tool* runs it, in declaration order."""
    return tuple(dict.fromkeys(read.key for read in step_config_reads(step, tool)))
