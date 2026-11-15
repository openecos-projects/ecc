"""Shared local PDK inventory commands. Never download or install tools."""

from pathlib import Path
from typing import Annotated, Literal

import typer

from chipcompiler.cli.core.apps import create_app
from chipcompiler.pdk.registry import inventory_transaction, register, relocate, set_default

from .pdk_configure import _failure, _print

library_app = create_app(help="Manage the local PDK library shared with Studio")


@library_app.command("list")
def list_installations() -> None:
    try:
        with inventory_transaction() as inventory:
            _print(inventory)
    except (ValueError, OSError) as exc:
        _failure(exc)


@library_app.command("import")
def import_installation(root: Annotated[Path, typer.Option(exists=True, file_okay=False)]) -> None:
    try:
        _print(register(root))
    except (ValueError, OSError) as exc:
        _failure(exc)


@library_app.command("default")
def default(
    installation: Annotated[str, typer.Option()],
    client: Annotated[Literal["ecc", "studio"], typer.Option()] = "ecc",
) -> None:
    try:
        set_default(installation, client)
        _print({"client": client, "installation": installation})
    except (ValueError, OSError) as exc:
        _failure(exc)


@library_app.command("locate")
def locate(
    installation: Annotated[str, typer.Option()],
    root: Annotated[Path, typer.Option(exists=True, file_okay=False)],
) -> None:
    try:
        _print(relocate(installation, root))
    except (ValueError, OSError) as exc:
        _failure(exc)
