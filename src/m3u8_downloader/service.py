from __future__ import annotations

import logging
import os
import secrets
import threading
from dataclasses import asdict
from multiprocessing.connection import AuthenticationError, Client, Listener
from pathlib import Path
from typing import Any

from .manager import Submission, TaskManager
from .models import AppSettings
from .protocol import EventFrame, ProtocolError, RequestFrame, ResponseFrame, receive_frame, send_frame

logger = logging.getLogger(__name__)


class ServiceAlreadyRunning(RuntimeError):
    pass


class ServiceInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                self._handle.close()
                raise ServiceAlreadyRunning("后台服务已在运行") from exc
        else:
            import fcntl

            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                self._handle.close()
                raise ServiceAlreadyRunning("后台服务已在运行") from exc

    def close(self) -> None:
        if self._handle.closed:
            return
        if os.name == "nt":
            import msvcrt

            try:
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()


def load_or_create_auth_key(path: Path) -> bytes:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        value = path.read_bytes()
    else:
        value = secrets.token_bytes(32)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    if len(value) < 32:
        raise RuntimeError("服务认证密钥无效")
    if os.name != "nt":
        path.chmod(0o600)
    return value


class ServiceServer:
    def __init__(
        self,
        manager: TaskManager,
        *,
        authkey: bytes,
        address: tuple[str, int],
        instance_lock_path: Path | None = None,
        instance_lock: ServiceInstanceLock | None = None,
    ) -> None:
        self.manager = manager
        self.authkey = authkey
        if instance_lock is None and instance_lock_path is None:
            raise ValueError("必须提供服务单实例锁")
        self._instance_lock = instance_lock or ServiceInstanceLock(Path(instance_lock_path))
        try:
            self._listener = Listener(address, family="AF_INET", authkey=authkey)
        except BaseException:
            self._instance_lock.close()
            raise
        self.address = self._listener.address
        self.ready = threading.Event()
        self._serving = threading.Event()
        self._stop = threading.Event()
        self._subscribers: set[Any] = set()
        self._subscribers_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._closed = False

    def serve_forever(self) -> None:
        self.ready.set()
        self._serving.set()
        monitor = threading.Thread(target=self._monitor_tasks, daemon=True, name="task-events")
        monitor.start()
        self._threads.append(monitor)
        try:
            while not self._stop.is_set():
                try:
                    connection = self._listener.accept()
                except AuthenticationError:
                    continue
                except (OSError, EOFError):
                    break
                if self._stop.is_set():
                    connection.close()
                    break
                thread = threading.Thread(
                    target=self._handle_connection,
                    args=(connection,),
                    daemon=True,
                    name="ipc-client",
                )
                thread.start()
                self._threads.append(thread)
        finally:
            self._serving.clear()

    def _monitor_tasks(self) -> None:
        while not self._stop.wait(0.1):
            try:
                if self.manager.drain_worker_events():
                    self.broadcast_tasks()
            except Exception:
                logger.exception("任务事件监控忽略了一次异常")
                continue

    def _handle_connection(self, connection: Any) -> None:
        request_id = "unknown"
        try:
            request = RequestFrame.from_mapping(receive_frame(connection))
            request_id = request.request_id
            if request.action == "subscribe":
                send_frame(connection, ResponseFrame.success(request_id, {"subscribed": True}))
                with self._subscribers_lock:
                    self._subscribers.add(connection)
                return
            result = self._dispatch(request)
            send_frame(connection, ResponseFrame.success(request_id, result))
            if request.action not in {"ping", "list", "get", "get_settings"}:
                self.broadcast_tasks()
        except ProtocolError as exc:
            send_frame(connection, ResponseFrame.error_response(request_id, exc.code, exc.message))
        except KeyError:
            send_frame(connection, ResponseFrame.error_response(request_id, "not_found", "任务不存在"))
        except (ValueError, FileExistsError) as exc:
            send_frame(connection, ResponseFrame.error_response(request_id, "invalid_request", str(exc)))
        except (EOFError, OSError):
            pass
        except Exception:  # noqa: BLE001 - keep one malformed client isolated
            try:
                send_frame(connection, ResponseFrame.error_response(request_id, "internal_error", "服务内部错误"))
            except (EOFError, OSError):
                pass
        finally:
            with self._subscribers_lock:
                subscribed = connection in self._subscribers
            if not subscribed:
                connection.close()

    def _dispatch(self, request: RequestFrame) -> dict[str, Any]:
        payload = request.payload
        action = request.action
        if action == "ping":
            return {"status": "ok"}
        if action in {"submit", "submit_batch"}:
            raw_tasks = [payload] if action == "submit" else payload.get("tasks")
            if not isinstance(raw_tasks, list):
                raise ValueError("tasks 必须是数组")
            submissions = [Submission(**item) for item in raw_tasks]
            return self.manager.submit_batch_idempotent(
                submissions,
                client_id=request.client_id,
                request_id=request.request_id,
            )
        if action == "list":
            return {"tasks": [item.to_dict() for item in self.manager.list()]}
        if action == "get":
            return {"task": self.manager.get(str(payload["task_id"])).to_dict()}
        if action == "pause":
            return {"task": self.manager.pause(str(payload["task_id"])).to_dict()}
        if action == "pause_all":
            return {"task_ids": self.manager.pause_all()}
        if action == "resume":
            return {"task": self.manager.resume(str(payload["task_id"])).to_dict()}
        if action == "cancel":
            return {"task": self.manager.cancel(str(payload["task_id"])).to_dict()}
        if action == "retry":
            return {"task": self.manager.retry(str(payload["task_id"])).to_dict()}
        if action == "get_settings":
            return {"settings": asdict(self.manager.get_settings())}
        if action == "update_settings":
            return {"settings": asdict(self.manager.update_settings(AppSettings(**payload)))}
        raise ProtocolError("unknown_action", f"未知操作: {action}")

    def broadcast_tasks(self) -> None:
        frame = EventFrame("tasks_changed", {"tasks": [item.to_dict() for item in self.manager.list()]})
        failed = []
        with self._subscribers_lock:
            subscribers = tuple(self._subscribers)
        for connection in subscribers:
            try:
                send_frame(connection, frame)
            except (EOFError, OSError):
                failed.append(connection)
        if failed:
            with self._subscribers_lock:
                for connection in failed:
                    self._subscribers.discard(connection)
                    connection.close()

    def stop_accepting(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._serving.is_set():
            try:
                Client(self.address, family="AF_INET", authkey=self.authkey).close()
            except (OSError, AuthenticationError):
                pass
        try:
            self._listener.close()
        except OSError:
            pass
        with self._subscribers_lock:
            subscribers, self._subscribers = tuple(self._subscribers), set()
        for connection in subscribers:
            connection.close()

    def release_instance_lock(self) -> None:
        self._instance_lock.close()

    def shutdown(self) -> None:
        self.stop_accepting()
        self.release_instance_lock()
