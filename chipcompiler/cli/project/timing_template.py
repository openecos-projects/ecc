"""Standalone five-field timing input included in new projects."""

SDC_INPUT_FILENAME = "timing_constraints_template.tcl"

SDC_INPUT_TEMPLATE = r"""
# ECC timing inputs: five TOML strings, not an executable Tcl script.
# Edit primary_clocks; uncomment optional commands inside the quotes as needed.
# ECC generates pre_CTS and post_CTS constraints from these inputs.

# 1. Primary clocks: period in ns; 10 ns = 100 MHz (all corners).
# One create_clock per line; the first supplies the flow's main clock.
primary_clocks = '''
create_clock -name CLK_clk -period 10 [get_ports clk]
'''

# 2. Generated clocks: define the source, target pin, and division ratio.
generated_clocks = '''
# create_generated_clock -name CLK_div2 -divide_by 2 \
#     -source [get_ports clk] [get_pins u_div/clk_reg/Q]
'''

# 3. Asynchronous groups: include each domain's primary, generated and virtual clocks.
clock_groups = '''
# set_clock_groups -asynchronous \
#     -group {CLK_clk VCLK_clk CLK_div2} -group {CLK_clk_aux VCLK_clk_aux}
'''

# 4. IO delays (ns): applied after automatic IO constraints.
io_constraints = '''
# set_input_delay   0.1    -max -clock CLK_clk [get_ports data_in*]
# set_input_delay  -0.1    -min -clock CLK_clk [get_ports data_in*]
# set_output_delay  0.0625 -max -clock CLK_clk [get_ports data_out*]
# set_output_delay -0.1    -min -clock CLK_clk [get_ports data_out*]
'''

# 5. Timing exceptions: false or multicycle paths justified by your design.
timing_exceptions = '''
# set_false_path -from [get_ports reset_n]
'''
"""
