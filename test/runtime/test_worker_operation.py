"""Tests for chipcompiler.runtime.worker_operation — typed operation orchestrator."""

import json
import os
import sys
import textwrap

import pytest

from chipcompiler.runtime.worker import WorkerClient
from chipcompiler.runtime.worker_operation import RunOperation

# Common RPC helpers injected into subprocess scripts.
_RPC_HELPERS = textwrap.dedent("""\
    import sys, os, json

    def read_request():
        data = b""
        while True:
            chunk = sys.stdin.buffer.read(1)
            if not chunk:
                return None
            data += chunk
            if b"\\r\\n\\r\\n" in data:
                header, _, body_start = data.partition(b"\\r\\n\\r\\n")
                length = int(header.split(b":")[1])
                while len(body_start) < length:
                    body_start += sys.stdin.buffer.read(1)
                return json.loads(body_start[:length])

    def send_response(resp):
        payload = json.dumps(resp)
        frame = f"Content-Length: {len(payload)}\\r\\n\\r\\n{payload}"
        sys.stdout.buffer.write(frame.encode())
        sys.stdout.buffer.flush()

    def make_marker(event, step, tool):
        p = json.dumps({"v": 1, "event": event, "step": step, "tool": tool})
        return chr(0x1e).encode() + b"ECC-STEP " + p.encode() + b"\\n"
""")

LIFECYCLE_SERVER = _RPC_HELPERS + textwrap.dedent("""\
    while True:
        req = read_request()
        if req is None:
            break
        method = req.get("method", "")
        req_id = req.get("id")

        if method == "rpc.hello":
            resp = {"jsonrpc": "2.0", "result": {"version": 1, "capabilities": []}, "id": req_id}
            send_response(resp)
        elif method == "workspace.open":
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "test"}, "id": req_id})
        elif method == "rpc.shutdown":
            send_response({"jsonrpc": "2.0", "result": {"ok": True}, "id": req_id})
            break
        elif method == "flow.run":
            send_response({"jsonrpc": "2.0", "result": {"steps": ["syn"]}, "id": req_id})
        else:
            err = {"code": -32601, "message": "unknown method"}
            resp = {"jsonrpc": "2.0", "error": err, "id": req_id}
            send_response(resp)
""")


class TestRunOperationLifecycle:
    def test_successful_lifecycle(self, tmp_path):
        script = tmp_path / "server.py"
        script.write_text(LIFECYCLE_SERVER)
        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is True
        assert result.rpc_result["result"] == {"steps": ["syn"]}
        assert result.exit_code == 0
        assert result.archive_error is None

    def test_rpc_error_returns_failure(self, tmp_path):
        script = tmp_path / "server.py"
        script.write_text(LIFECYCLE_SERVER)
        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
        )
        result = op.run("unknown.method", {"workspace_id": "test"})
        assert result.success is False
        assert "unknown method" in result.error


class TestRunOperationSequence:
    @staticmethod
    def _write_server(tmp_path):
        script = tmp_path / "sequence_server.py"
        script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            received = []
            fail_first = os.environ.get("SEQ_FAIL_FIRST") == "1"
            while True:
                req = read_request()
                if req is None:
                    break
                method = req.get("method", "")
                req_id = req.get("id")
                received.append(method)
                if method == "rpc.hello":
                    send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req_id})
                elif method == "workspace.open":
                    result = {"workspaceId": "test"}
                    send_response({"jsonrpc": "2.0", "result": result, "id": req_id})
                elif method == "flow.run_step":
                    if fail_first:
                        err = {"code": -32000, "message": "step failed"}
                        send_response({"jsonrpc": "2.0", "error": err, "id": req_id})
                    else:
                        result = {"step": "ok"}
                        send_response({"jsonrpc": "2.0", "result": result, "id": req_id})
                elif method == "flow.run":
                    send_response({"jsonrpc": "2.0", "result": {"ran": True}, "id": req_id})
                elif method == "rpc.shutdown":
                    with open(os.environ["SEQ_LOG"], "w") as fh:
                        fh.write("\\n".join(received))
                    send_response({"jsonrpc": "2.0", "result": {"ok": True}, "id": req_id})
                    break
                else:
                    err = {"code": -32601, "message": "unknown method"}
                    send_response({"jsonrpc": "2.0", "error": err, "id": req_id})
        """)
        )
        return script

    def _make_operation(self, tmp_path, monkeypatch, script, *, fail_first):
        log_file = tmp_path / "received.txt"
        monkeypatch.setenv("SEQ_LOG", str(log_file))
        if fail_first:
            monkeypatch.setenv("SEQ_FAIL_FIRST", "1")
        else:
            monkeypatch.delenv("SEQ_FAIL_FIRST", raising=False)
        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
        )
        return op, log_file

    CALLS = [
        ("flow.run_step", {"step": "Synthesis", "rerun": True, "reset_dependents": True}),
        ("flow.run", {"rerun": False}),
    ]

    def test_successful_sequence_returns_last_call_result(self, tmp_path, monkeypatch):
        script = self._write_server(tmp_path)
        op, log_file = self._make_operation(tmp_path, monkeypatch, script, fail_first=False)
        result = op.run_sequence(self.CALLS)
        assert result.success is True
        assert result.rpc_result["result"] == {"ran": True}
        received = log_file.read_text().splitlines()
        assert received == [
            "rpc.hello",
            "workspace.open",
            "flow.run_step",
            "flow.run",
            "rpc.shutdown",
        ]

    def test_first_failure_skips_follow_up_and_still_shuts_down(self, tmp_path, monkeypatch):
        script = self._write_server(tmp_path)
        op, log_file = self._make_operation(tmp_path, monkeypatch, script, fail_first=True)
        result = op.run_sequence(self.CALLS)
        assert result.success is False
        assert "step failed" in result.error
        received = log_file.read_text().splitlines()
        assert "flow.run" not in received
        assert received[-1] == "rpc.shutdown"


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


class TestWorkspaceIdInjection:
    def test_workspace_id_injected_into_flow_params(self, tmp_path):
        """workspace_id from workspace.open is injected into the flow request params."""
        script = tmp_path / "echo_server.py"
        script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            ws_resp = {"workspaceId": "injected-ws"}
            send_response({"jsonrpc": "2.0", "result": ws_resp, "id": req["id"]})
            req = read_request()  # flow.run — echo params back
            send_response({"jsonrpc": "2.0", "result": req.get("params", {}), "id": req["id"]})
            req = read_request()  # rpc.shutdown
            send_response({"jsonrpc": "2.0", "result": {"ok": True}, "id": req["id"]})
        """)
        )
        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
        )
        result = op.run("flow.run", {"rerun": True})
        assert result.success is True
        assert result.rpc_result["result"]["workspace_id"] == "injected-ws"
        assert result.rpc_result["result"]["rerun"] is True

    def test_workspace_open_sends_directory_field(self, tmp_path):
        """workspace.open sends 'directory' not 'path'."""
        script = tmp_path / "check_open_server.py"
        script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            params = req.get("params", {})
            assert "directory" in params, f"expected 'directory' in params, got {params}"
            assert "path" not in params, f"unexpected 'path' in params: {params}"
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "ok"}, "id": req["id"]})
            req = read_request()  # flow.run
            send_response({"jsonrpc": "2.0", "result": {}, "id": req["id"]})
            req = read_request()  # rpc.shutdown
            send_response({"jsonrpc": "2.0", "result": {"ok": True}, "id": req["id"]})
        """)
        )
        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
        )
        result = op.run("flow.run", {})
        assert result.success is True


class TestShutdownValidation:
    """Strict ok is True validation in _graceful_shutdown."""

    @pytest.mark.parametrize(
        "ok_value",
        [1, "yes", "true", [], {}],
        ids=["int", "string", "string-true", "list", "dict"],
    )
    def test_truthy_non_boolean_ok_fails_shutdown(self, tmp_path, ok_value):
        """Non-True truthy values must not be accepted as successful shutdown."""
        script = tmp_path / "bad_shutdown.py"
        script.write_text(
            _RPC_HELPERS
            + textwrap.dedent(f"""\
            req = read_request()  # hello
            send_response({{"jsonrpc": "2.0", "result": {{"version": 1}}, "id": req["id"]}})
            req = read_request()  # workspace.open
            send_response({{"jsonrpc": "2.0", "result": {{"workspaceId": "w"}}, "id": req["id"]}})
            req = read_request()  # flow.run
            send_response({{"jsonrpc": "2.0", "result": {{}}, "id": req["id"]}})
            req = read_request()  # rpc.shutdown
            ok_val = {repr(ok_value)}
            resp = {{"jsonrpc": "2.0", "result": {{"ok": ok_val}}, "id": req["id"]}}
            send_response(resp)
        """)
        )
        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
        )
        result = op.run("flow.run", {})
        assert result.success is False
        assert "worker did not exit cleanly" in result.error

    def test_false_ok_fails_shutdown(self, tmp_path):
        """ok: false must not be accepted."""
        script = tmp_path / "false_shutdown.py"
        script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "w"}, "id": req["id"]})
            req = read_request()  # flow.run
            send_response({"jsonrpc": "2.0", "result": {}, "id": req["id"]})
            req = read_request()  # rpc.shutdown
            send_response({"jsonrpc": "2.0", "result": {"ok": False}, "id": req["id"]})
        """)
        )
        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
        )
        result = op.run("flow.run", {})
        assert result.success is False
        assert "worker did not exit cleanly" in result.error

    def test_missing_ok_fails_shutdown(self, tmp_path):
        """Missing ok field must not be accepted."""
        script = tmp_path / "no_ok_shutdown.py"
        script.write_text(
            _RPC_HELPERS
            + textwrap.dedent("""\
            req = read_request()  # hello
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req["id"]})
            req = read_request()  # workspace.open
            send_response({"jsonrpc": "2.0", "result": {"workspaceId": "w"}, "id": req["id"]})
            req = read_request()  # flow.run
            send_response({"jsonrpc": "2.0", "result": {}, "id": req["id"]})
            req = read_request()  # rpc.shutdown
            send_response({"jsonrpc": "2.0", "result": {}, "id": req["id"]})
        """)
        )
        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script)],
        )
        result = op.run("flow.run", {})
        assert result.success is False
        assert "worker did not exit cleanly" in result.error


class TestParseMarkerNonObject:
    def test_non_object_json_treated_as_raw(self):
        """Non-dict JSON markers don't crash the reader."""
        from chipcompiler.runtime.log_stream import parse_marker

        assert parse_marker(b"\x1eECC-STEP []\n") is None
        assert parse_marker(b"\x1eECC-STEP 42\n") is None
        assert parse_marker(b'\x1eECC-STEP "hello"\n') is None
        assert parse_marker(b"\x1eECC-STEP true\n") is None
        assert parse_marker(b"\x1eECC-STEP null\n") is None


_ECC_BIN = os.path.join(os.path.dirname(sys.executable), "ecc")


@pytest.mark.skipif(not os.path.isfile(_ECC_BIN), reason="ecc binary not installed")
class TestRealServerLifecycle:
    """Prove the RPC protocol works against the real ecc rpc serve --stdio --persistent-db."""

    def test_hello_and_shutdown(self):
        """rpc.hello + rpc.shutdown succeed against the real server."""
        client = WorkerClient([_ECC_BIN, "rpc", "serve", "--stdio", "--persistent-db"])
        proc = client.start()
        try:
            hello = client.request("rpc.hello", {"version": 1}, request_id=0)
            assert hello.success is True
            assert hello.response["result"]["version"] == 1

            shutdown = client.request("rpc.shutdown", {}, request_id=0)
            assert shutdown.success is True
            assert shutdown.response["result"]["ok"] is True

            proc.wait(timeout=5.0)
            assert proc.returncode == 0
        finally:
            if proc.poll() is None:
                client.terminate()

    def test_run_operation_with_real_workspace(self, tmp_path, minimal_ics55_pdk_factory):
        """RunOperation lifecycle succeeds against the real server with a valid workspace."""
        from chipcompiler.data import create_workspace

        pdk_root = minimal_ics55_pdk_factory(tmp_path / "ics55")
        rtl_path = tmp_path / "gcd.v"
        rtl_path.write_text("module gcd(input clk, output y); assign y = clk; endmodule\n")
        workspace_dir = tmp_path / "workspace"
        create_workspace(
            directory=workspace_dir,
            origin_def="",
            origin_verilog=rtl_path,
            pdk="ics55",
            pdk_root=pdk_root,
            parameters={
                "PDK": "ics55",
                "Design": "gcd",
                "Top module": "gcd",
                "Clock": "clk",
                "Frequency max [MHz]": 100,
            },
        )
        flow_json = workspace_dir / "home" / "flow.json"
        op = RunOperation(
            workspace_dir=workspace_dir,
            flow_json_path=flow_json,
            worker_argv=[_ECC_BIN, "rpc", "serve", "--stdio", "--persistent-db"],
        )
        result = op.run("workspace.home", {})
        assert result.success is True
        assert result.exit_code == 0
        assert "path" in result.rpc_result["result"]
