import json
from types import SimpleNamespace

from chipcompiler.tools.replay_analysis import collect_analysis
from chipcompiler.tools.replay_reports import rcx


def test_rcx_keeps_reported_net_membership_and_capacitance_units(tmp_path):
    path = tmp_path / "slow.spef"
    path.write_text(
        "*C_UNIT 1 PF\n*NAME_MAP\n*1 core.net\n*2 clk\n"
        "*D_NET *1 0.006\n*CONN\n*N *1:1 *C 3 4\n"
        "*CAP\n1 *1:1 0.006\n*RES\n1 *1:1 *1:2 30\n*END\n"
        "*D_NET *2 0.001\n*END\n"
    )
    view = rcx(path)[0]
    assert view["items"] == [{"label": "core.net", "value": 6.0}, {"label": "clk", "value": 1.0}]
    assert view["unit"] == "fF"


def test_rcx_corners_share_net_names_and_do_not_store_electrical_graphs(tmp_path):
    step = SimpleNamespace(name="RCX", directory=tmp_path / "RCX_ecc")
    output = step.directory / "output"
    output.mkdir(parents=True)
    for corner, nets in [("a", [("clk", 1), ("data", 2)]), ("b", [("clk", 3)])]:
        (output / f"{corner}.spef").write_text(
            "*C_UNIT 1 FF\n" + "".join(f"*D_NET {net} {value}\n*END\n" for net, value in nets)
        )
    attempt = tmp_path / "attempt"
    result = collect_analysis(step, attempt, 0)
    payload = json.loads((attempt / result["analysis"]).read_text())
    assert payload["nets"] == ["clk", "data"]
    assert [v["items"] for v in payload["views"]] == [
        [{"net_ref": 0, "value": 1.0}, {"net_ref": 1, "value": 2.0}],
        [{"net_ref": 0, "value": 3.0}],
    ]
    assert result["analysis_view_count"] == 2
    assert [p.name for p in attempt.rglob("*") if p.is_file()] == ["index.json"]
