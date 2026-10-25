"""M3U8 Downloader Pro."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("m3u8-downloader-pro")
except PackageNotFoundError:
    __version__ = "0+unknown"
