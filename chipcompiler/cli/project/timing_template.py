"""Editable timing-input section included in new ecc.toml projects."""

SDC_INPUT_TEMPLATE = r"""
# Fill between the two lines of ''' below each field.
# Copy the example lines there, remove their leading #, and replace names/values.
# Leave unused fields empty. Write commands directly, not set <field> {...}.
# Used in pre_CTS and post_CTS; [design].sdc overrides this entire section.
[params.sdc]

# 1. Primary clocks: each row is <port-or-pin> <corner>:<MHz> ...
# Replace clk with your actual clock port, or an internal pin path such as u_pll/Q.
# Keep MAX/WCL/MIN/ML/TYP; replace each number with the frequency in MHz, not ns.
# Example: for clk at 100 MHz in all corners, replace the empty block with this
# complete block (remove the leading # from its three lines):
# clock_list = '''
# clk MAX:100 WCL:100 MIN:100 ML:100 TYP:100
# '''
# Multiple clocks: add one row per clock inside the SAME pair of triple quotes.
# Empty: use [design].clock_port / frequency_mhz instead.
clock_list = '''
'''

# 2. Generated clocks: replace clk and u_div/clk_reg/Q with your source and target.
# create_generated_clock -name CLK_div2 -divide_by 2 \
#     -source [get_ports clk] [get_pins u_div/clk_reg/Q]
generated_clock_txt = '''
'''

# 3. Asynchronous clock groups: use clocks you defined, including derived clocks.
# For designs without IO cells, include ECC's VCLK_<port> interface clocks too.
# set_clock_groups -asynchronous \
#     -group {CLK_clk VCLK_clk CLK_div2} -group {CLK_clk_aux VCLK_clk_aux}
clk_group_txt = '''
'''

# 4. IO delays (ns): replace ports and values; applied after automatic IO rules.
# set_input_delay   0.1    -max -clock CLK_clk [get_ports data_in*]
# set_input_delay  -0.1    -min -clock CLK_clk [get_ports data_in*]
# set_output_delay  0.0625 -max -clock CLK_clk [get_ports data_out*]
# set_output_delay -0.1    -min -clock CLK_clk [get_ports data_out*]
io_constraint_txt = '''
'''

# 5. Timing exceptions: add only false/multicycle paths justified by your design.
# set_false_path -from [get_ports reset_n]
timing_exception_txt = '''
'''
"""
