#!/usr/bin/env python3
"""P0 ECC RPC smoke: drive ``ecc rpc serve``, then check with ``ecc status --project``.

Methods exercised (in order):

  rpc.hello
  rpc.ping
  project.manifest.mutate   (type=create, when --create)
  workspace.create          (when --create and workspace missing)
  project.manifest.mutate   (register_workspace, when --create)
  workspace.open
  flow.run                  (when --run)
  rpc.shutdown

After the sidecar exits, the same project path is checked the CLI way:

  ecc status --project <path> --workspace <name> --plain

No CLI source changes; this is external glue for CI / local smoke.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RTL = REPO_ROOT / "test" / "fixtures" / "gcd" / "gcd.v"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ecc",
        default=os.environ.get("ECC", "ecc"),
        help="ecc executable or shell command (default: $ECC or ecc)",
    )
    parser.add_argument("--project", required=True, help="project directory")
    parser.add_argument("--workspace", default="default", help="managed workspace name")
    parser.add_argument(
        "--create",
        action="store_true",
        help="create project.json + workspace via RPC when missing",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="call flow.run before checking status",
    )
    parser.add_argument(
        "--pdk-root",
        default=os.environ.get("CHIPCOMPILER_ICS55_PDK_ROOT", ""),
        help="PDK root for workspace.create (default: $CHIPCOMPILER_ICS55_PDK_ROOT)",
    )
    parser.add_argument(
        "--pdk-json",
        default="",
        help="optional PDK JSON file path passed to workspace.create as pdkJson",
    )
    parser.add_argument("--pdk-name", default="ics55", help="PDK name for workspace.create")
    parser.add_argument(
        "--rtl",
        default=str(DEFAULT_RTL),
        help="origin verilog for workspace.create",
    )
    parser.add_argument("--flow-start", default="", help="optional flow_config start_step")
    parser.add_argument("--flow-end", default="", help="optional flow_config end_step")
    parser.add_argument(
        "--expect-status",
        default="",
        help="required status= value from ecc status (default: success with --run)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds to wait for one RPC response (flow.run has no limit)",
    )
    args = parser.parse_args()

    project_dir = Path(args.project).expanduser().resolve()
    workspace_name = args.workspace
    workspace_dir = project_dir / workspace_name
    expect = args.expect_status or ("success" if args.run else "")
    ecc_cmd = _ecc_command(args.ecc)

    client = RpcProcess(ecc_cmd)
    try:
        hello = client.call("rpc.hello", {"version": 1}, timeout=args.timeout)
        require_result(hello, "rpc.hello")
        if hello["result"].get("version") != 1:
            fail(f"rpc.hello version={hello['result'].get('version')!r}, expected 1")
        print(
            f"rpc.hello version=1 ecc={hello['result'].get('eccVersion')}",
            flush=True,
        )

        ping = client.call("rpc.ping", {}, timeout=args.timeout)
        require_result(ping, "rpc.ping")
        if ping["result"].get("ok") is not True:
            fail(f"rpc.ping result={ping['result']!r}")

        if args.create:
            _create_project_and_workspace(
                client,
                project_dir=project_dir,
                workspace_name=workspace_name,
                workspace_dir=workspace_dir,
                pdk_name=args.pdk_name,
                pdk_root=args.pdk_root,
                rtl=Path(args.rtl),
                flow_start=args.flow_start,
                flow_end=args.flow_end,
                timeout=args.timeout,
            )

        if not workspace_dir.is_dir():
            fail(f"workspace directory missing: {workspace_dir} (pass --create)")

        opened = client.call(
            "workspace.open",
            {"directory": str(workspace_dir)},
            timeout=args.timeout,
        )
        require_result(opened, "workspace.open")
        workspace_id = opened["result"].get("workspaceId")
        if not workspace_id:
            fail(f"workspace.open missing workspaceId: {opened['result']!r}")
        print(
            f"workspace.open id={workspace_id} directory={workspace_dir}",
            flush=True,
        )

        if args.run:
            ran = client.call(
                "flow.run",
                {"workspaceId": workspace_id, "rerun": False},
                timeout=None,
            )
            require_result(ran, "flow.run")
            print(
                f"flow.run result={json.dumps(ran['result'], ensure_ascii=False)}",
                flush=True,
            )
    finally:
        client.close()

    return cli_status_check(
        ecc_cmd,
        project_dir=project_dir,
        workspace_name=workspace_name,
        expect_status=expect,
    )


def _create_project_and_workspace(
    client: RpcProcess,
    *,
    project_dir: Path,
    workspace_name: str,
    workspace_dir: Path,
    pdk_name: str,
    pdk_root: str,
    rtl: Path,
    flow_start: str,
    flow_end: str,
    timeout: float,
) -> None:
    if not (project_dir / "ecc.toml").is_file():
        fail(f"missing ecc.toml in {project_dir}")
    if not rtl.is_file():
        fail(f"rtl not found: {rtl}")

    design, top, clock, frequency = _read_design_fields(project_dir / "ecc.toml")
    resolved_pdk_root = pdk_root or _read_pdk_root(project_dir / "ecc.toml")
    if not resolved_pdk_root:
        fail("PDK root required: pass --pdk-root or set [pdk].root / CHIPCOMPILER_ICS55_PDK_ROOT")

    if not (project_dir / "project.json").is_file():
        created = client.call(
            "project.manifest.mutate",
            {
                "projectRoot": str(project_dir),
                "mutation": {
                    "type": "create",
                    "name": project_dir.name,
                    "designName": design,
                },
            },
            timeout=timeout,
        )
        require_result(created, "project.manifest.mutate(create)")
        print(f"project.manifest.create root={project_dir}", flush=True)

    if not _looks_like_workspace(workspace_dir):
        params = {
            "directory": str(workspace_dir),
            "pdk": pdk_name,
            "pdkRoot": str(Path(resolved_pdk_root).resolve()),
            "parameters": {
                "design": design,
                "top_module": top,
                "clock": clock,
                "frequency_max": frequency,
            },
            "originVerilog": str(rtl.resolve()),
            "rtlList": [str(rtl.resolve())],
            "projectRoot": str(project_dir),
        }
        if flow_start and flow_end:
            params["flowConfig"] = {"start_step": flow_start, "end_step": flow_end}
        created_ws = client.call("workspace.create", params, timeout=timeout)
        require_result(created_ws, "workspace.create")
        print(
            f"workspace.create id={created_ws['result'].get('workspaceId')} "
            f"directory={workspace_dir}",
            flush=True,
        )

    registered = client.call(
        "project.manifest.mutate",
        {
            "projectRoot": str(project_dir),
            "mutation": {
                "type": "register_workspace",
                "workspaceId": workspace_name,
                "workspacePath": str(workspace_dir),
                "name": workspace_name,
            },
        },
        timeout=timeout,
    )
    require_result(registered, "project.manifest.mutate(register_workspace)")
    print(f"project.manifest.register workspace={workspace_name}", flush=True)


def cli_status_check(
    ecc_cmd: list[str],
    *,
    project_dir: Path,
    workspace_name: str,
    expect_status: str,
) -> int:
    command = [
        *ecc_cmd,
        "status",
        "--plain",
        "--project",
        str(project_dir),
        "--workspace",
        workspace_name,
    ]
    print("+ " + " ".join(shlex.quote(part) for part in command), flush=True)
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        return completed.returncode

    status = _parse_workspace_status(completed.stdout)
    if expect_status and status != expect_status:
        fail(f"ecc status --project reported status={status!r}, expected {expect_status!r}")
    print(f"ecc status --project ok status={status}", flush=True)
    return 0


def _parse_workspace_status(plain_out: str) -> str:
    for line in plain_out.splitlines():
        if "status=" not in line:
            continue
        if line.startswith("kind=error"):
            fail(f"ecc status error line: {line}")
        fields = dict(part.split("=", 1) for part in shlex.split(line) if "=" in part)
        if "workspace_id" in fields or "workspace" in fields:
            return fields.get("status", "")
    fail(f"could not parse workspace status from:\n{plain_out}")


def _read_design_fields(toml_path: Path) -> tuple[str, str, str, float]:
    data = tomllib.loads(toml_path.read_text())
    design = data.get("design", {})
    name = str(design.get("name") or "gcd")
    top = str(design.get("top") or name)
    clock = str(design.get("clock_port") or "clk")
    frequency = float(design.get("frequency_mhz") or 100.0)
    return name, top, clock, frequency


def _read_pdk_root(toml_path: Path) -> str:
    data = tomllib.loads(toml_path.read_text())
    root = data.get("pdk", {}).get("root", "")
    return str(root or "")


def _looks_like_workspace(directory: Path) -> bool:
    home = directory / "home"
    return (home / "home.json").is_file() and (
        (home / "params.toml").is_file() or (home / "parameters.json").is_file()
    )


def _ecc_command(value: str) -> list[str]:
    parts = shlex.split(value)
    if not parts:
        fail("--ecc must not be empty")
    return parts


class RpcProcess:
    def __init__(self, ecc_cmd: list[str]) -> None:
        self.proc = subprocess.Popen(
            [*ecc_cmd, "rpc", "serve", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._next_id = 1
        self._buffer = bytearray()

    def call(self, method: str, params: dict, *, timeout: float | None) -> dict:
        request_id = self._next_id
        self._next_id += 1
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            separators=(",", ":"),
        ).encode()
        frame = b"Content-Length: %d\r\n\r\n" % len(payload) + payload
        assert self.proc.stdin is not None
        self.proc.stdin.write(frame)
        self.proc.stdin.flush()
        while True:
            message = self._read_message(timeout)
            if "id" not in message:
                continue
            if message.get("id") != request_id:
                continue
            return message

    def close(self) -> None:
        if self.proc.poll() is not None:
            return
        with contextlib.suppress(Exception):
            self.call("rpc.shutdown", {}, timeout=5)
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)

    def _read_message(self, timeout: float | None) -> dict:
        assert self.proc.stdout is not None
        while True:
            separator = self._buffer.find(b"\r\n\r\n")
            if separator >= 0:
                header = self._buffer[:separator].decode("ascii", errors="replace")
                length = _content_length(header)
                start = separator + 4
                end = start + length
                if len(self._buffer) >= end:
                    body = bytes(self._buffer[start:end])
                    del self._buffer[:end]
                    return json.loads(body)
            chunk = _read_chunk(self.proc.stdout, timeout)
            if not chunk:
                err = b""
                if self.proc.stderr is not None:
                    err = self.proc.stderr.read() or b""
                fail("rpc server closed stdout\n" + err.decode("utf-8", errors="replace")[-2000:])
            self._buffer.extend(chunk)


def _read_chunk(stream, timeout: float | None) -> bytes:
    if timeout is None:
        return stream.read(4096)
    import select

    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        fail(f"timed out after {timeout}s waiting for rpc response")
    return os.read(stream.fileno(), 4096)


def _content_length(header: str) -> int:
    values = []
    for line in header.split("\r\n"):
        name, sep, value = line.partition(":")
        if sep and name.lower() == "content-length":
            values.append(value.strip())
    if len(values) != 1:
        fail(f"bad rpc frame header: {header!r}")
    return int(values[0])


def require_result(message: dict, method: str) -> None:
    if "error" in message:
        fail(f"{method} error: {json.dumps(message['error'], ensure_ascii=False)}")
    if "result" not in message:
        fail(f"{method} missing result: {message!r}")


def fail(message: str) -> None:
    print(f"rpc_check: {message}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
