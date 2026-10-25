from __future__ import annotations

import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .merger import FfmpegMerger, MergeError
from .models import OverwritePolicy, TaskState
from .network import FailoverHttpClient, NetworkRoute, RouteSelector, parse_manual_proxy
from .playlist import PlaylistError, PlaylistParser
from .segments import SegmentDownloader, SegmentDownloadError, SegmentResult, TaskCanceled, TaskControl, TaskPaused


@dataclass(frozen=True, slots=True)
class DownloadTaskSpec:
    task_id: str
    url: str
    workspace: str
    final_path: str
    overwrite_policy: OverwritePolicy
    segment_workers: int
    ffmpeg_path: str
    proxy_policy: str = "auto"
    manual_proxy: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerEvent:
    task_id: str
    state: TaskState
    payload: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "state": self.state.value, "payload": dict(self.payload)}


@dataclass(slots=True)
class WorkerDependencies:
    selector: Any
    client_factory: Callable[[Any], Any]
    parser: Any
    downloader_factory: Callable[[Any, int], Any]
    merger: Any


class _WorkerPaused(RuntimeError):
    pass


def _default_dependencies(spec: DownloadTaskSpec) -> WorkerDependencies:
    routes = None
    if spec.proxy_policy == "direct":
        routes = (NetworkRoute.direct(),)
    elif spec.proxy_policy == "manual":
        routes = (parse_manual_proxy(spec.manual_proxy or ""),)
    selector = RouteSelector(routes)
    return WorkerDependencies(
        selector=selector,
        client_factory=lambda route: FailoverHttpClient(selector, route),
        parser=PlaylistParser(),
        downloader_factory=lambda client, workers: SegmentDownloader(client, workers=workers),
        merger=FfmpegMerger(spec.ffmpeg_path),
    )


def _emit(
    event_queue: Any,
    spec: DownloadTaskSpec,
    state: TaskState,
    payload: Mapping[str, str | int | float | bool | None] | None = None,
) -> None:
    event_queue.put(WorkerEvent(spec.task_id, state, dict(payload or {})))


def run_download_task(
    spec: DownloadTaskSpec,
    event_queue: Any,
    control: TaskControl,
    merge_lock: Any,
    *,
    dependencies: WorkerDependencies | None = None,
) -> None:
    """Run one task without touching SQLite.

    This function is process-safe: inputs are plain dataclasses and all state
    changes are emitted to the owning service through ``event_queue``.
    """

    workspace = Path(spec.workspace)
    final_path = Path(spec.final_path)
    workspace.mkdir(parents=True, exist_ok=True)
    dependencies = dependencies or _default_dependencies(spec)
    client = None
    try:
        if final_path.exists() and spec.overwrite_policy is OverwritePolicy.REJECT:
            raise FileExistsError("目标文件已存在")
        if control.canceled:
            raise TaskCanceled("任务已取消")

        _emit(event_queue, spec, TaskState.PROBING)
        selection = dependencies.selector.select(spec.url)

        _emit(
            event_queue,
            spec,
            TaskState.PARSING,
            {"route": selection.route.display_name},
        )
        client = dependencies.client_factory(selection.route)

        def fetch_playlist(url: str) -> tuple[bytes, str]:
            response = client.get(url)
            try:
                response.raise_for_status()
                return bytes(response.content), str(getattr(response, "url", "") or url)
            finally:
                response.close()

        parsed = dependencies.parser.parse(
            selection.effective_url or spec.url,
            selection.manifest_bytes,
            fetch_playlist,
        )
        if control.paused:
            _emit(event_queue, spec, TaskState.PAUSED)
            return
        if control.canceled:
            raise TaskCanceled("任务已取消")

        completed = 0
        downloaded_bytes = 0
        download_started = time.monotonic()
        _emit(
            event_queue,
            spec,
            TaskState.DOWNLOADING,
            {"completed": completed, "total": len(parsed.segments)},
        )

        def progress(result: SegmentResult) -> None:
            nonlocal completed, downloaded_bytes
            completed += 1
            downloaded_bytes += result.bytes_written
            elapsed = max(time.monotonic() - download_started, 0.001)
            _emit(
                event_queue,
                spec,
                TaskState.DOWNLOADING,
                {
                    "completed": completed,
                    "total": len(parsed.segments),
                    "speed_bps": downloaded_bytes / elapsed,
                },
            )

        results = dependencies.downloader_factory(client, spec.segment_workers).download_all(
            parsed, workspace, control, progress
        )
        if len(results) != len(parsed.segments):
            raise RuntimeError("视频片段结果不完整")

        def merge_state(state: TaskState) -> None:
            if state is TaskState.WAITING_MERGE:
                _emit(event_queue, spec, state)
                return
            pause_rejected = control.paused
            if pause_rejected:
                control.resume()
            _emit(
                event_queue,
                spec,
                state,
                {"pause_rejected": pause_rejected},
            )

        merge_result = dependencies.merger.merge(
            workspace,
            (result.path for result in results),
            final_path,
            merge_lock,
            merge_state,
            control=control,
            overwrite_policy=spec.overwrite_policy,
        )
        shutil.rmtree(workspace, ignore_errors=True)
        _emit(
            event_queue,
            spec,
            TaskState.COMPLETED,
            {"bytes_written": int(merge_result.bytes_written)},
        )
    except (_WorkerPaused, TaskPaused):
        _emit(event_queue, spec, TaskState.PAUSED)
    except TaskCanceled:
        _emit(event_queue, spec, TaskState.CANCELING)
        shutil.rmtree(workspace, ignore_errors=True)
        _emit(event_queue, spec, TaskState.CANCELED)
    except Exception as exc:  # noqa: BLE001 - worker boundary converts failures into safe events
        _emit(
            event_queue,
            spec,
            TaskState.FAILED,
            {"error": _public_error(exc), "error_type": type(exc).__name__},
        )
    finally:
        if client is not None and hasattr(client, "close"):
            client.close()


def _public_error(exc: BaseException) -> str:
    if isinstance(exc, FileExistsError):
        return "目标文件已存在，请选择覆盖或修改任务名称"
    if isinstance(exc, (PlaylistError, SegmentDownloadError, MergeError)):
        detail = str(exc)[:500]
        lowered = detail.lower()
        if not any(value in lowered for value in ("http://", "https://", "token=", "secret", "password")):
            return detail
    return f"下载失败（{type(exc).__name__}）"
