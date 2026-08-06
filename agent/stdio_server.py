import sys

from chipcompiler.runtime.stdio_server import run_stdio_server

from .server import AgentRuntimeServer


def main(*, persistent_db_enabled: bool = False) -> int:
    return run_stdio_server(
        sys.stdin.buffer,
        sys.stdout.buffer,
        server=AgentRuntimeServer(persistent_db_enabled=persistent_db_enabled),
    )
