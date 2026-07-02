import os


class TestPackaging:
    def test_ecc_console_script_in_pyproject(self):
        import tomllib

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        pyproject = os.path.join(project_root, "pyproject.toml")
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["scripts"]["ecc"] == "chipcompiler.cli.main:main"
        assert set(data["project"]["scripts"]) == {"ecc"}

    def test_pyinstaller_spec_collects_jsonrpcserver_data_files(self):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        spec_path = os.path.join(project_root, "ecc.spec")

        with open(spec_path, encoding="utf-8") as f:
            source = f.read()

        assert 'collect_data_files("jsonrpcserver")' in source
