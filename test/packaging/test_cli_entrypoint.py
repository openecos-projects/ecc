import os


class TestPackaging:
    def test_ecc_console_script_in_pyproject(self):
        import tomllib

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        pyproject = os.path.join(project_root, "pyproject.toml")
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        assert data["project"]["scripts"]["ecc"] == "chipcompiler.cli.main:main"
