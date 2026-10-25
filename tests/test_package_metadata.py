from __future__ import annotations

import importlib
import importlib.metadata
from pathlib import Path

import tomllib

import m3u8_downloader


def test_runtime_version_matches_project_metadata() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))

    assert importlib.metadata.version("m3u8-downloader-pro") == project["project"]["version"]
    assert m3u8_downloader.__version__ == project["project"]["version"]


def test_source_checkout_without_installed_metadata_uses_unknown_version(monkeypatch) -> None:
    def missing_metadata(_: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(importlib.metadata, "version", missing_metadata)
        module = importlib.reload(m3u8_downloader)
        assert module.__version__ == "0+unknown"

    importlib.reload(m3u8_downloader)
