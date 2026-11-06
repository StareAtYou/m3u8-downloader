from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from .models import AppSettings


class SettingsStore(Protocol):
    def get_settings(self) -> AppSettings: ...

    def update_settings(self, settings: AppSettings) -> None: ...


class JsonSettingsStore:
    def __init__(self, path: Path, fallback: Callable[[], AppSettings] | None = None) -> None:
        self.path = Path(path)
        self._fallback = fallback
        self._lock = threading.RLock()

    def get_settings(self) -> AppSettings:
        with self._lock:
            if self.path.exists():
                return self._read_locked()
            settings = (self._fallback() if self._fallback is not None else AppSettings()).validate()
            self._write_locked(settings)
            return settings

    def update_settings(self, settings: AppSettings) -> None:
        with self._lock:
            self._write_locked(settings.validate())

    def _read_locked(self) -> AppSettings:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"设置文件无法读取: {self.path}") from exc
        if not isinstance(value, dict):
            raise TypeError(f"设置文件内容必须是 JSON 对象: {self.path}")
        try:
            merged = asdict(AppSettings())
            merged.update(value)
            return AppSettings(**merged).validate()
        except (TypeError, ValueError) as exc:
            raise ValueError(f"设置文件内容无效: {self.path}") from exc

    def _write_locked(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(asdict(settings), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                temporary_path.chmod(0o600)
            os.replace(temporary_path, self.path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
