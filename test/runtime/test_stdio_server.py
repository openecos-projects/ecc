import io
import json
import os
import subprocess
import sys

from chipcompiler.runtime.server import RuntimeServer
from chipcompiler.runtime.stdio_server import run_stdio_server
from chipcompiler.runtime.transport import ContentLengthDecoder, encode_content_length_frame


def _request(method: str, request_id, params: dict | None = None) -> bytes:
    payload = {"jsonrpc": "2.0", "method": method, "id": request_id}
    if params is not None:
        payload["params"] = params
    return encode_content_length_frame(json.dumps(payload, separators=(",", ":")))


def _decode_output(output: bytes) -> list[dict]:
    decoder = ContentLengthDecoder()
    return [json.loads(message) for message in decoder.feed(output)]


def test_stdio_server_writes_only_content_length_framed_responses():
    stdin = io.BytesIO(
        _request("rpc.hello", 1, {"version": 1})
        + _request("rpc.ping", 2)
        + _request("rpc.shutdown", 3)
    )
    stdout = io.BytesIO()

    rc = run_stdio_server(stdin, stdout, server=RuntimeServer())

    raw = stdout.getvalue()
    assert rc == 0
    assert raw.startswith(b"Content-Length: ")
    assert raw.count(b"Content-Length: ") == 3
    responses = _decode_output(raw)
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert responses[0]["result"]["version"] == 1
    assert responses[1]["result"] == {"ok": True}
    assert responses[2]["result"] == {"ok": True}


def test_stdio_server_redirects_print_noise_away_from_protocol_stdout(capfd):
    server = RuntimeServer()
    server.dispatcher.add_method("test.noisyPrint", lambda: print("tool output") or {"ok": True})
    stdin = io.BytesIO(_request("test.noisyPrint", 1))
    stdout = io.BytesIO()

    rc = run_stdio_server(stdin, stdout, server=server)

    captured = capfd.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "tool output" in captured.err
    assert _decode_output(stdout.getvalue())[0]["result"] == {"ok": True}


def test_stdio_server_redirects_fd_stdout_noise_away_from_protocol_stdout(capfd):
    server = RuntimeServer()

    def noisy_fd():
        os.write(1, b"tool output\n")
        return {"ok": True}

    server.dispatcher.add_method("test.noisyFd", noisy_fd)
    stdin = io.BytesIO(_request("test.noisyFd", 1))
    stdout = io.BytesIO()

    rc = run_stdio_server(stdin, stdout, server=server)

    captured = capfd.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "tool output" in captured.err
    assert _decode_output(stdout.getvalue())[0]["result"] == {"ok": True}


def test_rpc_stdio_subprocess_smoke():
    stdin = _request("rpc.hello", 1, {"version": 1}) + _request("rpc.ping", 2) + _request(
        "rpc.shutdown",
        3,
    )

    completed = subprocess.run(
        [sys.executable, "-m", "chipcompiler.cli.main", "rpc", "serve", "--stdio"],
        input=stdin,
        cwd=os.getcwd(),
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    responses = _decode_output(completed.stdout)
    assert [response["id"] for response in responses] == [1, 2, 3]
    assert responses[1]["result"] == {"ok": True}


def test_rpc_stdio_subprocess_workspace_open_home_smoke(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "home").mkdir(parents=True)
    (ws / "home" / "parameters.json").write_text("{}")
    (ws / "home" / "home.json").write_text("{}")
    stdin = (
        _request("workspace.open", 1, {"directory": str(ws)})
        + _request("workspace.home", 2, {"workspaceId": "workspace-1"})
        + _request("rpc.shutdown", 3)
    )
    script = """
import sys
from pathlib import Path
from types import SimpleNamespace

import chipcompiler.data
import chipcompiler.engine
import chipcompiler.rtl2gds

class DummyFlow:
    def __init__(self, workspace):
        self.workspace = workspace
        self.workspace_steps = []
    def has_init(self):
        return False
    def add_step(self, step, tool, state):
        self.workspace.flow.data.setdefault("steps", []).append(
            {"name": step, "tool": tool, "state": state}
        )
    def create_step_workspaces(self):
        return None

def fake_workspace(directory):
    directory = Path(directory).resolve()
    return SimpleNamespace(
        directory=directory,
        flow=SimpleNamespace(path=directory / "home" / "flow.json", data={"steps": []}),
        home=SimpleNamespace(path=directory / "home" / "home.json"),
        design=SimpleNamespace(origin_def="", origin_verilog=""),
    )

chipcompiler.data.load_workspace = fake_workspace
chipcompiler.engine.EngineFlow = DummyFlow
chipcompiler.rtl2gds.build_rtl2gds_flow = lambda: [("Synthesis", "yosys", "Unstart")]
sys.argv = ["ecc", "rpc", "serve", "--stdio"]

from chipcompiler.cli.main import main
main()
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        input=stdin,
        cwd=os.getcwd(),
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    responses = _decode_output(completed.stdout)
    assert responses[0]["result"] == {
        "workspaceId": "workspace-1",
        "directory": str(ws.resolve()),
    }
    assert responses[1]["result"] == {"path": str(ws.resolve() / "home" / "home.json")}
    assert responses[2]["result"] == {"ok": True}
