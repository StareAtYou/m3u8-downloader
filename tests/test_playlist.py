from __future__ import annotations

from pathlib import Path

import pytest

from m3u8_downloader.playlist import PlaylistError, PlaylistParser

FIXTURES = Path(__file__).parent / "fixtures" / "hls"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_master_selects_highest_bandwidth_and_resolves_relative_urls() -> None:
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return fixture("media.m3u8")

    parsed = PlaylistParser().parse("https://media.example/root/master.m3u8", fixture("master.m3u8"), fetch)

    assert fetched == ["https://media.example/root/high/media.m3u8"]
    assert parsed.source_url == fetched[0]
    assert parsed.media_sequence == 41
    assert parsed.segments[0].uri == "https://media.example/root/high/seg-a.ts"
    assert parsed.segments[-1].uri == "https://media.example/root/last.ts"


def test_segment_identity_encryption_rotation_and_byte_ranges_are_exact() -> None:
    parsed = PlaylistParser().parse("https://media.example/live/media.m3u8", fixture("media.m3u8"), lambda _: b"")

    first, second, third, fourth = parsed.segments
    assert [(item.index, item.media_sequence, item.filename) for item in parsed.segments] == [
        (0, 41, "000000.ts"),
        (1, 42, "000001.ts"),
        (2, 43, "000002.ts"),
        (3, 44, "000003.ts"),
    ]
    assert first.key is not None
    assert first.key.uri == "https://media.example/live/keys/first.bin"
    assert first.key.iv == (41).to_bytes(16, "big")
    assert second.key is not None
    assert second.key.uri == "https://media.example/live/keys/second.bin"
    assert second.key.iv == (0xAA).to_bytes(16, "big")
    assert third.key == second.key
    assert fourth.key is None
    assert second.byte_range == (25, 100)
    assert third.byte_range == (125, 40)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"#EXTM3U\n#EXT-X-ENDLIST\n", "没有媒体片段"),
        (
            b'#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"\n#EXTINF:1,\na.ts\n',
            "SAMPLE-AES",
        ),
        (b"#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\"\n#EXTINF:1,\na.m4s\n", "EXT-X-MAP"),
        (
            b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key",IV=oops\n#EXTINF:1,\na.ts\n',
            "IV",
        ),
    ],
)
def test_rejects_empty_or_unsupported_playlists(content: bytes, message: str) -> None:
    with pytest.raises(PlaylistError, match=message):
        PlaylistParser().parse("https://media.example/a.m3u8", content, lambda _: b"")


def test_rejects_variant_cycle() -> None:
    master = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\na.m3u8\n"

    with pytest.raises(PlaylistError, match="循环"):
        PlaylistParser().parse("https://media.example/a.m3u8", master, lambda _: master)


def test_rejects_variant_depth_above_limit() -> None:
    master = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\nnext.m3u8\n"

    with pytest.raises(PlaylistError, match="层级"):
        PlaylistParser(max_variant_depth=2).parse(
            "https://media.example/a.m3u8",
            master,
            lambda url: master.replace(b"next.m3u8", f"{len(url)}.m3u8".encode()),
        )


def test_child_playlist_uses_redirected_effective_url_as_base() -> None:
    master = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100\nchild.m3u8\n"
    media = b"#EXTM3U\n#EXTINF:1,\nsegment.ts\n#EXT-X-ENDLIST\n"

    parsed = PlaylistParser().parse(
        "https://media.example/root/master.m3u8",
        master,
        lambda _url: (media, "https://cdn.example/hls/media.m3u8"),
    )

    assert parsed.source_url == "https://cdn.example/hls/media.m3u8"
    assert parsed.segments[0].uri == "https://cdn.example/hls/segment.ts"
