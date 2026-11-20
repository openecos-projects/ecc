"""Structured default-profile API shared by CLI and Studio."""

from pathlib import Path
from typing import Annotated

import typer

from chipcompiler.cli.core.apps import create_app
from chipcompiler.pdk.documents import document_digest
from chipcompiler.pdk.profiles import (
    apply_profile,
    catalog,
    find_profile,
    profile_configuration,
)

from .configure import Root, _failure, _print

profiles_app = create_app(help="Inspect or apply bundled ECC default adaptations")


@profiles_app.command("list")
def list_profiles() -> None:
    try:
        entries = []
        for profile in catalog():
            configuration = profile_configuration(profile)
            entries.append(
                {
                    "id": profile.id,
                    "family_id": configuration.description.family_id,
                    "data_version": profile.id,
                    "release": configuration.description.release,
                    "profile_revision": configuration.adaptation.profile_revision,
                    "description_digests": profile.description_digests,
                    "compatibility": configuration.adaptation.tools.get("compatibility", {}),
                }
            )
        _print({"profiles": entries})
    except (ValueError, OSError) as exc:
        _failure(exc)


@profiles_app.command("show")
def show_profile(profile: Annotated[str, typer.Option()]) -> None:
    try:
        configuration = profile_configuration(find_profile(profile))
        _print(
            {
                **configuration.model_dump(),
                "description_digest": document_digest(configuration.description),
                "adaptation_digest": document_digest(configuration.adaptation),
            }
        )
    except (ValueError, OSError) as exc:
        _failure(exc)


@profiles_app.command("apply")
def apply(
    root: Root,
    profile: Annotated[str, typer.Option()],
    expected_revision: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Change the defaults used when a workspace is created."""
    try:
        path, revision = apply_profile(Path(root), profile, expected_revision)
        _print({"path": str(path), "revision": revision, "profile": profile})
    except (ValueError, OSError) as exc:
        _failure(exc)
