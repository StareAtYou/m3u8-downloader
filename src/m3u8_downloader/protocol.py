from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 1024 * 1024
ALLOWED_ACTIONS = frozenset(
    {
        "submit",
        "submit_batch",
        "list",
        "get",
        "pause",
        "pause_all",
        "resume",
        "cancel",
        "retry",
        "get_settings",
        "update_settings",
        "subscribe",
        "ping",
    }
)


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, str | int | float | bool):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


def _require_text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ProtocolError("invalid_request", f"字段 {key} 必须是非空短文本")
    return value


def _normalize_legacy(mapping: Mapping[str, Any]) -> dict[str, Any]:
    if "cmd" not in mapping:
        return dict(mapping)
    actions = {"add_task": "submit", "add_tasks": "submit_batch", "tasks": "list"}
    action = actions.get(str(mapping.get("cmd")), str(mapping.get("cmd")))
    payload = dict(mapping.get("data") or {})
    if action == "submit":
        if "name" in payload:
            payload["task_name"] = payload.pop("name")
        if "save_dir" in payload:
            payload["save_root"] = payload.pop("save_dir")
    return {
        "type": "request",
        "version": PROTOCOL_VERSION,
        "request_id": str(mapping.get("id") or "legacy-request"),
        "client_id": str(mapping.get("client") or "legacy-client"),
        "action": action,
        "payload": payload,
    }


@dataclass(frozen=True, slots=True)
class RequestFrame:
    request_id: str
    client_id: str
    action: str
    payload: Mapping[str, Any]
    version: int = PROTOCOL_VERSION
    type: str = "request"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RequestFrame:
        value = _normalize_legacy(value)
        if value.get("type") != "request":
            raise ProtocolError("invalid_request", "帧类型不是 request")
        if value.get("version") != PROTOCOL_VERSION:
            raise ProtocolError("unsupported_version", "不支持的协议版本")
        request_id = _require_text(value, "request_id")
        client_id = _require_text(value, "client_id")
        action = _require_text(value, "action")
        if action not in ALLOWED_ACTIONS:
            raise ProtocolError("unknown_action", f"未知操作: {action}")
        payload = value.get("payload", {})
        if not isinstance(payload, dict) or not _is_json_value(payload):
            raise ProtocolError("invalid_request", "payload 必须只包含 JSON 基础类型")
        return cls(request_id, client_id, action, payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResponseFrame:
    request_id: str
    ok: bool
    result: Any = None
    error: Mapping[str, str] | None = None
    version: int = PROTOCOL_VERSION
    type: str = "response"

    @classmethod
    def success(cls, request_id: str, result: Any) -> ResponseFrame:
        return cls(request_id=request_id, ok=True, result=result)

    @classmethod
    def error_response(cls, request_id: str, code: str, message: str) -> ResponseFrame:
        return cls(request_id=request_id, ok=False, error={"code": code, "message": message})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EventFrame:
    event: str
    payload: Mapping[str, Any]
    version: int = PROTOCOL_VERSION
    type: str = "event"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def encode_frame(frame: Any) -> bytes:
    if hasattr(frame, "to_dict"):
        value = frame.to_dict()
    elif is_dataclass(frame):
        value = asdict(frame)
    elif isinstance(frame, Mapping):
        value = dict(frame)
    else:
        raise ProtocolError("invalid_frame", "帧必须是对象")
    if not _is_json_value(value):
        raise ProtocolError("invalid_frame", "帧包含非 JSON 数据")
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_FRAME_BYTES:
        raise ProtocolError("frame_too_large", "协议帧过大")
    return encoded


def decode_frame(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_FRAME_BYTES:
        raise ProtocolError("frame_too_large", "协议帧过大")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid_json", "协议帧不是有效 JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("invalid_frame", "协议帧必须是 JSON 对象")
    return value


def send_frame(connection: Any, frame: Any) -> None:
    connection.send_bytes(encode_frame(frame))


def receive_frame(connection: Any) -> dict[str, Any]:
    try:
        data = connection.recv_bytes(MAX_FRAME_BYTES)
    except OSError as exc:
        if "bad message length" in str(exc).lower():
            raise ProtocolError("frame_too_large", "协议帧过大") from exc
        raise
    return decode_frame(data)
