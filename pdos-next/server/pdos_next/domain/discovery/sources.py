"""Concrete current-source guard over a server reader; no database/network access.

The narrow structured-JSON verifier proves whole-field correspondence. Ordinary
prose/translation stays pending; a source ID/hash does not verify arbitrary values.
"""

import hashlib
import json
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field

from pdos_next.errors import DomainError
from pdos_next.schemas.discovery.contracts import DTO, Citation, Location, Observation, Verification

from .ports import Authority


class LineMap(DTO):
    derived_line_start: int = Field(ge=1)
    derived_line_end: int = Field(ge=1)
    location: Location


class SourceSnapshot(DTO):
    """Server read under source/original locks, never an import payload."""

    artifact_id: UUID
    tenant_id: UUID
    revision: int
    active: bool
    readable: bool
    visibility: Literal["private", "category", "audience"]
    allowed_scope_ids: tuple[UUID, ...]
    allowed_product_ids: tuple[UUID, ...] = ()
    content: str
    content_hash: str
    original_id: UUID | None = None
    original_version: str | None = None
    original_hash: str | None = None
    original_usable: bool = False
    locator_map: tuple[LineMap, ...] = ()


class SourceReader(Protocol):
    def read(self, authority: Authority, source: Citation) -> SourceSnapshot:
        """Return current ACL and trusted immutable content, locks held to commit."""
        ...


class PinnedSources:
    def __init__(self, reader: SourceReader):
        self.reader = reader

    def check(self, authority: Authority, source: Citation) -> None:
        row = self.reader.read(authority, source)
        if (
            not row.readable
            or row.tenant_id != authority.tenant_id
            or authority.scope_id not in row.allowed_scope_ids
            or (
                authority.product_id is not None
                and authority.product_id not in row.allowed_product_ids
            )
            or (row.visibility == "private" and authority.audience != "private")
        ):
            raise DomainError("FORBIDDEN_SCOPE", "来源权限、研究绑定或受众已变化。", 403)
        if not row.active or row.artifact_id != source.artifact_id:
            raise DomainError("SOURCE_UNAVAILABLE", "来源已撤回或不再可用。")
        if row.revision != source.expected_revision or row.content_hash != source.content_hash:
            raise DomainError("SOURCE_STALE", "固定来源版本或内容身份已变化。")
        if hashlib.sha256(row.content.encode()).hexdigest() != row.content_hash:
            raise DomainError("INTEGRITY_MISMATCH", "来源正文与内容摘要不一致。")
        lines = row.content.splitlines()
        if source.derived_line > len(lines) or source.quote not in lines[source.derived_line - 1]:
            raise DomainError("INTEGRITY_MISMATCH", "引用与指定原文行不对应。")
        if source.original_id != row.original_id:
            raise DomainError("INTEGRITY_MISMATCH", "原件身份不对应。")
        if row.original_id:
            if not row.original_usable:
                raise DomainError("SOURCE_UNAVAILABLE", "原件扫描/解析或有效状态尚未满足。")
            if (
                source.original_version != row.original_version
                or source.original_hash != row.original_hash
            ):
                raise DomainError("SOURCE_STALE", "不可变原件版本或摘要不对应。")
            matches = [
                entry.location
                for entry in row.locator_map
                if entry.derived_line_start <= source.derived_line <= entry.derived_line_end
            ]
            if matches != [source.location]:
                raise DomainError("INTEGRITY_MISMATCH", "精确原件位置不存在或映射有歧义。")
        elif source.location != Location(kind="line", line=source.derived_line):
            raise DomainError("INTEGRITY_MISMATCH", "文本来源位置不对应。")

    def verify(self, authority: Authority, observation: Observation) -> Verification:
        for source in observation.sources:
            self.check(authority, source)
        if observation.origin == "translation":
            return Verification(status="pending", reason="翻译尚需逐字段核对原文")
        expected = observation.model_dump(mode="json", include={"key", "kind", "statement", "spec"})

        def unique_fields(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate raw field")
                result[key] = value
            return result

        for source in observation.sources:
            try:
                raw = json.loads(source.quote, object_pairs_hook=unique_fields)
            except (ValueError, TypeError):
                return Verification(status="pending", reason="非结构化原文尚未核对所有解析字段")
            if raw != expected or observation.raw_text != source.quote:
                return Verification(status="pending", reason="原位置完整字段或原文与候选不对应")
        # This proves correspondence, not customer approval/accepted requirement/spec maturity.
        return Verification(status="verified", reason="精确位置结构化原值逐字段相等")
