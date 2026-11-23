"""Separate portable process facts from ECC-owned execution policy.

Descriptor remains the version-one resolved snapshot contract for existing
projects and tool adapters. It is not the format to publish in a new PDK.
"""

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from .manifest import CellRoles, CellVariant, Descriptor, LibraryView, Resource, StrictModel
from .tool_settings import ToolSettings


class PdkDescription(StrictModel):
    schema_version: Literal[2] = 2
    family_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    release: str = ""
    resources: dict[str, Resource] = Field(default_factory=dict)
    cell_catalog: list[CellVariant] = Field(default_factory=list)
    views: dict[str, LibraryView] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self):
        Descriptor.model_validate({**self.model_dump(), "schema_version": 1})
        return self


class EccAdaptation(StrictModel):
    schema_version: Literal[1] = 1
    # Exact description binding, never a family-name heuristic.
    description_digest: str
    profile_revision: str = "1"
    cells: CellRoles = Field(default_factory=CellRoles)
    synthesis_libraries: list[str] = Field(default_factory=list)
    tools: dict[str, dict] = Field(default_factory=dict)
    parameters: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_settings(self):
        ToolSettings.model_validate(self.tools)
        json.dumps(self.parameters, allow_nan=False)
        return self


def document_digest(document: StrictModel) -> str:
    return hashlib.sha256(
        json.dumps(document.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ManagedConfiguration(StrictModel):
    schema_version: Literal[1] = 1
    description: PdkDescription
    adaptation: EccAdaptation

    @model_validator(mode="after")
    def validate_binding(self):
        if self.adaptation.description_digest != document_digest(self.description):
            raise ValueError("ECC adaptation does not match the PDK description")
        self.resolved()
        return self

    def resolved(self) -> Descriptor:
        policy = self.adaptation.model_dump(exclude={"schema_version", "description_digest"})
        return Descriptor.model_validate(
            {**self.description.model_dump(), "schema_version": 1, **policy}
        )


def split_descriptor(descriptor: Descriptor) -> ManagedConfiguration:
    data = descriptor.model_dump()
    facts = {name: data[name] for name in PdkDescription.model_fields if name != "schema_version"}
    description = PdkDescription.model_validate(facts)
    policy = {
        name: data[name]
        for name in EccAdaptation.model_fields
        if name not in {"schema_version", "description_digest"}
    }
    adaptation = EccAdaptation(description_digest=document_digest(description), **policy)
    return ManagedConfiguration(description=description, adaptation=adaptation)


def process_identity(descriptor: Descriptor, hashes: dict[str, str]) -> str:
    if not hashes:
        return hashlib.sha256(
            json.dumps([descriptor.family_id, descriptor.release]).encode()
        ).hexdigest()
    description = split_descriptor(descriptor).description
    payload = {"description": description.model_dump(), "resources": hashes}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
