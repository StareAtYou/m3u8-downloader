from __future__ import annotations

import json

import pytest

from m3u8_downloader.protocol import (
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    RequestFrame,
    ResponseFrame,
    decode_frame,
    encode_frame,
    receive_frame,
    send_frame,
)


class Connection:
    def __init__(self, incoming: bytes | None = None) -> None:
        self.incoming = incoming
        self.sent = None
        self.maxlength = None

    def send_bytes(self, data: bytes) -> None:
        self.sent = data

    def recv_bytes(self, maxlength: int) -> bytes:
        self.maxlength = maxlength
        return self.incoming


def test_request_validates_version_required_fields_action_and_json_primitives() -> None:
    request = RequestFrame.from_mapping(
        {
            "type": "request",
            "version": PROTOCOL_VERSION,
            "request_id": "req-1",
            "client_id": "cli-1",
            "action": "list",
            "payload": {},
        }
    )
    assert request.action == "list"

    for invalid in (
        {"type": "request", "version": 999, "request_id": "r", "client_id": "c", "action": "list", "payload": {}},
        {"type": "request", "version": 1, "request_id": "", "client_id": "c", "action": "list", "payload": {}},
        {"type": "request", "version": 1, "request_id": "r", "client_id": "c", "action": "delete_all", "payload": {}},
        {
            "type": "request",
            "version": 1,
            "request_id": "r",
            "client_id": "c",
            "action": "list",
            "payload": {"bad": b"bytes"},
        },
    ):
        with pytest.raises(ProtocolError):
            RequestFrame.from_mapping(invalid)


def test_structured_error_response_round_trips_over_bounded_bytes() -> None:
    frame = ResponseFrame.error_response("req-1", "invalid_request", "请求无效")
    connection = Connection()
    send_frame(connection, frame)
    connection.incoming = connection.sent
    decoded = receive_frame(connection)

    assert connection.maxlength == MAX_FRAME_BYTES
    assert decoded["ok"] is False
    assert decoded["error"] == {"code": "invalid_request", "message": "请求无效"}


def test_rejects_oversized_or_non_object_json_before_use() -> None:
    with pytest.raises(ProtocolError, match="过大"):
        decode_frame(b"x" * (MAX_FRAME_BYTES + 1))
    with pytest.raises(ProtocolError, match="对象"):
        decode_frame(json.dumps(["not", "object"]).encode())
    with pytest.raises(ProtocolError, match="JSON"):
        decode_frame(b"not json")


def test_legacy_command_payload_is_mapped_to_versioned_request() -> None:
    encoded = encode_frame(
        {
            "cmd": "add_task",
            "id": "old-1",
            "client": "legacy",
            "data": {"name": "Movie", "url": "https://e/a.m3u8", "save_dir": "/tmp"},
        }
    )
    request = RequestFrame.from_mapping(decode_frame(encoded))

    assert request.action == "submit"
    assert request.request_id == "old-1"
    assert request.payload["task_name"] == "Movie"
    assert request.payload["save_root"] == "/tmp"
