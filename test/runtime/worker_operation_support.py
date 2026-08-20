"""Shared fake-worker script preamble for the worker-operation tests."""

import textwrap

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
