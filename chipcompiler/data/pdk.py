#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _optional_path(path: str | Path | None) -> Path | None:
    return Path(path) if path else None


def _path_list(paths: list) -> list[Path]:
    return [Path(path) for path in paths if path]


@dataclass
class PDK:
    """
    Dataclass for PDK information
    """
    name : str = "" # pdk name
    version : str = "" # pdk version
    root : Path | None = None # resolved pdk root path
    tech : Path | None = None # pdk tech lef file
    lefs : list = field(default_factory=list) # pdk lef files
    libs : list = field(default_factory=list) # pdk liberty files
    mapping_file : Path | None = None # pdk mapping file
    corners : list = field(default_factory=list) 
    sdc : Path | None = None # pdk sdc file
    spef : Path | None = None # pdk spef file
    site_core : str = "" # core site
    site_io : str = "" # io site
    site_corner : str = "" # corner site
    tap_cell : str = "" # tap cell
    end_cap : str = "" # end cap
    buffers : list = field(default_factory=list) # buffers
    fillers : list = field(default_factory=list) # fillers
    tie_high_cell : str = ""
    tie_high_port : str = ""
    tie_low_cell : str = ""
    tie_low_port : str = ""
    dont_use : list = field(default_factory=list) # don't use cell list
    abc_driver_cell : str = "" # ABC driving cell
    abc_load : float = 0.015 # ABC output load

    def __post_init__(self) -> None:
        self.root = _optional_path(self.root)
        self.tech = _optional_path(self.tech)
        self.lefs = _path_list(self.lefs)
        self.libs = _path_list(self.libs)
        self.mapping_file = _optional_path(self.mapping_file)
        self.sdc = _optional_path(self.sdc)
        self.spef = _optional_path(self.spef)

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
        if errors:
            msg = "PDK validation failed:\n  " + "\n  ".join(errors)
            logger.error(msg)
            raise ValueError(msg)

def PDK_EXTERNAL(pdk_config: str | Path, pdk_name: str = "") -> PDK:
    with open(pdk_config, encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("external PDK JSON must be an object")

    requested_name = (pdk_name or "").strip()
    config_name = str(data.get("name", "")).strip()
    if requested_name and config_name and requested_name.lower() != config_name.lower():
        raise ValueError(
            f"PDK name mismatch: command line pdk={requested_name}, "
            f"pdk_json.name={config_name}"
        )

    return PDK(
        name=config_name or requested_name,
        version=str(data.get("version", "")),
        root=str(data.get("root", "")),
        tech=str(data.get("tech", "")),
        lefs=data.get("lefs", []),
        libs=data.get("libs", []),
        mapping_file=str(data.get("mapping_file", "")),
        corners=data.get("corners", []),
        sdc=str(data.get("sdc", "")),
        spef=str(data.get("spef", "")),
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
    )

def get_pdk(
    pdk_name : str,
    pdk_root: str | Path = "",
    pdk_config: str | Path = "",
) -> PDK:
    """
    Return the PDK instance based on the given pdk name.
    """
    pdk_name_normalized = (pdk_name or "").strip().lower()
    if pdk_config:
        pdk = PDK_EXTERNAL(
            pdk_config=pdk_config,
            pdk_name=pdk_name_normalized,
        )
    elif pdk_name_normalized == "ics55":
        pdk = PDK_ICS55(pdk_root=pdk_root)
    elif pdk_name_normalized == "sg13g2":
        pdk = PDK_SG13G2(pdk_root=pdk_root)
    else:
        pdk = PDK(name=pdk_name_normalized)
    pdk.validate()
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
            stdcell_dir / "ics55_LLSC_H7CR" / "liberty"
            / "ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib"
        ),
        (
            stdcell_dir / "ics55_LLSC_H7CL" / "liberty"
            / "ics55_LLSC_H7CL_ss_rcworst_1p08_125_nldm.lib"
        ),
    ]
    mapping_file = None
    corners = [
        {
            "name" : "TYPICAL",
            "temperature" : [25],
            "spef_file" : "./TYP.spef"
        },
        {
            "name" : "RCbest",
            "temperature" : [-40, 125],
            "spef_file" : "./RCbest.spef"
        },
        {
            "name" : "RCworst",
            "temperature" : [-40, 125],
            "spef_file" : "./RCworst.spef"
        },
        {
            "name" : "Cbest",
            "temperature" : [-40, 125],
            "spef_file" : "./Cbest.spef"
        },
        {
            "name" : "Cworst",
            "temperature" : [-40, 125],
            "spef_file" : "./Cworst.spef"
        }
    ]

    pdk = PDK(
        name="ics55",
        version="V1p10C100",
        root=resolved_root,
        tech=tech_path if tech_path.is_file() else None,
        lefs=[path for path in lef_paths if path.is_file()],
        libs=[path for path in lib_paths if path.is_file()],
        mapping_file = mapping_file,
        corners=corners,
        site_core = "core7",
        site_io = "core7",
        site_corner = "core7",
        tap_cell = "FILLTAPH7R",
        end_cap = "FILLTAPH7R",
        buffers = [
            "BUFX8H7L",
            "BUFX12H7L",
            "BUFX16H7L",
            "BUFX20H7L"
        ],
        fillers = [
            "FILLER64H7R",
            "FILLER32H7R",
            "FILLER16H7R",
            "FILLER8H7R",
            "FILLER4H7R",
            "FILLER2H7R",
            "FILLER1H7R" 
        ],
        tie_high_cell = "TIEHIH7R",
        tie_high_port = "Z",
        tie_low_cell = "TIELOH7R",
        tie_low_port = "Z",
        abc_driver_cell = "BUFX0P5H7R",
        abc_load = 0.015,
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
            "ICG*"
        ]
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
    lef_paths = [
        resolved_root / "libs.ref" / "sg13g2_stdcell" / "lef" / "sg13g2_stdcell.lef"
    ]
    lib_paths = [
        (
            resolved_root / "libs.ref" / "sg13g2_stdcell" / "lib"
            / "sg13g2_stdcell_typ_1p20V_25C.lib"
        )
    ]

    pdk = PDK(
        name="sg13g2",
        version="1.0",
        root=resolved_root,
        tech=tech_path if tech_path.is_file() else None,
        lefs=[path for path in lef_paths if path.is_file()],
        libs=[path for path in lib_paths if path.is_file()],
        site_core="CoreSite",
        buffers=[
            "sg13g2_buf_1",
            "sg13g2_buf_2",
            "sg13g2_buf_4",
            "sg13g2_buf_8",
            "sg13g2_buf_16"
        ],
        fillers=[
            "sg13g2_fill_1",
            "sg13g2_fill_2",
            "sg13g2_decap_4",
            "sg13g2_decap_8"
        ],
        tie_high_cell="sg13g2_tiehi",
        tie_high_port="L_HI",
        tie_low_cell="sg13g2_tielo",
        tie_low_port="L_LO",
        dont_use=[
            "sg13g2_lgcp_1",
            "sg13g2_sighold",
            "sg13g2_slgcp_1",
            "sg13g2_dfrbp_2"
        ]
    )

    return pdk
