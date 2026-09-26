"""Explicit selection of leaf PDF/XLSX MIME attachments from a stored EML original."""

import hashlib
from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import PurePath
from typing import Any

from app.domain.documents import MAX_DOCUMENT_BYTES, DocumentExtractionError, _safe_filename
from app.domain.email_documents import HEADERS, MAX_DEPTH, MAX_PARTS

PARSER_VERSION = "email-attachments.v1"
MEDIA = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def attachment_parts(content: bytes) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    try:
        message = BytesParser(policy=policy.default).parsebytes(content)
        if not any(name.lower() in HEADERS for name, _ in message.raw_items()):
            raise ValueError("missing email headers")
        items: list[dict[str, Any]] = []
        payloads: dict[str, bytes] = {}
        visited = 0

        def visit(part: Message, path: str, depth: int) -> None:
            nonlocal visited
            visited += 1
            if visited > MAX_PARTS or depth > MAX_DEPTH:
                raise DocumentExtractionError("邮件部分数量或层级超出当前范围")
            filename = part.get_filename()
            media = part.get_content_type()
            if (
                filename
                or part.get_content_disposition() == "attachment"
                or media == "message/rfc822"
            ):
                original = (
                    filename.encode("utf-8", "backslashreplace").decode("utf-8")
                    if filename
                    else None
                )
                entry: dict[str, Any] = {
                    "path": path,
                    "original_filename": original,
                    "declared_media_type": media,
                    "disposition": part.get_content_disposition(),
                    "content_id": str(part.get("Content-ID", "")),
                    "transfer_encoding": str(part.get("Content-Transfer-Encoding", "7bit")),
                    "status": "unsupported",
                    "filename": None,
                    "defects": [type(defect).__name__ for defect in part.defects],
                }
                items.append(entry)
                if part.is_multipart() or media == "message/rfc822":
                    entry["status"] = "nested_message_or_container"
                    return
                extension = PurePath(original or "").suffix.lower()
                if not original:
                    extension = next((ext for ext, value in MEDIA.items() if value == media), "")
                if extension not in MEDIA:
                    return
                safe_name = _safe_filename(original or f"email-part-{path}{extension}")
                if any(ord(char) < 32 for char in safe_name):
                    entry["status"] = "invalid_filename"
                    return
                entry["filename"] = safe_name
                encoding = str(part.get("Content-Transfer-Encoding", "7bit")).lower().strip()
                if encoding not in {"7bit", "8bit", "binary", "base64", "quoted-printable"}:
                    entry["status"] = "unsupported_encoding"
                    return
                payload = part.get_payload(decode=True)
                entry["defects"] = [type(defect).__name__ for defect in part.defects]
                if entry["defects"] or not isinstance(payload, bytes):
                    entry["status"] = "malformed_part"
                    return
                if not payload or len(payload) > MAX_DOCUMENT_BYTES:
                    entry["status"] = "invalid_size"
                    return
                entry |= {
                    "status": "available",
                    "media_type": MEDIA[extension],
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                payloads[path] = payload
                return
            if part.is_multipart():
                children = part.get_payload()
                if not isinstance(children, list):
                    raise DocumentExtractionError("邮件容器结构不完整")
                for index, child in enumerate(children, 1):
                    if isinstance(child, Message):
                        visit(child, f"{path}.{index}", depth + 1)

        visit(message, "1", 1)
        return items, payloads
    except (ValueError, RecursionError, LookupError, UnicodeError) as error:
        raise DocumentExtractionError("邮件附件结构或编码无法核对，请保留原件") from error
