from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from m3u8_downloader.network import (
    FailoverHttpClient,
    NetworkRoute,
    RouteSelector,
    ThreadLocalHttpClient,
    discover_routes,
    parse_manual_proxy,
)


class FakeResponse:
    def __init__(self, content: bytes = b"playlist", status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, behavior=None) -> None:
        self.behavior = behavior or {}
        self.trust_env = True
        self.proxies = {}
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs, dict(self.proxies)))
        delay, response = self.behavior.get(next(iter(self.proxies.values()), "direct"), (0, FakeResponse()))
        time.sleep(delay)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


def test_discovery_keeps_direct_and_only_local_deduplicated_proxies() -> None:
    routes = discover_routes(
        {
            "http": "http://127.0.0.1:7890",
            "https": "http://localhost:7890",
            "all": "socks5://[::1]:1080",
            "remote": "http://proxy.example:8080",
        },
        {
            "HTTP_PROXY": "http://127.0.0.1:7890",
            "HTTPS_PROXY": "http://user:secret@localhost:7891/path?token=x",
        },
    )

    assert routes[0].is_direct
    assert [route.proxy_url for route in routes[1:]] == [
        "http://127.0.0.1:7890",
        "http://localhost:7890",
        "socks5://[::1]:1080",
        "http://user:secret@localhost:7891/path?token=x",
    ]
    assert "secret" not in routes[-1].display_name
    assert "token=x" not in routes[-1].display_name


@pytest.mark.parametrize(
    "value",
    [
        "http://proxy.example:7890",
        "http://user:secret@127.0.0.1:7890",
        "ftp://127.0.0.1:7890",
        "http://127.0.0.1",
        "not-a-url",
    ],
)
def test_manual_proxy_rejects_unsafe_or_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_manual_proxy(value)


def test_manual_proxy_accepts_loopback_hostname_ipv4_and_ipv6() -> None:
    assert parse_manual_proxy("http://localhost:7890").proxy_url
    assert parse_manual_proxy("socks5://127.0.0.1:1080").proxy_url
    assert parse_manual_proxy("http://[::1]:8888").proxy_url


def test_selector_probes_concurrently_and_reuses_fastest_manifest_bytes() -> None:
    direct = NetworkRoute.direct()
    proxy = NetworkRoute.proxy("http://127.0.0.1:7890", source="system")
    responses = {
        "direct": (0.08, FakeResponse(b"slow")),
        proxy.proxy_url: (0.01, FakeResponse(b"fast")),
    }
    sessions: list[FakeSession] = []

    def factory() -> FakeSession:
        session = FakeSession(responses)
        sessions.append(session)
        return session

    started = time.monotonic()
    selection = RouteSelector([direct, proxy], session_factory=factory).select("https://media.example/master.m3u8")
    elapsed = time.monotonic() - started

    assert selection.route == proxy
    assert selection.manifest_bytes == b"fast"
    # Both probes finish before resources are released, but their wall time is
    # the slowest probe rather than the sum of both probe times.
    assert elapsed < 0.14
    assert all(session.trust_env is False for session in sessions)
    assert all(session.closed for session in sessions)


def test_selector_falls_back_after_repeated_winner_failures() -> None:
    direct = NetworkRoute.direct()
    proxy = NetworkRoute.proxy("http://127.0.0.1:7890", source="system")
    selector = RouteSelector([direct, proxy], failure_threshold=2)

    selector.record_failure(proxy)
    assert proxy in selector.available_routes()
    selector.record_failure(proxy)
    assert selector.available_routes() == (direct,)
    selector.record_success(proxy)
    assert proxy in selector.available_routes()


def test_thread_local_client_creates_one_session_per_thread_and_sets_range() -> None:
    created: list[FakeSession] = []
    lock = threading.Lock()

    def factory() -> FakeSession:
        session = FakeSession()
        with lock:
            created.append(session)
        return session

    client = ThreadLocalHttpClient(NetworkRoute.direct(), session_factory=factory)
    barrier = threading.Barrier(3)

    def request(index: int) -> int:
        barrier.wait()
        response = client.get("https://media.example/seg.ts", byte_range=(index, 10))
        return response.status_code

    with ThreadPoolExecutor(max_workers=3) as executor:
        assert list(executor.map(request, range(3))) == [200, 200, 200]

    assert len(created) == 3
    assert all(session.trust_env is False for session in created)
    headers = [session.calls[0][1]["headers"]["Range"] for session in created]
    assert sorted(headers) == ["bytes=0-9", "bytes=1-10", "bytes=2-11"]
    client.close()
    assert all(session.closed for session in created)


def test_failover_client_retries_request_on_alternate_route() -> None:
    direct = NetworkRoute.direct()
    proxy = NetworkRoute.proxy("http://127.0.0.1:7890", source="system")
    responses = {
        "direct": (0, RuntimeError("direct segment failed")),
        proxy.proxy_url: (0, FakeResponse(b"via-proxy")),
    }
    selector = RouteSelector([direct, proxy], session_factory=lambda: FakeSession(responses), failure_threshold=1)
    client = FailoverHttpClient(selector, direct, session_factory=lambda: FakeSession(responses))

    response = client.get("https://media.example/segment.ts")

    assert response.content == b"via-proxy"
    assert selector.available_routes() == (proxy,)
    client.close()


def test_route_selection_preserves_redirected_effective_url() -> None:
    response = FakeResponse(b"playlist")
    response.url = "https://media.example/hls/media.m3u8"
    selection = RouteSelector(
        [NetworkRoute.direct()], session_factory=lambda: FakeSession({"direct": (0, response)})
    ).select("https://media.example/start")

    assert selection.effective_url == response.url
