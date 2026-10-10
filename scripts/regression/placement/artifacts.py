"""Validate actual placement settings, window weights and final geometry."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .common import content_digest, digest, effective_parameters, grid, read, require, workspace


@dataclass(frozen=True)
class PlacementArtifacts:
    report: dict
    parameters: dict
    aggregation_events: list[dict]


def validate_windows(windows: list, policy: dict):
    for window in windows:
        actual = window["sizing"]["coefficients"]
        require(actual["mode"] == policy["mode"], "Sizing coefficient mode changed")
        if policy["mode"] == "fixed":
            expected = {
                "mode": "fixed",
                "timing_grad_balance_weight": 1.0,
                **{key: policy[key] for key in ("wns", "tns", "cap", "slew")},
            }
            require(actual == expected, f"Fixed sizing weights changed: {actual}")
        else:
            require(
                all(
                    math.isfinite(actual[key]) and actual[key] >= 0
                    for key in ("wns", "tns", "cap", "slew", "timing_grad_balance_weight")
                ),
                f"Invalid inherited weights: {actual}",
            )


def inspect_placement(batch: Path, case: dict):
    name = case["name"]
    out = batch / "cases" / name
    place = workspace(batch, name) / "place_dreamplace"
    log = place / "log/place.log"
    params = effective_parameters(log)
    expected = read(out / "preflight.json")["parameters"]
    require({key: params[key] for key in expected} == expected, f"Runtime profile changed: {name}")
    events = [
        json.loads(line.split("TIMING_AGGREGATION_EFFECTIVE ", 1)[1])
        for line in log.read_text(errors="replace").splitlines()
        if "TIMING_AGGREGATION_EFFECTIVE " in line
    ]
    require(
        bool(events)
        and all(
            event["mode"] == params["timing_aggregation_mode"]
            and event["tau_ps"] == params["timing_aggregation_tau_ps"]
            for event in events
        ),
        f"Propagation settings changed: {name}",
    )
    terminal = read(place / "data/pl" / f"{name}_inflation_s5b1_terminal.json")
    debug = read(place / "data/pl" / f"{name}_placement_debug_summary.json")
    windows = read(place / "data/pl" / f"{name}_inflation_s5b1.json")["windows"]
    require(
        terminal["status"] == "ok" and terminal["legal"] and terminal["virtual_count"] == 0,
        f"Incomplete or illegal terminal placement: {name}",
    )
    validate_windows(windows, params["timing_opt_coefficients"])
    terms = terminal["gp_timing"].get("objective_terms")
    if terms:
        if debug["timing_grad_balance"].get("initialized"):
            require(
                terms["weights"]["timing"] == debug["timing_grad_balance"]["weight_applied"],
                f"GP alpha was not restored: {name}",
            )
        require(
            terms["weights"]["cap"] == params["timing_cap_weight"]
            and terms["weights"]["slew"] == params["timing_slew_weight"],
            f"GP auxiliary weights were not restored: {name}",
        )
        if params["timing_coeff_growth_factor"] == 1.0:
            require(
                terms["coefficients"]
                == {"wns": params["timing_wns_coeff"], "tns": params["timing_tns_coeff"]},
                f"GP timing coefficients were not restored: {name}",
            )
    definition = place / "output" / f"{name}_place.def.gz"
    netlist = place / "output" / f"{name}_place.v.gz"
    require(grid(definition) == grid(Path(case["inputs"]["def"])), f"Routing grid changed: {name}")
    flow = read(place.parent / "home/flow.json")
    require(all(step["state"] == "Success" for step in flow["steps"]), f"Flow incomplete: {name}")
    report = {
        "status": "placement_completed",
        "case": name,
        "source_phase": case["source_phase"],
        "input_hashes": case["hashes"],
        "internal_ns": {key: terminal["final_timing"][key] / 1000 for key in ("wns", "tns")},
        "gp_ns": {key: terminal["gp_timing"][key] / 1000 for key in ("wns", "tns")},
        "iterations": debug["actual_iterations"],
        "final_overflow": debug["final_overflow"],
        "grad_balance": debug["timing_grad_balance"],
        "routing_grid_preserved": True,
        "gp_terminal_objective_terms": terms,
        "sizing_windows": [
            {
                "iteration": window["iteration"],
                "best_round": window["sizing"]["best_round"],
                "coefficients": window["sizing"]["coefficients"],
            }
            for window in windows
        ],
        "def": str(definition),
        "verilog": str(netlist),
        "def_sha256": digest(definition),
        "def_content_sha256": content_digest(definition),
    }
    return PlacementArtifacts(report, params, events)
