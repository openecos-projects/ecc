import re
import shlex


def disclosure_cmd(command: str, project: str | None = None, run_id: str | None = None) -> str:
    parts = [command]
    if project:
        parts.append(f"--project {shlex.quote(project)}")
    if run_id:
        parts.append(f"--run-id {shlex.quote(run_id)}")
    return " ".join(parts)


def normalize_step_name(internal: str) -> str:
    mapping = {
        "Synthesis": "synthesis",
        "Floorplan": "floorplan",
        "fixFanout": "fixfanout",
        "place": "placement",
        "CTS": "cts",
        "legalization": "legalization",
        "route": "routing",
        "drc": "drc",
        "filler": "filler",
    }
    return mapping.get(internal, internal.lower())


def normalize_state(internal: str) -> str:
    mapping = {
        "Success": "success",
        "Incomplete": "incomplete",
        "Unstart": "unstart",
        "Ongoing": "ongoing",
        "Pending": "pending",
        "Invalid": "invalid",
    }
    return mapping.get(internal, internal.lower())


def normalize_metric_key(raw_key: str) -> str:
    known = {
        "Cell number": "cell_number",
        "Cell area": "cell_area",
        "Wire number": "wire_number",
        "Port number": "port_number",
        "Frequency [MHz]": "frequency_mhz",
        "Die area [μm^2]": "die_area_um2",
        "Die width [um]": "die_width_um",
        "Die height [um]": "die_height_um",
        "Die util": "die_util",
        "Core util": "core_util",
        "Total io pins": "total_io_pins",
        "Total instances": "total_instances",
        "Total nets": "total_nets",
        "max_WNS": "max_wns",
        "max_TNS": "max_tns",
        "min_WNS": "min_wns",
        "min_TNS": "min_tns",
        "GP HPWL": "gp_hpwl",
        "DP HPWL": "dp_hpwl",
        "overflow": "overflow",
        "overflow_number": "overflow_number",
        "bin_number": "bin_number",
        "buffer_num": "buffer_num",
        "buffer_area": "buffer_area",
        "clock_path_max_buffer": "clock_path_max_buffer",
        "clock_path_min_buffer": "clock_path_min_buffer",
        "total_clock_wirelength": "total_clock_wirelength",
        "wire_len": "wire_len",
        "num_via": "num_via",
        "total_movement": "total_movement",
        "drc_num": "drc_num",
        "Max fanout": "max_fanout",
        "Tool": "tool",
    }
    if raw_key in known:
        return known[raw_key]
    s = raw_key.lower()
    s = re.sub(r"[\s\[\]μ^]+", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    return s
