"""Standalone five-field timing input included in new projects."""

SDC_INPUT_FILENAME = "timing_constraints_template.tcl"

SDC_INPUT_TEMPLATE = r"""
# ECC timing inputs: five TOML strings, not an executable Tcl script.
# Edit clock_list; uncomment optional commands inside the quotes as needed.
# ECC generates pre_CTS and post_CTS constraints from these inputs.

# 1. Primary clocks: each row is <port-or-pin> <corner>:<MHz> ...
# The first row's TYP value also drives flow metadata.
clock_list = '''
clk MAX:100 WCL:100 MIN:100 ML:100 TYP:100
'''

# 2. Generated clocks: define the source, target pin, and division ratio.
generated_clock_txt = '''
# create_generated_clock -name CLK_div2 -divide_by 2 \
#     -source [get_ports clk] [get_pins u_div/clk_reg/Q]
'''

# 3. Asynchronous groups: include each domain's primary, generated and virtual clocks.
clk_group_txt = '''
# set_clock_groups -asynchronous \
#     -group {CLK_clk VCLK_clk CLK_div2} -group {CLK_clk_aux VCLK_clk_aux}
'''

# 4. IO delays (ns): applied after automatic IO constraints.
io_constraint_txt = '''
# set_input_delay   0.1    -max -clock CLK_clk [get_ports data_in*]
# set_input_delay  -0.1    -min -clock CLK_clk [get_ports data_in*]
# set_output_delay  0.0625 -max -clock CLK_clk [get_ports data_out*]
# set_output_delay -0.1    -min -clock CLK_clk [get_ports data_out*]
'''

# 5. Timing exceptions: false or multicycle paths justified by your design.
timing_exception_txt = '''
# set_false_path -from [get_ports reset_n]
'''
"""
