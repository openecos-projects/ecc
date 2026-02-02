#!/usr/bin/env python

from dataclasses import dataclass, field


@dataclass
class PDK:
    """
    Dataclass for PDK information
    """
    name : str = "" # pdk name
    version : str = "" # pdk version
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
    

def get_pdk(pdk_name : str) -> PDK:
    """
    Return the PDK instance based on the given pdk name.
    """
    if pdk_name.lower() == "sky130":
        return PDK_SKY130()
    elif pdk_name.lower() == "ics55":
        return PDK_ICS55()
    else:
        return PDK()

def PDK_ICS55() -> PDK:
    import os
    current_dir = os.path.split(os.path.abspath(__file__))[0]
    root = current_dir.rsplit('/', 2)[0]

    pdk_root = f"{root}/chipcompiler/thirdparty/icsprout55-pdk"
    stdcell_dir = f"{pdk_root}/IP/STD_cell/ics55_LLSC_H7C_V1p10C100"

    pdk = PDK(
        name="ics55",
        version="V1p10C100",
        tech=f"{pdk_root}/prtech/techLEF/N551P6M.lef",
        lefs = [
            f"{stdcell_dir}/ics55_LLSC_H7CR/lef/ics55_LLSC_H7CR_ecos.lef",
            f"{stdcell_dir}/ics55_LLSC_H7CL/lef/ics55_LLSC_H7CL_ecos.lef"
        ],
        libs = [
            f"{stdcell_dir}/ics55_LLSC_H7CR/liberty/ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib",
            f"{stdcell_dir}/ics55_LLSC_H7CL/liberty/ics55_LLSC_H7CL_ss_rcworst_1p08_125_nldm.lib"
        ],
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

def PDK_SKY130() -> PDK:
    import os
    current_dir = os.path.split(os.path.abspath(__file__))[0]
    root = current_dir.rsplit('/', 2)[0]

    foundry_dir = f"{root}/chipcompiler/thirdparty/ecc-tools/scripts/foundry/sky130"
    
    pdk = PDK(
        name="sky130",
        version="v0.1",
        tech=f"{foundry_dir}/lef/sky130_fd_sc_hs.tlef",
        lefs = [
            f"{foundry_dir}/lef/sky130_fd_sc_hs_merged.lef",
            f"{foundry_dir}/lef/sky130_ef_io__com_bus_slice_10um.lef",
            f"{foundry_dir}/lef/sky130_ef_io__com_bus_slice_1um.lef",
            f"{foundry_dir}/lef/sky130_ef_io__com_bus_slice_20um.lef",
            f"{foundry_dir}/lef/sky130_ef_io__com_bus_slice_5um.lef",
            f"{foundry_dir}/lef/sky130_ef_io__connect_vcchib_vccd_and_vswitch_vddio_slice_20um.lef",
            f"{foundry_dir}/lef/sky130_ef_io__corner_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__disconnect_vccd_slice_5um.lef",
            f"{foundry_dir}/lef/sky130_ef_io__disconnect_vdda_slice_5um.lef",
            f"{foundry_dir}/lef/sky130_ef_io__gpiov2_pad_wrapped.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vccd_hvc_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vccd_lvc_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vdda_hvc_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vdda_lvc_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vddio_hvc_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vddio_lvc_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vssa_hvc_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vssa_lvc_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vssd_hvc_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vssd_lvc_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vssio_hvc_pad.lef",
            f"{foundry_dir}/lef/sky130_ef_io__vssio_lvc_pad.lef",
            f"{foundry_dir}/lef/sky130_fd_io__top_xres4v2.lef",
            f"{foundry_dir}/lef/sky130io_fill.lef",
            f"{foundry_dir}/lef/sky130_sram_1rw1r_128x256_8.lef",
            f"{foundry_dir}/lef/sky130_sram_1rw1r_44x64_8.lef",
            f"{foundry_dir}/lef/sky130_sram_1rw1r_64x256_8.lef",
            f"{foundry_dir}/lef/sky130_sram_1rw1r_80x64_8.lef",
        ],
        libs = [
            f"{foundry_dir}/lib/sky130_fd_sc_hs__tt_025C_1v80.lib",
            f"{foundry_dir}/lib/sky130_dummy_io.lib",
            f"{foundry_dir}/lib/sky130_sram_1rw1r_128x256_8_TT_1p8V_25C.lib",
            f"{foundry_dir}/lib/sky130_sram_1rw1r_44x64_8_TT_1p8V_25C.lib",
            f"{foundry_dir}/lib/sky130_sram_1rw1r_64x256_8_TT_1p8V_25C.lib",
            f"{foundry_dir}/lib/sky130_sram_1rw1r_80x64_8_TT_1p8V_25C.lib",
        ],
        site_core = "unit",
        site_io = "unit",
        site_corner= "unit",
        tap_cell = "sky130_fd_sc_hs__tap_1",
        end_cap = "sky130_fd_sc_hs__fill_1",
        buffers = [
            "sky130_fd_sc_hs__buf_1",
            "sky130_fd_sc_hs__buf_8"
        ],
        fillers = [
            "sky130_fd_sc_hs__fill_8",
            "sky130_fd_sc_hs__fill_4",
            "sky130_fd_sc_hs__fill_2",
            "sky130_fd_sc_hs__fill_1"   
        ],
        tie_high_cell = "sky130_fd_sc_hs__conb_1",
        tie_high_port = "HI",
        tie_low_cell = "sky130_fd_sc_hs__conb_1",
        tie_low_port = "LO",
        dont_use=[]
    )
    
    return pdk
