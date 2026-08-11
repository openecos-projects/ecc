"""Tests for chipcompiler.runtime.worker — lifecycle, signal handling, and state repair."""

import json
import signal
import sys
import textwrap
from unittest.mock import MagicMock

from chipcompiler.runtime.worker import (
    WorkerClient,
    WorkerResult,
    classify_worker_exit,
    repair_flow_state,
)


class TestWorkerResult:
    def test_success_result(self):
        r = WorkerResult(success=True, response={"result": {"ok": True}})
        assert r.success is True
        assert r.response == {"result": {"ok": True}}

    def test_failure_result(self):
        r = WorkerResult(success=False, error="timeout", exit_code=1)
        assert r.success is False
        assert r.error == "timeout"
        assert r.exit_code == 1


class TestClassifyWorkerExit:
    def test_normal_exit(self):
        proc = MagicMock()
        proc.returncode = 0
        result = classify_worker_exit(proc)
        assert result.success is True
        assert result.exit_code == 0

    def test_nonzero_exit(self):
        proc = MagicMock()
        proc.returncode = 1
        result = classify_worker_exit(proc)
        assert result.success is False
        assert result.exit_code == 1

    def test_signal_kill(self):
        proc = MagicMock()
        proc.returncode = -signal.SIGKILL
        result = classify_worker_exit(proc)
        assert result.success is False
        assert result.signal_number == signal.SIGKILL
        assert "SIGKILL" in result.error

    def test_signal_abort(self):
        proc = MagicMock()
        proc.returncode = -signal.SIGABRT
        result = classify_worker_exit(proc)
        assert result.success is False
        assert result.signal_number == signal.SIGABRT

    def test_still_running(self):
        proc = MagicMock()
        proc.returncode = None
        result = classify_worker_exit(proc)
        assert result.success is False
        assert "still running" in result.error


class TestRepairFlowState:
    def test_repairs_ongoing_to_incomplete(self, tmp_path):
        flow_json = tmp_path / "flow.json"
        data = {
            "steps": [
                {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                {"name": "Placement", "tool": "ecc", "state": "Ongoing"},
                {"name": "Routing", "tool": "ecc", "state": "Unstart"},
            ]
        }
        flow_json.write_text(json.dumps(data))
        repaired = repair_flow_state(flow_json)
        assert repaired == ["Placement"]
        result = json.loads(flow_json.read_text())
        assert result["steps"][1]["state"] == "Incomplete"
        assert result["steps"][0]["state"] == "Success"
        assert result["steps"][2]["state"] == "Unstart"

    def test_no_ongoing_steps(self, tmp_path):
        flow_json = tmp_path / "flow.json"
        data = {"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Success"}]}
        flow_json.write_text(json.dumps(data))
        repaired = repair_flow_state(flow_json)
        assert repaired == []

    def test_missing_file(self, tmp_path):
        flow_json = tmp_path / "nonexistent.json"
        repaired = repair_flow_state(flow_json)
        assert repaired == []

    def test_empty_file(self, tmp_path):
        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        repaired = repair_flow_state(flow_json)
        assert repaired == []

    def test_multiple_ongoing(self, tmp_path):
        flow_json = tmp_path / "flow.json"
        data = {
            "steps": [
                {"name": "A", "tool": "t1", "state": "Ongoing"},
                {"name": "B", "tool": "t2", "state": "Ongoing"},
            ]
        }
        flow_json.write_text(json.dumps(data))
        repaired = repair_flow_state(flow_json)
        assert set(repaired) == {"A", "B"}


class TestWorkerClientSubprocess:
    """Integration test using a real subprocess."""

    def test_start_and_terminate(self):
        client = WorkerClient([sys.executable, "-c", "import time; time.sleep(60)"])
        client.start()
        assert client.is_alive()
        client.terminate()
        assert not client.is_alive()

    def test_rpc_round_trip(self):
        script = textwrap.dedent("""\
            import sys, json
            data = b""
            while True:
                chunk = sys.stdin.buffer.read(1)
                if not chunk:
                    break
                data += chunk
                if b"\\r\\n\\r\\n" in data:
                    header, _, body_start = data.partition(b"\\r\\n\\r\\n")
                    length = int(header.split(b":")[1])
                    while len(body_start) < length:
                        body_start += sys.stdin.buffer.read(1)
                    request = json.loads(body_start[:length])
                    resp = {"jsonrpc": "2.0", "result": {"echo": True}, "id": request["id"]}
                    response = json.dumps(resp)
                    frame = f"Content-Length: {len(response)}\\r\\n\\r\\n{response}"
                    sys.stdout.buffer.write(frame.encode())
                    sys.stdout.buffer.flush()
                    break
        """)
        client = WorkerClient([sys.executable, "-c", script])
        client.start()
        try:
            result = client.request("test.echo", {})
            assert result.success is True
            assert result.response["result"]["echo"] is True
        finally:
            client.terminate()
