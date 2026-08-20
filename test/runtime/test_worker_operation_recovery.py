"""Tests for RunOperation crash and RPC-error recovery."""

import json
import os
import sys
import textwrap

from worker_operation_support import _RPC_HELPERS

from chipcompiler.runtime.worker_operation import RunOperation


class TestRunOperationRpcErrorRepair:
    def test_rpc_error_with_unmatched_step_repairs_flow_state(self, tmp_path):
        """A live worker's RPC error still repairs a step left Ongoing."""
        script = tmp_path / "error_after_begin.py"
        script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            while True:
                req = read_request()
                if req is None:
                    break
                method = req.get("method", "")
                req_id = req.get("id")
                if method == "rpc.hello":
                    send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req_id})
                elif method == "workspace.open":
                    result = {"workspaceId": "x"}
                    send_response({"jsonrpc": "2.0", "result": result, "id": req_id})
                elif method == "flow.run_step":
                    os.write(2, make_marker("begin", "Synthesis", "yosys"))
                    os.write(2, b"partial output\\n")
                    err = {"code": -32000, "message": "run step Synthesis failed"}
                    send_response({"jsonrpc": "2.0", "error": err, "id": req_id})
                elif method == "rpc.shutdown":
                    send_response({"jsonrpc": "2.0", "result": {"ok": True}, "id": req_id})
                    break
                else:
                    err = {"code": -32601, "message": "unknown method"}
                    send_response({"jsonrpc": "2.0", "error": err, "id": req_id})
        """)
        )
        flow_json = tmp_path / "flow.json"
        data = {"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Ongoing"}]}
        flow_json.write_text(json.dumps(data))
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
        )
        result = op.run_sequence([("flow.run_step", {"step": "Synthesis", "rerun": True})])
        assert result.success is False
        assert "run step Synthesis failed" in result.error
        assert result.repaired_steps == ["Synthesis"]
        repaired_data = json.loads(flow_json.read_text())
        assert repaired_data["steps"][0]["state"] == "Incomplete"


class TestRunOperationCrash:
    def test_worker_crash_triggers_repair(self, tmp_path):
        crash_script = tmp_path / "crash_after_open.py"
        crash_script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "x"}, "id": req["id"]})
            # Emit begin marker on stderr, then crash
            os.write(2, make_marker("begin", "Synthesis", "yosys"))
            os._exit(1)
        """)
        )
        flow_json = tmp_path / "flow.json"
        data = {"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Ongoing"}]}
        flow_json.write_text(json.dumps(data))
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(crash_script)],
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is False
        assert result.repaired_steps == ["Synthesis"]
        repaired_data = json.loads(flow_json.read_text())
        assert repaired_data["steps"][0]["state"] == "Incomplete"

    def test_crash_repair_failure_is_reported(self, tmp_path, monkeypatch):
        """A repair that cannot persist must surface in the result error."""
        crash_script = tmp_path / "crash_after_open.py"
        crash_script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "x"}, "id": req["id"]})
            os.write(2, make_marker("begin", "Synthesis", "yosys"))
            os._exit(1)
        """)
        )
        flow_json = tmp_path / "flow.json"
        data = {"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Ongoing"}]}
        flow_json.write_text(json.dumps(data))

        def failing_repair(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(
            "chipcompiler.runtime.worker_operation.repair_flow_state", failing_repair
        )
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(crash_script)],
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is False
        assert result.repaired_steps == []
        assert "state repair failed" in result.error
        # The record is left as it was — the failure is reported, not hidden.
        assert json.loads(flow_json.read_text())["steps"][0]["state"] == "Ongoing"

    def test_parent_sigterm_terminates_the_worker_group(self, tmp_path):
        """SIGTERM to the CLI must route through crash recovery and reap the
        worker process group instead of leaving EDA descendants running."""
        import signal as signal_module
        import threading
        import time

        script = _RPC_HELPERS + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "x"}, "id": req["id"]})
            # Hang forever, simulating a long EDA step.
            while True:
                time.sleep(1)
        """)
        script = "import time\n" + script
        flow_json = tmp_path / "flow.json"
        flow_json.write_text(json.dumps({"steps": []}))
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, "-c", script],
        )

        def send_sigterm():
            time.sleep(0.5)
            os.kill(os.getpid(), signal_module.SIGTERM)

        killer = threading.Thread(target=send_sigterm, daemon=True)
        killer.start()
        result = op.run("flow.run", {"workspace_id": "test"})

        assert result.success is False
        assert "interrupted" in (result.error or "")
        assert result.signal_number == -signal_module.SIGKILL or result.exit_code is not None

    def test_crash_before_any_marker_repairs_persisted_ongoing(self, tmp_path):
        """Killed between the Ongoing save and the begin marker: no stream
        evidence exists, so recovery falls back to the persisted Ongoing."""
        crash_script = tmp_path / "crash_before_marker.py"
        crash_script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "x"}, "id": req["id"]})
            # Die before any marker — as if killed between the Ongoing save
            # and the begin write.
            os._exit(1)
        """)
        )
        flow_json = tmp_path / "flow.json"
        flow_json.write_text(
            json.dumps({"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Ongoing"}]})
        )
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(crash_script)],
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is False
        assert result.repaired_steps == ["Synthesis"]
        repaired = json.loads(flow_json.read_text())
        assert repaired["steps"][0]["state"] == "Incomplete"

    def test_worker_crash_no_flow_json_no_repair(self, tmp_path):
        script = _RPC_HELPERS + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "x"}, "id": req["id"]})
            sys.exit(1)
        """)
        flow_json = tmp_path / "flow.json"
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, "-c", script],
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is False
        assert result.repaired_steps == []

    def test_protocol_failure_routes_to_recovery(self, tmp_path):
        """A worker that returns invalid JSON triggers crash recovery."""
        script = _RPC_HELPERS + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "x"}, "id": req["id"]})
            # Emit begin marker, then send garbage on stdout
            os.write(2, make_marker("begin", "Place", "ecc"))
            req = read_request()  # flow.run
            # Send invalid frame (bad Content-Length header)
            sys.stdout.buffer.write(b"Content-Length: 5\\r\\n\\r\\n{}")
            sys.stdout.buffer.flush()
            sys.stdout.buffer.close()
            os._exit(1)
        """)
        flow_json = tmp_path / "flow.json"
        data = {"steps": [{"name": "Place", "tool": "ecc", "state": "Ongoing"}]}
        flow_json.write_text(json.dumps(data))
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, "-c", script],
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is False
        assert result.repaired_steps == ["Place"]
