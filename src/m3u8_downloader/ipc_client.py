from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from multiprocessing.connection import Client
from typing import Any

from .protocol import RequestFrame, receive_frame, send_frame


class ServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Subscription:
    def __init__(self, connection: Any, callback: Any, on_disconnect: Any | None = None) -> None:
        self.connection = connection
        self.callback = callback
        self.on_disconnect = on_disconnect
        self._stop = threading.Event()
        self._callbacks = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ipc-callback")
        self.reader_thread = threading.Thread(target=self._read, daemon=True, name="ipc-reader")
        self.reader_thread.start()

    def _read(self) -> None:
        disconnected = False
        while not self._stop.is_set():
            try:
                frame = receive_frame(self.connection)
            except (EOFError, OSError):
                disconnected = not self._stop.is_set()
                break
            if frame.get("type") == "event":
                self._callbacks.submit(self.callback, frame)
        if disconnected and self.on_disconnect is not None:
            self._callbacks.submit(self.on_disconnect)

    def close(self) -> None:
        self._stop.set()
        self.connection.close()
        if threading.current_thread() is not self.reader_thread:
            self.reader_thread.join(timeout=0.5)
        self._callbacks.shutdown(wait=False, cancel_futures=True)


class ServiceClient:
    def __init__(
        self,
        address: tuple[str, int],
        authkey: bytes,
        *,
        client_id: str | None = None,
    ) -> None:
        self.address = address
        self.authkey = authkey
        self.client_id = client_id or f"client-{uuid.uuid4()}"

    def _connect(self):
        return Client(self.address, family="AF_INET", authkey=self.authkey)

    def request(
        self,
        action: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> Any:
        request = RequestFrame(
            request_id=request_id or str(uuid.uuid4()),
            client_id=self.client_id,
            action=action,
            payload=payload,
        )
        connection = self._connect()
        try:
            send_frame(connection, request)
            response = receive_frame(connection)
        finally:
            connection.close()
        if response.get("type") != "response" or response.get("request_id") != request.request_id:
            raise ServiceError("invalid_response", "服务响应与请求不匹配")
        if not response.get("ok"):
            error = response.get("error") or {}
            raise ServiceError(str(error.get("code", "error")), str(error.get("message", "请求失败")))
        return response.get("result")

    def subscribe(self, callback: Any, on_disconnect: Any | None = None) -> Subscription:
        request = RequestFrame(
            request_id=str(uuid.uuid4()),
            client_id=self.client_id,
            action="subscribe",
            payload={},
        )
        connection = self._connect()
        send_frame(connection, request)
        response = receive_frame(connection)
        if not response.get("ok"):
            connection.close()
            error = response.get("error") or {}
            raise ServiceError(str(error.get("code", "error")), str(error.get("message", "订阅失败")))
        return Subscription(connection, callback, on_disconnect)
