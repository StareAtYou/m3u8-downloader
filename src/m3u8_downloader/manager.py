from __future__ import annotations

import multiprocessing
import os
import queue
import shutil
import sqlite3
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .models import AppSettings, OverwritePolicy, TaskSnapshot, TaskState
from .naming import build_output_paths
from .storage import TaskRepository
from .worker import DownloadTaskSpec, WorkerEvent, run_download_task


@dataclass(frozen=True, slots=True)
class Submission:
    url: str
    task_name: str
    save_root: Path | str
    overwrite: bool = False


@dataclass(slots=True)
class _RunningTask:
    process: Any
    control: Any
    paused_exit_expected: bool = False
    resume_after_pause: bool = False


class ProcessTaskControl:
    """Minimal spawn-safe cooperative control used between service and workers."""

    exit_on_pause = True

    def __init__(self, context: Any) -> None:
        self._paused = context.Event()
        self._canceled = context.Event()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def canceled(self) -> bool:
        return self._canceled.is_set()

    def request_pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def request_cancel(self) -> None:
        self._canceled.set()
        self._paused.clear()

    def wait_if_paused(self) -> None:
        while self._paused.is_set() and not self._canceled.is_set():
            self._canceled.wait(0.05)
        if self._canceled.is_set():
            from .segments import TaskCanceled

            raise TaskCanceled("任务已取消")

    @contextmanager
    def work_unit(self):
        if self._canceled.is_set():
            from .segments import TaskCanceled

            raise TaskCanceled("任务已取消")
        if self._paused.is_set():
            from .segments import TaskPaused

            raise TaskPaused("任务已暂停")
        yield


class TaskManager:
    def __init__(
        self,
        repository: TaskRepository,
        workspace_root: Path,
        *,
        process_launcher: Callable[[DownloadTaskSpec, Any, Any, Any], Any] | None = None,
        event_queue: Any | None = None,
        merge_lock: Any | None = None,
        process_context: Any | None = None,
        auto_schedule: bool = True,
    ) -> None:
        self.repository = repository
        self.workspace_root = Path(workspace_root)
        self._context = process_context or multiprocessing.get_context("spawn")
        self.event_queue = event_queue or self._context.Queue()
        self.merge_lock = merge_lock or self._context.Lock()
        self._process_launcher = process_launcher or self._launch_process
        self._auto_schedule = auto_schedule
        self._lock = threading.RLock()
        self._running: dict[str, _RunningTask] = {}
        self.controls: dict[str, Any] = {}
        self._closed = False
        self.repository.recover_interrupted()

    def _launch_process(self, spec: DownloadTaskSpec, event_queue: Any, control: Any, merge_lock: Any):
        return self._context.Process(
            target=run_download_task,
            args=(spec, event_queue, control, merge_lock),
            daemon=True,
            name=f"m3u8-{spec.task_id[:8]}",
        )

    @staticmethod
    def _validate_url(url: str) -> str:
        value = str(url).strip()
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("M3U8 地址必须是有效的 HTTP 或 HTTPS URL")
        return value

    def _prepare_submission(self, submission: Submission) -> dict[str, Any]:
        url = self._validate_url(submission.url)
        root = Path(submission.save_root).expanduser().resolve()
        if not root.is_dir() or not os.access(root, os.W_OK):
            raise ValueError("保存目录不存在或不可写")
        paths = build_output_paths(root, submission.task_name)
        if paths.final_path.exists() and not submission.overwrite:
            raise FileExistsError(f"目标文件已存在: {paths.final_path.name}")
        task_id = str(uuid.uuid4())
        return {
            "task_id": task_id,
            "url": url,
            "task_name": paths.task_name,
            "filename": paths.final_path.name,
            "save_root": str(root),
            "workspace": str(self.workspace_root / task_id),
            "final_path": str(paths.final_path),
            "overwrite_policy": OverwritePolicy.OVERWRITE if submission.overwrite else OverwritePolicy.REJECT,
        }

    @staticmethod
    def _reservation_key(path: str | Path) -> str:
        return unicodedata.normalize("NFC", os.path.realpath(os.fspath(path))).casefold()

    def _validate_output_reservations(
        self,
        prepared: list[dict[str, Any]],
        *,
        exclude_task_ids: frozenset[str] = frozenset(),
    ) -> None:
        keys = [self._reservation_key(item["final_path"]) for item in prepared]
        if len(keys) != len(set(keys)):
            raise ValueError("批量任务包含重复输出路径")
        active = {
            self._reservation_key(item.final_path)
            for item in self.repository.list_snapshots()
            if item.task_id not in exclude_task_ids
            and item.state not in {TaskState.COMPLETED, TaskState.CANCELED, TaskState.FAILED}
        }
        if active.intersection(keys):
            raise ValueError("输出路径已被另一个活动任务占用")

    def submit(
        self,
        url: str,
        task_name: str,
        save_root: Path | str,
        *,
        overwrite: bool = False,
    ) -> TaskSnapshot:
        return self.submit_batch([Submission(url, task_name, save_root, overwrite)])[0]

    def submit_batch(self, submissions: Iterable[Submission | Mapping[str, Any]]) -> list[TaskSnapshot]:
        values = [item if isinstance(item, Submission) else Submission(**item) for item in submissions]
        if not values:
            raise ValueError("批量任务不能为空")
        with self._lock:
            records = self._create_batch_locked(values)
            if self._auto_schedule:
                self._schedule_locked()
            return [record.to_snapshot() for record in records]

    def submit_batch_idempotent(
        self,
        submissions: Iterable[Submission | Mapping[str, Any]],
        *,
        client_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        values = [item if isinstance(item, Submission) else Submission(**item) for item in submissions]
        if not values:
            raise ValueError("批量任务不能为空")
        with self._lock:
            existing = self.repository.recall_request(client_id, request_id)
            if existing is not None:
                return existing
            prepared = [self._prepare_submission(item) for item in values]
            self._validate_output_reservations(prepared)
            try:
                with self.repository.transaction():
                    records = [self.repository.create_task(**item) for item in prepared]
                    response = {"tasks": [record.to_snapshot().to_dict() for record in records]}
                    self.repository.remember_request(client_id, request_id, response)
            except sqlite3.IntegrityError as exc:
                raise ValueError("输出路径已被另一个活动任务占用") from exc
            if self._auto_schedule:
                self._schedule_locked()
            return response

    def _create_batch_locked(self, values: list[Submission]) -> list[Any]:
        prepared = [self._prepare_submission(item) for item in values]
        self._validate_output_reservations(prepared)
        try:
            with self.repository.transaction():
                return [self.repository.create_task(**item) for item in prepared]
        except sqlite3.IntegrityError as exc:
            raise ValueError("输出路径已被另一个活动任务占用") from exc

    def list(self) -> list[TaskSnapshot]:
        with self._lock:
            return self.repository.list_snapshots()

    def get(self, task_id: str) -> TaskSnapshot:
        with self._lock:
            return self.repository.get_snapshot(task_id)

    def pause(self, task_id: str) -> TaskSnapshot:
        with self._lock:
            record = self.repository.get_private(task_id)
            if record.state is TaskState.MERGING:
                raise ValueError("任务正在合并，不能暂停")
            if record.state is TaskState.QUEUED and task_id not in self._running:
                return self.repository.update_state(task_id, TaskState.PAUSED).to_snapshot()
            if record.state not in {
                TaskState.QUEUED,
                TaskState.PROBING,
                TaskState.PARSING,
                TaskState.DOWNLOADING,
                TaskState.WAITING_MERGE,
            }:
                raise ValueError(f"当前状态不能暂停: {record.state.value}")
            self.repository.set_pause_requested(task_id, True)
            control = self.controls.get(task_id)
            if control is None:
                raise RuntimeError("活动任务缺少进程控制句柄")
            self._running[task_id].resume_after_pause = False
            control.request_pause()
            if record.state is TaskState.QUEUED:
                return self.repository.update_state(task_id, TaskState.PAUSED).to_snapshot()
            return self.repository.get_snapshot(task_id)

    def pause_all(self) -> list[str]:
        paused = []
        for snapshot in self.list():
            if snapshot.state in {
                TaskState.QUEUED,
                TaskState.PROBING,
                TaskState.PARSING,
                TaskState.DOWNLOADING,
                TaskState.WAITING_MERGE,
            }:
                self.pause(snapshot.task_id)
                paused.append(snapshot.task_id)
        return paused

    def resume(self, task_id: str) -> TaskSnapshot:
        with self._lock:
            record = self.repository.get_private(task_id)
            if record.state is not TaskState.PAUSED:
                raise ValueError("只有暂停的任务可以继续")
            self.repository.set_pause_requested(task_id, False)
            running = self._running.get(task_id)
            if running is not None:
                running.control.resume()
                running.resume_after_pause = True
            result = self.repository.update_state(task_id, TaskState.QUEUED).to_snapshot()
            self._schedule_locked()
            return result

    def cancel(self, task_id: str) -> TaskSnapshot:
        with self._lock:
            record = self.repository.get_private(task_id)
            if record.state in {TaskState.COMPLETED, TaskState.CANCELED}:
                raise ValueError("任务已经结束")
            running = self._running.get(task_id)
            if running is not None:
                running.resume_after_pause = False
            if record.pause_requested:
                self.repository.set_pause_requested(task_id, False)
            if record.state is TaskState.PAUSED:
                if running is not None:
                    running.control.request_cancel()
                self.repository.update_state(task_id, TaskState.CANCELING)
                shutil.rmtree(record.workspace, ignore_errors=True)
                result = self.repository.update_state(task_id, TaskState.CANCELED).to_snapshot()
                self._schedule_locked()
                return result
            if running is None:
                self.repository.update_state(task_id, TaskState.CANCELING)
                shutil.rmtree(record.workspace, ignore_errors=True)
                result = self.repository.update_state(task_id, TaskState.CANCELED).to_snapshot()
                self._schedule_locked()
                return result
            self.repository.update_state(task_id, TaskState.CANCELING)
            running.control.request_cancel()
            return self.repository.get_snapshot(task_id)

    def retry(self, task_id: str) -> TaskSnapshot:
        with self._lock:
            record = self.repository.get_private(task_id)
            if record.state not in {TaskState.FAILED, TaskState.CANCELED, TaskState.INTERRUPTED}:
                raise ValueError("只有失败、取消或中断的任务可以重试")
            self._validate_output_reservations(
                [{"final_path": record.final_path}],
                exclude_task_ids=frozenset({task_id}),
            )
            result = self.repository.update_state(task_id, TaskState.QUEUED).to_snapshot()
            self._schedule_locked()
            return result

    def get_settings(self) -> AppSettings:
        with self._lock:
            return self.repository.get_settings()

    def update_settings(self, settings: AppSettings) -> AppSettings:
        with self._lock:
            settings.validate()
            self.repository.update_settings(settings)
            self._schedule_locked()
            return settings

    def _make_spec(self, task_id: str) -> DownloadTaskSpec:
        record = self.repository.get_private(task_id)
        settings = self.repository.get_settings()
        return DownloadTaskSpec(
            task_id=record.task_id,
            url=record.url,
            workspace=record.workspace,
            final_path=record.final_path,
            overwrite_policy=record.overwrite_policy,
            segment_workers=settings.segment_threads,
            ffmpeg_path=settings.ffmpeg_path,
            proxy_policy=settings.proxy_policy,
            manual_proxy=settings.manual_proxy,
        )

    def _schedule_locked(self) -> None:
        if self._closed or not self._auto_schedule:
            return
        limit = self.repository.get_settings().max_active_tasks
        available = limit - len(self._running)
        if available <= 0:
            return
        queued = [
            item
            for item in self.repository.list_snapshots()
            if item.state is TaskState.QUEUED and item.task_id not in self._running
        ]
        for snapshot in queued[:available]:
            control = ProcessTaskControl(self._context)
            spec = self._make_spec(snapshot.task_id)
            process = self._process_launcher(spec, self.event_queue, control, self.merge_lock)
            self.controls[snapshot.task_id] = control
            self._running[snapshot.task_id] = _RunningTask(process, control)
            try:
                process.start()
            except Exception:  # noqa: BLE001 - convert process startup failures to task state
                self._running.pop(snapshot.task_id, None)
                self.controls.pop(snapshot.task_id, None)
                self.repository.update_state(snapshot.task_id, TaskState.FAILED, error="无法启动下载进程")

    def drain_worker_events(self) -> int:
        drained = 0
        with self._lock:
            while True:
                try:
                    event = self.event_queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(event, Mapping):
                    event = WorkerEvent(
                        task_id=str(event["task_id"]),
                        state=TaskState(event["state"]),
                        payload=dict(event.get("payload", {})),
                    )
                try:
                    current = self.repository.get_snapshot(event.task_id).state
                except KeyError:
                    drained += 1
                    continue
                if (
                    current in {TaskState.COMPLETED, TaskState.CANCELED, TaskState.FAILED}
                    and event.state is not current
                ):
                    drained += 1
                    continue
                if current is TaskState.CANCELING and event.state not in {
                    TaskState.CANCELING,
                    TaskState.CANCELED,
                    TaskState.FAILED,
                }:
                    drained += 1
                    continue
                if current is TaskState.PAUSED and event.state is not TaskState.PAUSED:
                    drained += 1
                    continue
                running = self._running.get(event.task_id)
                if event.state is TaskState.PAUSED and running is not None and running.resume_after_pause:
                    try:
                        self.repository.apply_worker_event(event.task_id, event.state, event.payload)
                        self.repository.set_pause_requested(event.task_id, False)
                        self.repository.update_state(event.task_id, TaskState.QUEUED)
                    except ValueError:
                        drained += 1
                        continue
                    running.paused_exit_expected = True
                    drained += 1
                    continue
                try:
                    self.repository.apply_worker_event(event.task_id, event.state, event.payload)
                except ValueError:
                    drained += 1
                    continue
                if event.payload.get("pause_rejected") or event.state in {
                    TaskState.COMPLETED,
                    TaskState.CANCELED,
                    TaskState.FAILED,
                }:
                    self.repository.set_pause_requested(event.task_id, False)
                if event.state is TaskState.PAUSED and event.task_id in self._running:
                    self._running[event.task_id].paused_exit_expected = True
                drained += 1
            self._reap_locked()
            self._schedule_locked()
        return drained

    def _reap_locked(self) -> None:
        for task_id, running in tuple(self._running.items()):
            if running.process.is_alive():
                continue
            running.process.join(timeout=0)
            state = self.repository.get_snapshot(task_id).state
            if running.paused_exit_expected and state in {TaskState.PAUSED, TaskState.QUEUED}:
                pass
            elif state not in {
                TaskState.COMPLETED,
                TaskState.CANCELED,
                TaskState.FAILED,
                TaskState.PAUSED,
            }:
                if state is TaskState.CANCELING:
                    self.repository.update_state(task_id, TaskState.CANCELED)
                else:
                    self.repository.update_state(task_id, TaskState.FAILED, error="下载进程意外退出")
            self._running.pop(task_id, None)
            self.controls.pop(task_id, None)

    def shutdown(self, *, timeout: float = 5.0) -> None:
        with self._lock:
            self._closed = True
            running = list(self._running.values())
        deadline = time.monotonic() + max(0, timeout)
        for item in running:
            item.process.join(timeout=max(0, deadline - time.monotonic()))
        for item in running:
            if item.process.is_alive():
                item.process.terminate()
                item.process.join(timeout=0.2)
        with self._lock:
            self.repository.recover_interrupted()
            self._running.clear()
            self.controls.clear()
