from __future__ import annotations

import shutil
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def ffmpeg_path() -> str:
    value = shutil.which("ffmpeg")
    if value is None:
        pytest.skip("FFmpeg is required for real-media integration tests")
    return value


@pytest.fixture
def hls_source(tmp_path: Path, ffmpeg_path: str):
    media_root = tmp_path / "http-media"
    media_root.mkdir()
    playlist = media_root / "fixture.m3u8"
    subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=12",
            "-t",
            "1.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "3",
            "-sc_threshold",
            "0",
            "-f",
            "hls",
            "-hls_time",
            "0.25",
            "-hls_list_size",
            "0",
            "-hls_segment_filename",
            str(media_root / "segment-%03d.ts"),
            str(playlist),
        ],
        check=True,
        capture_output=True,
    )
    handler = partial(_QuietHandler, directory=str(media_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/{playlist.name}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
