"""Tests for RunOperation archive handling and reconciliation."""

import json
import sys
import textwrap

from worker_operation_support import _RPC_HELPERS

from chipcompiler.runtime.worker_operation import RunOperation


class TestRunOperationArchive:
    def test_archive_error_forces_failure(self, tmp_path):
        """Success is False when archive path cannot be opened."""
        script = tmp_path / "server_with_markers.py"
        script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "ws1"}, "id": req["id"]})
            os.write(2, make_marker("begin", "Synthesis", "yosys"))
            os.write(2, b'Synthesizing...\\n')
            os.write(2, make_marker("end", "Synthesis", "yosys"))
            req = read_request()  # flow.run
            send_response({"jsonrpc": "2.0", "result": {"steps": ["syn"]}, "id": req["id"]})
            req = read_request()  # rpc.shutdown
            send_response({"jsonrpc": "2.0", "result": {"ok": True}, "id": req["id"]})
        """)
        )

        # A regular file as path component makes mkdir fail with ENOTDIR even
        # when tests run as root (chmod-based read-only setups are bypassed).
        blocker = tmp_path / "not_a_dir"
        blocker.write_text("regular file")

        def bad_resolver(step: str, tool: str):
            return blocker / "sub" / f"{step}.log"

        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
            log_path_resolver=bad_resolver,
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is False
        assert result.archive_error is not None
        assert "archive error" in result.error

    def test_display_callback_failure_is_not_an_archive_failure(self, tmp_path):
        """A broken on_output renderer must not downgrade the step or fail
        the operation when the archive itself is fine."""
        script = tmp_path / "server_with_markers.py"
        script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "ws1"}, "id": req["id"]})
            os.write(2, make_marker("begin", "Synthesis", "yosys"))
            os.write(2, b'Synthesizing...\\n')
            os.write(2, make_marker("end", "Synthesis", "yosys"))
            req = read_request()  # flow.run
            send_response({"jsonrpc": "2.0", "result": {"steps": ["syn"]}, "id": req["id"]})
            req = read_request()  # rpc.shutdown
            send_response({"jsonrpc": "2.0", "result": {"ok": True}, "id": req["id"]})
        """)
        )
        logs_dir = tmp_path / "logs"

        def resolver(step: str, tool: str):
            return logs_dir / f"{step}.log"

        def broken_display(data: bytes):
            raise RuntimeError("renderer blew up")

        flow_json = tmp_path / "flow.json"
        flow_json.write_text(
            json.dumps({"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Success"}]})
        )
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
            log_path_resolver=resolver,
            on_output=broken_display,
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is True
        assert result.repaired_steps == []
        assert result.log_state is not None
        assert result.log_state.display_error is not None
        assert result.log_state.error is None
        assert json.loads(flow_json.read_text())["steps"][0]["state"] == "Success"

    def test_archive_error_reconciles_the_success_record(self, tmp_path):
        """An archive failure must not leave flow.json claiming Success."""
        script = tmp_path / "server_with_markers.py"
        script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "ws1"}, "id": req["id"]})
            os.write(2, make_marker("begin", "Synthesis", "yosys"))
            os.write(2, b'Synthesizing...\\n')
            os.write(2, make_marker("end", "Synthesis", "yosys"))
            req = read_request()  # flow.run
            send_response({"jsonrpc": "2.0", "result": {"steps": ["syn"]}, "id": req["id"]})
            req = read_request()  # rpc.shutdown
            send_response({"jsonrpc": "2.0", "result": {"ok": True}, "id": req["id"]})
        """)
        )

        blocker = tmp_path / "not_a_dir"
        blocker.write_text("regular file")

        def bad_resolver(step: str, tool: str):
            return blocker / "sub" / f"{step}.log"

        flow_json = tmp_path / "flow.json"
        flow_json.write_text(
            json.dumps({"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Success"}]})
        )
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
            log_path_resolver=bad_resolver,
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is False
        assert result.archive_error is not None
        # The persisted record is downgraded so a later resume reruns the step
        # and recreates the missing log instead of skipping it.
        assert result.repaired_steps == ["Synthesis"]
        repaired = json.loads(flow_json.read_text())
        assert repaired["steps"][0]["state"] == "Incomplete"

    def test_stderr_archived_to_step_log(self, tmp_path):
        script = tmp_path / "server_with_markers.py"
        script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "ws1"}, "id": req["id"]})
            os.write(2, make_marker("begin", "Synthesis", "yosys"))
            os.write(2, b'Synthesizing module top...\\n')
            os.write(2, make_marker("end", "Synthesis", "yosys"))
            req = read_request()  # flow.run
            send_response({"jsonrpc": "2.0", "result": {}, "id": req["id"]})
            req = read_request()  # rpc.shutdown
            send_response({"jsonrpc": "2.0", "result": {"ok": True}, "id": req["id"]})
        """)
        )
        logs_dir = tmp_path / "logs"

        def resolver(step: str, tool: str):
            return logs_dir / f"{step}.log"

        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
            log_path_resolver=resolver,
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is True
        log_file = logs_dir / "Synthesis.log"
        assert log_file.exists()
        assert b"Synthesizing module top..." in log_file.read_bytes()
