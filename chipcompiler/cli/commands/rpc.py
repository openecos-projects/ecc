from typing import Annotated

import typer

rpc_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
    help="Run the private ECC JSON-RPC runtime",
)


@rpc_app.command("serve", help="Serve the private ECC JSON-RPC runtime")
def serve_cmd(
    *,
    stdio: Annotated[
        bool,
        typer.Option("--stdio", help="Use Content-Length framed stdio transport."),
    ] = False,
    persistent_db: Annotated[
        bool,
        typer.Option(
            "--persistent-db",
            help="Enable explicit persistent DB lifecycle RPC methods.",
        ),
    ] = False,
) -> None:
    if not stdio:
        raise typer.BadParameter("--stdio is required", param_hint="--stdio")

    from chipcompiler.runtime.stdio_server import main

    raise typer.Exit(code=main(persistent_db_enabled=persistent_db))
