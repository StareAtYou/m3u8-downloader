from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Crypto.Cipher import AES

from .playlist import KeySpec, MediaSegment, ParsedPlaylist


class SegmentDownloadError(RuntimeError):
    pass


class TaskCanceled(RuntimeError):
    pass


class TaskPaused(RuntimeError):
    pass


class TaskControl:
    exit_on_pause = False

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._paused = False
        self._canceled = False
        self._active_work = 0

    @property
    def canceled(self) -> bool:
        with self._condition:
            return self._canceled

    @property
    def paused(self) -> bool:
        with self._condition:
            return self._paused

    def request_pause(self) -> None:
        with self._condition:
            self._paused = True
            while self._active_work:
                self._condition.wait()

    def resume(self) -> None:
        with self._condition:
            self._paused = False
            self._condition.notify_all()

    def request_cancel(self) -> None:
        with self._condition:
            self._canceled = True
            self._paused = False
            self._condition.notify_all()

    def wait_if_paused(self) -> None:
        with self._condition:
            while self._paused and not self._canceled:
                self._condition.wait()
            if self._canceled:
                raise TaskCanceled("任务已取消")

    @contextmanager
    def work_unit(self):
        with self._condition:
            while self._paused and not self._canceled:
                self._condition.wait()
            if self._canceled:
                raise TaskCanceled("任务已取消")
            self._active_work += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_work -= 1
                self._condition.notify_all()


@dataclass(frozen=True, slots=True)
class SegmentResult:
    segment: MediaSegment
    path: Path
    bytes_written: int
    resumed: bool


ProgressCallback = Callable[[SegmentResult], None]


class SegmentDownloader:
    def __init__(self, client: Any, *, workers: int = 16) -> None:
        if workers < 1:
            raise ValueError("片段并发数必须大于 0")
        self.client = client
        self.workers = workers
        self._key_cache: dict[str, bytes] = {}
        self._key_lock = threading.Lock()

    def download_all(
        self,
        playlist: ParsedPlaylist,
        workspace: Path,
        control: TaskControl,
        progress: ProgressCallback,
    ) -> tuple[SegmentResult, ...]:
        workspace = Path(workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        results: dict[int, SegmentResult] = {}
        pending_segments: list[MediaSegment] = []
        manifest_path = workspace / "segments.json"
        try:
            existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(existing_manifest, dict):
                existing_manifest = {}
        except (OSError, ValueError):
            existing_manifest = {}
        expected_manifest = {segment.filename: self._segment_identity(segment) for segment in playlist.segments}

        for segment in playlist.segments:
            target = workspace / segment.filename
            identity_matches = existing_manifest.get(segment.filename) == expected_manifest[segment.filename]
            if identity_matches and target.is_file() and target.stat().st_size > 0:
                result = SegmentResult(segment, target, target.stat().st_size, True)
                results[segment.index] = result
                progress(result)
            else:
                target.unlink(missing_ok=True)
                target.with_name(f"{target.name}.part").unlink(missing_ok=True)
                pending_segments.append(segment)

        manifest_part = manifest_path.with_suffix(".json.part")
        with manifest_part.open("w", encoding="utf-8") as handle:
            json.dump(expected_manifest, handle, ensure_ascii=True, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(manifest_part, manifest_path)

        failures: list[BaseException] = []
        next_index = 0
        futures: dict[Future[SegmentResult], MediaSegment] = {}
        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="segment") as pool:
            while next_index < len(pending_segments) or futures:
                while (
                    next_index < len(pending_segments)
                    and len(futures) < self.workers
                    and not control.canceled
                    and (not control.paused or not getattr(control, "exit_on_pause", False))
                ):
                    item = pending_segments[next_index]
                    next_index += 1
                    futures[pool.submit(self._download_one, item, workspace, control, progress)] = item

                if not futures:
                    break
                completed, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in completed:
                    futures.pop(future)
                    try:
                        result = future.result()
                    except (TaskCanceled, TaskPaused):
                        continue
                    except Exception as exc:  # noqa: BLE001 - collect every worker failure
                        failures.append(exc)
                    else:
                        results[result.segment.index] = result

        if control.canceled:
            raise TaskCanceled("任务已取消")
        if control.paused and getattr(control, "exit_on_pause", False):
            raise TaskPaused("任务已暂停")
        if failures:
            first = failures[0]
            if isinstance(first, SegmentDownloadError):
                raise first
            raise SegmentDownloadError("一个或多个视频片段下载失败") from first
        if len(results) != len(playlist.segments):
            raise SegmentDownloadError("视频片段未完整下载")
        return tuple(results[index] for index in sorted(results))

    @staticmethod
    def _segment_identity(segment: MediaSegment) -> str:
        key = None
        if segment.key is not None:
            key = {
                "method": segment.key.method,
                "uri": segment.key.uri,
                "iv": segment.key.iv.hex(),
            }
        value = json.dumps(
            {
                "media_sequence": segment.media_sequence,
                "uri": segment.uri,
                "byte_range": segment.byte_range,
                "key": key,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(value).hexdigest()

    def _download_one(
        self,
        segment: MediaSegment,
        workspace: Path,
        control: TaskControl,
        progress: ProgressCallback,
    ) -> SegmentResult:
        with control.work_unit():
            try:
                response = self.client.get(segment.uri, byte_range=segment.byte_range)
                try:
                    self._validate_response(response, segment)
                    body = bytes(response.content)
                finally:
                    response.close()
                if segment.key is not None:
                    body = self._decrypt(body, segment.key, segment.index)
                if not body:
                    raise SegmentDownloadError(f"片段 {segment.index + 1} 返回空内容")
                target = workspace / segment.filename
                part = target.with_name(f"{target.name}.part")
                with part.open("wb") as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(part, target)
                result = SegmentResult(segment, target, len(body), False)
                progress(result)
                return result
            except (SegmentDownloadError, TaskCanceled, TaskPaused):
                raise
            except Exception as exc:
                raise SegmentDownloadError(f"片段 {segment.index + 1} 下载失败") from exc

    @staticmethod
    def _validate_response(response: Any, segment: MediaSegment) -> None:
        try:
            response.raise_for_status()
        except Exception as exc:
            raise SegmentDownloadError(f"片段 {segment.index + 1} 请求失败") from exc
        if segment.byte_range is None:
            return
        offset, length = segment.byte_range
        expected = f"bytes {offset}-{offset + length - 1}/"
        content_range = response.headers.get("Content-Range", "")
        if response.status_code != 206 or not content_range.startswith(expected):
            raise SegmentDownloadError(f"片段 {segment.index + 1} 的字节范围响应无效")
        if len(response.content) != length:
            raise SegmentDownloadError(f"片段 {segment.index + 1} 的字节范围长度不匹配")

    def _fetch_key(self, key: KeySpec, segment_index: int) -> bytes:
        with self._key_lock:
            cached = self._key_cache.get(key.uri)
            if cached is not None:
                return cached
            try:
                response = self.client.get(key.uri)
                try:
                    response.raise_for_status()
                    value = bytes(response.content)
                finally:
                    response.close()
            except Exception as exc:
                raise SegmentDownloadError(f"片段 {segment_index + 1} 的解密密钥获取失败") from exc
            if len(value) != 16:
                raise SegmentDownloadError(f"片段 {segment_index + 1} 的 AES-128 密钥长度无效")
            self._key_cache[key.uri] = value
            return value

    def _decrypt(self, encrypted: bytes, key: KeySpec, segment_index: int) -> bytes:
        if len(encrypted) == 0 or len(encrypted) % AES.block_size:
            raise SegmentDownloadError(f"片段 {segment_index + 1} 的加密数据长度无效")
        decrypted = AES.new(self._fetch_key(key, segment_index), AES.MODE_CBC, key.iv).decrypt(encrypted)
        padding = decrypted[-1]
        if padding < 1 or padding > AES.block_size or decrypted[-padding:] != bytes([padding]) * padding:
            raise SegmentDownloadError(f"片段 {segment_index + 1} 的 PKCS#7 填充无效")
        return decrypted[:-padding]
