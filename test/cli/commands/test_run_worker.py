"""CLI-level run tests that execute against a real worker subprocess."""

import json
import os
import sys
import textwrap
from types import SimpleNamespace

import pytest

from chipcompiler.cli import main as cli_main
from chipcompiler.cli.command_handlers import project as project_module

# Captured at import time, before the autouse fixture replaces the module attr.
_REAL_RUN_FLOW_VIA_WORKER = project_module._run_flow_via_worker

_FAKE_WORKER = textwrap.dedent("""\
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
        payload = json.dumps({"v": 1, "event": event, "step": step, "tool": tool})
        return chr(0x1e).encode() + b"ECC-STEP " + payload.encode() + b"\\n"

    def flow_json_path(ws_dir):
        return os.path.join(ws_dir, "home", "flow.json")

    def run_one_step(ws_dir, name, tool):
        os.write(2, make_marker("begin", name, tool))
        os.write(2, ("output of " + name + "\\n").encode())
        os.write(2, make_marker("end", name, tool))
        path = flow_json_path(ws_dir)
        with open(path) as handle:
            data = json.load(handle)
        for record in data["steps"]:
            if record["name"] == name:
                record["state"] = "Success"
                record["runtime"] = "0:00:01"
        with open(path, "w") as handle:
            json.dump(data, handle)

    def run_pending(ws_dir):
        path = flow_json_path(ws_dir)
        with open(path) as handle:
            data = json.load(handle)
        for record in data["steps"]:
            if record.get("state") != "Success":
                run_one_step(ws_dir, record["name"], record.get("tool", "ecc"))

    ws_dir = ""
    while True:
        req = read_request()
        if req is None:
            break
        method = req.get("method", "")
        req_id = req.get("id")
        if method == "rpc.hello":
            send_response({"jsonrpc": "2.0", "result": {"version": 1}, "id": req_id})
        elif method == "workspace.open":
            ws_dir = req["params"]["directory"]
            result = {"workspaceId": "fake-worker"}
            send_response({"jsonrpc": "2.0", "result": result, "id": req_id})
        elif method == "flow.run_step":
            params = req["params"]
            step = params["step"]
            tool = "ecc"
            with open(flow_json_path(ws_dir)) as handle:
                flow_data = json.load(handle)
            for record in flow_data["steps"]:
                if record["name"] == step:
                    tool = record.get("tool", "ecc")
            if params.get("invalidate_dependents"):
                seen_target = False
                for record in flow_data["steps"]:
                    if record["name"] == step:
                        seen_target = True
                        continue
                    if seen_target:
                        record["state"] = "Unstart"
                with open(flow_json_path(ws_dir), "w") as handle:
                    json.dump(flow_data, handle)
            run_one_step(ws_dir, step, tool)
            result = {"step": step, "state": "Success"}
            send_response({"jsonrpc": "2.0", "result": result, "id": req_id})
        elif method == "flow.run":
            run_pending(ws_dir)
            send_response({"jsonrpc": "2.0", "result": {"rerun": False}, "id": req_id})
        elif method == "rpc.shutdown":
            send_response({"jsonrpc": "2.0", "result": {"ok": True}, "id": req_id})
            break
        else:
            err = {"code": -32601, "message": "unknown method"}
            send_response({"jsonrpc": "2.0", "error": err, "id": req_id})
""")


def _write_flow_json(workspace_dir, steps):
    home = os.path.join(workspace_dir, "home")
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "flow.json"), "w") as handle:
        json.dump({"steps": steps}, handle)


def _read_flow_states(workspace_dir):
    with open(os.path.join(workspace_dir, "home", "flow.json")) as handle:
        return {record["name"]: record["state"] for record in json.load(handle)["steps"]}


@pytest.fixture
def fake_worker(tmp_path, monkeypatch):
    script = tmp_path / "fake_worker.py"
    script.write_text(_FAKE_WORKER)
    monkeypatch.setattr(
        "chipcompiler.runtime.worker_operation._default_worker_argv",
        lambda: [sys.executable, str(script)],
    )
    return script


class TestWorkspaceRunWithRealWorker:
    @pytest.fixture
    def validation_mocks(self, monkeypatch):
        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def has_init(self):
                return True

        def fake_load_workspace(path):
            return SimpleNamespace(
                name="workspace",
                flow=SimpleNamespace(
                    data={
                        "steps": [
                            {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                            {"name": "place", "tool": "ecc", "state": "Imcomplete"},
                            {"name": "CTS", "tool": "ecc", "state": "Unstart"},
                        ]
                    }
                ),
            )

        monkeypatch.setattr("chipcompiler.data.load_workspace", fake_load_workspace)
        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)

    def test_resume_runs_suffix_through_worker_and_archives(
        self, fake_worker, validation_mocks, tmp_path, capsys
    ):
        workspace = str(tmp_path / "workspace")
        _write_flow_json(
            workspace,
            [
                {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                {"name": "place", "tool": "ecc", "state": "Imcomplete"},
                {"name": "CTS", "tool": "ecc", "state": "Unstart"},
            ],
        )

        rc = cli_main.run(["run", "--workspace", workspace, "--resume", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 0
        assert record["status"] == "success"
        assert record["executed_steps"] == ["place", "CTS"]
        assert _read_flow_states(workspace) == {
            "Synthesis": "Success",
            "place": "Success",
            "CTS": "Success",
        }
        for step, tool in (("place", "ecc"), ("CTS", "ecc")):
            log_path = os.path.join(workspace, f"{step}_{tool}", "log", f"{step}.log")
            with open(log_path, "rb") as handle:
                content = handle.read()
            assert f"output of {step}\n".encode() in content
            assert b"ECC-STEP" not in content

    def test_only_executes_single_step(self, fake_worker, validation_mocks, tmp_path, capsys):
        workspace = str(tmp_path / "workspace")
        _write_flow_json(
            workspace,
            [
                {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                {"name": "place", "tool": "ecc", "state": "Imcomplete"},
                {"name": "CTS", "tool": "ecc", "state": "Unstart"},
            ],
        )

        rc = cli_main.run(["run", "--workspace", workspace, "--only", "place", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 0
        assert record["executed_steps"] == ["place"]
        assert _read_flow_states(workspace) == {
            "Synthesis": "Success",
            "place": "Success",
            "CTS": "Unstart",
        }
        assert not os.path.exists(os.path.join(workspace, "CTS_ecc"))

    def test_only_force_marks_downstream_unstart_but_keeps_outputs(
        self, fake_worker, tmp_path, capsys, monkeypatch
    ):
        workspace = str(tmp_path / "workspace")
        _write_flow_json(
            workspace,
            [
                {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                {"name": "place", "tool": "ecc", "state": "Success"},
                {"name": "CTS", "tool": "ecc", "state": "Success"},
            ],
        )
        cts_output = os.path.join(workspace, "CTS_ecc", "output")
        os.makedirs(cts_output)
        with open(os.path.join(cts_output, "result.def"), "w") as handle:
            handle.write("old")

        class Flow:
            def __init__(self, workspace):
                self.workspace = workspace

            def has_init(self):
                return True

        def fake_load_workspace(path):
            return SimpleNamespace(
                name="workspace",
                flow=SimpleNamespace(
                    data={
                        "steps": [
                            {"name": "Synthesis", "tool": "yosys", "state": "Success"},
                            {"name": "place", "tool": "ecc", "state": "Success"},
                            {"name": "CTS", "tool": "ecc", "state": "Success"},
                        ]
                    }
                ),
            )

        monkeypatch.setattr("chipcompiler.data.load_workspace", fake_load_workspace)
        monkeypatch.setattr("chipcompiler.engine.EngineFlow", Flow)

        rc = cli_main.run(["run", "--workspace", workspace, "--only", "place", "--force", "--json"])

        record = json.loads(capsys.readouterr().out)["records"][0]
        assert rc == 0
        assert record["executed_steps"] == ["place"]
        assert _read_flow_states(workspace) == {
            "Synthesis": "Success",
            "place": "Success",
            "CTS": "Unstart",
        }
        with open(os.path.join(cts_output, "result.def")) as handle:
            assert handle.read() == "old"


class TestFlowRunViaWorkerArchival:
    def test_non_tty_run_archives_step_logs_without_markers(
        self, fake_worker, tmp_path, monkeypatch
    ):
        workspace = str(tmp_path / "workspace")
        _write_flow_json(
            workspace,
            [
                {"name": "Synthesis", "tool": "yosys", "state": "Unstart"},
                {"name": "place", "tool": "ecc", "state": "Unstart"},
            ],
        )

        result = _REAL_RUN_FLOW_VIA_WORKER(workspace)

        assert result.success is True
        for step, tool in (("Synthesis", "yosys"), ("place", "ecc")):
            log_path = os.path.join(workspace, f"{step}_{tool}", "log", f"{step}.log")
            with open(log_path, "rb") as handle:
                content = handle.read()
            assert f"output of {step}\n".encode() in content
            assert b"ECC-STEP" not in content
