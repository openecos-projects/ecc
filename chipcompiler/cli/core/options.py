from typing import Annotated

import typer

ProjectOption = Annotated[str | None, typer.Option("--project")]
JsonOption = Annotated[bool, typer.Option("--json")]
JsonlOption = Annotated[bool, typer.Option("--jsonl")]
PlainOption = Annotated[bool, typer.Option("--plain")]
WorkspaceOption = Annotated[
    str | None,
    typer.Option("--workspace", help="Managed workspace name in the selected project"),
]
