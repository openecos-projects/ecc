"""Public dataclasses and constants for the signoff package collector."""

from dataclasses import dataclass, field

from chipcompiler.data import StepEnum

SIGNOFF_REQUIRED_QOR_STEPS = {
    StepEnum.HARDEN.value,
    StepEnum.RCX.value,
    StepEnum.STA.value,
    StepEnum.DRC.value,
    StepEnum.LVS.value,
    StepEnum.FILLER.value,
    StepEnum.ROUTING.value,
}


@dataclass(frozen=True)
class SignoffPackageOptions:
    output_dir: str | None = None
    archive: bool = True
    include_debug: bool = False
    allow_incomplete: bool = False
    materialize: bool = True
    refresh_analysis: bool = False


@dataclass
class SignoffPackageResult:
    ok: bool
    package_dir: str
    archive_path: str | None = None
    manifest_path: str | None = None
    summary_path: str | None = None
    copied: list[dict] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    issues: list["SignoffPackageIssue"] = field(default_factory=list)


@dataclass(frozen=True)
class SignoffPackageIssue:
    kind: str
    label: str
    location: str
    reason: str
    required: bool
    destination: str
