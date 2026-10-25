from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_path, user_config_path, user_data_path

PROBE_TIMEOUT = (1.5, 4.0)
REQUEST_TIMEOUT = (5.0, 30.0)
HTTP_RETRIES = 2


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    config_dir: Path
    cache_dir: Path

    @classmethod
    def from_platform(cls, app_name: str = "M3U8 Downloader Pro") -> AppPaths:
        return cls(
            data_dir=Path(user_data_path(app_name, appauthor=False)),
            config_dir=Path(user_config_path(app_name, appauthor=False)),
            cache_dir=Path(user_cache_path(app_name, appauthor=False)),
        )
