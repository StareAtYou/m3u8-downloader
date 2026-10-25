from __future__ import annotations

import os
import threading
from multiprocessing.connection import AuthenticationError, Client
from pathlib import Path

import pytest

from m3u8_downloader import service
from m3u8_downloader.ipc_client import ServiceClient
from m3u8_downloader.manager import TaskManager
from m3u8_downloader.models import OverwritePolicy, TaskState
from m3u8_downloader.service import (
    ServiceAlreadyRunning,
    ServiceInstanceLock,
    ServiceServer,
    load_or_create_auth_key,
)
from m3u8_downloader.storage import TaskRepository


def make_manager(root: Path) -> TaskManager:
    return TaskManager(
        TaskRepository(root / "state.sqlite3"),
        root / "workspaces",
        auto_schedule=False,
    )


def start_server(root: Path, manager: TaskManager | None = None):
    key = load_or_create_auth_key(root / "service.key")
    server = ServiceServer(
        manager or make_manager(root),
        authkey=key,
        address=("127.0.0.1", 0),
        instance_lock_path=root / "service.lock",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    assert server.ready.wait(2)
    return server, thread, key


def stop_server(server: ServiceServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_auth_key_is_private_and_wrong_auth_is_rejected(tmp_path: Path) -> None:
    server, thread, key = start_server(tmp_path)
    try:
        if os.name != "nt":
            assert (tmp_path / "service.key").stat().st_mode & 0o777 == 0o600
        assert len(key) >= 32
        with pytest.raises(AuthenticationError):
            Client(server.address, authkey=b"wrong-key")
        assert ServiceClient(server.address, key).request("ping", {}) == {"status": "ok"}
    finally:
        stop_server(server, thread)


def test_command_dispatch_correlation_and_persistent_idempotency(tmp_path: Path) -> None:
    server, thread, key = start_server(tmp_path)
    client = ServiceClient(server.address, key, client_id="desktop")
    payload = {
        "url": "https://example/media.m3u8?token=hidden",
        "task_name": "Demo",
        "save_root": str(tmp_path),
    }
    try:
        first = client.request("submit", payload, request_id="same-request")
        duplicate = client.request("submit", payload, request_id="same-request")
        assert first == duplicate
        assert len(client.request("list", {})["tasks"]) == 1
        task_id = first["tasks"][0]["task_id"]
        paused = client.request("pause", {"task_id": task_id})
        assert paused["task"]["state"] == "paused"
        resumed = client.request("resume", {"task_id": task_id})
        assert resumed["task"]["state"] == "queued"
    finally:
        stop_server(server, thread)

    # The idempotency record survives a complete repository/service reopen.
    reopened = make_manager(tmp_path)
    server2, thread2, key2 = start_server(tmp_path, reopened)
    try:
        result = ServiceClient(server2.address, key2, client_id="desktop").request(
            "submit", payload, request_id="same-request"
        )
        assert result == first
        assert len(reopened.list()) == 1
    finally:
        stop_server(server2, thread2)


def test_batch_dedup_is_atomic_under_two_simultaneous_clients(tmp_path: Path) -> None:
    server, thread, key = start_server(tmp_path)
    barrier = threading.Barrier(2)
    results = []

    def submit() -> None:
        barrier.wait()
        client = ServiceClient(server.address, key, client_id="terminal")
        results.append(
            client.request(
                "submit_batch",
                {
                    "tasks": [
                        {
                            "url": "https://example/a.m3u8",
                            "task_name": "A",
                            "save_root": str(tmp_path),
                        },
                        {
                            "url": "https://example/b.m3u8",
                            "task_name": "B",
                            "save_root": str(tmp_path),
                        },
                    ]
                },
                request_id="batch-one",
            )
        )

    try:
        workers = [threading.Thread(target=submit) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=3)
        assert results[0] == results[1]
        assert len(ServiceClient(server.address, key).request("list", {})["tasks"]) == 2
    finally:
        stop_server(server, thread)


def test_subscriptions_use_callback_executor_and_disconnect_is_isolated(tmp_path: Path) -> None:
    server, thread, key = start_server(tmp_path)
    callback_thread_ids = []
    received = threading.Event()
    client = ServiceClient(server.address, key)
    subscription = client.subscribe(lambda event: (callback_thread_ids.append(threading.get_ident()), received.set()))
    broken = ServiceClient(server.address, key).subscribe(lambda _: None)
    broken.close()
    try:
        client.request(
            "submit",
            {
                "url": "https://example/a.m3u8",
                "task_name": "Subscribed",
                "save_root": str(tmp_path),
            },
        )
        assert received.wait(2)
        assert callback_thread_ids[0] != subscription.reader_thread.ident
        assert thread.is_alive()
    finally:
        subscription.close()
        stop_server(server, thread)


def test_singleton_lock_rejects_second_server(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    key = load_or_create_auth_key(tmp_path / "service.key")
    first = ServiceServer(
        manager,
        authkey=key,
        address=("127.0.0.1", 0),
        instance_lock_path=tmp_path / "service.lock",
    )
    try:
        with pytest.raises(ServiceAlreadyRunning):
            ServiceServer(
                manager,
                authkey=key,
                address=("127.0.0.1", 0),
                instance_lock_path=tmp_path / "service.lock",
            )
    finally:
        first.shutdown()


def test_service_ownership_can_be_acquired_before_repository_recovery(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "state.sqlite3")
    record = repository.create_task(
        task_id="active",
        url="https://example/a.m3u8",
        task_name="Active",
        filename="Active.mp4",
        save_root=str(tmp_path),
        workspace=str(tmp_path / "work"),
        final_path=str(tmp_path / "Active.mp4"),
        overwrite_policy=OverwritePolicy.REJECT,
    )
    repository.update_state(record.task_id, TaskState.PROBING)
    repository.close()
    owner = ServiceInstanceLock(tmp_path / "service.lock")
    try:
        with pytest.raises(ServiceAlreadyRunning):
            ServiceInstanceLock(tmp_path / "service.lock")
        check = TaskRepository(tmp_path / "state.sqlite3")
        assert check.get_snapshot("active").state.value == "probing"
        check.close()
    finally:
        owner.close()


def test_subscription_reports_unexpected_disconnect(tmp_path: Path) -> None:
    server, thread, key = start_server(tmp_path)
    disconnected = threading.Event()
    subscription = ServiceClient(server.address, key).subscribe(lambda _event: None, disconnected.set)

    server.shutdown()
    thread.join(timeout=2)

    assert disconnected.wait(2)
    subscription.close()


def test_stop_after_serve_loop_exit_does_not_connect_to_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = ServiceServer(
        make_manager(tmp_path),
        authkey=b"x" * 32,
        address=("127.0.0.1", 0),
        instance_lock_path=tmp_path / "service.lock",
    )

    class InterruptedListener:
        def accept(self):
            raise KeyboardInterrupt

        def close(self) -> None:
            pass

    server._listener.close()
    server._listener = InterruptedListener()
    try:
        with pytest.raises(KeyboardInterrupt):
            server.serve_forever()

        def reject_self_connect(*args, **kwargs):
            raise AssertionError("stopped serving loop must not connect to itself")

        monkeypatch.setattr(service, "Client", reject_self_connect)
        server.stop_accepting()
    finally:
        server._stop.set()
        server.release_instance_lock()
