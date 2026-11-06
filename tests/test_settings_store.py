from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from m3u8_downloader.models import AppSettings
from m3u8_downloader.settings_store import JsonSettingsStore


def test_json_settings_store_persists_all_fields_with_private_permissions(tmp_path: Path) -> None:
    path = tmp_path / "config" / "settings.json"
    settings = AppSettings(
        default_save_dir="/videos",
        max_active_tasks=5,
        segment_threads=24,
        proxy_policy="manual",
        manual_proxy="socks5://127.0.0.1:7890",
        ffmpeg_path="/opt/ffmpeg",
        theme="light",
        close_behavior="shutdown",
    )

    JsonSettingsStore(path).update_settings(settings)

    assert json.loads(path.read_text()) == {
        "close_behavior": "shutdown",
        "default_save_dir": "/videos",
        "ffmpeg_path": "/opt/ffmpeg",
        "manual_proxy": "socks5://127.0.0.1:7890",
        "max_active_tasks": 5,
        "proxy_policy": "manual",
        "segment_threads": 24,
        "theme": "light",
    }
    assert JsonSettingsStore(path).get_settings() == settings
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_json_settings_store_migrates_fallback_once_and_surfaces_corruption_without_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    legacy = AppSettings(default_save_dir="/legacy", max_active_tasks=4, segment_threads=12)
    fallback_calls: list[bool] = []
    store = JsonSettingsStore(path, fallback=lambda: (fallback_calls.append(True), legacy)[1])

    assert store.get_settings() == legacy
    assert fallback_calls == [True]
    assert JsonSettingsStore(path, fallback=lambda: (_ for _ in ()).throw(AssertionError())).get_settings() == legacy

    corrupt = b'{"max_active_tasks": '
    path.write_bytes(corrupt)
    with pytest.raises(ValueError, match="设置文件"):
        JsonSettingsStore(path).get_settings()
    assert path.read_bytes() == corrupt


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_active_tasks", 2.5),
        ("max_active_tasks", True),
        ("segment_threads", 4.5),
        ("segment_threads", False),
    ],
)
def test_json_settings_store_rejects_non_integer_concurrency_values(tmp_path: Path, field: str, value: object) -> None:
    path = tmp_path / "settings.json"
    payload = {
        "default_save_dir": "",
        "max_active_tasks": 3,
        "segment_threads": 16,
        "proxy_policy": "auto",
        "manual_proxy": None,
        "ffmpeg_path": "ffmpeg",
        "theme": "dark",
        "close_behavior": "tray",
    }
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="设置文件内容无效"):
        JsonSettingsStore(path).get_settings()


def test_failed_atomic_replace_keeps_previous_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "settings.json"
    original = AppSettings(max_active_tasks=2)
    store = JsonSettingsStore(path)
    store.update_settings(original)
    original_bytes = path.read_bytes()

    monkeypatch.setattr("m3u8_downloader.settings_store.os.replace", lambda *_: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError, match="boom"):
        store.update_settings(AppSettings(max_active_tasks=6))

    assert path.read_bytes() == original_bytes
    assert not list(tmp_path.glob("*.tmp"))
