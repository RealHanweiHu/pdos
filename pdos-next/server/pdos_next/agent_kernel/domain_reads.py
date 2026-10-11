"""Actual category/model and explicitly Run-bound sources; no root raw-text projection."""

from functools import partial
from typing import Literal
from uuid import UUID

from pydantic import Field

from pdos_next.errors import DomainError
from pdos_next.models import Category
from pdos_next.schema_base import StrictModel
from pdos_next.service import require_access, source_for


class EmptyInput(StrictModel):
    pass


class SearchInput(StrictModel):
    query: str = ""


class ArtifactInput(StrictModel):
    artifact_id: UUID
    cursor: int = Field(default=0, ge=0)
    page_size: int = Field(default=100, ge=1, le=500)


class PageInput(StrictModel):
    cursor: str | None = None
    page_size: int = Field(default=50, ge=1, le=200)


class KnowledgeInput(PageInput):
    kind: (
        Literal["boundary", "segment", "competitor", "voice", "regulation", "research_question"]
        | None
    ) = None
    status: Literal["active", "withdrawn"] | None = "active"
    origin: Literal["human", "ai_draft", "imported"] | None = None
    region: str | None = None
    include_history: bool = False


class ParameterInput(PageInput):
    parameter_ids: list[UUID] | None = None
    include_history: bool = False


class CompetitorInput(PageInput):
    parameter_ids: list[UUID] | None = None
    brand: str | None = None
    nature: Literal["measured", "claimed", "inferred", "unknown"] | None = None


SCHEMAS = {
    "category.read": EmptyInput,
    "category.list": EmptyInput,
    "product.baseline.read": EmptyInput,
    "evidence.search": SearchInput,
    "evidence.artifact.read": ArtifactInput,
    "category.knowledge.list": KnowledgeInput,
    "category.competitors.list": CompetitorInput,
    "category.parameters.list": ParameterInput,
}


class DomainReads:
    def __init__(self, store, commands):
        self.store, self.commands = store, commands

    def call(self, scope, arguments, *, name):
        payload = SCHEMAS[name].model_validate(arguments)
        if scope.category_id is None:
            raise DomainError("FORBIDDEN_SCOPE", "业务读取须绑定当前品类。", 403)
        with self.store.transaction(scope) as (session, run):
            ctx = self.commands.context(scope)
            if name in {
                "category.knowledge.list",
                "category.competitors.list",
                "category.parameters.list",
            }:
                from pdos_next.domain.preproject import category_reads

                values = payload.model_dump()
                if name == "category.parameters.list":
                    return category_reads.parameters(session, ctx, **values)
                if name == "category.competitors.list":
                    return category_reads.competitors(session, ctx, **values)
                return category_reads.knowledge(session, ctx, **values)
            if name in {"category.list", "category.read"}:
                require_access(session, ctx, scope.product_id)
                category = session.get(Category, scope.category_id)
                value = {
                    "id": str(category.id),
                    "key": category.key,
                    "name": category.name,
                    "purpose": category.purpose,
                    "revision": category.revision,
                }
                return [value] if name == "category.list" else value
            if name == "product.baseline.read":
                if scope.product_id is None:
                    raise DomainError("MISSING_REQUIRED_EVIDENCE", "本次运行尚未关联型号。")
                product = require_access(session, ctx, scope.product_id)
                return {
                    "id": str(product.id),
                    "name": product.name,
                    "purpose": product.purpose,
                    "revision": product.revision,
                    "visibility": product.visibility,
                }
            reads = {UUID(ref["artifact_id"]): ref for ref in run.read_sources}
            if name == "evidence.search":
                values = []
                # Search the complete explicit read set, returning only metadata to the root.
                for identity, ref in reads.items():
                    source = source_for(
                        session, ctx, scope.product_id, identity, ref["expected_revision"]
                    )
                    if payload.query.casefold() in source.title.casefold():
                        values.append(
                            {
                                "artifact_id": str(source.id),
                                "title": source.title,
                                "revision": source.revision,
                                "content_hash": source.content_hash,
                            }
                        )
                return values
            if scope.isolation != "extract" or payload.artifact_id not in scope.artifact_ids:
                raise DomainError("FORBIDDEN_SCOPE", "原文须在绑定来源的只读提取子任务读取。", 403)
            ref = reads.get(payload.artifact_id)
            if ref is None:
                raise DomainError("FORBIDDEN_SCOPE", "本次运行未绑定此原文。", 403)
            source = source_for(
                session, ctx, scope.product_id, payload.artifact_id, ref["expected_revision"]
            )
            lines = source.content.splitlines()
            end = min(len(lines), payload.cursor + payload.page_size)
            return {
                "artifact_id": str(source.id),
                "revision": source.revision,
                "content_hash": source.content_hash,
                "lines": [
                    {"line": index + 1, "text": lines[index]}
                    for index in range(payload.cursor, end)
                ],
                "next_cursor": end if end < len(lines) else None,
            }

    def handlers(self):
        return {name: partial(self.call, name=name) for name in SCHEMAS}
