"""Bundled, exact-content default adaptations. Never infer policy from a name."""

import json
from pathlib import Path

from pydantic import Field

from .compatibility import ecc_compatible
from .documents import ManagedConfiguration, document_digest
from .manifest import DescriptorError, StrictModel, content_identity, file_digest

PROFILE_DIRECTORY = Path(__file__).parent / "profiles"


class Profile(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    description_digests: list[str]
    description: str
    adaptation: str


def catalog() -> list[Profile]:
    data = json.loads((PROFILE_DIRECTORY / "index.json").read_text())
    if data.get("schema_version") != 1:
        raise DescriptorError("schema_unsupported", "unsupported bundled profile catalog")
    return [Profile.model_validate(entry) for entry in data["profiles"]]


def profile_configuration(profile: Profile) -> ManagedConfiguration:
    from .documents import EccAdaptation, PdkDescription

    def read(name: str) -> bytes:
        path = (PROFILE_DIRECTORY / name).resolve()
        if not path.is_relative_to(PROFILE_DIRECTORY.resolve()):
            raise DescriptorError("unsafe_path", "profile document escapes catalog")
        return path.read_bytes()

    return ManagedConfiguration(
        description=PdkDescription.model_validate_json(read(profile.description)),
        adaptation=EccAdaptation.model_validate_json(read(profile.adaptation)),
    )


def find_profile(profile_id: str) -> Profile:
    for profile in catalog():
        if profile.id == profile_id:
            return profile
    raise DescriptorError("profile_missing", f"unknown default profile: {profile_id}")


def matching_profile(configuration: ManagedConfiguration) -> Profile | None:
    digest = document_digest(configuration.description)
    matches = [p for p in catalog() if digest in p.description_digests]
    if len(matches) > 1:
        raise DescriptorError("profile_ambiguous", "multiple defaults match this description")
    return matches[0] if matches else None


def validated_default(root: Path, profile: Profile) -> ManagedConfiguration:
    configuration = profile_configuration(profile)
    ecc_compatible(configuration.adaptation.tools)
    # All bundled resource identities must be pinned. Validate contents before
    # publishing anything in management, including explicitly selected v1 roots.
    if not all(resource.sha256 for resource in configuration.description.resources.values()):
        raise DescriptorError("profile_invalid", "bundled resources must have content hashes")
    content_identity(root, configuration.resolved())
    return configuration


def default_for(root: Path, configuration: ManagedConfiguration) -> ManagedConfiguration:
    """First import only: preserve any explicit or legacy adaptation policy."""
    from .documents import EccAdaptation

    empty = EccAdaptation(description_digest=document_digest(configuration.description))
    if configuration.adaptation != empty:
        return configuration
    profile = matching_profile(configuration)
    return validated_default(root, profile) if profile else configuration


def apply_profile(root: Path, profile_id: str, expected_revision: str | None) -> tuple[Path, str]:
    """Explicitly initialize missing metadata or update new-project defaults."""
    from .managed import configuration_path, read_configuration, save_configuration, source_path

    profile = find_profile(profile_id)
    source = source_path(root)
    exists = source.exists()
    if exists:
        current = read_configuration(source)
        if document_digest(current.description) not in profile.description_digests:
            raise DescriptorError("profile_mismatch", "profile does not match the PDK description")
        if configuration_path(root).exists() and expected_revision is None:
            raise DescriptorError(
                "revision_required", "reload configure show and supply its revision"
            )
        # Also pin a vendor source while publishing its first managed configuration.
        expected_revision = expected_revision or file_digest(source)
    elif expected_revision is not None:
        raise DescriptorError("revision_conflict", "configuration no longer exists")
    configuration = validated_default(root, profile)
    from .documents import process_identity
    from .registry import inventory_transaction

    # A reviewed description may add resources, changing the immutable process
    # identity. Do not leave a registered installation pointing at different facts.
    with inventory_transaction() as inventory:
        registered = next(
            (r for r in inventory["installations"] if r["root"] == str(root.resolve())), None
        )
        if registered:
            descriptor = configuration.resolved()
            digest, hashes = content_identity(root, descriptor)
            current = (
                process_identity(descriptor, hashes) if registered.get("pdkDigest") else digest
            )
            previous = registered.get("pdkDigest") or registered.get("contentDigest")
            if previous and previous != current:
                raise DescriptorError(
                    "content_mismatch",
                    "profile changes registered process metadata; import a separate PDK root "
                    "to preserve existing installation bindings",
                )
        return save_configuration(
            root,
            configuration,
            expected_revision=expected_revision,
            create=not exists,
        )
