"""User-written inputs to ECC's generated timing constraints."""

from .common import ParamSchema

SCHEMAS = tuple(
    ParamSchema(
        param=f"sdc.{name}",
        group="sdc",
        name=name,
        type="str",
        default="",
        applies="all",
        maps_to={"sdc": name},
        description=description,
        example=example,
    )
    for name, description, example in (
        (
            "clock_list",
            "Primary clocks: port/pin and corner:MHz pairs per line; empty uses design defaults",
            "clk MAX:100 WCL:100 MIN:100 ML:100 TYP:100",
        ),
        (
            "generated_clock_txt",
            "Tcl defining generated clocks after primary clocks",
            "create_generated_clock -name CLK_div2 -divide_by 2 "
            "-source [get_ports clk] [get_pins u_div/Q]",
        ),
        (
            "clk_group_txt",
            "Tcl defining clock groups after generated clocks",
            "set_clock_groups -asynchronous -group {CLK_clk CLK_div2} -group {CLK_aux}",
        ),
        (
            "io_constraint_txt",
            "User IO timing Tcl, applied after automatic IO constraints",
            "set_input_delay 0.1 -max -clock CLK_clk [get_ports data_in*]",
        ),
        (
            "timing_exception_txt",
            "Timing-exception Tcl, applied after user IO timing constraints",
            "set_false_path -from [get_ports reset_n]",
        ),
    )
)
