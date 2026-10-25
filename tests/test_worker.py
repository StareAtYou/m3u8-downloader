from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from m3u8_downloader.models import OverwritePolicy, TaskState
from m3u8_downloader.network import NetworkRoute, RouteSelection
from m3u8_downloader.playlist import MediaSegment, ParsedPlaylist
from m3u8_downloader.segments import SegmentDownloadError, SegmentResult, TaskCanceled, TaskControl
from m3u8_downloader.worker import (
    DownloadTaskSpec,
    WorkerDependencies,
    run_download_task,
)


class EventQueue:
    def __init__(self) -> None:
        self.items = []

    def put(self, item) -> None:
        self.items.append(item)


class Selector:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def select(self, url: str) -> RouteSelection:
        if self.error:
            raise self.error
        return RouteSelection(NetworkRoute.direct(), b"manifest", 0.01)


class Client:
    def close(self) -> None:
        pass

    def get(self, url: str):
        return SimpleNamespace(content=b"manifest", raise_for_status=lambda: None, close=lambda: None)


class Parser:
    def __init__(self, parsed: ParsedPlaylist | None = None, error: Exception | None = None) -> None:
        self.parsed = parsed
        self.error = error

    def parse(self, url, content, fetch):
        if self.error:
            raise self.error
        return self.parsed


class Downloader:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def download_all(self, playlist, workspace, control, progress):
        if self.error:
            raise self.error
        results = []
        for item in playlist.segments:
            path = Path(workspace) / item.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"ts")
            result = SegmentResult(item, path, 2, False)
            progress(result)
            results.append(result)
        return tuple(results)


class Merger:
    def __init__(self, before_state=None) -> None:
        self.called = False
        self.before_state = before_state

    def merge(self, workspace, segments, final_path, merge_lock, on_state, **kwargs):
        self.called = True
        for state in (TaskState.WAITING_MERGE, TaskState.MERGING):
            if self.before_state:
                self.before_state(state)
            on_state(state)
            if state is TaskState.WAITING_MERGE and kwargs.get("control").paused:
                from m3u8_downloader.segments import TaskPaused

                raise TaskPaused("paused")
        Path(final_path).parent.mkdir(parents=True, exist_ok=True)
        Path(final_path).write_bytes(b"video")
        return SimpleNamespace(bytes_written=5)


@dataclass
class Lock:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def parsed_playlist() -> ParsedPlaylist:
    item = MediaSegment(0, 0, "https://media.example/seg.ts?token=hidden", "000000.ts", None, None, 1)
    return ParsedPlaylist("https://media.example/a.m3u8", 0, (item,), True, 1)


def spec(tmp_path: Path) -> DownloadTaskSpec:
    return DownloadTaskSpec(
        task_id="task-1",
        url="https://media.example/a.m3u8?token=hidden",
        workspace=str(tmp_path / "work"),
        final_path=str(tmp_path / "movie.mp4"),
        overwrite_policy=OverwritePolicy.REJECT,
        segment_workers=2,
        ffmpeg_path="ffmpeg",
    )


def deps(*, selector=None, parser=None, downloader=None, merger=None) -> WorkerDependencies:
    return WorkerDependencies(
        selector=selector or Selector(),
        client_factory=lambda _: Client(),
        parser=parser or Parser(parsed_playlist()),
        downloader_factory=lambda *_: downloader or Downloader(),
        merger=merger or Merger(),
    )


def states(queue: EventQueue) -> list[TaskState]:
    return [item.state for item in queue.items]


def test_successful_worker_event_order_and_cleanup(tmp_path: Path) -> None:
    queue = EventQueue()
    task_spec = spec(tmp_path)

    run_download_task(task_spec, queue, TaskControl(), Lock(), dependencies=deps())

    assert states(queue) == [
        TaskState.PROBING,
        TaskState.PARSING,
        TaskState.DOWNLOADING,
        TaskState.DOWNLOADING,
        TaskState.WAITING_MERGE,
        TaskState.MERGING,
        TaskState.COMPLETED,
    ]
    assert not Path(task_spec.workspace).exists()
    assert Path(task_spec.final_path).read_bytes() == b"video"


@pytest.mark.parametrize(
    "dependencies",
    [
        deps(selector=Selector(RuntimeError("network token=hidden"))),
        deps(parser=Parser(error=ValueError("parse token=hidden"))),
        deps(downloader=Downloader(SegmentDownloadError("segment token=hidden"))),
    ],
)
def test_failures_never_merge_or_leak_signed_queries_and_keep_workspace(
    tmp_path: Path, dependencies: WorkerDependencies
) -> None:
    queue = EventQueue()
    task_spec = spec(tmp_path)
    Path(task_spec.workspace).mkdir(parents=True)

    run_download_task(task_spec, queue, TaskControl(), Lock(), dependencies=dependencies)

    assert states(queue)[-1] == TaskState.FAILED
    assert dependencies.merger.called is False
    assert Path(task_spec.workspace).exists()
    rendered = repr([event.payload for event in queue.items])
    assert "hidden" not in rendered
    assert "media.example" not in rendered


def test_cancel_cleans_workspace_but_pause_keeps_it(tmp_path: Path) -> None:
    canceled_queue = EventQueue()
    canceled_spec = spec(tmp_path / "cancel")
    Path(canceled_spec.workspace).mkdir(parents=True)
    run_download_task(
        canceled_spec,
        canceled_queue,
        TaskControl(),
        Lock(),
        dependencies=deps(downloader=Downloader(TaskCanceled("stop"))),
    )
    assert states(canceled_queue)[-2:] == [TaskState.CANCELING, TaskState.CANCELED]
    assert not Path(canceled_spec.workspace).exists()

    paused_queue = EventQueue()
    paused_spec = spec(tmp_path / "pause")
    control = TaskControl()
    control.request_pause()
    run_download_task(paused_spec, paused_queue, control, Lock(), dependencies=deps())
    assert states(paused_queue)[-1] == TaskState.PAUSED
    assert Path(paused_spec.workspace).exists()


def test_waiting_merge_pause_exits_queue_immediately(tmp_path: Path) -> None:
    queue = EventQueue()
    control = TaskControl()
    merger = Merger(before_state=lambda state: control.request_pause() if state == TaskState.WAITING_MERGE else None)
    task_spec = spec(tmp_path)

    run_download_task(task_spec, queue, control, Lock(), dependencies=deps(merger=merger))

    assert states(queue)[-2:] == [TaskState.WAITING_MERGE, TaskState.PAUSED]
    assert not Path(task_spec.final_path).exists()
    assert Path(task_spec.workspace).exists()


def test_pause_during_merging_is_rejected_and_merge_completes(tmp_path: Path) -> None:
    queue = EventQueue()
    control = TaskControl()
    merger = Merger(before_state=lambda state: control.request_pause() if state == TaskState.MERGING else None)

    run_download_task(spec(tmp_path), queue, control, Lock(), dependencies=deps(merger=merger))

    assert states(queue)[-2:] == [TaskState.MERGING, TaskState.COMPLETED]
    merging = next(event for event in queue.items if event.state == TaskState.MERGING)
    assert merging.payload["pause_rejected"] is True
    assert control.paused is False
