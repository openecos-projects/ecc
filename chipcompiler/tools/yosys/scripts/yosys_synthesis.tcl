# Copyright 2020 Efabless Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

if {[info script] ne ""} {
    set script_dir "[file dirname [info script]]"
    set data_dir "[file normalize [file join $script_dir ../data]]"
    set global_var_path "[file join $data_dir global_var.tcl]"

    # source global variables
    # The global_var.tcl file is expected to be generated in the workspace/data/ directory
    if {[file exists $global_var_path]} {
        source $global_var_path
    } else {
        return -code error "global_var.tcl not found at $global_var_path"
    }
} else {
    return -code error "Unable to determine script directory"
}

# read liberty files and prepare some variables
source init_tech.tcl

set exclude_cells [concat {*}[lmap cell $dont_use_cells {concat "-dont_use" $cell}]]

#===========================================================
#   set parameter for ABC
#===========================================================

set synth_strategy "DELAY 4"
if {[info exists env(YOSYS_SYNTH_STRATEGY)]} {
  # TODO: Move this to global_var.tcl
  set synth_strategy $::env(YOSYS_SYNTH_STRATEGY)
}

set buffering 1
set sizing 1

set driver ${abc_driver_cell}
# unit: pF
set cap_load ${abc_load}

# input pin cap of BUF
set max_FO 24
set max_TR 0

#===========================================================
#   scripts for ABC
#===========================================================

# Generate abc.constr file dynamically
set abc_constr_path "${tmp_dir}/abc.constr"
set abc_constr_file [open $abc_constr_path w]
puts $abc_constr_file "set_driving_cell ${abc_driver_cell}"
puts $abc_constr_file "set_load ${abc_load}"
close $abc_constr_file

# Assemble Scripts (By Strategy)
set abc_rs_K    "resub,-K,"
set abc_rs      "resub"
set abc_rsz     "resub,-z"
set abc_rw_K    "rewrite,-K,"
set abc_rw      "rewrite"
set abc_rwz     "rewrite,-z"
set abc_rf      "refactor"
set abc_rfz     "refactor,-z"
set abc_b       "balance"

set abc_resyn2        "${abc_b}; ${abc_rw}; ${abc_rf}; ${abc_b}; ${abc_rw}; ${abc_rwz}; ${abc_b}; ${abc_rfz}; ${abc_rwz}; ${abc_b}"
set abc_share         "strash; multi,-m; ${abc_resyn2}"
set abc_resyn2a       "${abc_b};${abc_rw};${abc_b};${abc_rw};${abc_rwz};${abc_b};${abc_rwz};${abc_b}"
set abc_resyn3        "balance;resub;resub,-K,6;balance;resub,-z;resub,-z,-K,6;balance;resub,-z,-K,5;balance"
set abc_resyn2rs      "${abc_b};${abc_rs_K},6;${abc_rw};${abc_rs_K},6,-N,2;${abc_rf};${abc_rs_K},8;${abc_rw};${abc_rs_K},10;${abc_rwz};${abc_rs_K},10,-N,2;${abc_b},${abc_rs_K},12;${abc_rfz};${abc_rs_K},12,-N,2;${abc_rwz};${abc_b}"

set abc_choice        "fraig_store; ${abc_resyn2}; fraig_store; ${abc_resyn2}; fraig_store; fraig_restore"
set abc_choice2       "fraig_store; balance; fraig_store; ${abc_resyn2}; fraig_store; ${abc_resyn2}; fraig_store; ${abc_resyn2}; fraig_store; fraig_restore"

set abc_map_old_cnt			"map,-p,-a,-B,0.2,-A,0.9,-M,0"
set abc_map_old_dly     "map,-p,-B,0.2,-A,0.9,-M,0"
set abc_retime_area     "retime,-D,{D},-M,5"
set abc_retime_dly      "retime,-D,{D},-M,6"
set abc_map_new_area    "amap,-m,-Q,0.1,-F,20,-A,20,-C,5000"

set abc_area_recovery_1 "${abc_choice}; map;"
set abc_area_recovery_2 "${abc_choice2}; map;"

set map_old_cnt			    "map,-p,-a,-B,0.2,-A,0.9,-M,0"
set map_old_dly			    "map,-p,-B,0.2,-A,0.9,-M,0"
set abc_retime_area   	"retime,-D,{D},-M,5"
set abc_retime_dly    	"retime,-D,{D},-M,6"
set abc_map_new_area  	"amap,-m,-Q,0.1,-F,20,-A,20,-C,5000"

if {$buffering==1} {
  set max_tr_arg ""
  if { $max_TR != 0 } {
    set max_tr_arg ",-S,${max_TR}"
  }
  set abc_fine_tune		"buffer,-N,${max_FO}${max_tr_arg};upsize,{D};dnsize,{D}"
} elseif {$sizing} {
  set abc_fine_tune   "upsize,{D};dnsize,{D}"
} else {
  set abc_fine_tune   ""
}

set delay_scripts [list \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_dly}; scleanup;${abc_map_old_dly};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_fine_tune};stime,-p;print_stats -m" \
  \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_dly}; scleanup;${abc_choice2};${abc_map_old_dly};${abc_area_recovery_2}; retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_fine_tune};stime,-p;print_stats -m" \
  \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_dly}; scleanup;${abc_choice};${abc_map_old_dly};${abc_area_recovery_1}; retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_fine_tune};stime,-p;print_stats -m" \
  \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_area};scleanup;${abc_choice2};${abc_map_new_area};${abc_choice2};${abc_map_old_dly};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_fine_tune};stime,-p;print_stats -m" \
  \
  "+&get -n;&st;&dch;&nf;&put;&get -n;&st;&syn2;&if -g -K 6;&synch2;&nf;&put;&get -n;&st;&syn2;&if -g -K 6;&synch2;&nf;&put;&get -n;&st;&syn2;&if -g -K 6;&synch2;&nf;&put;&get -n;&st;&syn2;&if -g -K 6;&synch2;&nf;&put;&get -n;&st;&syn2;&if -g -K 6;&synch2;&nf;&put;buffer -c -N ${max_FO};topo;stime -c;upsize -c;dnsize -c;;stime,-p;print_stats -m" \
  ]

set area_scripts [list \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_area};scleanup;${abc_choice2};${abc_map_new_area};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_fine_tune};stime,-p;print_stats -m" \
  \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_area};scleanup;${abc_choice2};${abc_map_new_area};${abc_choice2};${abc_map_new_area};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_fine_tune};stime,-p;print_stats -m" \
  \
  "+fx;mfs;strash;refactor;${abc_choice2};${abc_retime_area};scleanup;${abc_choice2};${abc_map_new_area};${abc_choice2};${abc_map_new_area};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_fine_tune};stime,-p;print_stats -m" \
  \
  "+strash;dch;map -B 0.9;topo;stime -c;buffer -c -N ${max_FO};upsize -c;dnsize -c;stime,-p;print_stats -m" \
  ]

set strategy_parts [split $synth_strategy]

proc synth_strategy_format_err { } {
  upvar area_scripts area_scripts
  upvar delay_scripts delay_scripts
  log -stderr "\[ERROR] Misformatted synth_strategy (\"$synth_strategy\")."
  log -stderr "\[ERROR] Correct format is \"DELAY|AREA 0-[expr [llength $delay_scripts]-1]|0-[expr [llength $area_scripts]-1]\"."
  exit 1
}

if { [llength $strategy_parts] != 2 } {
  synth_strategy_format_err
}

set strategy_type [lindex $strategy_parts 0]
set strategy_type_idx [lindex $strategy_parts 1]

if { $strategy_type != "AREA" && $strategy_type != "DELAY" } {
  log -stderr "\[ERROR] AREA|DELAY tokens not found. ($strategy_type)"
  synth_strategy_format_err
}

if { $strategy_type == "DELAY" && $strategy_type_idx >= [llength $delay_scripts] } {
  log -stderr "\[ERROR] strategy index ($strategy_type_idx) is too high."
  synth_strategy_format_err
}

if { $strategy_type == "AREA" && $strategy_type_idx >= [llength $area_scripts] } {
  log -stderr "\[ERROR] strategy index ($strategy_type_idx) is too high."
  synth_strategy_format_err
}

set strategy_name "$strategy_type-$strategy_type_idx"
if { $strategy_type == "DELAY" } {
  set strategy_script [lindex $delay_scripts $strategy_type_idx]
} else {
  set strategy_script [lindex $area_scripts $strategy_type_idx]
}

#===========================================================
#   main running
#===========================================================
yosys -import

# Use Slang only for input forms that require its filelist/SystemVerilog support.
if {$use_slang} {
    yosys plugin -i slang

    # Check if FILELIST is set and non-empty, prioritize it over individual Verilog files
    if {[info exists filelist] && $filelist ne ""} {
        puts "Reading SystemVerilog sources from filelist: $filelist"
        yosys read_slang -F $filelist --top $top_design \
                --compat-mode --keep-hierarchy \
                +define+SYNTHESIS \
                --allow-use-before-declare \
                --ignore-timing \
                -Wduplicate-definition
    } else {
        puts "Reading SystemVerilog sources from rtl files: $rtl_file"
        yosys read_slang {*}$rtl_file --top $top_design \
                --compat-mode --keep-hierarchy \
                +define+SYNTHESIS \
                --allow-use-before-declare \
                --ignore-timing \
                -Wduplicate-definition
    }
} else {
    puts "Reading Verilog sources with native parser: $rtl_file"
    read_verilog -sv {*}$rtl_file
}

# preserve hierarchy of selected modules/instances
# 't' means type as in select all instances of this type/module
# yosys-slang uniquifies all modules with the naming scheme:
# <module-name>$<instance-name> -> match for t:<module-name>$$
# yosys setattr -set keep_hierarchy 1 "t:u_tc_pll$*"
# yosys setattr -set keep_hierarchy 1 "t:u_rcu$*"
# map dont_touch attribute commonly applied to output-nets of async regs to keep
attrmap -rename dont_touch keep
# copy the keep attribute to their driving cells (retain on net for debugging)
attrmvcp -copy -attr keep

# generic synthesis (coarse)
set flatten_flag ""
if {$keep_hierarchy == "false"} {
  set flatten_flag "-flatten"
}
synth -top $top_design {*}$flatten_flag -run :fine

share -aggressive
onehot
muxpack
opt_demorgan
opt_ffinv

# generic synthesis (fine)
synth -run fine:

# remove unused cells and wires
opt_clean -purge

tee -q -o "${generic_stat_json}" stat -json -tech cmos

# split internal nets
splitnets -format __v
# rename DFFs from the driven signal
yosys rename -wire -suffix _reg_p t:*DFF*_P*
yosys rename -wire -suffix _reg_n t:*DFF*_N*
# rename all other cells
select -write ${timing_cell_stat_rpt} t:*DFF*
autoname t:*DFF* %n
clean -purge

select -write ${timing_cell_stat_rpt} t:*DFF*
tee -q -o ${timing_cell_count_rpt} select -count t:*DFF*
tee -q -a ${timing_cell_count_rpt} select -count */t:*_DLATCH*_ */t:*_SR*_

# technology mapping for clockgate
clockgate {*}$tech_cells_args {*}$exclude_cells

# technology mapping for flip-flops
dfflibmap {*}$tech_cells_args {*}$exclude_cells

# optimize the design
opt -undriven -purge

log "\[INFO\]: USING STRATEGY $strategy_name"

# technology mapping for cells
abc -D "$clk_period_ps" \
  -constr "$abc_constr_path" \
  {*}$tech_cells_args {*}$exclude_cells \
  -script "$strategy_script" \
  -showtmp

# technology mapping for constant hi- and/or lo-drivers
hilomap -singleton -hicell {*}$tech_cell_tiehi -locell {*}$tech_cell_tielo

# replace undef values with defined constants
setundef -zero

# remove unused cells and wires
opt_clean -purge

# Generate public names for the various nets, resulting in very long names that include
# the full heirarchy, which is preferable to the internal names that are simply
# sequential numbers such as `_000019_`. Renamed net names can be very long, such as:
#     io_master_rvalid_AOI21X0P5H7R_A1_Y_NOR3BX0P5H7R_C_Y_ \
#     NAND4X1P4H7L_D_Y_NOR2X0P5H7R_A_Y_ICGX0P5H7R_E/E
autoname

# write synthesized design for netlist simulation without splitting module ports
write_verilog -attr2comment -noexpr -nohex -nodec -defparam ${final_netlist_sim_file}

# splitting nets resolves unwanted compound assign statements in netlist (assign {..} = {..}
splitnets -format __v -ports

# remove unused cells and wires
opt_clean -purge

# reports
tee -q -o "${synth_stat_json}" stat -json -top $top_design {*}$liberty_args
tee -q -o "${synth_check_rpt}" check -mapped

# write synthesized design
write_verilog -attr2comment -noexpr -nohex -nodec -defparam ${final_netlist_file}
