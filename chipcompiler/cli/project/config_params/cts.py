from .common import config_param

SCHEMAS = (
    config_param("cts.skew_bound", "cts", ("skew_bound",), "0.08", applies="cts"),
    config_param("cts.max_buf_tran", "cts", ("max_buf_tran",), "0.5", applies="cts"),
    config_param("cts.root_input_slew", "cts", ("root_input_slew",), "0.0", applies="cts"),
    config_param("cts.max_sink_tran", "cts", ("max_sink_tran",), "0.5", applies="cts"),
    config_param("cts.max_cap", "cts", ("max_cap",), "0.15", applies="cts"),
    config_param("cts.max_length", "cts", ("max_length",), "300", applies="cts"),
    config_param(
        "cts.wirelength_iterations", "cts", ("wirelength_iterations",), "3", applies="cts"
    ),
    config_param("cts.slew_steps", "cts", ("slew_steps",), "10", applies="cts"),
    config_param("cts.cap_steps", "cts", ("cap_steps",), "10", applies="cts"),
    config_param(
        "cts.routing_layer", "cts", ("routing_layer",), [4, 5], applies="cts", type="list[int]"
    ),
    config_param("cts.buffer_type", "cts", ("buffer_type",), [], applies="cts", type="list[str]"),
    config_param("cts.use_netlist", "cts", ("use_netlist",), "OFF", applies="cts"),
    config_param("cts.net_list", "cts", ("net_list",), [], applies="cts", type="list[str]"),
)
