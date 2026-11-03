"""Editable timing-input section included in new ecc.toml projects."""

SDC_INPUT_TEMPLATE = r"""
# Optional inputs to origin/pre_CTS/*.tcl and origin/post_CTS/*.tcl.
# A complete [design].sdc file takes priority over ALL five fields below.
# Write Tcl directly inside the triple SINGLE quotes: backslashes stay literal.
# Examples below are comments only. Use actual ports/pins and timing requirements.
[params.sdc]

# 1. Primary clocks: <port-or-pin> <corner>:<MHz> ... (one clock per line).
# Empty/comment-only: use [design].clock_port and frequency_mhz.
# Nonempty: replaces that generated clock; supply every generated PVT corner.
# Decimal MHz is supported. Default PVT names: MAX, WCL, MIN, ML, TYP.
# Port clock names: CLK_<port>. For pins, / . [ become _ and ] is removed.
# Examples (copy the desired rows between the quotes, WITHOUT the leading #):
# clk       MAX:100 WCL:100 MIN:100 ML:100 TYP:100
# clk_aux   MAX:25  WCL:25  MIN:25  ML:25  TYP:25
# u_pll/Q   MAX:200 WCL:200 MIN:200 ML:200 TYP:200
clock_list = '''
'''

# 2. Generated clocks: use real source/target objects; empty means none.
# Their per-clock limits require get_attribute and foreach_in_collection in
# the timing tool. Do not assume every bundled native tool implements them.
# Example:
# create_generated_clock -name CLK_div2 -divide_by 2 \
#     -source [get_ports clk] [get_pins u_div/clk_reg/Q]
generated_clock_txt = '''
'''

# 3. Clock groups: only declare domains asynchronous when that is true.
# Include their generated clocks. For a core without IO cells, ECC also creates
# VCLK_<port> interface clocks; include them in the corresponding group.
# Example (for the clk/clk_aux/CLK_div2 example above, without IO cells):
# set_clock_groups -asynchronous \
#     -group {CLK_clk VCLK_clk CLK_div2} -group {CLK_clk_aux VCLK_clk_aux}
clk_group_txt = '''
'''

# 4. User IO constraints: executed AFTER automatic IO constraints.
# Values below are examples in ns, NOT interface specifications.
# Whether delays replace or add to existing ones depends on the Tcl options.
# $corner and $rc_para name the scenario, if conditional commands are needed.
# Example:
# set_input_delay   0.1    -max -clock CLK_clk [get_ports data_in*]
# set_input_delay  -0.1    -min -clock CLK_clk [get_ports data_in*]
# set_output_delay  0.0625 -max -clock CLK_clk [get_ports data_out*]
# set_output_delay -0.1    -min -clock CLK_clk [get_ports data_out*]
io_constraint_txt = '''
'''

# 5. Timing exceptions: only constrain paths justified by the design/protocol.
# Examples (independent; do NOT enable blindly):
# set_false_path -from [get_ports reset_n]
# set_multicycle_path -setup 3 -end -to [get_ports data_out*]
# set_multicycle_path -hold  2 -end -to [get_ports data_out*]
timing_exception_txt = '''
'''
"""
