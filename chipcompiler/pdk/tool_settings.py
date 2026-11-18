"""Version-one adapter configuration contracts exposed to package authors."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .compatibility import Compatibility


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class TimingSettings(ToolModel):
    default_view: str = ""
    signoff_view: str = ""


class ExtractionCorner(ToolModel):
    name: str
    temperature: list[float]
    spef_file: str


class ExtractionSettings(ToolModel):
    backend_id: Literal["native", "ics55"] | None = None
    corners: list[ExtractionCorner] = Field(default_factory=list)


class VtGroup(ToolModel):
    id: str = Field(pattern=r"^\S+$")
    suffix: str = Field(pattern=r"^\S+$")


class SizerSettings(ToolModel):
    hold_view: str = ""
    vt_groups: list[VtGroup] = Field(default_factory=list)


class BufferDrive(ToolModel):
    master: str = Field(pattern=r"^\S+$")
    strength: float = Field(gt=0)


class BufferSettings(ToolModel):
    drive_strengths: list[BufferDrive] = Field(default_factory=list)


class PrimitiveInstance(ToolModel):
    master: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    pins: dict[str, str]


class PrimitiveMapping(ToolModel):
    primitive: str = Field(pattern=r"^\$_(DLATCH_[NP]([NP][01])?|TBUF)_$")
    wires: list[str] = Field(default_factory=list)
    instances: list[PrimitiveInstance]


class SynthesisSettings(ToolModel):
    primitive_mappings: list[PrimitiveMapping] = Field(default_factory=list)


class ToolSettings(ToolModel):
    compatibility: Compatibility = Field(default_factory=Compatibility)
    configs: dict[str, dict] = Field(default_factory=dict)
    timing: TimingSettings = Field(default_factory=TimingSettings)
    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)
    sizer: SizerSettings = Field(default_factory=SizerSettings)
    buffering: BufferSettings = Field(default_factory=BufferSettings)
    synthesis: SynthesisSettings = Field(default_factory=SynthesisSettings)
