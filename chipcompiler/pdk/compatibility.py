"""Execution requirements owned by an ECC adaptation, not by a process release."""

import json
import subprocess
from importlib.metadata import PackageNotFoundError, version
from typing import Literal

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import Field, field_validator

from .manifest import DescriptorError, StrictModel


class Compatibility(StrictModel):
    ecc: str = ""
    distributions: dict[Literal["ecc-tools-bin", "ecc-dreamplace"], str] = Field(
        default_factory=dict
    )
    sizer_vt_contract: Literal[1] | None = None

    @field_validator("ecc")
    @classmethod
    def valid_ecc(cls, value: str) -> str:
        SpecifierSet(value)
        return value

    @field_validator("distributions")
    @classmethod
    def valid_distributions(cls, value: dict) -> dict:
        for specifier in value.values():
            SpecifierSet(specifier)
        return value


def ecc_compatible(tools: dict) -> None:
    from chipcompiler import __version__

    spec = Compatibility.model_validate(tools.get("compatibility", {})).ecc
    if spec and not SpecifierSet(spec).contains(Version(__version__), prereleases=True):
        raise DescriptorError(
            "adapter_incompatible", f"adaptation requires ECC {spec}; running {__version__}"
        )


def runtime_issues(tools: dict, steps) -> list[str]:
    """Probe selected backends only; do not reject synthesis for an absent Sizer."""
    policy = Compatibility.model_validate(tools.get("compatibility", {}))
    issues = []
    try:
        ecc_compatible(tools)
    except DescriptorError as exc:
        issues.append(str(exc))
    selected = set(steps)
    dreamplace = {"macro_placement", "placement", "diff_sizing", "diff_opt", "legalization"}
    for distribution, spec in policy.distributions.items():
        if distribution == "ecc-dreamplace" and not selected & dreamplace:
            continue
        if not selected:
            continue
        try:
            actual = version(distribution)
            if not SpecifierSet(spec).contains(actual, prereleases=True):
                issues.append(f"adaptation requires {distribution}{spec}; found {actual}")
        except PackageNotFoundError:
            issues.append(f"adaptation requires {distribution}{spec}; distribution is missing")
    if policy.sizer_vt_contract and selected & {"preplace", "timing_optimization"}:
        from chipcompiler.tools.ecc_sizer.utility import get_sizer_command

        command = get_sizer_command()
        if not command:
            issues.append("adaptation requires Sizer explicit_vt_groups contract 1; Sizer missing")
        else:
            try:
                result = subprocess.run(
                    [*command, "--ecc-capabilities"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=True,
                )
                data = json.loads(result.stdout)
                if (
                    not isinstance(data, dict)
                    or data.get("schema_version") != 1
                    or data.get("tool") != "ecc-sizer"
                    or not isinstance(data.get("contracts"), dict)
                    or data.get("contracts", {}).get("explicit_vt_groups")
                    != policy.sizer_vt_contract
                ):
                    raise ValueError("explicit_vt_groups contract mismatch")
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                issues.append(
                    "adaptation requires a Sizer supporting --ecc-capabilities and "
                    f"explicit_vt_groups contract 1: {exc}"
                )
    return issues
