import chipcompiler.cli.inspection.tool_versions as tool_versions


def test_yosys_version_parses_yosys_v_output(monkeypatch):
    monkeypatch.setattr("chipcompiler.tools.yosys.utility.get_yosys_command", lambda: ["yosys"])
    monkeypatch.setattr("chipcompiler.tools.yosys.utility.get_yosys_runtime", lambda: (["yosys"], {}))
    query_calls = []

    def fake_query(command, env=None):
        query_calls.append(command)
        return "Yosys 0.68+132 (git sha1 13b43f8c8-dirty)"

    monkeypatch.setattr(tool_versions, "_query", fake_query)

    assert tool_versions.yosys_version() == "0.68+132"
    assert query_calls == [["yosys", "-V"]]


def test_yosys_version_reports_missing_and_failed_query(monkeypatch):
    monkeypatch.setattr("chipcompiler.tools.yosys.utility.get_yosys_command", lambda: [])
    assert tool_versions.yosys_version() == "not installed"

    monkeypatch.setattr("chipcompiler.tools.yosys.utility.get_yosys_command", lambda: ["yosys"])
    monkeypatch.setattr("chipcompiler.tools.yosys.utility.get_yosys_runtime", lambda: (["yosys"], {}))
    monkeypatch.setattr(tool_versions, "_query", lambda command, env=None: "")
    assert tool_versions.yosys_version() == "unknown"


def test_sizer_version_reports_missing_and_failed_query(monkeypatch):
    monkeypatch.setattr("chipcompiler.tools.ecc_sizer.utility.get_sizer_command", lambda: [])
    assert tool_versions.sizer_version() == "not installed"

    monkeypatch.setattr(
        "chipcompiler.tools.ecc_sizer.utility.get_sizer_command", lambda: ["/opt/bin/Sizer"]
    )
    monkeypatch.setattr(tool_versions, "_query", lambda command, env=None: "")
    assert tool_versions.sizer_version() == "unknown"


def test_sizer_version_uses_query_output(monkeypatch):
    monkeypatch.setattr(
        "chipcompiler.tools.ecc_sizer.utility.get_sizer_command", lambda: ["/opt/bin/Sizer"]
    )
    monkeypatch.setattr(tool_versions, "_query", lambda command, env=None: "ecc-sizer 1.2.3")
    assert tool_versions.sizer_version() == "ecc-sizer 1.2.3"


def test_klayout_version_uses_distribution_when_importable(monkeypatch):
    monkeypatch.setattr("chipcompiler.tools.klayout_tool.utility.is_eda_exist", lambda: True)
    monkeypatch.setattr(
        "chipcompiler.cli.core.version_info.distribution_version", lambda dist: "0.30.2"
    )
    assert tool_versions.klayout_version() == "0.30.2"

    monkeypatch.setattr("chipcompiler.tools.klayout_tool.utility.is_eda_exist", lambda: False)
    assert tool_versions.klayout_version() == "not installed"
