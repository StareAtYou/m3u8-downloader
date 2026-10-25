from __future__ import annotations

import ipaddress
import os
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import SplitResult, urlsplit, urlunsplit
from urllib.request import getproxies

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import HTTP_RETRIES, PROBE_TIMEOUT, REQUEST_TIMEOUT

SessionFactory = Callable[[], requests.Session]
_SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks4", "socks5", "socks5h"}


def _is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower().rstrip(".") == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _redact_proxy_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    credentials = "***:***@" if parsed.username is not None else ""
    port = f":{parsed.port}" if parsed.port else ""
    query = "redacted=***" if parsed.query else ""
    return urlunsplit(SplitResult(parsed.scheme, f"{credentials}{host}{port}", parsed.path, query, ""))


@dataclass(frozen=True, slots=True)
class NetworkRoute:
    proxy_url: str | None
    source: str

    @classmethod
    def direct(cls) -> NetworkRoute:
        return cls(proxy_url=None, source="direct")

    @classmethod
    def proxy(cls, url: str, *, source: str) -> NetworkRoute:
        return cls(proxy_url=url, source=source)

    @property
    def is_direct(self) -> bool:
        return self.proxy_url is None

    @property
    def display_name(self) -> str:
        if self.is_direct:
            return "直连"
        return f"本地代理 · {_redact_proxy_url(self.proxy_url or '')}"

    @property
    def requests_proxies(self) -> dict[str, str]:
        if self.proxy_url is None:
            return {}
        return {"http": self.proxy_url, "https": self.proxy_url}


@dataclass(frozen=True, slots=True)
class RouteSelection:
    route: NetworkRoute
    manifest_bytes: bytes
    elapsed_seconds: float
    effective_url: str = ""


def _validated_proxy(value: str, *, source: str, allow_credentials: bool) -> NetworkRoute:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("代理地址格式无效") from exc
    if parsed.scheme.lower() not in _SUPPORTED_PROXY_SCHEMES:
        raise ValueError("代理协议仅支持 HTTP、HTTPS、SOCKS4 和 SOCKS5")
    if not _is_loopback_host(parsed.hostname):
        raise ValueError("只允许连接本机回环地址上的代理")
    if port is None:
        raise ValueError("代理地址必须包含端口")
    if not allow_credentials and (parsed.username is not None or parsed.password is not None):
        raise ValueError("手动代理不允许在地址中包含用户名或密码")
    return NetworkRoute.proxy(value, source=source)


def parse_manual_proxy(url: str) -> NetworkRoute:
    return _validated_proxy(url.strip(), source="manual", allow_credentials=False)


def discover_routes(
    system_proxies: Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[NetworkRoute, ...]:
    """Discover safe local proxy routes without leaking ambient proxy behavior.

    Inject mappings in tests. In production, OS proxy settings and conventional
    environment variables are read explicitly, then every request uses
    ``Session.trust_env = False``.
    """

    system = getproxies() if system_proxies is None else system_proxies
    environment = os.environ if environ is None else environ
    candidates: list[tuple[str, str]] = []
    candidates.extend(("system", value) for value in system.values() if value)
    for key, value in environment.items():
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy"} and value:
            candidates.append(("environment", value))

    routes = [NetworkRoute.direct()]
    seen: set[str] = set()
    for source, value in candidates:
        try:
            route = _validated_proxy(value.strip(), source=source, allow_credentials=True)
        except ValueError:
            continue
        assert route.proxy_url is not None
        if route.proxy_url in seen:
            continue
        seen.add(route.proxy_url)
        routes.append(route)
    return tuple(routes)


def _configure_session(session: Any, route: NetworkRoute, retries: int) -> Any:
    session.trust_env = False
    session.proxies.clear()
    session.proxies.update(route.requests_proxies)
    if hasattr(session, "mount"):
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            backoff_factor=0.2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    return session


class RouteSelector:
    def __init__(
        self,
        routes: tuple[NetworkRoute, ...] | list[NetworkRoute] | None = None,
        *,
        session_factory: SessionFactory = requests.Session,
        probe_timeout: tuple[float, float] = PROBE_TIMEOUT,
        failure_threshold: int = 2,
    ) -> None:
        self.routes = tuple(routes or discover_routes())
        self.session_factory = session_factory
        self.probe_timeout = probe_timeout
        self.failure_threshold = failure_threshold
        self._failures: dict[NetworkRoute, int] = {}
        self._lock = threading.Lock()

    def available_routes(self) -> tuple[NetworkRoute, ...]:
        with self._lock:
            return tuple(route for route in self.routes if self._failures.get(route, 0) < self.failure_threshold)

    def record_failure(self, route: NetworkRoute) -> None:
        with self._lock:
            self._failures[route] = self._failures.get(route, 0) + 1

    def record_success(self, route: NetworkRoute) -> None:
        with self._lock:
            self._failures.pop(route, None)

    def _probe(self, route: NetworkRoute, url: str) -> RouteSelection:
        session = _configure_session(self.session_factory(), route, HTTP_RETRIES)
        response = None
        started = time.monotonic()
        try:
            response = session.get(url, timeout=self.probe_timeout)
            response.raise_for_status()
            return RouteSelection(
                route,
                bytes(response.content),
                time.monotonic() - started,
                str(getattr(response, "url", "") or url),
            )
        finally:
            if response is not None:
                response.close()
            session.close()

    def select(self, url: str) -> RouteSelection:
        routes = self.available_routes()
        if not routes:
            routes = (NetworkRoute.direct(),)
        successes: list[RouteSelection] = []
        with ThreadPoolExecutor(max_workers=len(routes), thread_name_prefix="route-probe") as pool:
            futures = {pool.submit(self._probe, route, url): route for route in routes}
            for future in as_completed(futures):
                route = futures[future]
                try:
                    selection = future.result()
                except Exception:  # noqa: BLE001 - one failed route must not cancel other probes
                    self.record_failure(route)
                else:
                    self.record_success(route)
                    successes.append(selection)
        if not successes:
            raise requests.ConnectionError("直连和本地代理均无法获取播放列表")
        return min(successes, key=lambda result: result.elapsed_seconds)


class ThreadLocalHttpClient:
    def __init__(
        self,
        route: NetworkRoute,
        *,
        session_factory: SessionFactory = requests.Session,
        timeout: tuple[float, float] = REQUEST_TIMEOUT,
        retries: int = HTTP_RETRIES,
    ) -> None:
        self.route = route
        self.session_factory = session_factory
        self.timeout = timeout
        self.retries = retries
        self._local = threading.local()
        self._sessions: list[Any] = []
        self._lock = threading.Lock()

    def _session(self) -> Any:
        session = getattr(self._local, "session", None)
        if session is None:
            session = _configure_session(self.session_factory(), self.route, self.retries)
            self._local.session = session
            with self._lock:
                self._sessions.append(session)
        return session

    def get(self, url: str, byte_range: tuple[int, int] | None = None, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        if byte_range is not None:
            start, length = byte_range
            if start < 0 or length <= 0:
                raise ValueError("字节范围必须具有非负起点和正长度")
            headers["Range"] = f"bytes={start}-{start + length - 1}"
        return self._session().get(
            url,
            headers=headers,
            timeout=kwargs.pop("timeout", self.timeout),
            **kwargs,
        )

    def close(self) -> None:
        with self._lock:
            sessions, self._sessions = self._sessions, []
        for session in sessions:
            session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class FailoverHttpClient:
    """Thread-safe client that retries a failed resource through alternate routes."""

    def __init__(
        self,
        selector: RouteSelector,
        preferred_route: NetworkRoute,
        *,
        session_factory: SessionFactory = requests.Session,
        timeout: tuple[float, float] = REQUEST_TIMEOUT,
        retries: int = HTTP_RETRIES,
    ) -> None:
        self.selector = selector
        self.preferred_route = preferred_route
        self.session_factory = session_factory
        self.timeout = timeout
        self.retries = retries
        self._clients: dict[NetworkRoute, ThreadLocalHttpClient] = {}
        self._lock = threading.Lock()

    def _client(self, route: NetworkRoute) -> ThreadLocalHttpClient:
        with self._lock:
            client = self._clients.get(route)
            if client is None:
                client = ThreadLocalHttpClient(
                    route,
                    session_factory=self.session_factory,
                    timeout=self.timeout,
                    retries=self.retries,
                )
                self._clients[route] = client
            return client

    def get(self, url: str, byte_range: tuple[int, int] | None = None, **kwargs: Any) -> Any:
        available = self.selector.available_routes()
        routes = (
            tuple(dict.fromkeys((self.preferred_route, *available)))
            if self.preferred_route in available
            else available or (self.preferred_route,)
        )
        last_error: BaseException | None = None
        for route in routes:
            response = None
            try:
                response = self._client(route).get(url, byte_range=byte_range, **kwargs)
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001 - route failure triggers the explicit fallback contract
                last_error = exc
                self.selector.record_failure(route)
                if response is not None:
                    response.close()
                continue
            self.selector.record_success(route)
            self.preferred_route = route
            return response
        if last_error is not None:
            raise last_error
        raise requests.ConnectionError("没有可用下载通道")

    def close(self) -> None:
        with self._lock:
            clients, self._clients = tuple(self._clients.values()), {}
        for client in clients:
            client.close()
