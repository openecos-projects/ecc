"""Machine-readable description authoring API shared with Studio."""

import json
from pathlib import Path
from typing import Annotated

import typer

from chipcompiler.cli.core.apps import create_app
from chipcompiler.pdk.configuration import discover_resources, replace_field, write_descriptor
from chipcompiler.pdk.manifest import (
    DESCRIPTOR_FILENAME,
    Descriptor,
    DescriptorError,
    file_digest,
    load_descriptor,
    resource_path,
)
from chipcompiler.pdk.validation import validate_resources

configure_app = create_app(help="Create and edit a portable ecc-pdk.json description")
Root = Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)]
Output = Annotated[
    Path | None, typer.Option(help="Description path; resources remain relative to --root")
]


def _print(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


def _failure(exc: Exception) -> None:
    _print(
        {
            "error": {
                "code": exc.code if isinstance(exc, DescriptorError) else "invalid_configuration",
                "message": str(exc),
            }
        }
    )
    raise typer.Exit(2)


@configure_app.command("schema")
def schema() -> None:
    """Return the versioned JSON Schema for CLI and GUI editors."""
    from chipcompiler.pdk.tool_settings import ToolSettings

    result = Descriptor.model_json_schema()
    tools_schema = ToolSettings.model_json_schema()
    result.setdefault("$defs", {}).update(tools_schema.pop("$defs", {}))
    result["properties"]["tools"] = tools_schema
    _print(result)


@configure_app.command("init")
def initialize(root: Root, family: Annotated[str, typer.Option()], output: Output = None) -> None:
    """Create an incomplete draft without guessing a process or overwriting files."""
    try:
        path = output or root / DESCRIPTOR_FILENAME
        revision = write_descriptor(path, Descriptor(family_id=family), create=True)
        _print({"path": str(path), "revision": revision, "state": "draft"})
    except (ValueError, OSError) as exc:
        _failure(exc)


@configure_app.command("discover")
def discover(root: Root) -> None:
    """List resource candidates; selection and roles require explicit configuration."""
    try:
        _print({"candidates": discover_resources(root)})
    except (ValueError, OSError) as exc:
        _failure(exc)


@configure_app.command("show")
def show(root: Root, output: Output = None) -> None:
    try:
        path = output or root / DESCRIPTOR_FILENAME
        descriptor = load_descriptor(root, path)
        resources = {
            name: {"role": resource.role, "path": str(resource_path(root, resource))}
            for name, resource in descriptor.resources.items()
        }
        _print(
            {
                "descriptor": descriptor.model_dump(),
                "revision": file_digest(path),
                "resolved_resources": resources,
            }
        )
    except (ValueError, OSError) as exc:
        _failure(exc)


@configure_app.command("set")
def set_field(
    root: Root,
    field: Annotated[str, typer.Option()],
    value_json: Annotated[str, typer.Option(help="JSON value, not shell syntax")],
    expected_revision: Annotated[str, typer.Option(help="Revision returned by show/init")],
    output: Output = None,
) -> None:
    try:
        path = output or root / DESCRIPTOR_FILENAME
        descriptor = replace_field(load_descriptor(root, path), field, json.loads(value_json))
        revision = write_descriptor(path, descriptor, expected_digest=expected_revision)
        _print({"path": str(path), "revision": revision, **validate_resources(root, descriptor)})
    except (ValueError, OSError) as exc:
        _failure(exc)


@configure_app.command("validate")
def validate(root: Root, output: Output = None) -> None:
    """Validate resources; this does not certify backend support or signoff."""
    try:
        result = validate_resources(root, load_descriptor(root, output))
        _print(result)
        if result["diagnostics"]:
            raise typer.Exit(2)
    except (ValueError, OSError) as exc:
        _failure(exc)


@configure_app.command("resolve")
def resolve(root: Root, output: Output = None) -> None:
    """Return content identity and resolved physical units for client consumers."""
    from chipcompiler.pdk.context import resolved_context

    try:
        _print(resolved_context(root, load_descriptor(root, output)))
    except (ValueError, OSError) as exc:
        _failure(exc)
