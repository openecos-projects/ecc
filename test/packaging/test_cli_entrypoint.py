import os


class TestPackaging:
    def test_ecc_console_script_in_pyproject(self):
        import tomllib

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        pyproject = os.path.join(project_root, "pyproject.toml")
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["scripts"]["ecc"] == "chipcompiler.cli.main:main"

    def test_pyinstaller_spec_collects_jsonrpcserver_data_files(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        spec_path = os.path.join(project_root, "ecc.spec")

        with open(spec_path, encoding="utf-8") as f:
            source = f.read()

        assert 'collect_data_files("jsonrpcserver")' in source

    def test_pyinstaller_spec_filters_payloads_before_analysis(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        spec_path = os.path.join(project_root, "ecc.spec")

        with open(spec_path, encoding="utf-8") as f:
            source = f.read()

        analysis_index = source.index("a = Analysis(")
        datas_filter_index = source.index("datas = filter_collected_payloads(datas)")
        binaries_filter_index = source.index("binaries = filter_collected_payloads(binaries)")

        assert datas_filter_index < analysis_index
        assert binaries_filter_index < analysis_index

    def test_pyinstaller_spec_reuses_ecc_executable_for_agent_rpc(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        spec_path = os.path.join(project_root, "ecc.spec")

        with open(spec_path, encoding="utf-8") as f:
            source = f.read()

        assert source.count(" = Analysis(") == 1
        assert "os.link(ecc_exe_path, agent_exe_path)" in source
