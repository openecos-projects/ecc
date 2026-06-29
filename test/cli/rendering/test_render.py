import json


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

    def test_json_preserves_cmd_keys(self):
        from io import StringIO

        from chipcompiler.cli.core.types import CommandResult
        from chipcompiler.cli.rendering.render import render_json

        buf = StringIO()
        result = CommandResult(records=({"inspect_cmd": "ecc status", "log_cmd": "ecc log"},))
        render_json(result, file=buf)
        data = json.loads(buf.getvalue())
        assert "inspect_cmd" in data["records"][0]
        assert "log_cmd" in data["records"][0]

    def test_jsonl_preserves_cmd_keys(self):
        from io import StringIO

        from chipcompiler.cli.core.types import CommandResult
        from chipcompiler.cli.rendering.render import render_jsonl

        buf = StringIO()
        result = CommandResult(records=({"inspect_cmd": "ecc status", "log_cmd": "ecc log"},))
        render_jsonl(result, file=buf)
        record = json.loads(buf.getvalue().strip())
        assert "inspect_cmd" in record
        assert "log_cmd" in record
