from __future__ import annotations

import sys
from typing import BinaryIO

from chipcompiler.runtime.server import RuntimeServer
from chipcompiler.runtime.transport import (
    ContentLengthDecoder,
    TransportError,
    encode_content_length_frame,
)


def run_stdio_server(
    input_stream: BinaryIO,
    output_stream: BinaryIO,
    *,
    server: RuntimeServer | None = None,
) -> int:
    runtime_server = server or RuntimeServer()
    decoder = ContentLengthDecoder()

    while not runtime_server.should_exit:
        chunk = input_stream.read(8192)
        if not chunk:
            break
        try:
            messages = decoder.feed(chunk)
        except TransportError as exc:
            print(f"transport error: {exc}", file=sys.stderr)
            return 1

        for message in messages:
            response = runtime_server.dispatch(message)
            output_stream.write(encode_content_length_frame(response))
            output_stream.flush()
            if runtime_server.should_exit:
                break

    return 0


def main() -> int:
    return run_stdio_server(sys.stdin.buffer, sys.stdout.buffer)
