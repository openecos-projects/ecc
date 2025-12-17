# Copyright (c) 2022 ETH Zurich and University of Bologna.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0
#
# Authors:
# - Philippe Sauter <phsauter@iis.ee.ethz.ch>

# This flows assumes it is beign executed in the yosys/ directory
# but just to be sure, we go there
if {[info script] ne ""} {
    cd "[file dirname [info script]]/../"
}
source global_var.tcl

# process ABC script and write to temporary directory
proc processAbcScript {abc_script} {
    global tmp_dir
    set src_dir [file join [file dirname [info script]] ../src]
    set abc_out_path $tmp_dir/[file tail $abc_script]

    set raw [read -nonewline [open $abc_script r]]
    set abc_script_recaig [string map -nocase [list "{REC_AIG}" [subst "$src_dir/lazy_man_synth_library.aig"]] $raw]
    set abc_out [open $abc_out_path w]
    puts -nonewline $abc_out $abc_script_recaig

    flush $abc_out
    close $abc_out
    return $abc_out_path
}

# read liberty files and prepare some variables
source scripts/init_tech.tcl

yosys plugin -i slang

# Check if FILELIST is set and non-empty, prioritize it over individual Verilog files
if {[info exists filelist] && $filelist ne ""} {
    # Use SystemVerilog filelist file
    puts "Reading SystemVerilog sources from filelist: $filelist"
    yosys read_slang -F $filelist --top $top_design \
            --compat-mode --keep-hierarchy \
            --allow-use-before-declare --ignore-unknown-modules \
            --ignore-timing --ignore-initial
} else {
    # Fall back to individual Verilog files
    puts "Reading Verilog sources from rtl files: $rtl_file"
    yosys read_slang {*}$rtl_file --top $top_design \
            --compat-mode --keep-hierarchy \
            --allow-use-before-declare --ignore-unknown-modules \
            --ignore-timing --ignore-initial
}

# preserve hierarchy of selected modules/instances
# 't' means type as in select all instances of this type/module
# yosys-slang uniquifies all modules with the naming scheme:
# <module-name>$<instance-name> -> match for t:<module-name>$$
# yosys setattr -set keep_hierarchy 1 "t:u_tc_pll$*"
# yosys setattr -set keep_hierarchy 1 "t:u_rcu$*"
# map dont_touch attribute commonly applied to output-nets of async regs to keep
yosys attrmap -rename dont_touch keep
# copy the keep attribute to their driving cells (retain on net for debugging)
yosys attrmvcp -copy -attr keep
# -----------------------------------------------------------------------------
# this section heavily borrows from the yosys synth command:
# synth - check
yosys hierarchy -top $top_design
yosys check
yosys proc

# synth - coarse:
# similar to yosys synth -run coarse -noalumacc
yosys opt_expr
yosys opt -noff
yosys fsm
yosys wreduce 
yosys peepopt
yosys opt_clean
yosys opt -full
yosys booth
yosys share
yosys opt
yosys memory -nomap
yosys memory_map
yosys opt -fast

yosys opt_dff -sat -nodffe -nosdff
yosys share
yosys opt -full
yosys clean -purge

yosys techmap
yosys opt -fast
yosys clean -purge

yosys tee -q -o "${generic_stat_json}" stat -json -tech cmos
# yosys tee -q -o "${generic_stat_json}.rpt" stat -tech cmos
# -----------------------------------------------------------------------------
if {$keep_hierarchy == "false"} {
    yosys flatten
    yosys clean -purge
}

# -----------------------------------------------------------------------------
# Preserve flip-flop names as far as possible
# split internal nets
yosys splitnets -format __v
# rename DFFs from the driven signal
yosys rename -wire -suffix _reg_p t:*DFF*_P*
yosys rename -wire -suffix _reg_n t:*DFF*_N*
# rename all other cells
yosys autoname t:*DFF* %n
yosys clean -purge

yosys select -write ${timing_cell_stat_rpt} t:*DFF*
yosys tee -q -o ${timing_cell_count_rpt} select -count t:*DFF*_P*
yosys tee -q -a ${timing_cell_count_rpt} select -count t:*DFF*_N*
yosys tee -q -a ${timing_cell_count_rpt} select -count */t:*_DLATCH*_ */t:*_SR*_

# yosys tee -q -o "${generic_stat_json}" stat -json -tech cmos
# yosys tee -q -o "${generic_stat_json}.rpt" stat -tech cmos
# -----------------------------------------------------------------------------
# mapping to technology

# set don't use cells for dfflibmap
set dfflibmap_args ""
foreach cell $dont_use_cells {
    lappend dfflibmap_args -dont_use $cell
}
# first map flip-flops
yosys dfflibmap {*}$tech_cells_args {*}$dfflibmap_args

# set don't use cells for abc
set abc_dont_use_cells ""
# TODO: Most of the time we only care whether a certain cell exists in the final netlist,
# but in fact it may still be necessary to distinguish between the dontuse accepted by abc and the dontuse accepted by dfflibmap
foreach cell $dont_use_cells {
    lappend abc_dont_use_cells -dont_use $cell
}

# then perform bit-level optimization and mapping on all combinational clouds in ABC
# pre-process abc file (written to tmp directory)
set abc_comb_script   [processAbcScript scripts/abc-opt.script]

# Generate abc.constr file dynamically
set abc_constr_path "${tmp_dir}/abc.constr"
set abc_constr_file [open $abc_constr_path w]
set driver_cell {BUFX4H7L}
puts $abc_constr_file "set_driving_cell ${driver_cell}"
puts $abc_constr_file "set_load 0.015"
close $abc_constr_file

# call ABC
yosys abc {*}$tech_cells_args -D $clk_period_ps -script $abc_comb_script -constr src/abc.constr -showtmp {*}$abc_dont_use_cells

yosys clean -purge

# -----------------------------------------------------------------------------
# prep for openROAD
# yosys write_verilog -norename -noexpr -attr2comment ${tmp_dir}/${top_design}_yosys_debug.v

# yosys splitnets -driver
yosys splitnets -ports
yosys setundef -zero
yosys clean -purge
# map constants to tie cells
yosys hilomap -singleton -hicell {*}$tech_cell_tiehi -locell {*}$tech_cell_tielo

# final reports
yosys tee -q -o "${synth_stat_json}" stat -json {*}$liberty_args
# yosys tee -q -o "${synth_stat_json}.rpt" stat {*}$liberty_args
yosys tee -q -o "${synth_check_rpt}" check

# final netlist
yosys write_verilog -noattr -noexpr -nohex -nodec ${final_netlist_file}
