"""Machine-readable description authoring API shared with Studio."""

import json
from pathlib import Path
from typing import Annotated

import typer

from chipcompiler.cli.core.apps import create_app
from chipcompiler.pdk.configuration import discover_resources, replace_field
from chipcompiler.pdk.documents import document_digest, split_descriptor
from chipcompiler.pdk.managed import (
    import_configuration,
    publish_configuration,
    read_configuration,
    save_configuration,
    source_path,
)
from chipcompiler.pdk.manifest import (
    Descriptor,
    DescriptorError,
    check_release,
    file_digest,
    load_descriptor,
    release_version,
    resource_path,
)
from chipcompiler.pdk.validation import validate_resources

configure_app = create_app(
    help="Manage PDK descriptions and ECC adaptations without modifying PDK resources"
)
Root = Annotated[Path, typer.Option(exists=True, file_okay=False, resolve_path=True)]
Output = Annotated[
    Path | None,
    typer.Option(
        help="ECC configuration path outside the PDK; resources remain relative to --root"
    ),
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
    from chipcompiler.pdk.documents import EccAdaptation, PdkDescription

    for name, prop in result["properties"].items():
        owner = "PDK description" if name in PdkDescription.model_fields else "ECC adaptation"
        prop["description"] = f"{owner}. " + prop.get("description", "")
    result["x-pdk-description-schema"] = PdkDescription.model_json_schema()
    result["x-ecc-adaptation-schema"] = EccAdaptation.model_json_schema()
    _print(result)


@configure_app.command("init")
def initialize(root: Root, family: Annotated[str, typer.Option()], output: Output = None) -> None:
    """Create an incomplete draft without guessing a process or overwriting files."""
    try:
        path, revision = save_configuration(
            root,
            split_descriptor(Descriptor(family_id=family, release=release_version(root) or "")),
            create=True,
            output=output,
        )
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
        path = source_path(root, output)
        if output is None and not path.exists():
            from chipcompiler.pdk.profiles import detect_release

            configuration = detect_release(root)
        else:
            configuration = read_configuration(path)
        descriptor = configuration.resolved()
        check_release(root, descriptor.release)
        resources = {
            name: {"role": resource.role, "path": str(resource_path(root, resource))}
            for name, resource in descriptor.resources.items()
        }
        _print(
            {
                "descriptor": descriptor.model_dump(),
                "revision": file_digest(path) if path.exists() else None,
                "path": str(path) if path.exists() else None,
                "description": configuration.description.model_dump(),
                "adaptation": configuration.adaptation.model_dump(),
                "description_digest": document_digest(configuration.description),
                "adaptation_digest": document_digest(configuration.adaptation),
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
        descriptor = replace_field(load_descriptor(root, output), field, json.loads(value_json))
        configuration = split_descriptor(descriptor)
        if output is None:
            path, revision = publish_configuration(
                root, configuration, expected_revision=expected_revision, draft=True
            )
        else:
            path, revision = save_configuration(
                root, configuration, expected_revision=expected_revision, output=output
            )
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


@configure_app.command("import")
def import_documents(
    root: Root,
    description: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    adaptation: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    expected_revision: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Import vendor facts and optional ECC policy, splitting legacy combined files."""
    try:
        path, revision = import_configuration(
            root, description, adaptation, expected_revision=expected_revision
        )
        _print({"path": str(path), "revision": revision})
    except (ValueError, OSError) as exc:
        _failure(exc)


@configure_app.command("export-description")
def export_description(root: Root) -> None:
    """Print only portable PDK facts for the PDK maintainer to publish."""
    try:
        _print(split_descriptor(load_descriptor(root)).description.model_dump())
    except (ValueError, OSError) as exc:
        _failure(exc)


@configure_app.command("export-adaptation")
def export_adaptation(root: Root) -> None:
    """Print ECC policy separately; never publish it as the PDK description."""
    try:
        _print(split_descriptor(load_descriptor(root)).adaptation.model_dump())
    except (ValueError, OSError) as exc:
        _failure(exc)


@configure_app.command("adopt")
def adopt(root: Root) -> None:
    """Copy vendor metadata into ECC management; existing local edits are retained."""
    from chipcompiler.pdk.managed import adopt_configuration

    try:
        path = adopt_configuration(root)
        _print({"path": str(path), "revision": file_digest(path)})
    except (ValueError, OSError) as exc:
        _failure(exc)
