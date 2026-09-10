from typing import Annotated

import typer

ProjectOption = Annotated[str | None, typer.Option("--project")]
PlainOption = Annotated[bool, typer.Option("--plain")]
WorkspaceOption = Annotated[
    str | None,
    typer.Option("--workspace", help="Managed workspace name in the selected project"),
]
