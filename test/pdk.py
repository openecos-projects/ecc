#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from chipcompiler.data import PDK

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
    root = current_dir.rsplit('/', 1)[0]

    pdk_root = "{}/chipcompiler/thirdparty/icsprout55-pdk".format(root)
    stdcell_dir = "{}/IP/STD_cell/ics55_LLSC_H7C_V1p10C100".format(pdk_root)

    stdcell_corner = "{}/ics55_LLSC_H7CR".format(stdcell_dir)

    pdk = PDK(
        name="ics55",
        version="V1p10C100",
        tech="{}/prtech/techLEF/N551P6M.lef".format(pdk_root),
        lefs = [
            "{}/prtech/techLEF/N551P6M.lef".format(pdk_root),
            "{}/lef/ics55_LLSC_H7CR_ecos.lef".format(stdcell_corner),
        ],
        libs = [
            "{}/liberty/ics55_LLSC_H7CR_typ_tt_1p2_25_nldm.lib".format(stdcell_corner),
        ]
    )

    return pdk

def PDK_SKY130() -> PDK:
    import os
    current_dir = os.path.split(os.path.abspath(__file__))[0]
    root = current_dir.rsplit('/', 1)[0]

    foundry_dir = "{}/chipcompiler/thirdparty/iEDA/scripts/foundry/sky130".format(root)
    
    pdk = PDK(
        name="sky130",
        version="v0.1",
        tech="{}/lef/sky130_fd_sc_hs.tlef".format(foundry_dir),
        lefs = [
            "{}/lef/sky130_fd_sc_hs_merged.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__com_bus_slice_10um.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__com_bus_slice_1um.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__com_bus_slice_20um.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__com_bus_slice_5um.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__connect_vcchib_vccd_and_vswitch_vddio_slice_20um.lef".format(
                foundry_dir
            ),
            "{}/lef/sky130_ef_io__corner_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__disconnect_vccd_slice_5um.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__disconnect_vdda_slice_5um.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__gpiov2_pad_wrapped.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vccd_hvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vccd_lvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vdda_hvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vdda_lvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vddio_hvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vddio_lvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vssa_hvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vssa_lvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vssd_hvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vssd_lvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vssio_hvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_ef_io__vssio_lvc_pad.lef".format(foundry_dir),
            "{}/lef/sky130_fd_io__top_xres4v2.lef".format(foundry_dir),
            "{}/lef/sky130io_fill.lef".format(foundry_dir),
            "{}/lef/sky130_sram_1rw1r_128x256_8.lef".format(foundry_dir),
            "{}/lef/sky130_sram_1rw1r_44x64_8.lef".format(foundry_dir),
            "{}/lef/sky130_sram_1rw1r_64x256_8.lef".format(foundry_dir),
            "{}/lef/sky130_sram_1rw1r_80x64_8.lef".format(foundry_dir),
        ],
        libs = [
            "{}/lib/sky130_fd_sc_hs__tt_025C_1v80.lib".format(foundry_dir),
            "{}/lib/sky130_dummy_io.lib".format(foundry_dir),
            "{}/lib/sky130_sram_1rw1r_128x256_8_TT_1p8V_25C.lib".format(foundry_dir),
            "{}/lib/sky130_sram_1rw1r_44x64_8_TT_1p8V_25C.lib".format(foundry_dir),
            "{}/lib/sky130_sram_1rw1r_64x256_8_TT_1p8V_25C.lib".format(foundry_dir),
            "{}/lib/sky130_sram_1rw1r_80x64_8_TT_1p8V_25C.lib".format(foundry_dir),
        ]   
    )
    
    return pdk
