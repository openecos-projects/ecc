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
    pdk_name_normalized = (pdk_name or "").strip().lower()
    if pdk_name_normalized == "ics55":
        pdk = PDK_ICS55(pdk_root=pdk_root)
    elif pdk_name_normalized == "sg13g2":
        pdk = PDK_SG13G2(pdk_root=pdk_root)
    elif pdk_name_normalized == "gf180mcu":
        pdk = PDK_GF180MCU(pdk_root=pdk_root)
    elif pdk_name_normalized in ["sky130", "skywater130"]:
        pdk = PDK_SKY130(pdk_root=pdk_root)
    else:
        pdk = PDK(name=pdk_name_normalized)
    
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

def PDK_SG13G2(pdk_root: str = "") -> PDK:
    resolved_root = os.path.abspath(os.path.expanduser(
        (pdk_root or "").strip()
        or os.environ.get("CHIPCOMPILER_SG13G2_PDK_ROOT", "").strip()
        or os.environ.get("SG13G2_PDK_ROOT", "").strip()
    ))

    tech_path = "{}/lef/sg13g2_tech.lef".format(resolved_root)
    lef_paths = [
        "{}/lef/sg13g2_stdcell.lef".format(resolved_root)
    ]
    lib_paths = [
        "{}/lib/sg13g2_stdcell_typ_1p20V_25C.lib".format(resolved_root)
    ]

    pdk = PDK(
        name="sg13g2",
        version="1.0",
        root=resolved_root,
        tech=tech_path if os.path.isfile(tech_path) else "",
        lefs=[path for path in lef_paths if os.path.isfile(path)],
        libs=[path for path in lib_paths if os.path.isfile(path)],
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

def PDK_GF180MCU(pdk_root: str = "") -> PDK:
    resolved_root = os.path.abspath(os.path.expanduser(
        (pdk_root or "").strip()
        or os.environ.get("CHIPCOMPILER_GF180_PDK_ROOT", "").strip()
        or os.environ.get("GF180_PDK_ROOT", "").strip()
    ))

    # Standard paths for pruned GF180 distributions
    tech_path = "{}/lef/gf180mcu_7t_tech.lef".format(resolved_root)
    lef_paths = [
        "{}/lef/gf180mcu_fd_sc_mcu7t5v0.lef".format(resolved_root)
    ]
    lib_paths = [
        "{}/lib/gf180mcu_fd_sc_mcu7t5v0__ss_125C_1p65V.lib".format(resolved_root)
    ]

    pdk = PDK(
        name="gf180mcu",
        version="1.0",
        root=resolved_root,
        tech=tech_path if os.path.isfile(tech_path) else "",
        lefs=[path for path in lef_paths if os.path.isfile(path)],
        libs=[path for path in lib_paths if os.path.isfile(path)],
        site_core="GF_018_7_5_MC_TYP",
        tap_cell="gf180mcu_fd_sc_mcu7t5v0__filltap",
        end_cap="gf180mcu_fd_sc_mcu7t5v0__endcap",
        buffers=[
            "gf180mcu_fd_sc_mcu7t5v0__buf_1",
            "gf180mcu_fd_sc_mcu7t5v0__buf_2",
            "gf180mcu_fd_sc_mcu7t5v0__buf_4",
            "gf180mcu_fd_sc_mcu7t5v0__buf_8",
            "gf180mcu_fd_sc_mcu7t5v0__buf_16"
        ],
        fillers=[
            "gf180mcu_fd_sc_mcu7t5v0__fill_1",
            "gf180mcu_fd_sc_mcu7t5v0__fill_2",
            "gf180mcu_fd_sc_mcu7t5v0__fill_4",
            "gf180mcu_fd_sc_mcu7t5v0__fill_8",
            "gf180mcu_fd_sc_mcu7t5v0__fill_16",
            "gf180mcu_fd_sc_mcu7t5v0__fill_32"
        ],
        tie_high_cell="gf180mcu_fd_sc_mcu7t5v0__tieh",
        tie_high_port="Z",
        tie_low_cell="gf180mcu_fd_sc_mcu7t5v0__tiel",
        tie_low_port="ZN",
        dont_use=[
            "gf180mcu_fd_sc_mcu7t5v0__ant*",
            "gf180mcu_fd_sc_mcu7t5v0__lat*",
            "gf180mcu_fd_sc_mcu7t5v0__dff*" # Example: if you want to restrict DFFs
        ]
    )

    return pdk

def PDK_SKY130(pdk_root: str = "") -> PDK:
    resolved_root = os.path.abspath(os.path.expanduser(
        (pdk_root or "").strip()
        or os.environ.get("CHIPCOMPILER_SKY130_PDK_ROOT", "").strip()
        or os.environ.get("SKY130_PDK_ROOT", "").strip()
    ))

    # Standard paths for sky130 high-density (hd) library
    tech_path = "{}/lef/sky130_fd_sc_hd.tech.lef".format(resolved_root)
    lef_paths = [
        "{}/lef/sky130_fd_sc_hd.lef".format(resolved_root)
    ]
    lib_paths = [
        "{}/lib/sky130_fd_sc_hd__tt_025C_1v80.lib".format(resolved_root)
    ]

    pdk = PDK(
        name="sky130",
        version="1.0",
        root=resolved_root,
        tech=tech_path if os.path.isfile(tech_path) else "",
        lefs=[path for path in lef_paths if os.path.isfile(path)],
        libs=[path for path in lib_paths if os.path.isfile(path)],
        site_core="unithd",  # Standard site name for sky130_fd_sc_hd
        tap_cell="sky130_fd_sc_hd__filltap_2",
        end_cap="sky130_fd_sc_hd__decap_3",
        buffers=[
            "sky130_fd_sc_hd__buf_1",
            "sky130_fd_sc_hd__buf_2",
            "sky130_fd_sc_hd__buf_4",
            "sky130_fd_sc_hd__buf_8",
            "sky130_fd_sc_hd__buf_12",
            "sky130_fd_sc_hd__buf_16"
        ],
        fillers=[
            "sky130_fd_sc_hd__fill_1",
            "sky130_fd_sc_hd__fill_2",
            "sky130_fd_sc_hd__fill_4",
            "sky130_fd_sc_hd__fill_8"
        ],
        # Sky130 uses the 'conb' (connect bias) cell for both tie high and low
        tie_high_cell="sky130_fd_sc_hd__conb_1",
        tie_high_port="HI",
        tie_low_cell="sky130_fd_sc_hd__conb_1",
        tie_low_port="LO",
        dont_use=[
            "sky130_fd_sc_hd__ant*",   # Exclude antenna cells from logic
            "sky130_fd_sc_hd__lpflow*", # Exclude power management cells for basic flow
            "sky130_fd_sc_hd__clkbuf_1" # Usually too small for clock trees
        ]
    )

    return pdk