#!/usr/bin/env python

import json

from chipcompiler.engine.reconcile import (
    compare_flows,
    reconcile_workspace,
    resolve_target_section,
)

RTL2GDS_STEPS = [
    ("Synthesis", "yosys"),
    ("lec", "yosys_lec"),
    ("Floorplan", "ecc"),
    ("place", "dreamplace"),
    ("CTS", "ecc"),
    ("legalization", "dreamplace"),
    ("Timing optimization", "sizer"),
    ("route", "ecc"),
    ("filler", "ecc"),
    ("RCX", "ecc"),
    ("sta", "ecc"),
    ("lvs", "ecc"),
    ("postRouteLec", "yosys_lec"),
    ("drc", "ecc"),
    ("Harden", "ecc"),
]
LEGACY_RTL2GDS_STEPS = RTL2GDS_STEPS[:-3]
FULL_FLOW_SUFFIX = RTL2GDS_STEPS[-3:]
LEGACY_SYNTH_LEC_STEPS = [entry for entry in RTL2GDS_STEPS if entry[0] != "lec"]


def _write_workspace(tmp_path, steps, states=None, flow_section=None, params=None):
    workspace_dir = tmp_path / "workspace"
    home = workspace_dir / "home"
    home.mkdir(parents=True)
    states = states or ["Success"] * len(steps)
    flow = {
        "steps": [
            {
                "name": name,
                "tool": tool,
                "state": state,
                "runtime": "",
                "peak memory (mb)": 0,
                "info": {},
            }
            for (name, tool), state in zip(steps, states, strict=True)
        ]
    }
    (home / "flow.json").write_text(json.dumps(flow))

    from chipcompiler.data.workspace_config import save_workspace_config

    payload = params or {
        "pdk": "ics55",
        "design": "gcd",
        "top_module": "gcd",
        "clock": "clk",
    }
    assert save_workspace_config(workspace_dir, payload, flow_section)
    return workspace_dir


def _flow_steps(workspace_dir):
    return json.loads((workspace_dir / "home" / "flow.json").read_text())["steps"]


def _flow_section(workspace_dir):
    from chipcompiler.data.workspace_config import load_workspace_config

    return load_workspace_config(workspace_dir)["_flow"]


class TestCompareFlows:
    def test_equal(self):
        assert compare_flows(RTL2GDS_STEPS, RTL2GDS_STEPS) == "equal"

    def test_proper_prefix(self):
        assert compare_flows(LEGACY_RTL2GDS_STEPS, RTL2GDS_STEPS) == "proper_prefix"

    def test_target_prefix(self):
        assert compare_flows(RTL2GDS_STEPS, LEGACY_RTL2GDS_STEPS) == "target_prefix"

    def test_divergent(self):
        diverged = [("Synthesis", "ecc")] + RTL2GDS_STEPS[1:]
        assert compare_flows(diverged, RTL2GDS_STEPS) == "divergent"
        assert compare_flows(RTL2GDS_STEPS[:3], RTL2GDS_STEPS[1:4]) == "divergent"


class TestReconcile:
    def test_upgrade_inserts_new_synthesis_lec_step(self, tmp_path):
        workspace_dir = _write_workspace(
            tmp_path, LEGACY_SYNTH_LEC_STEPS, flow_section={"preset": "rtl2gds"}
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

        assert result.outcome == "extended"
        assert result.appended == ("lec",)
        steps = _flow_steps(workspace_dir)
        assert [(s["name"], s["tool"]) for s in steps] == RTL2GDS_STEPS
        assert steps[0]["state"] == "Success"
        assert steps[1]["state"] == "Unstart"
        assert all(s["state"] == "Success" for s in steps[2:])

    def test_extension_appends_suffix_and_adopts_target(self, tmp_path):
        workspace_dir = _write_workspace(
            tmp_path, LEGACY_RTL2GDS_STEPS, flow_section={"preset": "rtl2gds"}
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

        assert result.outcome == "extended"
        assert result.appended == tuple(name for name, _tool in FULL_FLOW_SUFFIX)
        steps = _flow_steps(workspace_dir)
        assert [(s["name"], s["tool"]) for s in steps] == RTL2GDS_STEPS
        assert all(s["state"] == "Success" for s in steps[: len(LEGACY_RTL2GDS_STEPS)])
        assert [s["state"] for s in steps[-3:]] == ["Unstart", "Unstart", "Unstart"]
        assert _flow_section(workspace_dir) == {"preset": "rtl2gds"}

    def test_extension_resumes_from_first_non_success(self, tmp_path):
        states = ["Success"] * (len(LEGACY_RTL2GDS_STEPS) - 1) + ["Ongoing"]
        workspace_dir = _write_workspace(
            tmp_path, LEGACY_RTL2GDS_STEPS, states=states, flow_section={"preset": "rtl2gds"}
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

        assert result.outcome == "extended"
        assert result.appended == tuple(name for name, _tool in FULL_FLOW_SUFFIX)

    def test_equal_all_success_is_no_op(self, tmp_path):
        workspace_dir = _write_workspace(
            tmp_path, RTL2GDS_STEPS, flow_section={"preset": "rtl2gds"}
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

        assert result.outcome == "no_op"

    def test_equal_with_non_success_is_resume(self, tmp_path):
        states = ["Success"] * (len(RTL2GDS_STEPS) - 1) + ["Imcomplete"]
        workspace_dir = _write_workspace(
            tmp_path, RTL2GDS_STEPS, states=states, flow_section={"preset": "rtl2gds"}
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

        assert result.outcome == "resume"

    def test_target_prefix_keeps_extra_steps(self, tmp_path):
        workspace_dir = _write_workspace(
            tmp_path,
            RTL2GDS_STEPS,
            flow_section={"preset": "rtl2gds"},
        )

        result = reconcile_workspace(workspace_dir, {"start": "Synthesis", "end": "postRouteLec"})

        assert result.outcome == "no_op"
        assert len(_flow_steps(workspace_dir)) == len(RTL2GDS_STEPS)
        # A stale wider target is adopted to the effective one; the extra
        # persisted steps stay in the ledger untouched.
        assert _flow_section(workspace_dir) == {"start": "Synthesis", "end": "postRouteLec"}

    def test_target_prefix_noop_even_with_unfinished_extras(self, tmp_path):
        # Extra steps beyond the target are never the run's business, and
        # the workspace's [flow] is never widened to cover them.
        target_end = next(
            index for index, (name, _tool) in enumerate(RTL2GDS_STEPS) if name == "postRouteLec"
        )
        states = ["Success"] * (target_end + 1) + ["Unstart"] * (
            len(RTL2GDS_STEPS) - target_end - 1
        )
        workspace_dir = _write_workspace(
            tmp_path,
            RTL2GDS_STEPS,
            states=states,
            flow_section={"preset": "rtl2gds"},
        )

        target = {"start": "Synthesis", "end": "postRouteLec"}
        result = reconcile_workspace(workspace_dir, target)

        assert result.outcome == "no_op"
        assert _flow_section(workspace_dir) == target
        # A follow-up reconcile with the same target no-ops too — the extras
        # never become executable.
        assert reconcile_workspace(workspace_dir, target).outcome == "no_op"

    def test_crash_window_repair_then_resume(self, tmp_path):
        # flow.json appended (suffix Unstart) but [flow] never adopted.
        states = ["Success"] * len(LEGACY_RTL2GDS_STEPS) + ["Unstart"] * len(FULL_FLOW_SUFFIX)
        workspace_dir = _write_workspace(
            tmp_path,
            RTL2GDS_STEPS,
            states=states,
            flow_section={"start": "Synthesis", "end": "postRouteLec"},
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

        assert result.outcome == "resume"
        assert _flow_section(workspace_dir) == {"preset": "rtl2gds"}

    def test_stale_flow_section_repaired(self, tmp_path):
        # Crash window: flow.json already extended, [flow] never adopted.
        workspace_dir = _write_workspace(
            tmp_path,
            RTL2GDS_STEPS,
            flow_section={"start": "Synthesis", "end": "postRouteLec"},
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

        assert result.outcome == "repaired"
        assert _flow_section(workspace_dir) == {"preset": "rtl2gds"}
        # A follow-up reconcile with the same target is a clean no-op.
        assert reconcile_workspace(workspace_dir, {"preset": "rtl2gds"}).outcome == "no_op"

    def test_divergent_flows_fail_with_zero_mutation(self, tmp_path):
        workspace_dir = _write_workspace(
            tmp_path, RTL2GDS_STEPS, flow_section={"preset": "rtl2gds"}
        )
        flow_before = (workspace_dir / "home" / "flow.json").read_bytes()
        config_before = (workspace_dir / "home" / "params.toml").read_bytes()

        result = reconcile_workspace(workspace_dir, {"start": "place", "end": "route"})

        assert result.outcome == "mismatch"
        assert result.error == "flow_mismatch"
        assert (workspace_dir / "home" / "flow.json").read_bytes() == flow_before
        assert (workspace_dir / "home" / "params.toml").read_bytes() == config_before

    def test_missing_flow_section_derives_target_from_persisted(self, tmp_path):
        workspace_dir = _write_workspace(tmp_path, RTL2GDS_STEPS, flow_section=None)

        result = reconcile_workspace(workspace_dir)

        # Absent [flow] derives from the persisted ledger at load; the
        # derived range matches the persisted flow, so the run no-ops.
        assert result.outcome == "no_op"
        assert _flow_section(workspace_dir) == {"start": "Synthesis", "end": "Harden"}

    def test_unknown_persisted_steps_are_a_mismatch_not_a_crash(self, tmp_path):
        workspace_dir = _write_workspace(
            tmp_path, [("MysteryStep", "ecc"), ("Synthesis", "yosys")], flow_section=None
        )
        flow_before = (workspace_dir / "home" / "flow.json").read_bytes()

        result = reconcile_workspace(workspace_dir)

        # The target derives from the persisted ledger when no [flow]
        # exists; a foreign or hand-edited ledger is unreadable, never an
        # uncaught exception — and classification stays pure-read.
        assert result.outcome == "mismatch"
        assert (result.error or "").startswith("workspace_config_invalid")
        assert (workspace_dir / "home" / "flow.json").read_bytes() == flow_before

    def test_undecodable_config_is_a_mismatch_not_a_crash(self, tmp_path):
        workspace_dir = _write_workspace(tmp_path, RTL2GDS_STEPS, flow_section=None)
        (workspace_dir / "home" / "params.toml").write_bytes(b"\xff")
        flow_before = (workspace_dir / "home" / "flow.json").read_bytes()

        result = reconcile_workspace(workspace_dir)

        assert result.outcome == "mismatch"
        assert (result.error or "").startswith("workspace_config_invalid")
        assert (workspace_dir / "home" / "flow.json").read_bytes() == flow_before


class TestTargetPrecedence:
    def test_project_flow_wins_over_workspace_flow(self):
        assert resolve_target_section(
            {"start": "Synthesis", "end": "sta"}, {"preset": "rtl2gds"}
        ) == {"start": "Synthesis", "end": "sta"}
        assert resolve_target_section({}, {"preset": "rtl2gds"}) == {"preset": "rtl2gds"}
        assert resolve_target_section(None, {"start": "place", "end": "route"}) == {
            "start": "place",
            "end": "route",
        }


def test_adoption_failure_is_an_error_not_a_tolerated_stale_target(tmp_path, monkeypatch):
    workspace_dir = _write_workspace(
        tmp_path, LEGACY_RTL2GDS_STEPS, flow_section={"preset": "rtl2gds"}
    )
    monkeypatch.setattr(
        "chipcompiler.data.workspace_config.save_workspace_config", lambda *a, **k: False
    )

    result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

    assert result.outcome == "mismatch"
    assert result.error is not None
    assert result.error.startswith("flow_adopt_failed")
