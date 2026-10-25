from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from multiprocessing.connection import AuthenticationError
from pathlib import Path
from typing import Any

from rich.console import Console

from .config import AppPaths
from .ipc_client import ServiceClient, ServiceError
from .manager import TaskManager
from .service import ServiceAlreadyRunning, ServiceInstanceLock, ServiceServer, load_or_create_auth_key
from .storage import TaskRepository
from .terminal_view import render_tasks

# Avoid the port used by the legacy implementation so both versions can
# coexist while users migrate active downloads.
DEFAULT_ADDRESS = ("127.0.0.1", 61288)


def _default_paths() -> AppPaths:
    paths = AppPaths.from_platform()
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    return paths


def _default_client() -> ServiceClient:
    paths = _default_paths()
    authkey = load_or_create_auth_key(paths.config_dir / "service.key")
    return connect_or_start(
        lambda: ServiceClient(DEFAULT_ADDRESS, authkey),
        spawn_service,
    )


def connect_or_start(
    client_factory: Callable[[], Any],
    service_starter: Callable[[], None],
    *,
    retries: int = 10,
    retry_delay: float = 0.1,
) -> Any:
    started = False
    last_error: BaseException | None = None
    for _ in range(max(1, retries)):
        client = client_factory()
        try:
            client.request("ping", {})
            return client
        except (OSError, EOFError, ConnectionError, AuthenticationError, ServiceError) as exc:
            last_error = exc
            if not started:
                service_starter()
                started = True
            if retry_delay:
                time.sleep(retry_delay)
    raise ConnectionError("无法连接后台服务") from last_error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="m3u8-client", description="M3U8 下载任务客户端")
    subcommands = parser.add_subparsers(dest="command", required=True)
    submit = subcommands.add_parser("submit", help="添加下载任务")
    submit.add_argument("url")
    submit.add_argument("name", help="任务名，同时作为最终 MP4 文件名")
    submit.add_argument("--save-dir", default=str(Path.cwd()))
    submit.add_argument("--overwrite", action="store_true")
    subcommands.add_parser("list", help="列出任务")
    for command in ("pause", "resume", "cancel", "retry"):
        action = subcommands.add_parser(command)
        action.add_argument("task_id")
    subcommands.add_parser("interactive", help="交互添加任务")
    return parser


def _interactive(client: Any, console: Console, input_fn: Callable[[str], str]) -> int:
    url = input_fn("请输入 M3U8 地址: ").strip()
    if not url:
        console.print("[red]M3U8 地址不能为空[/red]")
        return 2
    name = ""
    while not name:
        name = input_fn("请输入任务名称（将作为输出文件名）: ").strip()
        if not name:
            console.print("[yellow]任务名称不能为空，请重新输入。[/yellow]")
    save_root = input_fn(f"请输入保存目录（默认 {Path.cwd()}）: ").strip() or str(Path.cwd())
    overwrite = input_fn("若文件已存在是否覆盖？[y/N]: ").strip().lower() in {"y", "yes"}
    result = client.request(
        "submit",
        {"url": url, "task_name": name, "save_root": save_root, "overwrite": overwrite},
    )
    console.print(f"已添加任务：{result['tasks'][0]['task_id']}")
    return 0


def client_main(
    argv: Sequence[str] | None = None,
    *,
    client: Any | None = None,
    console: Console | None = None,
    input_fn: Callable[[str], str] = input,
) -> int:
    args = _parser().parse_args(argv)
    console = console or Console()
    client = client or _default_client()
    try:
        if args.command == "interactive":
            return _interactive(client, console, input_fn)
        if args.command == "submit":
            result = client.request(
                "submit",
                {
                    "url": args.url,
                    "task_name": args.name,
                    "save_root": args.save_dir,
                    "overwrite": args.overwrite,
                },
            )
            console.print(f"已添加任务：{result['tasks'][0]['task_id']}")
            return 0
        if args.command == "list":
            render_tasks(console, client.request("list", {})["tasks"])
            return 0
        result = client.request(args.command, {"task_id": args.task_id})
        console.print(f"任务状态：{result['task']['state']}")
        return 0
    except (ServiceError, OSError, EOFError, ConnectionError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 3
    except (ValueError, KeyError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 2


def service_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m3u8-service")
    parser.add_argument("--host", default=DEFAULT_ADDRESS[0])
    parser.add_argument("--port", type=int, default=DEFAULT_ADDRESS[1])
    args = parser.parse_args(argv)
    paths = _default_paths()
    try:
        instance_lock = ServiceInstanceLock(paths.data_dir / "service.lock")
    except ServiceAlreadyRunning:
        return 0
    repository = None
    manager = None
    try:
        repository = TaskRepository(paths.data_dir / "tasks.sqlite3")
        manager = TaskManager(repository, paths.cache_dir / "workspaces")
        server = ServiceServer(
            manager,
            authkey=load_or_create_auth_key(paths.config_dir / "service.key"),
            address=(args.host, args.port),
            instance_lock=instance_lock,
        )
    except BaseException:
        instance_lock.close()
        if manager is not None:
            manager.shutdown(timeout=0)
        if repository is not None:
            repository.close()
        raise
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop_accepting()
        try:
            manager.shutdown()
        finally:
            try:
                repository.close()
            finally:
                server.release_instance_lock()
    return 0


def spawn_service() -> None:
    subprocess.Popen(
        service_command(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def service_command(*, frozen: bool | None = None) -> list[str]:
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False) or "__compiled__" in globals())
    if frozen:
        return [sys.executable, "--service"]
    return [sys.executable, "-m", "m3u8_downloader.cli", "service"]


if __name__ == "__main__":
    raise SystemExit(service_main(sys.argv[2:]) if sys.argv[1:2] == ["service"] else client_main())
