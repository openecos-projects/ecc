"""The req/rsp handshake between the flow and each of its steps.

- ``messages``: the request a step runs from and the response it publishes.
- ``files``: ``req.json`` and ``rsp.json`` in the step directory.
- ``request``: the request for a step, as the flow wired it.
- ``readiness``: whether a step has the design data it requires.
- ``response``: the response for a step that finished.
- ``stale``: steps built from upstream runs that are no longer current.
"""

from chipcompiler.data.handshake.files import (
    REQ_FILE,
    RSP_FILE,
    HandshakeError,
    clear_response,
    load_request,
    load_response,
    write_request,
    write_response,
)
from chipcompiler.data.handshake.messages import (
    DesignFiles,
    ResponseStatus,
    StepInputs,
    StepRequest,
    StepResponse,
    UpstreamResponse,
)
from chipcompiler.data.handshake.readiness import input_design_states, missing_design_data
from chipcompiler.data.handshake.request import build_step_request
from chipcompiler.data.handshake.response import build_step_response
from chipcompiler.data.handshake.stale import ChangedInput, StaleStep, stale_steps

__all__ = [
    "REQ_FILE",
    "RSP_FILE",
    "ChangedInput",
    "DesignFiles",
    "HandshakeError",
    "ResponseStatus",
    "StaleStep",
    "StepInputs",
    "StepRequest",
    "StepResponse",
    "UpstreamResponse",
    "build_step_request",
    "build_step_response",
    "clear_response",
    "input_design_states",
    "load_request",
    "load_response",
    "missing_design_data",
    "stale_steps",
    "write_request",
    "write_response",
]
