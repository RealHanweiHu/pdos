"""Explicit public DNS over verified TLS; no system/proxy changes or private fallback."""

import ipaddress
import json
import re

import httpx2

from app.ai.reach import BLOCKED_HOST_SUFFIXES, BLOCKED_HOSTNAMES, ReachDeniedError

ENDPOINT = "https://1.1.1.1/dns-query"


def resolve_public(hostname: str) -> tuple[str, ...]:
    try:
        name = hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as error:
        raise ReachDeniedError("unresolvable_host", "来源域名无效") from error
    try:
        literal = ipaddress.ip_address(name)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global or literal.is_multicast:
            raise ReachDeniedError("internal_address", "来源地址非公开")
        return (str(literal),)
    if name in BLOCKED_HOSTNAMES or name.endswith(BLOCKED_HOST_SUFFIXES):
        raise ReachDeniedError("internal_host", "内部域名不能作为公开来源")
    if len(name) > 253 or not re.fullmatch(r"[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})+", name):
        raise ReachDeniedError("unresolvable_host", "来源域名无效")
    addresses = []
    try:
        with httpx2.Client(timeout=4, trust_env=False, follow_redirects=False) as client:
            for record_type in (1, 28):
                with client.stream(
                    "GET",
                    ENDPOINT,
                    params={"name": name, "type": record_type},
                    headers={"Accept": "application/dns-json"},
                ) as response:
                    if response.status_code != 200:
                        raise ValueError("DNS HTTP response rejected")
                    raw = b""
                    for chunk in response.iter_bytes():
                        raw += chunk
                        if len(raw) > 16384:
                            raise ValueError("DNS response too large")
                body = json.loads(raw)
                if not isinstance(body, dict) or body.get("Status") != 0:
                    raise ValueError("DNS lookup failed")
                question = body.get("Question")
                if question != [{"name": name, "type": record_type}] and question != [
                    {"name": name + ".", "type": record_type}
                ]:
                    raise ValueError("DNS question mismatch")
                answers = body.get("Answer", [])
                if not isinstance(answers, list) or len(answers) > 32:
                    raise ValueError("DNS answer invalid")
                for item in answers:
                    if not isinstance(item, dict):
                        raise ValueError("DNS answer invalid")
                    if item.get("type") not in {1, 28}:
                        continue
                    address = ipaddress.ip_address(item["data"])
                    if not address.is_global or address.is_multicast:
                        raise ReachDeniedError("internal_address", "来源解析到非公开地址")
                    if address.version != (4 if item["type"] == 1 else 6):
                        raise ValueError("DNS address type mismatch")
                    addresses.append(str(address))
        if not addresses:
            raise ValueError("DNS returned no addresses")
    except (httpx2.HTTPError, ValueError, KeyError, TypeError) as error:
        raise ReachDeniedError("unresolvable_host", "公开DNS解析失败，请稍后重试") from error
    return tuple(dict.fromkeys(addresses))
