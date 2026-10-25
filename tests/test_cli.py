from __future__ import annotations

from io import StringIO
from multiprocessing.connection import AuthenticationError
from pathlib import Path

import pytest
import tomllib
from rich.console import Console

from m3u8_downloader import cli
from m3u8_downloader.cli import client_main, connect_or_start, service_command
from m3u8_downloader.config import AppPaths
from m3u8_downloader.ipc_client import ServiceError
from m3u8_downloader.terminal_view import render_tasks


class Client:
    def __init__(self, *, fail_ping: bool = False) -> None:
        self.calls = []
        self.fail_ping = fail_ping

    def request(self, action, payload, request_id=None):
        self.calls.append((action, payload))
        if action == "ping" and self.fail_ping:
            raise OSError("offline")
        if action == "list":
            return {"tasks": []}
        if action == "submit":
            return {"tasks": [{"task_id": "task-1", "task_name": payload["task_name"]}]}
        return {"task": {"task_id": payload.get("task_id", "task-1"), "state": action}}


def console() -> tuple[Console, StringIO]:
    output = StringIO()
    return Console(file=output, force_terminal=False, color_system=None, width=120), output


def test_scriptable_submit_requires_name_and_overwrite_is_explicit(tmp_path: Path) -> None:
    fake = Client()
    terminal, output = console()
    assert (
        client_main(
            ["submit", "https://example/a.m3u8", "Movie", "--save-dir", str(tmp_path)],
            client=fake,
            console=terminal,
        )
        == 0
    )
    assert fake.calls[-1][1]["overwrite"] is False

    client_main(
        ["submit", "https://example/a.m3u8", "Movie", "--save-dir", str(tmp_path), "--overwrite"],
        client=fake,
        console=terminal,
    )
    assert fake.calls[-1][1]["overwrite"] is True
    assert "task-1" in output.getvalue()

    with pytest.raises(SystemExit) as caught:
        client_main(["submit", "https://example/a.m3u8"], client=fake, console=terminal)
    assert caught.value.code == 2


def test_declared_python_minimum_matches_runtime_only_imports() -> None:
    metadata = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert metadata["project"]["requires-python"] == ">=3.11"


def test_interactive_submit_requires_nonempty_task_name(tmp_path: Path) -> None:
    fake = Client()
    terminal, _ = console()
    answers = iter(["https://example/a.m3u8", "", "Movie", str(tmp_path), "n"])

    result = client_main(
        ["interactive"],
        client=fake,
        console=terminal,
        input_fn=lambda _: next(answers),
    )

    assert result == 0
    assert fake.calls[-1][0] == "submit"
    assert fake.calls[-1][1]["task_name"] == "Movie"


@pytest.mark.parametrize("command", ["list", "pause", "resume", "cancel", "retry"])
def test_scriptable_management_commands(command: str) -> None:
    fake = Client()
    terminal, _ = console()
    args = [command] if command == "list" else [command, "task-1"]
    assert client_main(args, client=fake, console=terminal) == 0
    assert fake.calls[-1][0] == command


def test_exit_code_reports_service_errors() -> None:
    class Broken(Client):
        def request(self, action, payload, request_id=None):
            raise ServiceError("offline", "服务不可用")

    terminal, output = console()
    assert client_main(["list"], client=Broken(), console=terminal) == 3
    assert "服务不可用" in output.getvalue()


def test_connect_or_start_attaches_first_and_starts_only_when_offline() -> None:
    attached = Client()
    starts = []
    assert connect_or_start(lambda: attached, lambda: starts.append(True), retries=1) is attached
    assert starts == []

    attempts = iter([Client(fail_ping=True), Client()])
    connected = connect_or_start(lambda: next(attempts), lambda: starts.append(True), retries=2)
    assert connected.calls[-1][0] == "ping"
    assert starts == [True]

    class Rejected(Client):
        def request(self, action, payload, request_id=None):
            raise AuthenticationError("stale service")

    attempts = iter([Rejected(), Client()])
    assert connect_or_start(lambda: next(attempts), lambda: starts.append(True), retries=2)


def test_packaged_gui_relaunches_itself_in_service_mode() -> None:
    assert service_command(frozen=True)[1:] == ["--service"]
    assert service_command(frozen=False)[1:] == ["-m", "m3u8_downloader.cli", "service"]


def test_service_keeps_instance_ownership_until_workers_and_repository_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lifecycle: list[str] = []

    class Lock:
        def __init__(self, path: Path) -> None:
            self.closed = False

        def close(self) -> None:
            if not self.closed:
                self.closed = True
                lifecycle.append("release")

    class Repository:
        def __init__(self, path: Path) -> None:
            pass

        def close(self) -> None:
            lifecycle.append("repository")

    class Manager:
        def __init__(self, repository: Repository, workspace: Path) -> None:
            self.lock: Lock | None = None

        def shutdown(self, *, timeout: float = 5.0) -> None:
            assert self.lock is not None and not self.lock.closed
            lifecycle.append("workers")

    class Server:
        def __init__(self, manager: Manager, **kwargs) -> None:
            self.lock = kwargs["instance_lock"]
            manager.lock = self.lock

        def serve_forever(self) -> None:
            lifecycle.append("serve")

        def stop_accepting(self) -> None:
            lifecycle.append("stop")

        def release_instance_lock(self) -> None:
            self.lock.close()

        def shutdown(self) -> None:
            self.lock.close()

    monkeypatch.setattr(
        cli,
        "_default_paths",
        lambda: AppPaths(tmp_path / "data", tmp_path / "config", tmp_path / "cache"),
    )
    monkeypatch.setattr(cli, "ServiceInstanceLock", Lock)
    monkeypatch.setattr(cli, "TaskRepository", Repository)
    monkeypatch.setattr(cli, "TaskManager", Manager)
    monkeypatch.setattr(cli, "ServiceServer", Server)
    monkeypatch.setattr(cli, "load_or_create_auth_key", lambda path: b"x" * 32)

    assert cli.service_main([]) == 0
    assert lifecycle == ["serve", "stop", "workers", "repository", "release"]


def test_rich_view_displays_route_waiting_merge_and_errors() -> None:
    terminal, output = console()
    render_tasks(
        terminal,
        [
            {
                "task_id": "task-1",
                "task_name": "Movie",
                "state": "waiting_merge",
                "completed": 8,
                "total": 8,
                "route": "本地代理 · http://127.0.0.1:7890",
                "error": "磁盘空间不足",
            }
        ],
    )
    rendered = output.getvalue()
    assert "等待合并" in rendered
    assert "127.0.0.1:7890" in rendered
    assert "磁盘空间不足" in rendered
