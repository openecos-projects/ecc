"""Tests for chipcompiler.runtime.worker_operation — typed operation orchestrator."""

import json
import sys
import textwrap

from chipcompiler.runtime.worker_operation import RunOperation


class TestRunOperationSuccess:
    def test_successful_rpc_returns_result(self, tmp_path):
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
                    resp = {"jsonrpc": "2.0", "result": {"steps": ["syn"]}, "id": request["id"]}
                    response = json.dumps(resp)
                    frame = f"Content-Length: {len(response)}\\r\\n\\r\\n{response}"
                    sys.stdout.buffer.write(frame.encode())
                    sys.stdout.buffer.flush()
                    break
        """)
        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, "-c", script],
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is True
        assert result.rpc_result["result"] == {"steps": ["syn"]}
        assert result.archive_error is None

    def test_rpc_error_returns_failure(self, tmp_path):
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
                    resp = {
                        "jsonrpc": "2.0",
                        "error": {"code": -1, "message": "step failed"},
                        "id": request["id"],
                    }
                    response = json.dumps(resp)
                    frame = f"Content-Length: {len(response)}\\r\\n\\r\\n{response}"
                    sys.stdout.buffer.write(frame.encode())
                    sys.stdout.buffer.flush()
                    break
        """)
        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, "-c", script],
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is False
        assert "step failed" in result.error


class TestRunOperationCrash:
    def test_worker_crash_triggers_repair(self, tmp_path):
        script_file = tmp_path / "crash_worker.py"
        script_file.write_text(
            "import sys, os, json\n"
            "marker = chr(0x1e).encode() + b'ECC-STEP ' + "
            "json.dumps({'event':'begin','step':'Synthesis','tool':'yosys'}).encode()"
            " + b'\\n'\n"
            "os.write(2, marker)\n"
            "os._exit(1)\n"
        )
        flow_json = tmp_path / "flow.json"
        data = {"steps": [{"name": "Synthesis", "tool": "yosys", "state": "Ongoing"}]}
        flow_json.write_text(json.dumps(data))
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script_file)],
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is False
        assert result.repaired_steps == ["Synthesis"]
        repaired_data = json.loads(flow_json.read_text())
        assert repaired_data["steps"][0]["state"] == "Incomplete"

    def test_worker_crash_no_flow_json_no_repair(self, tmp_path):
        script = "import sys; sys.exit(1)"
        flow_json = tmp_path / "flow.json"
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, "-c", script],
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is False
        assert result.repaired_steps == []


class TestRunOperationStderrArchive:
    def test_stderr_archived_to_step_log(self, tmp_path):
        script_file = tmp_path / "archive_worker.py"
        script_file.write_text(
            "import sys, os, json\n"
            "def marker(event, step, tool):\n"
            "    payload = json.dumps({'event':event,'step':step,'tool':tool})\n"
            "    return chr(0x1e).encode() + b'ECC-STEP ' + "
            "payload.encode() + b'\\n'\n"
            "os.write(2, marker('begin', 'Synthesis', 'yosys'))\n"
            "os.write(2, b'Synthesizing module top...\\n')\n"
            "os.write(2, marker('end', 'Synthesis', 'yosys'))\n"
            "data = b''\n"
            "while True:\n"
            "    chunk = sys.stdin.buffer.read(1)\n"
            "    if not chunk:\n"
            "        break\n"
            "    data += chunk\n"
            "    if b'\\r\\n\\r\\n' in data:\n"
            "        header, _, body_start = data.partition(b'\\r\\n\\r\\n')\n"
            "        length = int(header.split(b':')[1])\n"
            "        while len(body_start) < length:\n"
            "            body_start += sys.stdin.buffer.read(1)\n"
            "        request = json.loads(body_start[:length])\n"
            "        resp = {'jsonrpc': '2.0', 'result': {}, 'id': request['id']}\n"
            "        response = json.dumps(resp)\n"
            "        frame = f'Content-Length: {len(response)}\\r\\n\\r\\n{response}'\n"
            "        sys.stdout.buffer.write(frame.encode())\n"
            "        sys.stdout.buffer.flush()\n"
            "        break\n"
        )
        logs_dir = tmp_path / "logs"

        def resolver(step: str, tool: str):
            return logs_dir / f"{step}.log"

        flow_json = tmp_path / "flow.json"
        flow_json.write_text("{}")
        op = RunOperation(
            workspace_dir=tmp_path,
            flow_json_path=flow_json,
            worker_argv=[sys.executable, str(script_file)],
            log_path_resolver=resolver,
        )
        result = op.run("flow.run", {"workspace_id": "test"})
        assert result.success is True
        log_file = logs_dir / "Synthesis.log"
        assert log_file.exists()
        assert b"Synthesizing module top..." in log_file.read_bytes()
