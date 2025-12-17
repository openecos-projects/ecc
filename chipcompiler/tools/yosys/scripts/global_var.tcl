set top_design              "$::env(TOP_NAME)"
set clk_freq_mhz            "$::env(CLK_FREQ_MHZ)"

if {[info exists ::env(FILELIST)]} {
    set filelist            "$::env(FILELIST)"
} else {
    if {![info exists ::env(RTL_FILE)] || $::env(RTL_FILE) eq ""} {
        return -code error "Neither RTL_FILE and FILELIST are set"
    }
    set rtl_file            [split $::env(RTL_FILE)]
}
set final_netlist_file      "$::env(NETLIST_FILE)"
set timing_cell_stat_rpt    "$::env(TIMING_CELL_STAT_RPT)"
set timing_cell_count_rpt   "$::env(TIMING_CELL_COUNT_RPT)"
set generic_stat_json       "$::env(GENERIC_STAT_JSON)"
set synth_stat_json         "$::env(SYNTH_STAT_JSON)"
set synth_check_rpt         "$::env(SYNTH_CHECK_RPT)"
set keep_hierarchy          [string tolower "$::env(KEEP_HIERARCHY)"]

set dont_use_cells          "$::env(CELL_DONT_USE)"
set tie_low_cell            "$::env(CELL_TIE_LOW)"
set tie_low_port            "$::env(CELL_TIE_LOW_PORT)"
set tie_high_cell           "$::env(CELL_TIE_HIGH)"
set tie_high_port           "$::env(CELL_TIE_HIGH_PORT)"

set lib_stdcell_list        [split "$::env(LIB_STDCELL)"]
set lib_list                [split "$::env(LIB_ALL)"]

set tmp_dir                 "$::env(RESULT_DIR)/tmp"

###############

set clk_period_ps  [expr 1000000.0 / ${clk_freq_mhz}]

file mkdir $tmp_dir
set stat_dir [file dirname $synth_stat_json]
if {![file isdirectory $stat_dir]} {
    file mkdir $stat_dir
}