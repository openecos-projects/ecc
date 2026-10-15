from chipcompiler.tools.klayout_tool.viewer import view_gds


def test_view_gds_launches_klayout_gui(monkeypatch, tmp_path):
    calls = []
    gds = tmp_path / "design.gds"
    gds.write_bytes(b"GDS")
    monkeypatch.setenv("KLAYOUT_BIN", "/bin/true")
    monkeypatch.setattr(
        "chipcompiler.tools.klayout_tool.viewer.subprocess.run",
        lambda args, check: calls.append((args, check))
        or type("Result", (), {"returncode": 0})(),
    )

    view_gds(gds)

    assert calls == [(["/bin/true", str(gds)], False)]
