#!/usr/bin/env python

import json
import logging
import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from chipcompiler.utility.path import optional_path, path_list

logger = logging.getLogger(__name__)


@dataclass
class PDK:
    """
    Dataclass for PDK information
    """

    name: str = ""  # pdk name
    version: str = ""  # pdk version
    root: Path | None = None  # resolved pdk root path
    tech: Path | None = None  # pdk tech lef file
    lefs: list[Path] = field(default_factory=list[Path])  # pdk lef files
    libs: list[Path] = field(default_factory=list[Path])  # pdk liberty files
    mapping_file: Path | None = None  # pdk mapping file
    corners: list = field(default_factory=list)
    sdc: Path | None = None  # pdk sdc file
    spef: Path | None = None  # pdk spef file
    site_core: str = ""  # core site
    site_io: str = ""  # io site
    site_corner: str = ""  # corner site
    tap_cell: str = ""  # tap cell
    end_cap: str = ""  # end cap
    buffers: list[str] = field(default_factory=list[str])  # buffers
    fillers: list[str] = field(default_factory=list[str])  # fillers
    tie_high_cell: str = ""
    tie_high_port: str = ""
    tie_low_cell: str = ""
    tie_low_port: str = ""
    dont_use: list[str] = field(default_factory=list[str])  # don't use cell list
    abc_driver_cell: str = ""  # ABC driving cell
    abc_load: float = 0.015  # ABC output load
    sdc_load: float = 0.0  # output load (pF) for generated SDC; 0 omits set_load

    def __post_init__(self) -> None:
        self.root = optional_path(self.root)
        self.tech = optional_path(self.tech)
        self.lefs = path_list(self.lefs)
        self.libs = path_list(self.libs)
        self.mapping_file = optional_path(self.mapping_file)
        self.sdc = optional_path(self.sdc)
        self.spef = optional_path(self.spef)

    def validate(self) -> None:
        """Check that critical PDK paths exist. Raises ValueError if not."""
        errors = []
        if self.root and not self.root.is_dir():
            errors.append(f"PDK root directory not found: {self.root}")
        if not self.tech:
            errors.append("PDK tech LEF is missing")
        elif not self.tech.is_file():
            errors.append(f"PDK tech LEF not found: {self.tech}")
        if not self.lefs:
            errors.append("PDK has no LEF files")
        else:
            for lef in self.lefs:
                if not lef.is_file():
                    errors.append(f"PDK LEF not found: {lef}")
        if not self.libs:
            errors.append("PDK has no liberty files")
        else:
            for liberty in self.libs:
                if not liberty.is_file():
                    errors.append(f"PDK liberty file not found: {liberty}")
        _raise_pdk_validation_error(errors)


def _raise_pdk_validation_error(errors: list) -> None:
    if errors:
        msg = "PDK validation failed:\n  " + "\n  ".join(errors)
        logger.error(msg)
        raise ValueError(msg)


_DEFAULT_PDK = PDK()
_PROTECTED_FIELDS = {"name", "version"}

# Fields whose values are filesystem paths, derived from the dataclass
# annotations so CLI path resolution and override validation stay in sync
# with the field definitions.
PATH_SCALAR_FIELDS = {f.name for f in fields(PDK) if f.type == Path | None}
PATH_LIST_FIELDS = {f.name for f in fields(PDK) if f.type == list[Path]}
STRING_LIST_FIELDS = {f.name for f in fields(PDK) if f.type == list[str]}

# Path fields holding PDK content: relative override values resolve against
# the PDK root. sdc/spef are design data and stay project-relative; root is
# the resolution anchor itself.
PDK_CONTENT_PATH_FIELDS = {"tech", "lefs", "libs", "mapping_file"}

# Optional path fields not covered by PDK.validate() (which only checks the
# always-required root/tech/lefs/libs). When one of these is set through an
# override, get_pdk checks its existence so a bad configured path fails before
# a run; base and external PDKs are unaffected because the check is scoped to
# override-supplied keys only.
_OPTIONAL_PATH_LABELS = {
    "mapping_file": "PDK mapping file not found",
    "sdc": "PDK SDC file not found",
    "spef": "PDK SPEF file not found",
}


def apply_pdk_overrides(pdk: PDK, overrides: dict) -> PDK:
    """
    Apply field overrides to a PDK instance via whole-field replacement.

    Args:
        pdk: Base PDK instance
        overrides: Mapping of field names to new values

    Returns:
        New PDK instance with overrides applied

    Raises:
        ValueError: If unknown fields or type-invalid values are provided
    """
    if not overrides:
        return pdk

    all_fields = {f.name for f in fields(PDK)}
    # root is rejected below with its own guidance; keep it out of the
    # advertised set so the error matches the actual contract.
    overridable = sorted(all_fields - _PROTECTED_FIELDS - {"root"})
    unknown = sorted(set(overrides) - all_fields)

    if unknown:
        raise ValueError(
            f"unknown PDK override fields: {unknown}; valid overridable fields: {overridable}"
        )

    protected = sorted(set(overrides) & _PROTECTED_FIELDS)
    if protected:
        raise ValueError(
            f"PDK override fields {protected} cannot be overridden; "
            "use the appropriate built-in PDK name instead"
        )

    # root names the tree every other path field is resolved against; letting
    # an override retarget it after PDK construction would mix default content
    # paths from one tree with a root pointing at another.
    if "root" in overrides:
        raise ValueError("PDK override 'root' cannot be overridden; set pdk.root in [pdk] instead")

    for key, value in overrides.items():
        default = getattr(_DEFAULT_PDK, key)
        if isinstance(default, list):
            ok, kind = isinstance(value, list), "a list"
        elif isinstance(default, float):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            kind = "a number"
        else:
            ok, kind = isinstance(value, str), "a string"
        if not ok:
            raise ValueError(f"PDK override '{key}' must be {kind}, got {type(value).__name__}")
        # Path-list elements hit Path() in __post_init__; cell-name list
        # elements are written verbatim into generated tool configs. Reject
        # non-strings here with ValueError instead of escaping replace() as
        # TypeError or reaching tool input.
        if key in PATH_LIST_FIELDS | STRING_LIST_FIELDS and isinstance(value, list):
            for index, element in enumerate(value):
                if not isinstance(element, str):
                    raise ValueError(
                        f"PDK override '{key}' elements must be strings, "
                        f"got {type(element).__name__} at index {index}"
                    )

    return replace(pdk, **overrides)


def PDK_EXTERNAL(pdk_config: str | Path, pdk_name: str = "") -> PDK:
    data = _read_external_pdk_config(pdk_config)
    return _pdk_from_external_config(data, pdk_name)


def _read_external_pdk_config(pdk_config: str | Path) -> dict:
    with open(pdk_config, encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("external PDK JSON must be an object")
    return data


def _pdk_from_external_config(data: dict, pdk_name: str = "") -> PDK:
    requested_name = (pdk_name or "").strip()
    config_name = str(data.get("name", "")).strip()
    if requested_name and config_name and requested_name.lower() != config_name.lower():
        raise ValueError(
            f"PDK name mismatch: command line pdk={requested_name}, pdk_json.name={config_name}"
        )

    return PDK(
        name=config_name or requested_name,
        version=str(data.get("version", "")),
        root=optional_path(str(data.get("root", ""))),
        tech=optional_path(str(data.get("tech", ""))),
        lefs=data.get("lefs", []),
        libs=data.get("libs", []),
        mapping_file=optional_path(str(data.get("mapping_file", ""))),
        corners=data.get("corners", []),
        sdc=optional_path(str(data.get("sdc", ""))),
        spef=optional_path(str(data.get("spef", ""))),
        site_core=str(data.get("site_core", "")),
        site_io=str(data.get("site_io", "")),
        site_corner=str(data.get("site_corner", "")),
        tap_cell=str(data.get("tap_cell", "")),
        end_cap=str(data.get("end_cap", "")),
        buffers=data.get("buffers", []),
        fillers=data.get("fillers", []),
        tie_high_cell=str(data.get("tie_high_cell", "")),
        tie_high_port=str(data.get("tie_high_port", "")),
        tie_low_cell=str(data.get("tie_low_cell", "")),
        tie_low_port=str(data.get("tie_low_port", "")),
        dont_use=data.get("dont_use", []),
        abc_driver_cell=str(data.get("abc_driver_cell", "")),
        abc_load=float(data.get("abc_load", 0.015)),
        sdc_load=float(data.get("sdc_load", 0.0)),
    )


def _builtin_pdk(pdk_name: str, pdk_root: str | Path = "") -> PDK | None:
    if pdk_name == "ics55":
        return PDK_ICS55(pdk_root=pdk_root)
    if pdk_name == "sg13g2":
        return PDK_SG13G2(pdk_root=pdk_root)
    return None


def _merge_builtin_pdk_with_external_config(
    builtin: PDK,
    external: PDK,
    data: dict,
) -> PDK:
    """Overlay only explicitly configured external fields on a built-in PDK."""
    configured = {field.name for field in fields(PDK)} & set(data)
    configured -= {"name", "root"}
    return replace(builtin, **{field: getattr(external, field) for field in configured})


def get_pdk(
    pdk_name: str,
    pdk_root: str | Path = "",
    pdk_config: str | Path = "",
    overrides: dict | None = None,
) -> PDK:
    """
    Return the PDK instance based on the given pdk name.
    """
    pdk_name_normalized = (pdk_name or "").strip().lower()
    if pdk_config:
        external_data = _read_external_pdk_config(pdk_config)
        external_pdk = _pdk_from_external_config(
            data=external_data,
            pdk_name=pdk_name_normalized,
        )
        builtin = _builtin_pdk(
            external_pdk.name.lower(),
            pdk_root=external_pdk.root or pdk_root,
        )
        pdk = (
            _merge_builtin_pdk_with_external_config(builtin, external_pdk, external_data)
            if builtin is not None
            else external_pdk
        )
    else:
        pdk = _builtin_pdk(pdk_name_normalized, pdk_root=pdk_root) or PDK(name=pdk_name_normalized)
    overrides = overrides or {}
    pdk = apply_pdk_overrides(pdk, overrides)
    pdk.validate()
    errors = []
    for key, label in _OPTIONAL_PATH_LABELS.items():
        if key not in overrides:
            continue
        path = getattr(pdk, key)
        if path and not path.is_file():
            errors.append(f"{label}: {path}")
    _raise_pdk_validation_error(errors)
    return pdk


def PDK_ICS55(pdk_root: str | Path = "") -> PDK:
    root = Path(__file__).resolve().parents[2]
    default_pdk_root = root / "chipcompiler" / "thirdparty" / "icsprout55-pdk"

    # Resolve: explicit arg > env vars > default
    root_text = (
        str(pdk_root).strip()
        or os.environ.get("CHIPCOMPILER_ICS55_PDK_ROOT", "").strip()
        or os.environ.get("ICS55_PDK_ROOT", "").strip()
        or str(default_pdk_root)
    )
    resolved_root = Path(root_text).expanduser().resolve()
    stdcell_dir = resolved_root / "IP" / "STD_cell" / "ics55_LLSC_H7C_V1p10C100"

    tech_path = resolved_root / "prtech" / "techLEF" / "N551P6M_ecos.lef"
    lef_paths = [
        stdcell_dir / "ics55_LLSC_H7CR" / "lef" / "ics55_LLSC_H7CR_ecos.lef",
        stdcell_dir / "ics55_LLSC_H7CL" / "lef" / "ics55_LLSC_H7CL_ecos.lef",
    ]
    lib_paths = [
        (
            stdcell_dir
            / "ics55_LLSC_H7CR"
            / "liberty"
            / "ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib"
        ),
        (
            stdcell_dir
            / "ics55_LLSC_H7CL"
            / "liberty"
            / "ics55_LLSC_H7CL_ss_rcworst_1p08_125_nldm.lib"
        ),
    ]
    mapping_file = None
    corners = [
        {"name": "TYPICAL", "temperature": [25], "spef_file": "./TYP.spef"},
        {"name": "RCbest", "temperature": [-40, 125], "spef_file": "./RCbest.spef"},
        {"name": "RCworst", "temperature": [-40, 125], "spef_file": "./RCworst.spef"},
        {"name": "Cbest", "temperature": [-40, 125], "spef_file": "./Cbest.spef"},
        {"name": "Cworst", "temperature": [-40, 125], "spef_file": "./Cworst.spef"},
    ]

    pdk = PDK(
        name="ics55",
        version="V1p10C100",
        root=resolved_root,
        tech=tech_path if tech_path.is_file() else None,
        lefs=[path for path in lef_paths if path.is_file()],
        libs=[path for path in lib_paths if path.is_file()],
        mapping_file=mapping_file,
        corners=corners,
        site_core="core7",
        site_io="core7",
        site_corner="core7",
        tap_cell="FILLTAPH7R",
        end_cap="FILLTAPH7R",
        buffers=["BUFX8H7L", "BUFX12H7L", "BUFX16H7L", "BUFX20H7L"],
        fillers=[
            "FILLER64H7R",
            "FILLER32H7R",
            "FILLER16H7R",
            "FILLER8H7R",
            "FILLER4H7R",
            "FILLER2H7R",
            "FILLER1H7R",
        ],
        tie_high_cell="TIEHIH7R",
        tie_high_port="Z",
        tie_low_cell="TIELOH7R",
        tie_low_port="Z",
        abc_driver_cell="BUFX0P5H7R",
        abc_load=0.015,
        sdc_load=0.001,
        dont_use=[
            "DFFSRQX*",
            "DFFSRX*",
            "*AO222*",
            "*2BB2*",
            "*AOI222*",
            "*AOI33*",
            "*OA222*",
            "*OAI222*",
            "*OAI33*",
            "*NOR4*",
            "ICG*",
        ],
    )

    return pdk


def PDK_SG13G2(pdk_root: str | Path = "") -> PDK:
    root_text = (
        str(pdk_root).strip()
        or os.environ.get("CHIPCOMPILER_SG13G2_PDK_ROOT", "").strip()
        or os.environ.get("SG13G2_PDK_ROOT", "").strip()
    )
    resolved_root = Path(root_text).expanduser().resolve()

    tech_path = resolved_root / "libs.ref" / "sg13g2_stdcell" / "lef" / "sg13g2_tech.lef"
    lef_paths = [resolved_root / "libs.ref" / "sg13g2_stdcell" / "lef" / "sg13g2_stdcell.lef"]
    lib_paths = [
        (resolved_root / "libs.ref" / "sg13g2_stdcell" / "lib" / "sg13g2_stdcell_typ_1p20V_25C.lib")
    ]

    pdk = PDK(
        name="sg13g2",
        version="1.0",
        root=resolved_root,
        tech=tech_path if tech_path.is_file() else None,
        lefs=[path for path in lef_paths if path.is_file()],
        libs=[path for path in lib_paths if path.is_file()],
        site_core="CoreSite",
        buffers=["sg13g2_buf_1", "sg13g2_buf_2", "sg13g2_buf_4", "sg13g2_buf_8", "sg13g2_buf_16"],
        fillers=["sg13g2_fill_1", "sg13g2_fill_2", "sg13g2_decap_4", "sg13g2_decap_8"],
        tie_high_cell="sg13g2_tiehi",
        tie_high_port="L_HI",
        tie_low_cell="sg13g2_tielo",
        tie_low_port="L_LO",
        dont_use=["sg13g2_lgcp_1", "sg13g2_sighold", "sg13g2_slgcp_1", "sg13g2_dfrbp_2"],
    )

    return pdk
