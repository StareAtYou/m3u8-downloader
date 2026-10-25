from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from Crypto.Cipher import AES

from m3u8_downloader.playlist import KeySpec, MediaSegment, ParsedPlaylist
from m3u8_downloader.segments import (
    SegmentDownloader,
    SegmentDownloadError,
    TaskCanceled,
    TaskControl,
)


class Response:
    def __init__(self, body: bytes, *, status: int = 200, headers=None) -> None:
        self.content = body
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self) -> None:
        self.closed = True


class Client:
    def __init__(self, responses: dict[str, list[Response] | Response], delay: float = 0) -> None:
        self.responses = responses
        self.calls: list[tuple[str, tuple[int, int] | None, int]] = []
        self.delay = delay
        self.lock = threading.Lock()

    def get(self, url: str, byte_range=None):
        with self.lock:
            self.calls.append((url, byte_range, threading.get_ident()))
            value = self.responses[url]
            response = value.pop(0) if isinstance(value, list) else value
        if self.delay:
            time.sleep(self.delay)
        return response


def segment(
    index: int,
    *,
    key: KeySpec | None = None,
    byte_range: tuple[int, int] | None = None,
) -> MediaSegment:
    return MediaSegment(
        index=index,
        media_sequence=100 + index,
        uri=f"https://media.example/seg-{index}.ts?secret=value",
        filename=f"{index:06d}.ts",
        byte_range=byte_range,
        key=key,
        duration=1,
    )


def playlist(*segments: MediaSegment) -> ParsedPlaylist:
    return ParsedPlaylist("https://media.example/a.m3u8", 100, segments, True, len(segments))


def test_download_uses_part_then_atomic_replace_and_redownloads_partial(tmp_path: Path, monkeypatch) -> None:
    item = segment(0)
    workspace = tmp_path / "task-a"
    workspace.mkdir()
    (workspace / "000000.ts.part").write_bytes(b"truncated")
    client = Client({item.uri: Response(b"complete")})
    replaced: list[tuple[Path, Path]] = []
    real_replace = __import__("os").replace

    def tracking_replace(source, target):
        replaced.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr("m3u8_downloader.segments.os.replace", tracking_replace)
    result = SegmentDownloader(client, workers=1).download_all(
        playlist(item), workspace, TaskControl(), lambda _: None
    )

    assert (workspace / "000000.ts").read_bytes() == b"complete"
    assert not (workspace / "000000.ts.part").exists()
    assert (workspace / "000000.ts.part", workspace / "000000.ts") in replaced
    assert result[0].resumed is False


def test_nonempty_completed_file_resumes_only_inside_current_workspace(tmp_path: Path) -> None:
    item = segment(0)
    workspace = tmp_path / "current"
    workspace.mkdir()
    (tmp_path / item.filename).write_bytes(b"unrelated")
    first_client = Client({item.uri: Response(b"done")})
    SegmentDownloader(first_client, workers=1).download_all(playlist(item), workspace, TaskControl(), lambda _: None)
    client = Client({item.uri: Response(b"new")})

    result = SegmentDownloader(client, workers=1).download_all(
        playlist(item), workspace, TaskControl(), lambda _: None
    )

    assert result[0].resumed is True
    assert client.calls == []


def test_changed_media_sequence_invalidates_index_named_segment(tmp_path: Path) -> None:
    old = segment(0)
    current = MediaSegment(
        old.index,
        20,
        "https://media.example/new.ts",
        old.filename,
        old.byte_range,
        old.key,
        old.duration,
    )
    first_client = Client({old.uri: Response(b"old")})
    SegmentDownloader(first_client, workers=1).download_all(playlist(old), tmp_path, TaskControl(), lambda _: None)
    second_client = Client({current.uri: Response(b"new")})

    result = SegmentDownloader(second_client, workers=1).download_all(
        ParsedPlaylist("https://media.example/new.m3u8", 20, (current,), True, 1),
        tmp_path,
        TaskControl(),
        lambda _: None,
    )

    assert result[0].resumed is False
    assert tmp_path.joinpath(current.filename).read_bytes() == b"new"


def test_zero_byte_final_is_redownloaded(tmp_path: Path) -> None:
    item = segment(0)
    tmp_path.joinpath(item.filename).touch()
    client = Client({item.uri: Response(b"fixed")})
    SegmentDownloader(client, workers=1).download_all(playlist(item), tmp_path, TaskControl(), lambda _: None)
    assert tmp_path.joinpath(item.filename).read_bytes() == b"fixed"


def test_range_response_is_validated_and_errors_are_sanitized(tmp_path: Path) -> None:
    item = segment(0, byte_range=(10, 5))
    client = Client({item.uri: Response(b"wrong", status=200)})

    with pytest.raises(SegmentDownloadError) as caught:
        SegmentDownloader(client, workers=1).download_all(playlist(item), tmp_path, TaskControl(), lambda _: None)

    assert "secret" not in str(caught.value)
    assert "media.example" not in str(caught.value)


def test_aes_128_decrypts_with_cached_key_and_validates_padding(tmp_path: Path) -> None:
    key_bytes = b"0123456789abcdef"
    key = KeySpec("AES-128", "https://media.example/key?token=hidden", (100).to_bytes(16, "big"))
    one, two = segment(0, key=key), segment(1, key=key)
    plain_one, plain_two = b"first payload", b"second payload"

    def encrypted(value: bytes, iv: bytes) -> bytes:
        pad = 16 - len(value) % 16
        return AES.new(key_bytes, AES.MODE_CBC, iv).encrypt(value + bytes([pad]) * pad)

    client = Client(
        {
            key.uri: Response(key_bytes),
            one.uri: Response(encrypted(plain_one, key.iv)),
            two.uri: Response(encrypted(plain_two, key.iv)),
        }
    )
    SegmentDownloader(client, workers=2).download_all(playlist(one, two), tmp_path, TaskControl(), lambda _: None)

    assert tmp_path.joinpath(one.filename).read_bytes() == plain_one
    assert tmp_path.joinpath(two.filename).read_bytes() == plain_two
    assert sum(call[0] == key.uri for call in client.calls) == 1


@pytest.mark.parametrize("key_bytes", [b"short", b"x" * 32])
def test_rejects_non_16_byte_aes_keys_without_leaking_key(tmp_path: Path, key_bytes: bytes) -> None:
    key = KeySpec("AES-128", "https://media.example/key?token=hidden", b"\0" * 16)
    item = segment(0, key=key)
    client = Client({key.uri: Response(key_bytes), item.uri: Response(b"x" * 16)})

    with pytest.raises(SegmentDownloadError) as caught:
        SegmentDownloader(client, workers=1).download_all(playlist(item), tmp_path, TaskControl(), lambda _: None)
    assert "hidden" not in str(caught.value)
    assert key_bytes.decode(errors="ignore") not in str(caught.value)


def test_progress_counts_only_success_and_any_failure_blocks_success(tmp_path: Path) -> None:
    items = tuple(segment(index) for index in range(3))
    client = Client(
        {
            items[0].uri: Response(b"ok"),
            items[1].uri: Response(b"bad", status=500),
            items[2].uri: Response(b"ok"),
        }
    )
    progressed = []

    with pytest.raises(SegmentDownloadError):
        SegmentDownloader(client, workers=2).download_all(playlist(*items), tmp_path, TaskControl(), progressed.append)
    assert len(progressed) == 2


def test_pause_waits_for_atomic_commit_resume_continues_and_cancel_stops_scheduling(
    tmp_path: Path,
) -> None:
    items = tuple(segment(index) for index in range(6))
    client = Client({item.uri: Response(b"ok") for item in items}, delay=0.04)
    control = TaskControl()
    progressed = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            SegmentDownloader(client, workers=2).download_all(playlist(*items), tmp_path, control, progressed.append)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.01)
    control.request_pause()
    paused_count = len(progressed)
    time.sleep(0.06)
    assert len(progressed) == paused_count
    control.resume()
    time.sleep(0.02)
    control.request_cancel()
    thread.join(timeout=2)

    assert errors and isinstance(errors[0], TaskCanceled)
    assert len(client.calls) < len(items)
