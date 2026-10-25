from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import m3u8

PlaylistContent = bytes | str | tuple[bytes | str, str]
FetchPlaylist = Callable[[str], PlaylistContent]


class PlaylistError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class KeySpec:
    method: str
    uri: str
    iv: bytes


@dataclass(frozen=True, slots=True)
class MediaSegment:
    index: int
    media_sequence: int
    uri: str
    filename: str
    byte_range: tuple[int, int] | None
    key: KeySpec | None
    duration: float


@dataclass(frozen=True, slots=True)
class ParsedPlaylist:
    source_url: str
    media_sequence: int
    segments: tuple[MediaSegment, ...]
    is_endlist: bool
    duration: float


def _decode(content: bytes | str) -> str:
    if isinstance(content, str):
        return content
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PlaylistError("播放列表不是有效的 UTF-8 文本") from exc


def _iv_bytes(raw: str | None, media_sequence: int) -> bytes:
    if raw is None:
        return media_sequence.to_bytes(16, "big")
    if not raw.lower().startswith("0x"):
        raise PlaylistError("AES-128 IV 必须是 0x 开头的十六进制值")
    hex_value = raw[2:]
    if not hex_value or len(hex_value) > 32:
        raise PlaylistError("AES-128 IV 长度无效")
    try:
        value = int(hex_value, 16)
    except ValueError as exc:
        raise PlaylistError("AES-128 IV 不是有效的十六进制值") from exc
    return value.to_bytes(16, "big")


def _extension(url: str) -> str:
    path = urlsplit(url).path.lower()
    if path.endswith(".aac"):
        return ".aac"
    return ".ts"


class PlaylistParser:
    def __init__(self, *, max_variant_depth: int = 5) -> None:
        if max_variant_depth < 1:
            raise ValueError("播放列表层级限制必须大于 0")
        self.max_variant_depth = max_variant_depth

    def parse(self, url: str, content: bytes | str, fetch: FetchPlaylist) -> ParsedPlaylist:
        return self._parse(url, content, fetch, depth=0, visited=frozenset())

    def _parse(
        self,
        url: str,
        content: bytes | str,
        fetch: FetchPlaylist,
        *,
        depth: int,
        visited: frozenset[str],
    ) -> ParsedPlaylist:
        if url in visited:
            raise PlaylistError("检测到播放列表循环引用")
        visited = visited | {url}
        text = _decode(content)
        if "#EXT-X-MAP" in text.upper():
            raise PlaylistError("暂不支持 EXT-X-MAP/fMP4 播放列表")
        try:
            playlist = m3u8.loads(text, uri=url)
        except Exception as exc:
            raise PlaylistError("播放列表解析失败") from exc

        if playlist.is_variant:
            if depth >= self.max_variant_depth:
                raise PlaylistError("播放列表嵌套层级超过限制")
            if not playlist.playlists:
                raise PlaylistError("主播放列表没有可用码率")
            selected = max(
                playlist.playlists,
                key=lambda item: item.stream_info.bandwidth or item.stream_info.average_bandwidth or 0,
            )
            child_url = urljoin(url, selected.uri)
            if child_url in visited:
                raise PlaylistError("检测到播放列表循环引用")
            fetched = fetch(child_url)
            if isinstance(fetched, tuple):
                child_content, effective_url = fetched
            else:
                child_content, effective_url = fetched, child_url
            return self._parse(
                effective_url,
                child_content,
                fetch,
                depth=depth + 1,
                visited=visited,
            )

        if not playlist.segments:
            raise PlaylistError("播放列表没有媒体片段")

        media_sequence = int(playlist.media_sequence or 0)
        segments: list[MediaSegment] = []
        previous_range_uri: str | None = None
        previous_range_end: int | None = None
        for index, segment in enumerate(playlist.segments):
            sequence = media_sequence + index
            segment_url = urljoin(url, segment.uri)
            key = self._key_spec(url, segment.key, sequence)
            byte_range = self._byte_range(
                segment.byterange,
                segment_url,
                previous_range_uri,
                previous_range_end,
            )
            if byte_range is not None:
                previous_range_uri = segment_url
                previous_range_end = byte_range[0] + byte_range[1]
            else:
                previous_range_uri = None
                previous_range_end = None
            segments.append(
                MediaSegment(
                    index=index,
                    media_sequence=sequence,
                    uri=segment_url,
                    filename=f"{index:06d}{_extension(segment_url)}",
                    byte_range=byte_range,
                    key=key,
                    duration=float(segment.duration or 0),
                )
            )

        return ParsedPlaylist(
            source_url=url,
            media_sequence=media_sequence,
            segments=tuple(segments),
            is_endlist=bool(playlist.is_endlist),
            duration=sum(segment.duration for segment in segments),
        )

    @staticmethod
    def _key_spec(base_url: str, key: object | None, sequence: int) -> KeySpec | None:
        if key is None:
            return None
        method = str(getattr(key, "method", "") or "").upper()
        if method == "NONE":
            return None
        if method != "AES-128":
            raise PlaylistError(f"暂不支持加密方式 {method or 'UNKNOWN'}，包括 SAMPLE-AES")
        key_uri = getattr(key, "uri", None)
        if not key_uri:
            raise PlaylistError("AES-128 密钥缺少 URI")
        return KeySpec(
            method=method,
            uri=urljoin(base_url, str(key_uri)),
            iv=_iv_bytes(getattr(key, "iv", None), sequence),
        )

    @staticmethod
    def _byte_range(
        raw: str | None,
        uri: str,
        previous_uri: str | None,
        previous_end: int | None,
    ) -> tuple[int, int] | None:
        if raw is None:
            return None
        try:
            length_text, separator, offset_text = raw.partition("@")
            length = int(length_text)
            if separator:
                offset = int(offset_text)
            elif previous_uri == uri and previous_end is not None:
                offset = previous_end
            else:
                raise PlaylistError("隐式字节范围缺少同一资源的前置范围")
        except ValueError as exc:
            raise PlaylistError("EXT-X-BYTERANGE 格式无效") from exc
        if length <= 0 or offset < 0:
            raise PlaylistError("EXT-X-BYTERANGE 必须使用有效的正长度和非负偏移")
        return offset, length
