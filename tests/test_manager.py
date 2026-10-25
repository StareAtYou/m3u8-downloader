from __future__ import annotations

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from m3u8_downloader.manager import Submission, TaskManager
from m3u8_downloader.models import AppSettings, TaskState
from m3u8_downloader.storage import TaskRepository
from m3u8_downloader.worker import WorkerEvent


class FakeProcess:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.started = False
        self.alive = False
        self.exitcode = None
        self.terminated = False

    def start(self) -> None:
        self.started = True
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout=None) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True
        self.alive = False
        self.exitcode = -15


class Launcher:
    def __init__(self) -> None:
        self.processes: list[FakeProcess] = []
        self.specs = []

    def __call__(self, spec, event_queue, control, merge_lock) -> FakeProcess:
        self.specs.append(spec)
        process = FakeProcess(spec.task_id)
        self.processes.append(process)
        return process


def manager(tmp_path: Path, *, max_active: int = 3):
    repository = TaskRepository(tmp_path / "state.sqlite3")
    repository.update_settings(AppSettings(default_save_dir=str(tmp_path), max_active_tasks=max_active))
    launcher = Launcher()
    events = queue.Queue()
    instance = TaskManager(
        repository,
        tmp_path / "workspaces",
        process_launcher=launcher,
        event_queue=events,
        merge_lock=threading.Lock(),
    )
    return instance, repository, launcher, events


def test_submission_validates_name_url_path_and_explicit_overwrite(tmp_path: Path) -> None:
    instance, _, _, _ = manager(tmp_path)
    with pytest.raises(ValueError):
        instance.submit("ftp://example/a.m3u8", "Movie", tmp_path)
    with pytest.raises(ValueError):
        instance.submit("https://example/a.m3u8", "***", tmp_path)
    missing = tmp_path / "missing"
    with pytest.raises(ValueError):
        instance.submit("https://example/a.m3u8", "Movie", missing)

    final = tmp_path / "Movie" / "Movie.mp4"
    final.parent.mkdir()
    final.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        instance.submit("https://example/a.m3u8", "Movie", tmp_path)

    created = instance.submit("https://example/a.m3u8", "Movie", tmp_path, overwrite=True)
    assert created.final_path == str(final)
    assert created.filename == "Movie.mp4"


def test_workspace_is_stable_uuid_and_same_names_do_not_share_it(tmp_path: Path) -> None:
    instance, repository, _, _ = manager(tmp_path)
    first = instance.submit("https://example/1.m3u8", "One", tmp_path)
    repository.update_state(first.task_id, TaskState.FAILED)
    second = instance.submit("https://example/2.m3u8", "One", tmp_path)

    assert Path(first.workspace).name == first.task_id
    assert Path(second.workspace).name == second.task_id
    assert first.workspace != second.workspace


def test_batch_is_atomic_and_duplicate_output_writes_nothing(tmp_path: Path) -> None:
    instance, _, _, _ = manager(tmp_path)
    batch = [
        Submission("https://example/1.m3u8", "Same", tmp_path),
        Submission("https://example/2.m3u8", "Same", tmp_path),
    ]
    with pytest.raises(ValueError):
        instance.submit_batch(batch)
    assert instance.list() == []


def test_concurrent_single_and_batch_same_output_have_one_reservation_winner(
    tmp_path: Path,
) -> None:
    instance, _, _, _ = manager(tmp_path)
    barrier = threading.Barrier(2)

    def single():
        barrier.wait()
        return instance.submit("https://example/1.m3u8", "Race", tmp_path)

    def batch():
        barrier.wait()
        return instance.submit_batch([Submission("https://example/2.m3u8", "Race", tmp_path)])

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(single), pool.submit(batch)]
    successes = 0
    failures = 0
    for future in futures:
        try:
            future.result()
            successes += 1
        except ValueError:
            failures += 1
    assert (successes, failures) == (1, 1)
    assert len(instance.list()) == 1


def _put_success(events, task_id: str) -> None:
    for state in (
        TaskState.PROBING,
        TaskState.PARSING,
        TaskState.DOWNLOADING,
        TaskState.WAITING_MERGE,
        TaskState.MERGING,
        TaskState.COMPLETED,
    ):
        events.put(WorkerEvent(task_id, state, {}))


def test_scheduler_enforces_limit_drains_events_and_reaps_processes(tmp_path: Path) -> None:
    instance, repository, launcher, events = manager(tmp_path, max_active=2)
    tasks = [instance.submit(f"https://example/{index}.m3u8", f"Task {index}", tmp_path) for index in range(3)]
    assert len(launcher.processes) == 2

    _put_success(events, tasks[0].task_id)
    launcher.processes[0].alive = False
    launcher.processes[0].exitcode = 0
    instance.drain_worker_events()

    assert repository.get_snapshot(tasks[0].task_id).state == TaskState.COMPLETED
    assert len(launcher.processes) == 3

    launcher.processes[1].alive = False
    launcher.processes[1].exitcode = 2
    instance.drain_worker_events()
    assert repository.get_snapshot(tasks[1].task_id).state == TaskState.FAILED


def test_control_commands_settings_restart_and_bounded_shutdown(tmp_path: Path) -> None:
    instance, repository, launcher, events = manager(tmp_path, max_active=1)
    first = instance.submit("https://example/1.m3u8", "First", tmp_path)
    second = instance.submit("https://example/2.m3u8", "Second", tmp_path)

    instance.pause(second.task_id)
    assert repository.get_snapshot(second.task_id).state == TaskState.PAUSED
    instance.resume(second.task_id)
    assert repository.get_snapshot(second.task_id).state == TaskState.QUEUED
    instance.cancel(second.task_id)
    assert repository.get_snapshot(second.task_id).state == TaskState.CANCELED
    instance.retry(second.task_id)
    assert repository.get_snapshot(second.task_id).state == TaskState.QUEUED

    events.put(WorkerEvent(first.task_id, TaskState.PROBING, {}))
    events.put(WorkerEvent(first.task_id, TaskState.PARSING, {}))
    events.put(WorkerEvent(first.task_id, TaskState.DOWNLOADING, {"completed": 1, "total": 3}))
    instance.drain_worker_events()
    instance.pause(first.task_id)
    assert instance.controls[first.task_id].paused is True

    updated = AppSettings(default_save_dir=str(tmp_path), max_active_tasks=2, segment_threads=8)
    instance.update_settings(updated)
    assert instance.get_settings() == updated
    with pytest.raises(ValueError):
        instance.update_settings(AppSettings(max_active_tasks=0))

    instance.shutdown(timeout=0.01)
    assert launcher.processes[0].terminated is True
    assert repository.get_snapshot(first.task_id).state == TaskState.INTERRUPTED

    restarted = TaskManager(repository, tmp_path / "workspaces", auto_schedule=False)
    assert restarted.list()[0].state in {TaskState.INTERRUPTED, TaskState.QUEUED}


def test_worker_spec_receives_explicit_proxy_policy(tmp_path: Path) -> None:
    instance, repository, launcher, _ = manager(tmp_path)
    repository.update_settings(AppSettings(proxy_policy="manual", manual_proxy="socks5://127.0.0.1:7890"))

    instance.submit("https://example/1.m3u8", "Proxy", tmp_path)

    assert launcher.specs[-1].proxy_policy == "manual"
    assert launcher.specs[-1].manual_proxy == "socks5://127.0.0.1:7890"


def test_disabled_auto_schedule_stays_disabled_after_resume(tmp_path: Path) -> None:
    repository = TaskRepository(tmp_path / "state.sqlite3")
    launcher = Launcher()
    instance = TaskManager(
        repository,
        tmp_path / "workspaces",
        process_launcher=launcher,
        event_queue=queue.Queue(),
        merge_lock=threading.Lock(),
        auto_schedule=False,
    )
    task = instance.submit("https://example/1.m3u8", "Manual", tmp_path)

    instance.pause(task.task_id)
    instance.resume(task.task_id)

    assert launcher.processes == []
    assert instance.get(task.task_id).state is TaskState.QUEUED


def test_pause_all_skips_merging_and_part_files_do_not_count_as_completed(tmp_path: Path) -> None:
    instance, repository, _, events = manager(tmp_path, max_active=2)
    first = instance.submit("https://example/1.m3u8", "First", tmp_path)
    second = instance.submit("https://example/2.m3u8", "Second", tmp_path)
    for state in (
        TaskState.PROBING,
        TaskState.PARSING,
        TaskState.DOWNLOADING,
        TaskState.WAITING_MERGE,
        TaskState.MERGING,
    ):
        events.put(WorkerEvent(first.task_id, state, {}))
    for state in (TaskState.PROBING, TaskState.PARSING, TaskState.DOWNLOADING):
        events.put(WorkerEvent(second.task_id, state, {}))
    instance.drain_worker_events()

    paused = instance.pause_all()
    assert first.task_id not in paused
    assert second.task_id in paused
    workspace = Path(repository.get_private(second.task_id).workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    workspace.joinpath("000000.ts.part").write_bytes(b"partial")
    assert repository.get_snapshot(second.task_id).completed == 0


def test_cancel_ignores_in_flight_progress_and_monitor_can_process_later_events(tmp_path: Path) -> None:
    instance, repository, launcher, events = manager(tmp_path, max_active=2)
    first = instance.submit("https://example/1.m3u8", "First", tmp_path)
    second = instance.submit("https://example/2.m3u8", "Second", tmp_path)
    events.put(WorkerEvent(first.task_id, TaskState.PROBING, {}))
    events.put(WorkerEvent(first.task_id, TaskState.PARSING, {}))
    events.put(WorkerEvent(first.task_id, TaskState.DOWNLOADING, {}))
    instance.drain_worker_events()

    instance.cancel(first.task_id)
    events.put(WorkerEvent(first.task_id, TaskState.DOWNLOADING, {"completed": 2, "total": 3}))
    events.put(WorkerEvent(first.task_id, TaskState.CANCELING, {}))
    events.put(WorkerEvent(first.task_id, TaskState.CANCELED, {}))
    events.put(WorkerEvent(second.task_id, TaskState.PROBING, {}))
    instance.drain_worker_events()

    assert repository.get_snapshot(first.task_id).state is TaskState.CANCELED
    assert repository.get_snapshot(second.task_id).state is TaskState.PROBING
    launcher.processes[0].alive = False


def test_pause_dispatched_queued_task_signals_worker_and_ignores_startup_events(tmp_path: Path) -> None:
    instance, repository, _, events = manager(tmp_path, max_active=1)
    task = instance.submit("https://example/1.m3u8", "First", tmp_path)

    instance.pause(task.task_id)
    assert instance.controls[task.task_id].paused is True
    events.put(WorkerEvent(task.task_id, TaskState.PROBING, {}))
    events.put(WorkerEvent(task.task_id, TaskState.PAUSED, {}))
    instance.drain_worker_events()

    assert repository.get_snapshot(task.task_id).state is TaskState.PAUSED


def test_resume_wins_over_delayed_pause_acknowledgement(tmp_path: Path) -> None:
    instance, repository, launcher, events = manager(tmp_path, max_active=1)
    task = instance.submit("https://example/1.m3u8", "First", tmp_path)

    instance.pause(task.task_id)
    instance.resume(task.task_id)
    events.put(WorkerEvent(task.task_id, TaskState.PROBING, {}))
    events.put(WorkerEvent(task.task_id, TaskState.PARSING, {}))
    events.put(WorkerEvent(task.task_id, TaskState.PAUSED, {}))
    launcher.processes[0].alive = False
    launcher.processes[0].exitcode = 0
    instance.drain_worker_events()

    assert repository.get_snapshot(task.task_id).state is TaskState.QUEUED
    assert len(launcher.processes) == 2
    assert instance.controls[task.task_id].paused is False


def test_pause_rejected_at_merge_clears_persisted_request(tmp_path: Path) -> None:
    instance, repository, _, events = manager(tmp_path, max_active=1)
    task = instance.submit("https://example/1.m3u8", "First", tmp_path)
    for state in (TaskState.PROBING, TaskState.PARSING, TaskState.DOWNLOADING, TaskState.WAITING_MERGE):
        events.put(WorkerEvent(task.task_id, state, {}))
    instance.drain_worker_events()
    instance.pause(task.task_id)
    assert repository.get_snapshot(task.task_id).pause_requested is True

    events.put(WorkerEvent(task.task_id, TaskState.MERGING, {"pause_rejected": True}))
    instance.drain_worker_events()

    assert repository.get_snapshot(task.task_id).pause_requested is False


def test_case_equivalent_output_names_share_one_reservation(tmp_path: Path) -> None:
    instance, _, _, _ = manager(tmp_path)
    instance.submit("https://example/1.m3u8", "Movie", tmp_path)

    with pytest.raises(ValueError, match="输出路径"):
        instance.submit("https://example/2.m3u8", "movie", tmp_path)


@pytest.mark.parametrize("terminal_state", [TaskState.FAILED, TaskState.CANCELED])
def test_retry_rechecks_case_equivalent_active_output_reservation(tmp_path: Path, terminal_state: TaskState) -> None:
    instance, _, launcher, events = manager(tmp_path, max_active=2)
    first = instance.submit("https://example/1.m3u8", "Movie", tmp_path)
    if terminal_state is TaskState.CANCELED:
        instance.cancel(first.task_id)
    events.put(WorkerEvent(first.task_id, terminal_state, {}))
    launcher.processes[0].alive = False
    launcher.processes[0].exitcode = 0
    instance.drain_worker_events()
    instance.submit("https://example/2.m3u8", "movie", tmp_path)

    with pytest.raises(ValueError, match="输出路径"):
        instance.retry(first.task_id)

    assert instance.get(first.task_id).state is terminal_state
