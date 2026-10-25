"""Legacy interactive client entry point."""

from m3u8_downloader.cli import client_main

if __name__ == "__main__":
    raise SystemExit(client_main(["interactive"]))
