"""Standalone desktop entry point used by pyside6-deploy."""

from __future__ import annotations

import sys

from m3u8_downloader.cli import service_main
from m3u8_downloader.gui.app import main as gui_main

if __name__ == "__main__":
    if sys.argv[1:2] == ["--service"]:
        raise SystemExit(service_main(sys.argv[2:]))
    raise SystemExit(gui_main())
