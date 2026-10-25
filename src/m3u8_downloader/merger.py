from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import OverwritePolicy, TaskState
from .segments import TaskCanceled, TaskPaused


class MergeError(RuntimeError):
    def __init__(self, message: str, *, diagnostics: str = "") -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


@dataclass(frozen=True, slots=True)
class MergeResult:
    final_path: Path
    bytes_written: int
    diagnostics: str


def _concat_quote(path: Path) -> str:
    value = str(path.resolve())
    if "\n" in value or "\r" in value:
        raise MergeError("片段路径包含不支持的换行符")
    return "file '" + value.replace("'", "'\\''") + "'"


class FfmpegMerger:
    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        *,
        runner: Callable[..., Any] = subprocess.run,
        max_diagnostic_chars: int = 16_000,
    ) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.runner = runner
        self.max_diagnostic_chars = max_diagnostic_chars

    def merge(
        self,
        workspace: Path,
        segments: Iterable[Path],
        final_path: Path,
        merge_lock: Any,
        on_state: Callable[[TaskState], None],
        *,
        control: Any | None = None,
        overwrite_policy: OverwritePolicy = OverwritePolicy.OVERWRITE,
    ) -> MergeResult:
        workspace = Path(workspace)
        final_path = Path(final_path)
        ordered = tuple(Path(path) for path in segments)
        if not ordered:
            raise MergeError("没有可合并的视频片段")
        for path in ordered:
            if not path.is_file() or path.stat().st_size <= 0:
                raise MergeError(f"待合并片段无效: {path.name}")

        workspace.mkdir(parents=True, exist_ok=True)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = workspace / "concat.txt"
        manifest.write_text("\n".join(_concat_quote(path) for path in ordered) + "\n", encoding="utf-8")
        partial = final_path.with_name(f".{final_path.stem}.{uuid.uuid4().hex}.part{final_path.suffix or '.mp4'}")
        on_state(TaskState.WAITING_MERGE)
        diagnostics = ""
        acquired = False
        try:
            while not acquired:
                self._check_control(control, allow_pause=True)
                acquired = bool(merge_lock.acquire(timeout=0.05))
            self._check_control(control, allow_pause=True)
            on_state(TaskState.MERGING)
            command = [
                self.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "warning",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(manifest),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                "-y",
                str(partial),
            ]
            completed = self._run(command, control)
            diagnostics = str(completed.stderr or "")[-self.max_diagnostic_chars :]
            if completed.returncode != 0:
                raise MergeError("FFmpeg 合并失败", diagnostics=diagnostics)
            if not partial.is_file() or partial.stat().st_size <= 0:
                raise MergeError("FFmpeg 未生成有效的视频文件", diagnostics=diagnostics)
            self._check_control(control, allow_pause=False)
            if overwrite_policy is OverwritePolicy.REJECT:
                os.link(partial, final_path)
                partial.unlink()
            else:
                os.replace(partial, final_path)
        except (MergeError, FileExistsError, TaskCanceled, TaskPaused):
            partial.unlink(missing_ok=True)
            raise
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise MergeError("执行 FFmpeg 合并时发生错误", diagnostics=diagnostics) from exc
        finally:
            if acquired:
                merge_lock.release()
        return MergeResult(final_path, final_path.stat().st_size, diagnostics)

    @staticmethod
    def _check_control(control: Any | None, *, allow_pause: bool) -> None:
        if control is None:
            return
        if control.canceled:
            raise TaskCanceled("任务已取消")
        if allow_pause and control.paused:
            raise TaskPaused("任务已暂停")

    def _run(self, command: list[str], control: Any | None) -> Any:
        if self.runner is not subprocess.run:
            return self.runner(command, capture_output=True, text=True, check=False, shell=False)
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False)
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.1)
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if control is not None and control.canceled:
                    process.terminate()
                    try:
                        process.communicate(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    raise TaskCanceled("任务已取消")
