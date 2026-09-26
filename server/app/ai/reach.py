"""agent-reach v1: default-allow outbound reads with a fail-closed blocklist (D25).

D25 chose **默认放行 + blocklist** over an allowlist: an approval queue for every
new domain would make research unusable, and the material an engineer needs is
spread across the whole public web. The safety therefore does not come from
deciding *which* sites are acceptable — it comes from four hard limits that hold
whatever the target is:

1. **Read-only.** GET only. No POST, no credentials, no cookies, no auth headers.
   The tool cannot cause an effect on the far side, only observe.
2. **Nothing internal.** Every hostname is resolved and every resulting IP must
   be globally routable. This blocks loopback, RFC1918, link-local, and cloud
   metadata endpoints, and it is re-checked on every redirect hop — so DNS
   rebinding and open redirects cannot walk the fetcher back inside.
3. **No credential harvesting, no executables.** Login and OAuth paths are
   refused because fetching one is never research, and executable payloads are
   refused by extension *and* by Content-Type.
4. **Everything fetched becomes evidence.** The caller gets a snapshot id, and
   the snapshot is born `untrusted_external`. Per D25 the label travels with the
   citation rather than blocking the read — but a conclusion can only cite the
   snapshot, never the raw fetch.

The policy is deliberately separate from the transport so it can be tested
exhaustively without any network access.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from urllib.parse import unquote, urljoin, urlsplit
from uuid import UUID

from app.domain.evidence import EvidenceService

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_CONTENT_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3

# Fetching one of these is never research; it is either a credential prompt or
# an authenticated surface the agent has no business touching.
BLOCKED_PATH_MARKERS = (
    "/login",
    "/signin",
    "/sign-in",
    "/logon",
    "/session",
    "/oauth",
    "/openid",
    "/saml",
    "/password",
    "/passwd",
    "/reset",
    "/token",
    "/apikey",
    "/api-key",
    "/credential",
    "/wp-admin",
    "/phpmyadmin",
)

BLOCKED_EXTENSIONS = (
    ".exe",
    ".dll",
    ".msi",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".sh",
    ".bash",
    ".ps1",
    ".psm1",
    ".jar",
    ".apk",
    ".dmg",
    ".pkg",
    ".deb",
    ".rpm",
    ".bin",
    ".run",
    ".appimage",
)

# Names that only ever resolve inside an infrastructure boundary.
BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".internal",
    ".localdomain",
    ".cluster.local",
    ".svc",
)
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "instance-data",
    }
)

# Only these render as readable material. Anything else — octet-stream, a
# binary, an installer — is refused rather than snapshotted as garbage.
ALLOWED_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "application/atom+xml",
)


class ReachDeniedError(PermissionError):
    """Raised when the reach policy refuses a target. Carries the reason code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class ReachFetchError(RuntimeError):
    """Raised when a permitted target could not be read."""


class ReachRateLimitedError(RuntimeError):
    """Raised when a host's budget for this run is exhausted."""


@dataclass(frozen=True)
class ReachResponse:
    """What a transport must return for a single GET. Deliberately inert.

    The transport must NOT follow redirects itself: a 3xx comes back with its
    `location` so the policy can vet the next hop before it is opened.
    """

    status_code: int
    content: str
    content_type: str
    byte_size: int
    location: str | None = None
    source_version: str | None = None
    content_language: str | None = None


Resolver = Callable[[str], Sequence[str]]


def _default_resolver(hostname: str) -> Sequence[str]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError as error:
        raise ReachDeniedError("unresolvable_host", f"could not resolve {hostname}") from error
    # sockaddr is (host, port) for IPv4 and (host, port, flow, scope) for IPv6;
    # element 0 is the address in both, but the stub types it as str | int.
    return [str(info[4][0]) for info in infos]


def _deny(reason: str, message: str) -> ReachDeniedError:
    return ReachDeniedError(reason, message)


@dataclass
class ReachPolicy:
    """Vets a URL before any connection is opened, and again on every redirect."""

    resolver: Resolver = _default_resolver
    max_content_bytes: int = MAX_CONTENT_BYTES
    # Per-host budget for one agent run: a research tool should read a few pages
    # from a site, not crawl it.
    per_host_budget: int = 8
    _host_reads: dict[str, int] = field(default_factory=dict)

    def assert_url_allowed(self, url: str) -> str:
        """Return the normalized URL, or raise ReachDeniedError with a reason."""
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as error:
            raise _deny("malformed_url", "target URL is malformed") from error

        if parsed.scheme not in ALLOWED_SCHEMES:
            raise _deny(
                "scheme_not_allowed",
                f"only http and https may be read, not {parsed.scheme or 'empty'}",
            )
        # Credentials in a URL would be sent on the wire and land in the
        # snapshot's provenance; refuse rather than strip them silently.
        if parsed.username is not None or parsed.password is not None:
            raise _deny("credentials_in_url", "target URL carries credentials")

        hostname = parsed.hostname
        if not hostname:
            raise _deny("malformed_url", "target URL has no host")
        normalized = hostname.lower().rstrip(".")

        if normalized in BLOCKED_HOSTNAMES or normalized.endswith(BLOCKED_HOST_SUFFIXES):
            raise _deny("internal_host", f"{normalized} is an internal name")
        if port is not None and port not in {80, 443}:
            raise _deny(
                "port_not_allowed",
                "only the standard web ports may be read",
            )

        decoded_path = unquote(parsed.path).lower()
        if any(marker in decoded_path for marker in BLOCKED_PATH_MARKERS):
            raise _deny(
                "credential_surface",
                "login and credential pages are never research targets",
            )
        if decoded_path.endswith(BLOCKED_EXTENSIONS):
            raise _deny("executable_download", "executable downloads are not readable material")

        self._assert_public_address(normalized)
        return url

    def _assert_public_address(self, hostname: str) -> None:
        """Every address the name resolves to must be globally routable.

        Checking the resolved addresses rather than the name is what stops an
        attacker-controlled domain from pointing at 127.0.0.1 or the cloud
        metadata endpoint. Because the caller re-runs this on each redirect,
        a rebind between hops is caught too.
        """
        literal = _as_ip(hostname)
        addresses = [literal] if literal is not None else []
        if not addresses:
            resolved = self.resolver(hostname)
            if not resolved:
                raise _deny("unresolvable_host", f"could not resolve {hostname}")
            for candidate in resolved:
                address = _as_ip(candidate)
                if address is None:
                    raise _deny("unresolvable_host", f"{hostname} resolved to a non-address")
                addresses.append(address)

        for address in addresses:
            if not address.is_global or address.is_multicast:
                raise _deny(
                    "internal_address",
                    f"{hostname} resolves to non-public address {address}",
                )

    def note_read(self, hostname: str) -> None:
        """Count a completed read against the host budget (限流退避)."""
        key = hostname.lower()
        used = self._host_reads.get(key, 0) + 1
        if used > self.per_host_budget:
            raise ReachRateLimitedError(
                f"host read budget exhausted for {key}; back off and cite what is captured"
            )
        self._host_reads[key] = used

    def assert_response_allowed(self, response: ReachResponse) -> None:
        content_type = response.content_type.split(";")[0].strip().lower()
        if content_type in {
            "application/javascript",
            "application/ecmascript",
            "text/javascript",
            "text/ecmascript",
            "text/x-python",
            "text/x-shellscript",
        } or not (content_type.startswith("text/") or content_type in ALLOWED_CONTENT_TYPES[1:]):
            raise _deny(
                "content_type_not_readable",
                f"{content_type or 'unknown content type'} is not readable material",
            )
        if response.byte_size > self.max_content_bytes:
            raise _deny(
                "content_too_large",
                f"response exceeds the {self.max_content_bytes} byte reach limit",
            )


def _as_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    # Strip an IPv6 scope id (fe80::1%eth0) before parsing.
    candidate = value.split("%")[0]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


class ReachTransport(Protocol):
    """A single GET. Must not follow redirects, send credentials, or use POST."""

    def get(self, url: str) -> ReachResponse: ...


@dataclass(frozen=True)
class ReachResult:
    """A completed read, already recorded as evidence."""

    snapshot_id: UUID
    final_url: str
    content: str
    content_digest: str
    taint: str
    trust_tier: str
    redirect_chain: tuple[str, ...]
    reused_existing: bool


class ReachService:
    """Fetch a public page and record it as an evidence snapshot.

    The snapshot id is the only thing a conclusion may cite. Returning the text
    as well is a convenience for the same turn — it is not a citable reference,
    because text in a model's context has no provenance once it is paraphrased.
    """

    def __init__(
        self,
        *,
        transport: ReachTransport,
        evidence: EvidenceService,
        policy: ReachPolicy | None = None,
        before_read: Callable[[], None] | None = None,
    ) -> None:
        self._transport = transport
        self._evidence = evidence
        self._policy = policy or ReachPolicy()
        self._before_read = before_read

    def fetch(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        url: str,
        source_id: UUID | None = None,
        source_version: str | None = None,
        freshness_expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> ReachResult:
        current = self._policy.assert_url_allowed(url)
        chain: list[str] = [current]

        for _ in range(MAX_REDIRECTS + 1):
            hostname = urlsplit(current).hostname or ""
            self._policy.note_read(hostname)
            if self._before_read is not None:
                self._before_read()
            response = self._transport.get(current)

            if 300 <= response.status_code < 400:
                if not response.location:
                    raise ReachFetchError(
                        f"{current} returned {response.status_code} with no location"
                    )
                # Re-vet every hop: an open redirect pointing at 169.254.169.254
                # is the classic way past a first-hop-only check.
                nxt = urljoin(current, response.location)
                current = self._policy.assert_url_allowed(nxt)
                chain.append(current)
                continue

            if not 200 <= response.status_code < 300:
                raise ReachFetchError(f"{current} returned {response.status_code}")

            self._policy.assert_response_allowed(response)
            snapshot = self._evidence.capture(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                content=response.content,
                source_id=source_id,
                url=current,
                source_version=source_version or response.source_version,
                content_language=response.content_language or "und",
                # Never trusted at capture: reach material is external by
                # definition, and D25 labels rather than blocks it.
                taint="untrusted_external",
                freshness_expires_at=freshness_expires_at,
                now=now,
            )
            return ReachResult(
                snapshot_id=snapshot.id,
                final_url=current,
                content=response.content,
                content_digest=snapshot.content_digest,
                taint=snapshot.taint,
                trust_tier=snapshot.trust_tier,
                redirect_chain=tuple(chain),
                reused_existing=snapshot.reused_existing,
            )

        raise ReachFetchError(f"too many redirects starting at {url}")


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str


class ReachSearchUnavailableError(RuntimeError):
    """Raised when web_search is called with no search provider configured."""


class SearchProvider(Protocol):
    """A read-only search backend. Returns candidate URLs, never page content."""

    def search(self, query: str, *, limit: int) -> Sequence[SearchHit]: ...


class ReachSearchService:
    """Find candidate URLs. Every hit is still vetted before it can be fetched.

    With no provider configured this fails closed with a specific message. It
    deliberately does not degrade to "no results": an agent that cannot tell
    "nothing matched" from "search is switched off" will report the first as
    though it were evidence of absence.
    """

    def __init__(
        self,
        *,
        provider: SearchProvider | None = None,
        policy: ReachPolicy | None = None,
    ) -> None:
        self._provider = provider
        self._policy = policy or ReachPolicy()

    @property
    def is_available(self) -> bool:
        return self._provider is not None

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        if self._provider is None:
            raise ReachSearchUnavailableError(
                "no search provider is configured; set one up or fetch a known URL "
                "directly — this is not an empty result set"
            )
        if not query.strip():
            raise ValueError("search query is empty")
        hits: list[SearchHit] = []
        for hit in self._provider.search(query, limit=limit):
            # A hit the policy would refuse is dropped here rather than offered
            # to the model as a link it can never open.
            try:
                self._policy.assert_url_allowed(hit.url)
            except ReachDeniedError:
                continue
            hits.append(hit)
        return hits
