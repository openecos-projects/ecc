import re
from pathlib import Path

import pytest

from chipcompiler.runtime.transport import (
    ContentLengthDecoder,
    TransportError,
    encode_content_length_frame,
)


def test_encodes_and_decodes_one_content_length_frame():
    frame = encode_content_length_frame(b'{"jsonrpc":"2.0","id":1}')

    assert frame.startswith(b"Content-Length: 24\r\n\r\n")
    decoder = ContentLengthDecoder()
    assert decoder.feed(frame) == [b'{"jsonrpc":"2.0","id":1}']


def test_decodes_multiple_frames_from_one_buffer():
    frame = encode_content_length_frame(b'{"id":1}') + encode_content_length_frame(b'{"id":2}')

    decoder = ContentLengthDecoder()

    assert decoder.feed(frame) == [b'{"id":1}', b'{"id":2}']


def test_buffers_partial_header_and_payload_until_complete():
    frame = encode_content_length_frame(b'{"id":1}')
    decoder = ContentLengthDecoder()

    assert decoder.feed(frame[:5]) == []
    assert decoder.feed(frame[5:20]) == []
    assert decoder.feed(frame[20:-1]) == []
    assert decoder.feed(frame[-1:]) == [b'{"id":1}']


def test_malformed_content_length_header_is_transport_error():
    decoder = ContentLengthDecoder()

    with pytest.raises(TransportError, match="Content-Length"):
        decoder.feed(b"Content-Length: nope\r\n\r\n{}")


def test_missing_content_length_header_is_transport_error():
    decoder = ContentLengthDecoder()

    with pytest.raises(TransportError, match="Content-Length"):
        decoder.feed(b"X-Length: 2\r\n\r\n{}")


def test_oversize_payload_is_transport_error():
    decoder = ContentLengthDecoder(max_payload_size=4)

    with pytest.raises(TransportError, match="exceeds"):
        decoder.feed(encode_content_length_frame(b"12345"))


def test_workspace_rpc_doc_content_lengths_match_payloads():
    source = Path("docs/workspace-cli.md").read_text(encoding="utf-8")
    frames = re.findall(r"Content-Length: (\d+)\n\n({\"jsonrpc\"[^\n]+})", source)

    assert frames
    for declared, payload in frames:
        assert int(declared) == len(payload.encode("utf-8"))


def test_workspace_rpc_docs_cover_opt_in_persistent_db_surface():
    source = Path("docs/workspace-cli.md").read_text(encoding="utf-8")
    cli_design = Path("docs/specification/cli-design.md").read_text(encoding="utf-8")

    for text in (source, cli_design):
        assert "--persistent-db" in text
        assert "db.ensure" in text
        assert "db.release" in text
    assert "default sidecar does not advertise or persist native DB handles" in cli_design
    assert (
        "Opening or creating a workspace does not initialize persistent native DB state" in source
    )
