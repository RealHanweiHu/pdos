"""Bounded public HTTP reads, pinned to the addresses actually checked by policy."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import quote, urlsplit

from app.ai.reach import (
    MAX_CONTENT_BYTES,
    ReachDeniedError,
    ReachFetchError,
    ReachPolicy,
    ReachResponse,
    Resolver,
    _default_resolver,
)


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(
        self, hostname: str, port: int, addresses: tuple[str, ...], *, tls: bool, deadline: float
    ) -> None:
        super().__init__(hostname, port, timeout=max(0.1, deadline - time.monotonic()))
        self._addresses = addresses
        self._tls = tls
        self._deadline = deadline

    def connect(self) -> None:
        last: OSError | None = None
        for address in self._addresses[:8]:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Public read deadline exceeded")
            family = (
                socket.AF_INET6 if ipaddress.ip_address(address).version == 6 else socket.AF_INET
            )
            sock = socket.socket(family, socket.SOCK_STREAM)
            try:
                sock.settimeout(min(5.0, remaining))
                # Connect the numeric address directly. No second DNS lookup or environment proxy.
                sock.connect((address, self.port))
                sock.settimeout(max(0.1, self._deadline - time.monotonic()))
                self.sock = (
                    ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
                    if self._tls
                    else sock
                )
                return
            except OSError as error:
                sock.close()
                last = error
        raise ReachFetchError("无法连接已校验的公开来源地址") from last


class PublicReachTransport:
    """One GET per call, no redirect following, cookies, credentials or decompression."""

    def __init__(
        self,
        *,
        resolver: Resolver = _default_resolver,
        total_timeout: float = 20.0,
        required_origin: tuple[str, str, int] | None = None,
    ) -> None:
        self._resolver = resolver
        self._deadline = time.monotonic() + total_timeout
        self._required_origin = required_origin

    def get(self, url: str) -> ReachResponse:
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if (
                self._required_origin is not None
                and (parsed.scheme, host, port) != self._required_origin
            ):
                raise ReachDeniedError(
                    "source_origin_changed", "页面或重定向不属于所选来源，请单独登记对应来源"
                )
            addresses = tuple(dict.fromkeys(self._resolver(host)))
            ReachPolicy(resolver=lambda _: addresses).assert_url_allowed(url)
            # Literal hosts are checked by policy; they still must be the actual connection target.
            for address in addresses:
                value = ipaddress.ip_address(address)
                if not value.is_global or value.is_multicast:
                    raise ReachDeniedError("internal_address", "来源解析到非公开地址")
            if not addresses:
                raise ReachFetchError("来源域名没有可用公开地址")
            connection = _PinnedConnection(
                host, port, addresses, tls=parsed.scheme == "https", deadline=self._deadline
            )
            try:
                path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
                if parsed.query:
                    path += "?" + quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
                connection.request(
                    "GET",
                    path,
                    headers={
                        "User-Agent": "PDOS-Research/1.0",
                        "Accept": "text/html, text/plain, application/json, application/xml;q=0.8",
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                    },
                )
                response = connection.getresponse()
                content_type = response.getheader("Content-Type", "")
                if not 200 <= response.status < 300:
                    return ReachResponse(
                        response.status, "", content_type, 0, response.getheader("Location")
                    )
                if response.getheader("Content-Encoding", "identity").lower() not in {
                    "identity",
                    "",
                }:
                    raise ReachDeniedError(
                        "content_encoding_not_readable", "来源未提供可直接读取的未压缩正文"
                    )
                ReachPolicy().assert_response_allowed(
                    ReachResponse(response.status, "", content_type, 0)
                )
                declared_size = response.getheader("Content-Length")
                if declared_size is not None and int(declared_size) > MAX_CONTENT_BYTES:
                    raise ReachDeniedError(
                        "content_too_large", "正文超过2 MiB采集上限，请选择更具体的页面"
                    )
                chunks: list[bytes] = []
                size = 0
                while True:
                    remaining = self._deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Public read deadline exceeded")
                    if connection.sock is not None:
                        connection.sock.settimeout(remaining)
                    chunk = response.read1(min(65536, MAX_CONTENT_BYTES + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_CONTENT_BYTES:
                        raise ReachDeniedError(
                            "content_too_large", "正文超过2 MiB采集上限，请选择更具体的页面"
                        )
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    content = b"".join(chunks).decode(charset, errors="strict")
                except (UnicodeError, LookupError) as error:
                    raise ReachFetchError("正文编码无法识别，请使用明确编码的文本来源") from error
                return ReachResponse(
                    response.status,
                    content,
                    content_type,
                    size,
                    source_version=(
                        response.getheader("ETag") or response.getheader("Last-Modified") or ""
                    )[:128]
                    or None,
                    content_language=(response.getheader("Content-Language") or "und")
                    .split(",")[0]
                    .strip()[:16],
                )
            finally:
                connection.close()
        except (ReachDeniedError, ReachFetchError):
            raise
        except (OSError, http.client.HTTPException, ValueError, UnicodeError) as error:
            raise ReachFetchError("公开来源读取失败或超时，可稍后重试") from error
