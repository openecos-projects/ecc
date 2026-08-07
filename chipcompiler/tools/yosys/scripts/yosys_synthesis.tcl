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

yosys -import

#===========================================================
# Strategy selection
#===========================================================
# Three optimization directions:
#   DELAY N   — maximize frequency
#   AREA N    — minimize area
#   BALANCE N — balanced PPA
set synth_strategy "BALANCE 3"
if {[info exists env(YOSYS_SYNTH_STRATEGY)]} {
  # TODO: Move this to global_var.tcl
  set synth_strategy $::env(YOSYS_SYNTH_STRATEGY)
}

set strategy_parts [split $synth_strategy]
if {[llength $strategy_parts] != 2} {
  log -stderr "\[ERROR] Misformatted synth_strategy (\"$synth_strategy\")."
  log -stderr "\[ERROR] Correct format: DELAY|AREA|BALANCE 0-N."
  exit 1
}
set strategy_type [lindex $strategy_parts 0]
set strategy_type_idx [lindex $strategy_parts 1]

set valid_types {DELAY AREA BALANCE}
  if {$strategy_type ni $valid_types} {
  log -stderr "\[ERROR] Unknown strategy type \"$strategy_type\"."
  log -stderr "\[ERROR] Must be one of: DELAY, AREA, BALANCE."
  exit 1
}

#===========================================================
# Per-family configuration (overridable via env)
#===========================================================

# --- DELAY family ---
# Slack margin: tighten target to push frequency (<1 = tighter)
set delay_slack_margin 0.92
# Redelay depth
set delay_retime_M 8
# Max fanout for buffer insertion
set delay_max_FO 24
# Multi-pass: 0=off, 1=on (second ABC pass to reinforce critical paths)
set delay_multipass 1
# Pass-2 relaxation factor
set delay_pass2_relax 1.05

# --- AREA family ---
# Relax factor: loosen target so ABC can pick smaller cells (>1 = looser)
set area_relax_factor 1.15
# Retiming depth (light for area mode)
set area_retime_M 3
# Max fanout (lower = fewer buffers = smaller area)
set area_max_FO 16

# --- BALANCE family ---
# Slight relax (1.0 = nominal, 1.05 = slightly relaxed for area recovery)
set balance_relax_factor 1.0
# Moderate retiming depth
set balance_retime_M 5
# Moderate fanout
set balance_max_FO 24
# Multi-pass for BALANCE
set balance_multipass 0

#===========================================================
# Compute target delay per family
#===========================================================

if {$strategy_type == "DELAY"} {
  set abc_delay_target [expr {int($clk_period_ps * $delay_slack_margin)}]
  set max_FO $delay_max_FO
  set retime_M $delay_retime_M
  set multipass $delay_multipass
  set pass2_relax $delay_pass2_relax
} elseif {$strategy_type == "AREA"} {
  set abc_delay_target [expr {int($clk_period_ps * $area_relax_factor)}]
  set max_FO $area_max_FO
  set retime_M $area_retime_M
  set multipass 0
  set pass2_relax 1.0
} else {
  # BALANCE
  set abc_delay_target [expr {int($clk_period_ps * $balance_relax_factor)}]
  set max_FO $balance_max_FO
  set retime_M $balance_retime_M
  set multipass $balance_multipass
  set pass2_relax 1.0
}

#===========================================================
#   scripts for ABC
#===========================================================

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

# Standard resyn2
set abc_resyn2        "${abc_b};${abc_rw};${abc_rf};${abc_b};${abc_rw};${abc_rwz};${abc_b};${abc_rfz};${abc_rwz};${abc_b}"
set abc_share         "strash;multi,-m;${abc_resyn2}"

# More aggressive resyn variants
set abc_resyn2a       "${abc_b};${abc_rw};${abc_b};${abc_rw};${abc_rwz};${abc_b};${abc_rwz};${abc_b}"
set abc_resyn3        "balance;resub;resub,-K,6;balance;resub,-z;resub,-z,-K,6;balance;resub,-z,-K,5;balance"
set abc_resyn2rs      "${abc_b};${abc_rs_K},6;${abc_rw};${abc_rs_K},6,-N,2;${abc_rf};${abc_rs_K},8;${abc_rw};${abc_rs_K},10;${abc_rwz};${abc_rs_K},10,-N,2;${abc_b},${abc_rs_K},12;${abc_rfz};${abc_rs_K},12,-N,2;${abc_rwz};${abc_b}"

# Choice-based scripts (explore multiple structurally-equivalent forms)
set abc_choice        "fraig_store;${abc_resyn2};fraig_store;${abc_resyn2};fraig_store;fraig_restore"
set abc_choice2       "fraig_store;balance;fraig_store;${abc_resyn2};fraig_store;${abc_resyn2};fraig_store;${abc_resyn2};fraig_store;fraig_restore"

# Retime variants
set abc_retime_std    "retime,-D,{D},-M,${retime_M}"
set abc_retime_fwd    "retime,-D,{D},-M,${retime_M},-f"
set abc_retime_agg    "retime,-D,{D},-M,[expr {${retime_M}+2}],-f"
set abc_retime_dly    "retime,-D,{D},-M,6"
set abc_retime_area   "retime,-D,{D},-M,5"

# Map variants
set abc_map_std       "map,{D}"
set abc_map_tight     "map,-p,-B,0.2,-A,0.9,-M,0"
set abc_map_effort    "map,-p,-B,0.15,-A,0.95,-M,0"
set abc_map_verytight "map,-p,-B,0.10,-A,0.98,-M,0"

# Area map (amap) for AREA family
set abc_amap          "amap,-m,-Q,0.1,-F,20,-A,20,-C,5000"

# Fine-tune variants
# DELAY: grow drivers first, then buffer, then recover slack
set abc_finetune_delay   "buffer,-N,${max_FO};upsize,{D};dnsize,{D};buffer,-N,${max_FO};upsize,{D}"
set abc_finetune_delay2  "upsize,{D};upsize,{D};buffer,-N,${max_FO};dnsize,{D}"
set abc_finetune_delay3  "buffer,-N,${max_FO};upsize,{D};dnsize,{D}"
# AREA: only shrink drivers
set abc_finetune_area    "dnsize,{D};dnsize,{D};dnsize,{D}"
# BALANCE: grow then shrink (net effect = balanced)
set abc_finetune_balance "upsize,{D};dnsize,{D};upsize,{D};dnsize,{D}"

# # Area recovery: after initial mapping, do another resyn+map cycle
# # This is the KEY improvement — multiple mapping passes recover area
# # that the first pass missed.
set abc_area_recovery_1 "${abc_choice}; map;"
set abc_area_recovery_2 "${abc_choice2}; map;"
set abc_area_recovery_3 "${abc_choice2}; ${abc_amap}; ${abc_choice}; map;"

#===========================================================
# Generate abc.constr file dynamically
#===========================================================
set abc_constr_path "${tmp_dir}/abc.constr"
set abc_constr_file [open $abc_constr_path w]
puts $abc_constr_file "set_driving_cell ${abc_driver_cell}"
puts $abc_constr_file "set_load ${abc_load}"
close $abc_constr_file

#=======================================================================
# DELAY scripts — maximize frequency
# 12 scripts (index 0..11)
# Common prefix: fx;mfs;strash;refactor;resyn2;retime_dly;scleanup
# Mapper: abc_map_tight (map,-p,-B,0.2,-A,0.9,-M,0)
# Fine-tune: abc_finetune_delay / delay2 / delay3 (upsize+buffer)
#=======================================================================
# DELAY 0:  baseline resyn2 + map_tight + single fine-tune (lightest)
# DELAY 1:  +choice2 before/after map + retime after map (area_recovery_2 flavor)
# DELAY 2:  +choice before/after map + retime after map (area_recovery_1 flavor)
# DELAY 3:  +choice2 + amap (Q=0.1) mixed in + dual fine-tune
# DELAY 4:  5x unrolled syn2/if-K6 multi-pass + buffer + upsize/dnsize (classic aggressive)
# DELAY 5:  resyn3 + fwd retime + map_effort + dual upsize (no choice2)
# DELAY 6:  resyn2rs + fwd retime + map_effort + dual upsize (cut-size 8/10/12)
# DELAY 7:  resyn3 + fwd retime + choice2 + map_effort + dual upsize
# DELAY 8:  resyn2rs + fwd retime + choice2 + map_effort + dual upsize
# DELAY 9:  resyn3 + agg retime (M=retime_M+4) + choice2 + map_effort
#            + triple upsize + buffer + dnsize (most aggressive single-pass)
# DELAY 10: resyn2 + retime_dly + map_tight + retime + 3x upsize/dnsize
#            (legacy-style aggressive fine-tune)
# DELAY 11: resyn2 + retime_dly + choice2 + map_tight + area_recovery_2
#            + retime + 3x upsize/dnsize (legacy + recovery)
set delay_scripts [list \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_std};scleanup;${abc_map_tight};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_std};scleanup;${abc_choice2};${abc_map_tight};${abc_choice2};map,-p,-B,0.2,-A,0.9,-M,0;retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_std};scleanup;${abc_choice};${abc_map_tight};${abc_choice};map,-p,-B,0.2,-A,0.9,-M,0;retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_std};scleanup;${abc_choice2};amap,-m,-Q,0.1,-F,20,-A,20,-C,5000;${abc_choice2};map,-p,-B,0.2,-A,0.9,-M,0;retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay};stime,-p;print_stats -m" \
  "+&get -n;&st;&dch;&nf;&put;&get -n;&st;&syn2;&if -g -K 6;&synch2;&nf;&put;&get -n;&st;&syn2;&if -g -K 6;&synch2;&nf;&put;&get -n;&st;&syn2;&if -g -K 6;&synch2;&nf;&put;&get -n;&st;&syn2;&if -g -K 6;&synch2;&nf;&put;&get -n;&st;&syn2;&if -g -K 6;&synch2;&nf;&put;buffer -c -N ${max_FO};topo;stime -c;upsize -c;dnsize -c;;stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn3};${abc_retime_fwd};scleanup;${abc_choice2};${abc_map_effort};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay2};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2rs};${abc_retime_fwd};scleanup;${abc_choice2};${abc_map_effort};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay2};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn3};${abc_retime_fwd};scleanup;${abc_choice2};${abc_map_effort};${abc_choice2};map,-p,-B,0.15,-A,0.95,-M,0;retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay2};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2rs};${abc_retime_fwd};scleanup;${abc_choice2};${abc_map_effort};${abc_choice2};map,-p,-B,0.15,-A,0.95,-M,0;retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay2};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn3};${abc_retime_agg};scleanup;${abc_choice2};${abc_map_effort};${abc_choice2};map,-p,-B,0.12,-A,0.97,-M,0;retime,-D,{D};&get,-n;&st;&dch;&nf;&put;upsize,{D};upsize,{D};upsize,{D};buffer,-N,${max_FO};dnsize,{D};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_dly}; scleanup;${abc_map_tight};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay3};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_dly}; scleanup;${abc_choice2};${abc_map_tight};${abc_area_recovery_2}; retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay3};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_dly}; scleanup;${abc_choice};${abc_map_tight};${abc_area_recovery_1}; retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay3};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_area};scleanup;${abc_choice2};${abc_amap};${abc_choice2};${abc_map_tight};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_delay3};stime,-p;print_stats -m" \
]

#=======================================================================
# AREA scripts — minimize area
# 12 scripts (index 0..11)
# Mapper: abc_amap (amap -m -Q 0.1 -F 20 -A 20 -C 5000) or map -a
# Fine-tune: abc_finetune_area (dnsize only, no upsize)
# Retime: abc_retime_area (light, M=retime_M-2) or abc_retime_std
#=======================================================================
# AREA 0:  baseline dch + map -a + single dnsize (lightest)
# AREA 1:  resyn2 + map -a + dnsize x2
# AREA 2:  resyn2 + rewrite -z + balance + map -a + dnsize x3
# AREA 3:  resyn3 + retime_std + amap + dnsize x3
# AREA 4:  resyn2rs + retime_std + amap + dnsize x3 (cut-size 8/10/12)
# AREA 5:  resyn3 + retime_std + choice2 + amap + choice2 + amap(Q=0.1) + dnsize x3
# AREA 6:  resyn2rs + retime_std + choice2 + amap + choice2 + amap(Q=0.1) + dnsize x4
# AREA 7:  resyn3 + agg retime(M+2) + choice2 + amap + mfs(-a,-e)
#           + choice2 + amap(Q=0.1) + dnsize x4 (deepest recovery)
# AREA 8:  resyn2 + retime_area + choice2 + amap + retime + 3x dnsize
#           (legacy-style area recovery, single amap)
# AREA 9:  resyn2 + retime_area + choice2 + amap + choice2 + amap
#           + retime + 3x dnsize (legacy double amap)
# AREA 10: resyn2 + choice2 + retime_area + choice2 + amap x3
#           + retime + 3x dnsize (legacy triple amap)
# AREA 11: resyn3 + retime_area + choice2 + amap x2 + area_recovery_3
#           + choice2 + amap x3 + retime + 3x dnsize (legacy max recovery)
set area_scripts [list \
  "+fx;mfs;strash;dch;map -a;topo;dnsize;stime -p;print_stats -m" \
  "+fx;mfs;strash;dch;${abc_resyn2};map -a;topo;dnsize;dnsize;stime -p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_rwz};${abc_b};dch;map -a;topo;dnsize;dnsize;dnsize;stime -p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn3};${abc_retime_std};scleanup;${abc_amap};topo;dnsize;dnsize;dnsize;stime -p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2rs};${abc_retime_std};scleanup;${abc_amap};topo;dnsize;dnsize;dnsize;stime -p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn3};${abc_retime_std};scleanup;${abc_choice2};${abc_amap};${abc_choice2};amap,-m,-Q,0.1,-F,20,-A,20,-C,5000;topo;dnsize;dnsize;dnsize;stime -p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2rs};${abc_retime_std};scleanup;${abc_choice2};${abc_amap};${abc_choice2};amap,-m,-Q,0.1,-F,20,-A,20,-C,5000;topo;dnsize;dnsize;dnsize;dnsize;stime -p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn3};retime,-D,{D},-M,[expr {${retime_M}+2}];scleanup;${abc_choice2};${abc_amap};mfs,-a,-e;${abc_choice2};amap,-m,-Q,0.1,-F,20,-A,20,-C,5000;topo;dnsize;dnsize;dnsize;dnsize;stime -p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_area};scleanup;${abc_choice2};${abc_amap};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_area};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_area};scleanup;${abc_choice2};${abc_amap};${abc_choice2};${abc_amap};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_area};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_choice2};${abc_retime_area};scleanup;${abc_choice2};${abc_amap};${abc_choice2};${abc_amap};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_area};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn3};${abc_retime_area};scleanup;${abc_choice2};${abc_amap};${abc_choice2};${abc_amap};${abc_area_recovery_3};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_area};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2rs};${abc_retime_area};scleanup;${abc_choice2};${abc_amap};${abc_choice2};${abc_amap};${abc_area_recovery_3};${abc_choice2};${abc_amap};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;${abc_finetune_area};stime,-p;print_stats -m" \
]

#=======================================================================
# BALANCE scripts — balanced PPA
# 8 scripts (index 0..7)
# Retime: abc_retime_std (M=retime_M, default 5, no -f)
# Mapper: abc_map_std (map,-p,-B,0.25,-A,0.9,-M,0) or abc_map_tight or abc_map_effort
# Fine-tune: upsize {D}; dnsize {D} alternating (balance, not pure up/dn)
# Constraint: nominal clock (no slack margin, no relax)
#=======================================================================
# BALANCE 0: baseline resyn2 + map_std + retime + upsize/dnsize (lightest)
# BALANCE 1: resyn2 + map_std + retime + upsize/dnsize/upsize/dnsize (2x2 alternating)
# BALANCE 2: resyn2 + rewrite + map_tight + retime + 2x2 alternating fine-tune
# BALANCE 3: resyn2 + refactor + map_tight + retime + 2x2 alternating fine-tune
# BALANCE 4: resyn3 + map_effort + retime + 2x2 alternating fine-tune
# BALANCE 5: resyn2rs + map_effort + retime + 2x2 alternating fine-tune
# BALANCE 6: resyn3 + choice2 + map_effort + retime + 2x2 alternating fine-tune
# BALANCE 7: resyn2rs + choice2 + map_effort + choice2
#            + map(-p,-B,0.18,-A,0.92,-M,0) + retime + 2x2 alternating (max balanced)
set balance_scripts [list \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_std};scleanup;${abc_map_std};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;upsize,{D};dnsize,{D};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_retime_std};scleanup;${abc_map_std};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;upsize,{D};dnsize,{D};upsize,{D};dnsize,{D};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_rw};${abc_retime_std};scleanup;${abc_map_tight};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;upsize,{D};dnsize,{D};upsize,{D};dnsize,{D};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2};${abc_rf};${abc_retime_std};scleanup;${abc_map_tight};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;upsize,{D};dnsize,{D};upsize,{D};dnsize,{D};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn3};${abc_retime_std};scleanup;${abc_map_effort};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;upsize,{D};dnsize,{D};upsize,{D};dnsize,{D};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2rs};${abc_retime_std};scleanup;${abc_map_effort};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;upsize,{D};dnsize,{D};upsize,{D};dnsize,{D};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn3};${abc_retime_std};scleanup;${abc_choice2};${abc_map_effort};retime,-D,{D};&get,-n;&st;&dch;&nf;&put;upsize,{D};dnsize,{D};upsize,{D};dnsize,{D};stime,-p;print_stats -m" \
  "+fx;mfs;strash;refactor;${abc_resyn2rs};${abc_retime_std};scleanup;${abc_choice2};${abc_map_effort};${abc_choice2};map,-p,-B,0.18,-A,0.92,-M,0;retime,-D,{D};&get,-n;&st;&dch;&nf;&put;upsize,{D};dnsize,{D};upsize,{D};dnsize,{D};stime,-p;print_stats -m" \
]

#===========================================================
# Select script list and clamp index
#===========================================================
set max_idx 0
if {$strategy_type == "DELAY"} {
  set script_list $delay_scripts
  set max_idx [expr {[llength $delay_scripts] - 1}]
} elseif {$strategy_type == "AREA"} {
  set script_list $area_scripts
  set max_idx [expr {[llength $area_scripts] - 1}]
} else {
  set script_list $balance_scripts
  set max_idx [expr {[llength $balance_scripts] - 1}]
}

# Clamp index
if {$strategy_type_idx > $max_idx} {
  log -stderr "\[WARN] $strategy_type index $strategy_type_idx too high, clamping to $max_idx."
  set strategy_type_idx $max_idx
}

set strategy_script [lindex $script_list $strategy_type_idx]
set strategy_name "$strategy_type-$strategy_type_idx"

#===========================================================
# Error handling
#===========================================================
proc synth_strategy_format_err { } {
  upvar area_scripts area_scripts
  upvar delay_scripts delay_scripts
  upvar balance_scripts balance_scripts
  log -stderr "\[ERROR] Misformatted synth_strategy (\"$synth_strategy\")."
  log -stderr "\[ERROR] Format: DELAY 0-[expr [llength $delay_scripts]-1]"
  log -stderr "\[ERROR]         AREA 0-[expr [llength $area_scripts]-1]"
  log -stderr "\[ERROR]         BALANCE 0-[expr [llength $balance_scripts]-1]"
  exit 1
}

#===========================================================
# Logging
#===========================================================
log "\[INFO\]: STRATEGY = $strategy_name"
log "\[INFO\]: CLK_PERIOD = ${clk_period_ps}ps"
log "\[INFO\]: ABC_TARGET  = ${abc_delay_target}ps"
if {$strategy_type == "DELAY"} {
  log "\[INFO\]: DELAY_SLACK_MARGIN = $delay_slack_margin"
  log "\[INFO\]: DELAY_RETIME_M    = $delay_retime_M"
  log "\[INFO\]: DELAY_MAX_FO      = $delay_max_FO"
  log "\[INFO\]: DELAY_MULTIPASS   = $delay_multipass"
} elseif {$strategy_type == "AREA"} {
  log "\[INFO\]: AREA_RELAX_FACTOR  = $area_relax_factor"
  log "\[INFO\]: AREA_RETIME_M      = $area_retime_M"
  log "\[INFO\]: AREA_MAX_FO        = $area_max_FO"
} else {
  log "\[INFO\]: BALANCE_RELAX_FAC  = $balance_relax_factor"
  log "\[INFO\]: BALANCE_RETIME_M   = $balance_retime_M"
  log "\[INFO\]: BALANCE_MAX_FO     = $balance_max_FO"
}
log "\[INFO\]: ABC script: $strategy_script"

#===========================================================
#   main running
#===========================================================

# Use Slang only for input forms that require its filelist/SystemVerilog support.
if {$use_slang} {
  yosys plugin -i slang

  # Check if FILELIST is set and non-empty, prioritize it over individual Verilog files
  if {[info exists filelist] && $filelist ne ""} {
    puts "Reading SystemVerilog sources from filelist: $filelist"
    set arg "-F $filelist"
  } else {
    puts "Reading SystemVerilog sources from rtl files: $rtl_file"
    set arg "{*}$rtl_file"
  }
  yosys read_slang {*}$arg --top $top_design \
    --compat-mode --keep-hierarchy \
    +define+SYNTHESIS \
    --allow-use-before-declare \
    --ignore-timing \
    -Wduplicate-definition
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

#===========================================================
# Generic synthesis (coarse)
#===========================================================
set flatten_flag ""
if {$keep_hierarchy == "false"} {
  set flatten_flag "-flatten"
}
synth -top $top_design {*}$flatten_flag -run :fine

# remove \$check node generated by assert/assume/cover
chformal -remove

share
onehot
muxpack
opt_demorgan
opt_ffinv

opt -fast -purge

#===========================================================
# Generic synthesis (fine)
#===========================================================
synth -run fine:

# simplemap: break complex gates into simple primitives
# This gives ABC a simpler, more uniform input graph.
simplemap

# techmap: map to technology-specific cells where possible
techmap -map +/techmap.v

# Clean up after techmap
opt -fast -purge

# remove unused cells and wires
opt_clean -purge

# Log area after generic synthesis
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

# dfflibmap intentionally handles only flip-flops.  For ics55 it selects the
# final matching DFF library in lib_stdcell_list, so use that same H7 variant
# for the plain D-latch mapping before ABC.
set ics55_latch_suffix ""
if {[llength $lib_stdcell_list] > 0} {
  set dff_lib [lindex $lib_stdcell_list end]
  if {[regexp {ics55_LLSC_H7C([HLR])_} [file tail $dff_lib] -> vt]} {
    set ics55_latch_suffix "H7$vt"
  }
}
if {$ics55_latch_suffix ne ""} {
  set ics55_latch_map "${tmp_dir}/ics55_latch_map.v"
  set latch_map_file [open $ics55_latch_map "w"]
  puts $latch_map_file [format {
module \$_DLATCH_N_ (E, D, Q);
  input E, D;
  output Q;
  LATLX1%s _TECHMAP_REPLACE_ (.D(D), .GN(E), .Q(Q));
endmodule

module \$_DLATCH_P_ (E, D, Q);
  input E, D;
  output Q;
  LATHX1%s _TECHMAP_REPLACE_ (.D(D), .G(E), .Q(Q));
endmodule
} $ics55_latch_suffix $ics55_latch_suffix]
  close $latch_map_file
  techmap -map $ics55_latch_map
  opt -fast -purge
}

# Optimize again after FF mapping — sometimes FFs create
# new optimization opportunities (constant propagation, etc.)
opt -undriven -purge


# technology mapping for cells
abc -D "$abc_delay_target" \
  -constr "$abc_constr_path" \
  {*}$tech_cells_args {*}$exclude_cells \
  -script "$strategy_script" \
  -showtmp

# technology mapping for constant hi- and/or lo-drivers
hilomap -singleton -hicell {*}$tech_cell_tiehi -locell {*}$tech_cell_tielo

# replace undef values with defined constants
setundef -zero

# Multiple clean passes to catch all redundant logic
opt_clean -purge
clean -purge
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
