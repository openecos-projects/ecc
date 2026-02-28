#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from dataclasses import dataclass, field
import logging
import os

logger = logging.getLogger(__name__)

@dataclass
class PDK:
    """
    Dataclass for PDK information
    """
    name : str = "" # pdk name
    version : str = "" # pdk version
    root : str = "" # resolved pdk root path
    tech : str = "" # pdk tech lef file
    lefs : list = field(default_factory=list) # pdk lef files
    libs : list = field(default_factory=list) # pdk liberty files
    sdc : str = "" # pdk sdc file
    spef : str = "" # pdk spef file
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

    def validate(self) -> None:
        """Check that critical PDK paths exist. Raises ValueError if not."""
        errors = []
        if self.root and not os.path.isdir(self.root):
            errors.append(f"PDK root directory not found: {self.root}")
        if not self.tech:
            errors.append("PDK tech LEF is missing")
        if not self.lefs:
            errors.append("PDK has no LEF files")
        if not self.libs:
            errors.append("PDK has no liberty files")
        if errors:
            msg = "PDK validation failed:\n  " + "\n  ".join(errors)
            logger.error(msg)
            raise ValueError(msg)

def get_pdk(pdk_name : str, pdk_root: str = "") -> PDK:
    """
    Return the PDK instance based on the given pdk name.
    """
    pdk_name_normalized = (pdk_name or "").strip().lower()
    if pdk_name_normalized == "ics55":
        pdk = PDK_ICS55(pdk_root=pdk_root)
    else:
        pdk = PDK(name=pdk_name_normalized)
    pdk.validate()
    return pdk

def PDK_ICS55(pdk_root: str = "") -> PDK:
    current_dir = os.path.split(os.path.abspath(__file__))[0]
    root = current_dir.rsplit('/', 2)[0]
    default_pdk_root = "{}/chipcompiler/thirdparty/icsprout55-pdk".format(root)

    # Resolve: explicit arg > env vars > default
    resolved_root = os.path.abspath(os.path.expanduser(
        (pdk_root or "").strip()
        or os.environ.get("CHIPCOMPILER_ICS55_PDK_ROOT", "").strip()
        or os.environ.get("ICS55_PDK_ROOT", "").strip()
        or default_pdk_root
    ))
    stdcell_dir = "{}/IP/STD_cell/ics55_LLSC_H7C_V1p10C100".format(resolved_root)

    tech_path = "{}/prtech/techLEF/N551P6M.lef".format(resolved_root)
    lef_paths = [
        "{}/ics55_LLSC_H7CR/lef/ics55_LLSC_H7CR_ecos.lef".format(stdcell_dir),
        "{}/ics55_LLSC_H7CL/lef/ics55_LLSC_H7CL_ecos.lef".format(stdcell_dir)
    ]
    lib_paths = [
        "{}/ics55_LLSC_H7CR/liberty/ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib".format(stdcell_dir),
        "{}/ics55_LLSC_H7CL/liberty/ics55_LLSC_H7CL_ss_rcworst_1p08_125_nldm.lib".format(stdcell_dir)
    ]

    pdk = PDK(
        name="ics55",
        version="V1p10C100",
        root=resolved_root,
        tech=tech_path if os.path.isfile(tech_path) else "",
        lefs=[path for path in lef_paths if os.path.isfile(path)],
        libs=[path for path in lib_paths if os.path.isfile(path)],
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
