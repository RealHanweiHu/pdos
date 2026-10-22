"""Public-address validation and direct, pinned HTTP reads without proxy credentials."""

import asyncio
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit


class ResearchError(Exception):
    def __init__(
        self,
        reason,
        message,
        *,
        provider=None,
        http_status=None,
        service_code=None,
        request_id=None,
        retry_after=None,
    ):
        super().__init__(message)
        self.reason, self.message = reason, message
        self.provider, self.http_status = provider, http_status
        self.service_code, self.request_id = service_code, request_id
        self.retry_after = retry_after


@dataclass(frozen=True)
class ResourceLimits:
    max_body_bytes: int = 2 * 1024 * 1024
    max_markdown_chars: int = 1024 * 1024
    page_chars: int = 16_000
    timeout_seconds: float = 20
    redirects: int = 5
    concurrency: int = 4

    def __post_init__(self):
        if (
            min(
                self.max_body_bytes,
                self.max_markdown_chars,
                self.page_chars,
                self.timeout_seconds,
                self.concurrency,
            )
            <= 0
            or self.redirects < 0
        ):
            raise ValueError("Research resource budgets must be positive")


def public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ResearchError("invalid_address", "DNS returned an invalid address") from exc
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if isinstance(address, ipaddress.IPv6Address):
        embedded = (address.sixtofour,) if address.sixtofour else ()
        embedded += address.teredo or ()
        if address in ipaddress.ip_network("64:ff9b::/96"):
            embedded += (ipaddress.IPv4Address(int(address) & 0xFFFFFFFF),)
        for inner in embedded:
            public_ip(str(inner))
    if (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
    ):
        raise ResearchError("non_public_address", "Private or reserved addresses cannot be read")
    return str(address)


def canonical_url(value: str) -> str:
    if not isinstance(value, str) or re.search(r"[\x00-\x20\\]", value):
        raise ResearchError("invalid_url", "A valid public HTTP URL is required")
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
        if parts.scheme.lower() not in {"http", "https"} or not host:
            raise ValueError("scheme/host")
        if parts.username is not None or parts.password is not None:
            raise ValueError("credentials")
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
        if "%" in host or not host:
            raise ValueError("host")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9.-]+", host) or ".." in host:
                raise ValueError("host") from None
        else:
            host = public_ip(host)
        default = 443 if parts.scheme.lower() == "https" else 80
        if port == 0:
            raise ValueError("port")
    except (ValueError, UnicodeError) as exc:
        raise ResearchError(
            "invalid_url", "URL scheme, host, credentials or port is invalid"
        ) from exc
    authority = f"[{host}]" if ":" in host else host
    if port is not None and port != default:
        authority += f":{port}"
    return urlunsplit((parts.scheme.lower(), authority, parts.path or "/", parts.query, ""))


async def resolve_public(host: str) -> tuple[str, ...]:
    try:
        raw = await asyncio.to_thread(socket.getaddrinfo, host, None, 0, socket.SOCK_STREAM)
    except OSError as exc:
        raise ResearchError("dns_failed", "Public hostname resolution failed") from exc
    # Reject the complete answer if any address is unsafe; no unsafe fallback candidate exists.
    addresses = tuple(dict.fromkeys(public_ip(row[4][0]) for row in raw))
    if not addresses:
        raise ResearchError("dns_failed", "Public hostname resolution returned no addresses")
    return addresses


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes
    service_error: str | None = None
    service_code: str | None = None

    def header(self, name):
        return next((value for key, value in self.headers if key.lower() == name.lower()), None)


class PinnedHTTPTransport:
    """Connect to the validated IP; retain the hostname only for Host and TLS SNI."""

    async def request(self, url: str, address: str, limits: ResourceLimits) -> HTTPResponse:
        return await asyncio.to_thread(self._request, url, address, limits)

    @staticmethod
    def _request(url, address, limits):
        url = canonical_url(url)
        parsed = urlsplit(url)
        pinned = public_ip(address)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        connection = (
            http.client.HTTPSConnection(
                parsed.hostname,
                port,
                timeout=limits.timeout_seconds,
                context=ssl.create_default_context(),
            )
            if parsed.scheme == "https"
            else http.client.HTTPConnection(parsed.hostname, port, timeout=limits.timeout_seconds)
        )

        def create_connection(_address, timeout, source_address=None):
            # Numeric address prevents a second DNS lookup at connect time.
            family = socket.AF_INET6 if ":" in pinned else socket.AF_INET
            sock = socket.socket(family, socket.SOCK_STREAM)
            try:
                sock.settimeout(timeout)
                sock.connect((pinned, port))
                if ipaddress.ip_address(sock.getpeername()[0]) != ipaddress.ip_address(pinned):
                    raise ResearchError(
                        "peer_address_changed", "Connected peer differs from pinned IP"
                    )
                return sock
            except BaseException:
                sock.close()
                raise

        connection._create_connection = create_connection
        started = time.monotonic()
        try:
            target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            connection.request(
                "GET",
                target,
                headers={
                    "Accept": "text/html,text/plain,text/markdown;q=0.9",
                    "Accept-Encoding": "identity",
                    "User-Agent": "PDOS-PublicResearch/1",
                },
            )
            response = connection.getresponse()
            length = response.getheader("Content-Length")
            if length and (not length.isdigit() or int(length) > limits.max_body_bytes):
                raise ResearchError("body_limit", "Public response exceeds the byte budget")
            pieces, size = [], 0
            while True:
                remaining = limits.timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise ResearchError("read_timeout", "Public read exceeded its time budget")
                # Each socket read consumes the remaining total budget, not a fresh timeout.
                stream = getattr(response.fp, "raw", None)
                read_sock = getattr(stream, "_sock", None)
                if read_sock is not None:
                    read_sock.settimeout(remaining)
                chunk = response.read(min(64 * 1024, limits.max_body_bytes - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > limits.max_body_bytes:
                    raise ResearchError("body_limit", "Public response exceeds the byte budget")
                pieces.append(chunk)
            return HTTPResponse(response.status, tuple(response.getheaders()), b"".join(pieces))
        except (OSError, http.client.HTTPException) as exc:
            raise ResearchError("read_failed", "Public HTTP connection failed") from exc
        finally:
            connection.close()


class HostRateLimiter:
    """Shared across children, runs and event loops; Retry-After extends the host deadline."""

    def __init__(self, interval=0.1, *, monotonic=time.monotonic, sleep=asyncio.sleep):
        self.interval, self.monotonic, self.sleep = interval, monotonic, sleep
        self._deadlines, self._lock = {}, threading.Lock()

    async def wait(self, host: str, timeout: float):
        start = self.monotonic()
        while True:
            with self._lock:
                now = self.monotonic()
                delay = self._deadlines.get(host, now) - now
                if delay <= 0:
                    self._deadlines[host] = now + self.interval
                    return
            if self.monotonic() - start + delay > timeout:
                raise ResearchError(
                    "host_rate_limited", "Host backoff exceeds the current read budget"
                )
            await self.sleep(delay)

    def defer(self, host: str, retry_after: str | None):
        if not retry_after:
            return
        try:
            delay = float(retry_after)
            if not (0 <= delay < float("inf")):
                return
        except ValueError:
            try:
                deadline = parsedate_to_datetime(retry_after)
                delay = max(0, (deadline - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                return
        with self._lock:
            self._deadlines[host] = max(self._deadlines.get(host, 0), self.monotonic() + delay)


SHARED_HOST_LIMITER = HostRateLimiter()


class MarkdownParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self.ignored = [], [], []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self.ignored.append(tag)
        if self.ignored:
            return
        if tag == "title":
            self.in_title = True
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in {"p", "div", "section", "article", "tr", "blockquote"}:
            self.parts.append("\n\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
            return
        if tag == "title":
            self.in_title = False
        elif tag in {"p", "div", "section", "article", "tr", "blockquote"}:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if self.ignored:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.parts.append(data)


def extract_markdown(response: HTTPResponse, limits: ResourceLimits) -> tuple[str, str]:
    if len(response.body) > limits.max_body_bytes:
        raise ResearchError("body_limit", "Public response exceeds the byte budget")
    mime = (response.header("Content-Type") or "").lower()
    if response.body.startswith(b"%PDF-") or "application/pdf" in mime:
        raise ResearchError(
            "pdf_requires_isolated_parser", "Public PDF requires the isolated parser"
        )
    encoding = response.header("Content-Encoding")
    if encoding and encoding.lower() != "identity":
        raise ResearchError("unsupported_encoding", "Compressed content requires bounded decoding")
    if mime and not any(
        t in mime for t in ("text/html", "text/plain", "text/markdown", "application/xhtml+xml")
    ):
        raise ResearchError(
            "unsupported_content_type", "Public resource is not a supported text page"
        )
    charset = re.search(r"charset\s*=\s*[\"']?([\w-]+)", mime)
    try:
        text = response.body.decode(charset[1] if charset else "utf-8", errors="replace")
    except LookupError as exc:
        raise ResearchError(
            "unsupported_charset", "Public page declares an unsupported charset"
        ) from exc
    if "html" in mime or re.search(r"<(?:html|body|title|p)\b", text, re.I):
        parser = MarkdownParser()
        parser.feed(text)
        title = " ".join("".join(parser.title).split())
        markdown = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "".join(parser.parts)).strip()
    else:
        markdown = text.strip()
        title = next(
            (line.lstrip("# ").strip() for line in markdown.splitlines() if line.strip()), ""
        )
    if not markdown:
        raise ResearchError("empty_body", "Public page contains no readable text")
    if len(markdown) > limits.max_markdown_chars:
        raise ResearchError("markdown_limit", "Extracted text exceeds the character budget")
    return title, markdown
