"""Read uploaded RFC 5322 originals without following links or opening MIME attachments."""

from email import policy
from email.header import decode_header
from email.message import Message
from email.parser import BytesParser
from html.parser import HTMLParser
from typing import Any

from app.domain.documents import (
    MAX_DOCUMENT_CHARACTERS,
    DocumentExtractionError,
    DocumentTooLargeError,
    ExtractedFragment,
    _fragment,
)

PARSER = "email-original.v1"
HEADERS = {
    "from",
    "sender",
    "reply-to",
    "to",
    "cc",
    "bcc",
    "subject",
    "date",
    "message-id",
    "in-reply-to",
    "references",
}
MAX_PARTS = 500
MAX_DEPTH = 20


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.hidden: list[str] = []
        self.images = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"head", "script", "style", "template"}:
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag == "img":
            self.images += 1
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "blockquote"}:
            self.chunks.append("\n")
        elif tag in {"td", "th"}:
            self.chunks.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag in {"p", "div", "li", "tr", "blockquote"}:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.chunks.append(data)


def _header(raw: str) -> str:
    chunks = []
    for value, charset in decode_header(raw):
        decoded = (
            value.decode(charset or "ascii", errors="strict") if isinstance(value, bytes) else value
        )
        decoded.encode("utf-8", errors="strict")
        chunks.append(decoded)
    return "".join(chunks)


def extract_email(content: bytes) -> tuple[tuple[ExtractedFragment, ...], dict[str, Any]]:
    try:
        message = BytesParser(policy=policy.default).parsebytes(content)
    except (ValueError, RecursionError) as error:
        raise DocumentExtractionError("邮件原件结构无法解析") from error
    if not any(name.lower() in HEADERS for name, _ in message.raw_items()):
        raise DocumentExtractionError("未找到邮件头，请上传实际EML原件")
    fragments: list[ExtractedFragment] = []
    headers: list[dict[str, Any]] = []
    parts: list[dict[str, Any]] = []
    total = 0

    def add(locator: str, value: str) -> None:
        nonlocal total
        total += len(value)
        if total > MAX_DOCUMENT_CHARACTERS:
            raise DocumentTooLargeError("邮件文本超过200万字，请保留原件并拆分整理")
        fragments.extend(_fragment(locator, value, start_ordinal=len(fragments) + 1))

    raw_characters = 0
    occurrences: dict[str, int] = {}
    for name, raw in message.raw_items():
        key = name.lower()
        if key not in HEADERS:
            continue
        raw_characters += len(raw)
        if raw_characters > MAX_DOCUMENT_CHARACTERS:
            raise DocumentTooLargeError("邮件头原文超过当前解析范围")
        occurrences[key] = occurrences.get(key, 0) + 1
        locator = f"email:header:{key}:{occurrences[key]}"
        # Raw header strings can contain surrogate escaped octets; retain their byte
        # representation in the original, and identify the decoding failure separately.
        item: dict[str, Any] = {
            "name": name,
            "locator": locator,
            "raw": raw.encode("utf-8", "backslashreplace").decode("utf-8"),
        }
        try:
            value = _header(raw)
            add(locator, value)
            item |= {"status": "extracted", "decoded": value}
        except DocumentTooLargeError:
            raise
        except (LookupError, UnicodeError, ValueError):
            item |= {"status": "decode_failed", "decoded": None}
        headers.append(item)
        if len(headers) > 500:
            raise DocumentTooLargeError("邮件头数量超出当前解析范围")

    def visit(part: Message, path: str, depth: int, reason: str | None = None) -> None:
        if depth > MAX_DEPTH or len(parts) >= MAX_PARTS:
            raise DocumentTooLargeError("邮件MIME层级或部分数量超出当前解析范围")
        media = part.get_content_type()
        filename = part.get_filename()
        entry: dict[str, Any] = {
            "path": path,
            "media_type": media,
            "filename": filename,
            "charset": part.get_content_charset(),
            "transfer_encoding": str(part.get("Content-Transfer-Encoding", "7bit")),
            "status": "container",
            "defects": [type(defect).__name__ for defect in part.defects],
        }
        parts.append(entry)
        if (
            reason
            or part.get_content_disposition() == "attachment"
            or filename
            or media == "message/rfc822"
        ):
            entry |= {"status": reason or "attachment_not_read"}
            return
        if part.is_multipart():
            payload = part.get_payload()
            if not isinstance(payload, list):
                entry["status"] = "invalid_multipart"
                return
            preferred = None
            if media == "multipart/alternative":
                for desired in ("text/plain", "text/html"):
                    preferred = next(
                        (
                            i
                            for i, child in enumerate(payload)
                            if isinstance(child, Message)
                            and child.get_content_type() == desired
                            and child.get_content_disposition() != "attachment"
                            and not child.get_filename()
                        ),
                        None,
                    )
                    if preferred is not None:
                        break
            for i, child in enumerate(payload):
                if isinstance(child, Message):
                    visit(
                        child,
                        f"{path}.{i + 1}",
                        depth + 1,
                        "alternative_not_selected"
                        if preferred is not None and i != preferred
                        else None,
                    )
            return
        if media not in {"text/plain", "text/html"}:
            entry["status"] = "unsupported_part"
            return
        try:
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                entry["status"] = "body_unavailable"
                return
            # MIME defaults to ASCII, not a guessed local encoding. Any failure is
            # surfaced, leaving the original bytes available for human review.
            value = payload.decode(part.get_content_charset() or "ascii", errors="strict")
            entry["defects"] = [type(defect).__name__ for defect in part.defects]
            if entry["defects"]:
                entry["status"] = "malformed_part"
                return
            if media == "text/html":
                parser = _HtmlText()
                parser.feed(value)
                parser.close()
                value = "".join(parser.chunks)
                entry["images_not_read"] = parser.images
            add(f"email:part:{path}", value)
            entry |= {
                "status": "extracted" if value.strip() else "empty_body",
                "text_characters": len(value),
            }
        except (LookupError, UnicodeError, ValueError) as error:
            if isinstance(error, DocumentTooLargeError):
                raise
            entry["status"] = "decode_failed"

    visit(message, "1", 1)
    if not fragments:
        raise DocumentExtractionError("邮件未得到可核对文字，请保留原件并检查编码")
    return tuple(fragments), {
        "kind": "email",
        "parser_version": PARSER,
        "headers": headers,
        "parts": parts,
        "defects": [type(defect).__name__ for defect in message.defects],
        "scope": "selected_inline_text_only",
        "attachments_read": False,
        "external_resources_loaded": False,
        "sender_authenticated": False,
    }
