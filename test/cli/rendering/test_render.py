class TestRendererCmdStripping:
    def test_text_strips_cmd_suffix(self):
        from io import StringIO

        from chipcompiler.cli.rendering.render import render_text

        buf = StringIO()
        render_text(({"inspect_cmd": "ecc status", "log_cmd": "ecc log"},), file=buf)
        line = buf.getvalue().strip()
        assert "inspect=" in line
        assert "log=" in line
        assert "inspect_cmd=" not in line
        assert "log_cmd=" not in line
