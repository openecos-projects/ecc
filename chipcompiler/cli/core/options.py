from typing import Annotated

import typer

ProjectOption = Annotated[str | None, typer.Option("--project")]
PlainOption = Annotated[bool, typer.Option("--plain")]
JsonOption = Annotated[bool, typer.Option("--json")]
WorkspaceOption = Annotated[
    str | None,
    typer.Option("--workspace", help="Managed workspace name in the selected project"),
]
