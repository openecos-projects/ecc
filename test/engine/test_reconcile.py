#!/usr/bin/env python

import json

import pytest

from chipcompiler.data.workspace import _canonical_rtl2gds_flow_entries
from chipcompiler.engine.reconcile import (
    compare_flows,
    reconcile_workspace,
    resolve_target_section,
)
from test.flow_fixture import step_fields

# Derived from the canonical builder so reconciliation tests always
# exercise the real current topology, never a stale hand-copied chain.
RTL2GDS_STEPS = [(name, tool) for name, tool, _state in _canonical_rtl2gds_flow_entries()]
LEGACY_RTL2GDS_STEPS = RTL2GDS_STEPS[:-3]
FULL_FLOW_SUFFIX = RTL2GDS_STEPS[-3:]


def _write_workspace(tmp_path, steps, states=None, flow_section=None, params=None):
    workspace_dir = tmp_path / "workspace"
    home = workspace_dir / "home"
    home.mkdir(parents=True)
    states = states or ["Success"] * len(steps)
    flow = {
        "schema_version": 2,
        "steps": [
            {
                "name": name,
                "tool": tool,
                "state": state,
                "runtime": "",
                "peak memory (mb)": 0,
                "info": {},
                **step_fields(name, tool),
            }
            for (name, tool), state in zip(steps, states, strict=True)
        ],
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


class TestLecEngineReconcile:
    def test_target_entries_run_post_route_lec_with_kepler_formal(self):
        from chipcompiler.engine.reconcile import _target_entries

        entries = _target_entries({"start": "Synthesis", "end": "Harden", "skip_steps": []})

        assert [(name, tool) for name, tool in entries if "lec" in name.lower()] == [
            ("postRouteLec", "kepler_formal"),
        ]


class TestReconcile:
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

    def test_equal_with_legacy_warned_lec_resumes(self, tmp_path):
        # The removed terminal Warning state is not finished: a persisted
        # warned LEC reconciles to a resume that re-runs it and its suffix.
        lec_index = next(
            index for index, (name, _tool) in enumerate(RTL2GDS_STEPS) if name == "postRouteLec"
        )
        states = ["Success"] * len(RTL2GDS_STEPS)
        states[lec_index] = "Warning"
        workspace_dir = _write_workspace(
            tmp_path, RTL2GDS_STEPS, states=states, flow_section={"preset": "rtl2gds"}
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

        assert result.outcome == "resume"

    def test_ledger_starting_off_synthesis_is_still_a_mismatch(self, tmp_path):
        workspace_dir = _write_workspace(
            tmp_path, [("place", "dreamplace")], flow_section={"preset": "rtl2gds"}
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

        assert result.outcome == "mismatch"
        assert result.error == "flow_mismatch"

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


class TestSkipPolicyReconcile:
    """Policy-driven targets: default-skip reproduces post-#280 ledgers;
    skipped ledger steps are inert, never removed or re-inserted."""

    def test_default_policy_reproduces_ledger_without_diff_opt(self, tmp_path):
        without_diff_opt = [(name, tool) for name, tool in RTL2GDS_STEPS if name != "diff_opt"]

        workspace_dir = _write_workspace(
            tmp_path, without_diff_opt, flow_section={"preset": "rtl2gds"}
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})
        assert result.outcome == "no_op"

    def test_ledger_with_diff_opt_stays_runnable_under_default_policy(self, tmp_path):
        workspace_dir = _write_workspace(
            tmp_path, RTL2GDS_STEPS, flow_section={"preset": "rtl2gds"}
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

        assert result.outcome == "no_op"
        # The ledger keeps its diff_opt entry: policy changes never remove steps.
        names = [step["name"] for step in _flow_steps(workspace_dir)]
        assert "diff_opt" in names

    def test_a_ledger_without_diff_opt_never_gains_it_when_policy_enables_it(self, tmp_path):
        without_diff_opt = [(name, tool) for name, tool in RTL2GDS_STEPS if name != "diff_opt"]
        workspace_dir = _write_workspace(
            tmp_path, without_diff_opt, flow_section={"start": "Synthesis", "end": "Harden"}
        )

        result = reconcile_workspace(
            workspace_dir,
            {"start": "Synthesis", "end": "Harden", "skip_steps": []},
        )

        assert result.outcome == "mismatch"
        names = [step["name"] for step in _flow_steps(workspace_dir)]
        assert "diff_opt" not in names

    def test_partial_ledger_with_lec_appends_only_the_missing_suffix(self, tmp_path):
        prefix = RTL2GDS_STEPS[: RTL2GDS_STEPS.index(("CTS", "ecc")) + 1]
        states = ["Success"] * len(prefix)
        workspace_dir = _write_workspace(
            tmp_path, prefix, states=states, flow_section={"preset": "rtl2gds"}
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds"})

        assert result.outcome == "extended"
        names = [step["name"] for step in _flow_steps(workspace_dir)]
        assert names == [name for name, _tool in RTL2GDS_STEPS]
        assert result.appended == tuple(name for name, _tool in RTL2GDS_STEPS[len(prefix) :])

    def test_declared_policy_extends_the_target_chain(self, tmp_path):
        # A workspace declaring skip_steps=[] gets a target WITH diff_opt: a
        # ledger without it extends by the suffix after the last kept step.
        prefix = RTL2GDS_STEPS[:2]  # Synthesis, preFloorplan
        workspace_dir = _write_workspace(
            tmp_path,
            prefix,
            flow_section={"preset": "rtl2gds", "skip_steps": []},
        )

        result = reconcile_workspace(workspace_dir, {"preset": "rtl2gds", "skip_steps": []})

        assert result.outcome == "extended"
        names = [step["name"] for step in _flow_steps(workspace_dir)]
        assert names == [name for name, _tool in RTL2GDS_STEPS]


class TestTargetPrefixWithSkippedLedgerSteps:
    def test_unfinished_in_range_step_resumes_despite_interspersed_skip(self, tmp_path):
        """A skipped ledger entry before the target boundary must not shift
        the state evaluation: an unfinished in-range step means resume, not
        no_op."""
        ledger = RTL2GDS_STEPS  # full chain including diff_opt
        target_end = next(
            index for index, (name, _tool) in enumerate(RTL2GDS_STEPS) if name == "RCX"
        )
        # Everything finished except filler: inside the target range by
        # name, but shifted out of a positional slice by the skipped diff_opt.
        unfinished = next(
            index for index, (name, _tool) in enumerate(RTL2GDS_STEPS) if name == "filler"
        )
        states = ["Unstart" if index == unfinished else "Success" for index in range(len(ledger))]
        assert unfinished < target_end
        workspace_dir = _write_workspace(
            tmp_path, ledger, states=states, flow_section={"preset": "rtl2gds"}
        )

        result = reconcile_workspace(
            workspace_dir,
            {"start": "Synthesis", "end": "RCX", "skip_steps": ["diff_opt"]},
        )

        assert result.outcome == "resume"


@pytest.mark.parametrize(
    ("ledger_lec", "old_line", "flow_line"),
    [
        (("lec", "kepler_formal"), 'end = "preFloorplan"', 'end = "lec"'),
        (("lec", "yosys_lec"), 'lec_engine = "kepler_formal"', 'lec_engine = "yosys_lec"'),
        (("lec", "lec_dual"), 'lec_engine = "kepler_formal"', 'lec_engine = "lec_dual"'),
        # Every LEC skipped: only the workspace [flow] names the engine.
        (None, 'lec_engine = "kepler_formal"', 'lec_engine = "yosys_lec"'),
    ],
)
def test_a_workspace_built_with_a_removed_lec_is_a_flow_mismatch(
    tmp_path, ledger_lec, old_line, flow_line
):
    names = [name for name, _tool in RTL2GDS_STEPS]
    ledger = RTL2GDS_STEPS[: names.index("preFloorplan") + 1]
    if ledger_lec is not None:
        ledger = [ledger[0], ledger_lec, *ledger[1:]]
    section = {"start": "Synthesis", "end": "preFloorplan", "lec_engine": "kepler_formal"}
    workspace_dir = _write_workspace(tmp_path, ledger, flow_section=section)
    # The workspace's own [flow] still names what that version recorded.
    params = workspace_dir / "home" / "params.toml"
    params.write_text(params.read_text().replace(old_line, flow_line))

    assert (
        reconcile_workspace(workspace_dir, None).error,
        reconcile_workspace(workspace_dir, {"preset": "rtl2gds"}).error,
    ) == ("flow_mismatch", "flow_mismatch")


def test_a_malformed_lec_engine_stays_an_invalid_workspace_config(tmp_path):
    names = [name for name, _tool in RTL2GDS_STEPS]
    section = {"start": "Synthesis", "end": "preFloorplan", "lec_engine": "kepler_formal"}
    workspace_dir = _write_workspace(
        tmp_path, RTL2GDS_STEPS[: names.index("preFloorplan") + 1], flow_section=section
    )
    params = workspace_dir / "home" / "params.toml"
    params.write_text(params.read_text().replace('lec_engine = "kepler_formal"', "lec_engine = []"))

    result = reconcile_workspace(workspace_dir, None)

    assert (result.outcome, result.error.split(":")[0]) == ("mismatch", "workspace_config_invalid")


@pytest.mark.parametrize("anchor", ["Synthesis", "CTS", "diff_opt"])
def test_a_ledger_without_a_flow_target_keeps_its_inserted_steps(tmp_path, anchor):
    # No [flow] in home/params.toml: the target is derived from the ledger,
    # whose inserted step is no range boundary but an insertion. The default
    # policy skips diff_opt: its ledger entry and its check are both inert.
    names = [name for name, _tool in RTL2GDS_STEPS]
    ledger = _with_lec_after(anchor, RTL2GDS_STEPS[: names.index(anchor) + 2])
    workspace_dir = _write_workspace(tmp_path, ledger, flow_section=None)

    result = reconcile_workspace(workspace_dir, None)

    assert (result.outcome, result.error) == ("no_op", None)


def _with_lec_after(anchor, steps):
    position = [name for name, _tool in steps].index(anchor) + 1
    return [*steps[:position], (f"lec@{anchor}", "kepler_formal"), *steps[position:]]


class TestInsertedStepReconcile:
    def test_target_entries_put_the_inserted_lec_after_its_step(self):
        from chipcompiler.engine.reconcile import _target_entries

        entries = _target_entries(
            {"start": "place", "end": "route", "skip_steps": [], "insert_steps": ["lec@CTS"]}
        )

        assert [name for name, _tool in entries] == [
            "place",
            "diff_opt",
            "diff_sizing",
            "CTS",
            "lec@CTS",
            "legalization",
            "Timing optimization",
            "route",
        ]

    def test_a_ledger_with_the_same_insertion_matches(self, tmp_path):
        target = {"preset": "rtl2gds", "insert_steps": ["lec@CTS"]}
        ledger = _with_lec_after("CTS", RTL2GDS_STEPS)
        workspace_dir = _write_workspace(tmp_path, ledger, flow_section=target)

        assert reconcile_workspace(workspace_dir, target).outcome == "no_op"

    def test_adding_or_removing_an_insertion_is_a_mismatch(self, tmp_path):
        inserted = _with_lec_after("CTS", RTL2GDS_STEPS)
        with_insertion = {"preset": "rtl2gds", "insert_steps": ["lec@CTS"]}
        added = _write_workspace(
            tmp_path / "added", RTL2GDS_STEPS, flow_section={"preset": "rtl2gds"}
        )
        removed = _write_workspace(tmp_path / "removed", inserted, flow_section=with_insertion)

        assert (
            reconcile_workspace(added, with_insertion).error,
            reconcile_workspace(removed, {"preset": "rtl2gds"}).error,
        ) == ("flow_mismatch", "flow_mismatch")

    def test_skipping_an_anchor_leaves_its_check_inert(self, tmp_path):
        names = [name for name, _tool in RTL2GDS_STEPS]
        ledger = _with_lec_after("diff_opt", RTL2GDS_STEPS[: names.index("diff_sizing") + 1])
        section = {
            "start": "Synthesis",
            "end": "diff_sizing",
            "skip_steps": [],
            "insert_steps": ["lec@diff_opt"],
        }
        workspace_dir = _write_workspace(tmp_path, ledger, flow_section=section)

        result = reconcile_workspace(workspace_dir, {**section, "skip_steps": ["diff_opt"]})

        assert (result.outcome, result.error) == ("no_op", None)

    def test_an_insertion_after_the_ledgers_last_step_is_a_mismatch(self, tmp_path):
        names = [name for name, _tool in RTL2GDS_STEPS]
        ledger = RTL2GDS_STEPS[: names.index("CTS") + 1]
        section = {"start": "Synthesis", "end": "CTS", "skip_steps": []}
        with_insertion = {**section, "insert_steps": ["lec@CTS"]}
        added = _write_workspace(tmp_path / "added", ledger, flow_section=section)
        inserted = _with_lec_after("CTS", ledger)
        removed = _write_workspace(
            tmp_path / "removed",
            inserted,
            states=["Success"] * len(ledger) + ["Unstart"],
            flow_section=with_insertion,
        )

        assert (
            reconcile_workspace(added, with_insertion).error,
            reconcile_workspace(removed, section).error,
        ) == ("flow_mismatch", "flow_mismatch")

    def test_extending_the_range_brings_the_new_steps_insertions(self, tmp_path):
        names = [name for name, _tool in RTL2GDS_STEPS]
        ledger = RTL2GDS_STEPS[: names.index("CTS") + 1]
        section = {"start": "Synthesis", "end": "CTS", "skip_steps": []}
        workspace_dir = _write_workspace(tmp_path, ledger, flow_section=section)

        result = reconcile_workspace(
            workspace_dir, {**section, "end": "legalization", "insert_steps": ["lec@legalization"]}
        )

        assert (result.outcome, result.appended) == (
            "extended",
            ("legalization", "lec@legalization"),
        )
