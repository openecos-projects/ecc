"""ECC-owned descriptions and adaptations; PDK roots are read-only inputs."""

import hashlib
import json
from pathlib import Path

from chipcompiler.utility.workspace_lock import workspace_lock

from .configuration import write_descriptor
from .documents import (
    EccAdaptation,
    ManagedConfiguration,
    PdkDescription,
    document_digest,
    split_descriptor,
)
from .manifest import DESCRIPTOR_FILENAME, Descriptor, DescriptorError, file_digest


def configuration_path(root: Path) -> Path:
    from .registry import inventory_path

    key = hashlib.sha256(str(root.expanduser().resolve()).encode()).hexdigest()
    return inventory_path().parent / "pdk-configurations" / key / "configuration.json"


def source_path(root: Path, explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    managed = configuration_path(root)
    return managed if managed.exists() else root / DESCRIPTOR_FILENAME


def read_configuration(path: Path) -> ManagedConfiguration:
    if not path.is_file():
        raise DescriptorError(
            "pdk_descriptor_missing",
            f"PDK description is missing: {path}; use ecc pdk configure init --root <PDK-root>",
        )
    try:
        data = json.loads(path.read_bytes())
        if isinstance(data, dict) and "description" in data:
            return ManagedConfiguration.model_validate(data)
        if isinstance(data, dict) and data.get("schema_version") == 2:
            description = PdkDescription.model_validate(data)
            return ManagedConfiguration(
                description=description,
                adaptation=EccAdaptation(description_digest=document_digest(description)),
            )
        # Version-one packages and project snapshots are explicit migration inputs.
        return split_descriptor(Descriptor.model_validate(data))
    except (ValueError, OSError) as exc:
        raise DescriptorError("pdk_descriptor_invalid", f"{path}: {exc}") from exc


def save_configuration(
    root: Path,
    configuration: ManagedConfiguration,
    *,
    expected_revision: str | None = None,
    create: bool = False,
    output: Path | None = None,
    import_new: bool = False,
) -> tuple[Path, str]:
    destination = output or configuration_path(root)
    if destination.resolve().is_relative_to(root.resolve()):
        raise DescriptorError(
            "pdk_read_only", "ECC configuration must be stored outside the PDK root"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    # The shared lock is reentrant, so the revision check and atomic writer
    # participate in one transaction, including concurrent first imports.
    with workspace_lock(destination.parent):
        source = source_path(root, output)
        if import_new and destination.exists():
            raise DescriptorError("already_exists", "managed configuration already exists")
        if create and source.exists():
            raise DescriptorError("already_exists", f"configuration already exists: {source}")
        if expected_revision is not None and (
            not source.is_file() or file_digest(source) != expected_revision
        ):
            raise DescriptorError(
                "revision_conflict", "configuration changed; reload before saving"
            )
        revision = write_descriptor(destination, configuration)
    return destination, revision


def import_configuration(
    root: Path, description: Path, adaptation: Path | None, *, expected_revision: str | None = None
) -> tuple[Path, str]:
    configuration = read_configuration(description)
    if adaptation is not None:
        configuration = ManagedConfiguration(
            description=configuration.description,
            adaptation=EccAdaptation.model_validate_json(adaptation.read_bytes()),
        )
    elif expected_revision and json.loads(description.read_bytes()).get("schema_version") == 2:
        current = read_configuration(source_path(root))
        if (current.description.family_id, current.description.release) != (
            configuration.description.family_id,
            configuration.description.release,
        ):
            raise DescriptorError(
                "release_mismatch", "resource updates must match the installed release"
            )
        configuration = ManagedConfiguration(
            description=configuration.description,
            adaptation=current.adaptation.model_copy(
                update={"description_digest": document_digest(configuration.description)}
            ),
        )
    else:
        from .profiles import default_for

        configuration = default_for(root, configuration)
    return publish_configuration(root, configuration, expected_revision=expected_revision)


def publish_configuration(
    root: Path,
    configuration: ManagedConfiguration,
    *,
    expected_revision: str | None,
    draft: bool = False,
) -> tuple[Path, str]:
    destination = configuration_path(root)
    if destination.exists() and expected_revision is None:
        raise DescriptorError(
            "already_exists",
            "managed configuration exists; pass --expected-revision from configure show",
        )
    from .catalog import shared_sta_catalog
    from .documents import process_identity
    from .manifest import content_identity
    from .registry import inventory_transaction

    descriptor = configuration.resolved()
    with inventory_transaction() as inventory:
        record = next(
            (r for r in inventory["installations"] if r["root"] == str(root.resolve())), None
        )
        if draft and record is None:
            return save_configuration(root, configuration, expected_revision=expected_revision)
        if expected_revision is not None and (
            not source_path(root).is_file() or file_digest(source_path(root)) != expected_revision
        ):
            raise DescriptorError(
                "revision_conflict", "configuration changed; reload before saving"
            )
        if record and record["familyId"] != descriptor.family_id:
            raise DescriptorError(
                "family_mismatch", "configuration must match the installed PDK family"
            )
        digest, hashes = content_identity(root, descriptor)
        shared_sta_catalog(root, descriptor)
        result = save_configuration(
            root,
            configuration,
            expected_revision=expected_revision,
            import_new=expected_revision is None,
        )
        if record:
            record.update(
                contentDigest=digest,
                pdkDigest=process_identity(descriptor, hashes),
                adaptationDigest=document_digest(configuration.adaptation),
                configurationPath=str(result[0]),
            )
        return result


def adopt_configuration(root: Path) -> Path:
    """Copy an upstream description into ECC management once, without rewriting it."""
    destination = configuration_path(root)
    if not destination.exists():
        from .profiles import default_for

        source = root / DESCRIPTOR_FILENAME
        revision = file_digest(source) if source.exists() else None
        if source.exists():
            configuration = default_for(root, read_configuration(source))
        else:
            from .profiles import detect_release

            configuration = detect_release(root)
        try:
            save_configuration(root, configuration, import_new=True, expected_revision=revision)
        except DescriptorError as exc:
            if exc.code != "already_exists":
                raise
    from .catalog import shared_sta_catalog

    shared_sta_catalog(root, read_configuration(destination).resolved())
    return destination


def legacy_identity(root: Path, descriptor: Descriptor, hashes: dict[str, str]) -> str | None:
    """Verify an old inventory identity while keeping process and policy separate."""
    from .manifest import execution_identity

    source = root / DESCRIPTOR_FILENAME
    if not source.is_file():
        return None
    try:
        original = read_configuration(source)
    except DescriptorError:
        return None
    if original.description != split_descriptor(descriptor).description:
        return None
    # The caller has validated the same declared resources and their hashes.
    return execution_identity(original.resolved(), hashes)
