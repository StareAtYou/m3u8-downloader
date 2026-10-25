from __future__ import annotations

import multiprocessing
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from m3u8_downloader.merger import FfmpegMerger, MergeError
from m3u8_downloader.models import OverwritePolicy, TaskState
from m3u8_downloader.segments import TaskCanceled, TaskControl, TaskPaused


def make_segments(workspace: Path) -> tuple[Path, ...]:
    paths = (
        workspace / "000002.ts",
        workspace / "clip's 000000.ts",
        workspace / "000001.ts",
    )
    for index, path in enumerate(paths):
        path.write_bytes(bytes([index + 1]))
    return paths


def test_concat_manifest_preserves_given_order_and_escapes_apostrophe(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    segments = make_segments(workspace)
    captured = {}

    def runner(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        Path(args[-1]).write_bytes(b"video")
        return SimpleNamespace(returncode=0, stderr="diagnostic")

    states = []
    result = FfmpegMerger(runner=runner).merge(
        workspace, segments, tmp_path / "movie.mp4", multiprocessing.Lock(), states.append
    )

    manifest = (workspace / "concat.txt").read_text()
    lines = manifest.splitlines()
    assert "000002.ts" in lines[0]
    assert "clip'\\''s 000000.ts" in lines[1]
    assert "000001.ts" in lines[2]
    assert captured["kwargs"]["shell"] is False
    assert result.final_path.read_bytes() == b"video"
    assert result.diagnostics == "diagnostic"
    assert states == [TaskState.WAITING_MERGE, TaskState.MERGING]


def test_failure_preserves_existing_final_and_removes_unique_partial(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    segments = make_segments(workspace)
    final = tmp_path / "movie.mp4"
    final.write_bytes(b"existing")
    seen_output = None

    def runner(args, **_):
        nonlocal seen_output
        seen_output = Path(args[-1])
        seen_output.write_bytes(b"broken")
        return SimpleNamespace(returncode=1, stderr="x" * 20_000)

    with pytest.raises(MergeError) as caught:
        FfmpegMerger(runner=runner, max_diagnostic_chars=2000).merge(
            workspace, segments, final, multiprocessing.Lock(), lambda _: None
        )

    assert final.read_bytes() == b"existing"
    assert seen_output is not None and not seen_output.exists()
    assert seen_output.name.startswith(".movie.") and seen_output.name.endswith(".part.mp4")
    assert len(caught.value.diagnostics) == 2000


def test_success_requires_nonempty_output_and_lock_releases_after_exception(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    segments = make_segments(workspace)
    lock = multiprocessing.Lock()

    def runner(args, **_):
        Path(args[-1]).touch()
        raise RuntimeError("boom")

    with pytest.raises(MergeError):
        FfmpegMerger(runner=runner).merge(workspace, segments, tmp_path / "movie.mp4", lock, lambda _: None)
    assert lock.acquire(timeout=0.2)
    lock.release()


def _merge_process(workspace, final, lock, active, maximum) -> None:
    def runner(args, **_):
        with active.get_lock(), maximum.get_lock():
            active.value += 1
            maximum.value = max(maximum.value, active.value)
        time.sleep(0.08)
        Path(args[-1]).write_bytes(b"video")
        with active.get_lock():
            active.value -= 1
        return SimpleNamespace(returncode=0, stderr="")

    segment_path = Path(workspace) / "000000.ts"
    FfmpegMerger(runner=runner).merge(Path(workspace), (segment_path,), Path(final), lock, lambda _: None)


def test_process_shared_lock_allows_only_one_ffmpeg_at_a_time(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    lock = context.Lock()
    active = context.Value("i", 0)
    maximum = context.Value("i", 0)
    processes = []
    for index in range(2):
        workspace = tmp_path / f"work-{index}"
        workspace.mkdir()
        workspace.joinpath("000000.ts").write_bytes(b"ts")
        process = context.Process(
            target=_merge_process,
            args=(workspace, tmp_path / f"movie-{index}.mp4", lock, active, maximum),
        )
        process.start()
        processes.append(process)
    for process in processes:
        process.join(timeout=3)
        assert process.exitcode == 0
    assert maximum.value == 1


def test_pause_or_cancel_while_waiting_for_merge_lock_aborts_before_ffmpeg(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    segments = make_segments(workspace)
    lock = multiprocessing.Lock()
    assert lock.acquire(timeout=0.2)
    called = []
    control = TaskControl()
    control.request_pause()
    try:
        with pytest.raises(TaskPaused):
            FfmpegMerger(runner=lambda *_a, **_k: called.append(True)).merge(
                workspace, segments, tmp_path / "movie.mp4", lock, lambda _: None, control=control
            )
    finally:
        lock.release()
    assert called == []


def test_cancel_during_ffmpeg_preserves_existing_output(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    segments = make_segments(workspace)
    final = tmp_path / "movie.mp4"
    final.write_bytes(b"existing")
    control = TaskControl()

    def runner(args, **_):
        Path(args[-1]).write_bytes(b"new")
        control.request_cancel()
        return SimpleNamespace(returncode=0, stderr="")

    with pytest.raises(TaskCanceled):
        FfmpegMerger(runner=runner).merge(
            workspace,
            segments,
            final,
            multiprocessing.Lock(),
            lambda _: None,
            control=control,
            overwrite_policy=OverwritePolicy.OVERWRITE,
        )
    assert final.read_bytes() == b"existing"


def test_reject_policy_does_not_clobber_file_created_during_merge(tmp_path: Path) -> None:
    workspace = tmp_path / "work"
    workspace.mkdir()
    segments = make_segments(workspace)
    final = tmp_path / "movie.mp4"

    def runner(args, **_):
        Path(args[-1]).write_bytes(b"new")
        final.write_bytes(b"raced")
        return SimpleNamespace(returncode=0, stderr="")

    with pytest.raises(FileExistsError):
        FfmpegMerger(runner=runner).merge(
            workspace,
            segments,
            final,
            multiprocessing.Lock(),
            lambda _: None,
            overwrite_policy=OverwritePolicy.REJECT,
        )
    assert final.read_bytes() == b"raced"
