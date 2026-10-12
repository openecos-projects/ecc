# Auto-generated SDC file

set clk_name          clk
set clk_port_name     clk
set clk_freq_mhz      100.0
set clk_period        [expr 1000.0 / $clk_freq_mhz]

# -------------------------------------------------
# Clock definition
# -------------------------------------------------
set clk_port [get_ports $clk_port_name]
create_clock -name $clk_name -period $clk_period $clk_port

# -------------------------------------------------
# IO Delay
# -------------------------------------------------
set clk_input          [get_ports $clk_port_name]
set all_inputs_wo_clk  [remove_from_collection [all_inputs] $clk_input]

set_input_delay  0  -clock [get_clocks $clk_name] $all_inputs_wo_clk
set_output_delay 0 -clock [get_clocks $clk_name] [all_outputs]

# -------------------------------------------------
# Output load (pF) - ics55 pdk
# -------------------------------------------------
set_load 0.001 [all_outputs]

# -------------------------------------------------
# Clock uncertainty & transition
# -------------------------------------------------
set clk_setup_uncertainty [expr $clk_period * 0.015]            ;# 1.5% of period
set clk_hold_uncertainty  [expr $clk_period * 0.005]            ;# 0.5% of period
set clk_transition        [expr min(0.15, $clk_period * 0.03)]  ;# 3%, cap 0.15ns
set input_transition      [expr min(0.20, $clk_period * 0.05)]  ;# 5%, cap 0.20ns

set_clock_uncertainty -setup $clk_setup_uncertainty [get_clocks $clk_name]
set_clock_uncertainty -hold  $clk_hold_uncertainty  [get_clocks $clk_name]
set_clock_transition  $clk_transition   [get_clocks $clk_name]
set_input_transition  $input_transition $all_inputs_wo_clk

# -------------------------------------------------
# Design-level constraints
# -------------------------------------------------
set_max_fanout 32 [current_design]
