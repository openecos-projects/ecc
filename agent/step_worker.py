"""Agent-flavored entry for the shared one-shot step worker."""

from functools import partial

from chipcompiler.engine.step_subprocess import run_step_worker
from chipcompiler.engine.worker import worker_main

from .engine import AgentEngineFlow
from .tools import run_step


def main() -> int:
    handler = partial(
        run_step_worker,
        flow_factory=AgentEngineFlow,
        tool_runner=run_step,
    )
    return worker_main(handler)


if __name__ == "__main__":
    raise SystemExit(main())
