import multiprocessing
import sys

from agent.server import AgentRuntimeServer
from chipcompiler.runtime.stdio_server import run_stdio_server


def main() -> int:
    multiprocessing.freeze_support()
    return run_stdio_server(
        sys.stdin.buffer,
        sys.stdout.buffer,
        server=AgentRuntimeServer(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
