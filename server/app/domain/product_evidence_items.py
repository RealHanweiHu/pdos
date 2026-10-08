"""Independent item decisions derived from an immutable, authorized AI bundle.

Reads never materialize findings. A named review creates its item finding and
decision in one transaction; application reuses the original domain service.
"""

from copy import deepcopy
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select

from app.ai.product_work_context import key
from app.ai.product_work_runs import authorize
from app.ai.rollout_guard import require_live_key
from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.product_evidence_findings import (
    Apply,
    ProductEvidenceFindings,
    Read,
    Review,
    config,
    receipt,
)
from app.domain.product_workspace import ProductWorkError, _emit, digest


class ItemRead(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID
    parent_finding_id: UUID
    position: int = Field(ge=1, le=6)


class ItemReview(ItemRead):
    review: Review


def item_title(item: dict[str, Any]) -> str:
    return (
        str(
            item.get("title")
            or item.get("hypothesis")
            or " · ".join(str(item.get(field, "")) for field in ("brand", "model", "variant"))
        ).strip(" ·")[:512]
        or "产品工作候选"
    )


def virtual_item(run: Any, parent: Any, position: int) -> dict[str, Any]:
    _, field, _ = config(run)
    assessment = deepcopy(parent["proposed_payload"]["assessment"])
    items = assessment[field]
    if not 1 <= position <= len(items):
        raise ProductWorkError("此候选项不存在，请重新读取")
    item = items[position - 1]
    assessment[field] = [item]
    return {
        **parent,
        "id": uuid5(parent["id"], f"item:{position}"),
        "origin_key": f"product-evidence:{run['id']}:item:{position}",
        "title": item_title(item),
        "summary": "待逐条裁决；接受后仍须独立应用",
        "proposed_payload": {
            "version": "product-evidence-item-v1",
            "parent_finding_id": str(parent["id"]),
            "parent_digest": digest(parent["proposed_payload"]),
            "position": position,
            "source_digest": parent["proposed_payload"]["source_digest"],
            "assessment": assessment,
        },
    }


def validate_item_binding(
    c: Connection, context: AuthContext, run: Any, row: Any, *, lock: bool
) -> Any:
    payload = row["proposed_payload"]
    query = select(tables.findings).where(
        tables.findings.c.tenant_id == context.tenant.id,
        tables.findings.c.run_id == run["id"],
        tables.findings.c.id == UUID(payload["parent_finding_id"]),
        tables.findings.c.finding_type == config(run)[0],
    )
    parent = c.execute(query.with_for_update() if lock else query).mappings().one_or_none()
    if (
        parent is None
        or parent["status"] != "pending_review"
        or parent["proposed_payload"].get("parent_finding_id")
    ):
        raise ProductWorkError("原批次已办理或候选绑定失效，请重新读取")
    expected = virtual_item(run, parent, payload["position"])
    if (
        row["id"] != expected["id"]
        or row["origin_key"] != expected["origin_key"]
        or digest(payload) != digest(expected["proposed_payload"])
    ):
        raise ProductWorkError("候选项与原始 AI 结果不一致")
    return parent


def item_receipts(
    c: Connection, context: AuthContext, run: Any, parent: Any
) -> list[dict[str, Any]]:
    _, field, _ = config(run)
    saved = {
        row["id"]: row
        for row in c.execute(
            select(tables.findings).where(
                tables.findings.c.tenant_id == context.tenant.id,
                tables.findings.c.run_id == run["id"],
                tables.findings.c.finding_type == config(run)[0],
                tables.findings.c.proposed_payload["parent_finding_id"].as_string()
                == str(parent["id"]),
            )
        ).mappings()
    }
    result = []
    for position in range(1, len(parent["proposed_payload"]["assessment"][field]) + 1):
        virtual = virtual_item(run, parent, position)
        row = saved.get(virtual["id"], virtual)
        if row["id"] in saved:
            validate_item_binding(c, context, run, row, lock=False)
        result.append(receipt(row))
    return result


class ProductEvidenceItems(ProductEvidenceFindings):
    def _parent(
        self, c: Connection, context: AuthContext, space: UUID, body: ItemRead, *, write: bool
    ) -> tuple[Any, Any]:
        if write:
            authorize(c, context, space, None, write=True, lock=True)
        run, parent = self._load(
            c, context, space, Read(run_id=body.run_id, finding_id=body.parent_finding_id)
        )
        if (
            parent is None
            or parent["status"] != "pending_review"
            or parent["proposed_payload"].get("parent_finding_id")
        ):
            raise ProductWorkError("原批次已按整批办理，请读取原办理记录")
        if write:
            selection = run["run_context"]["product_work_selection"]
            require_live_key(key(selection["capability"]))
            line = selection["product_line_id"]
            authorize(c, context, space, UUID(line) if line else None, write=True)
            parent = (
                c.execute(
                    select(tables.findings)
                    .where(
                        tables.findings.c.id == parent["id"],
                        tables.findings.c.tenant_id == context.tenant.id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
        return run, parent

    def read_item(self, context: AuthContext, space: UUID, body: ItemRead) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            run, parent = self._parent(c, context, space, body, write=False)
            virtual = virtual_item(run, parent, body.position)
            row = (
                c.execute(
                    select(tables.findings).where(
                        tables.findings.c.tenant_id == context.tenant.id,
                        tables.findings.c.id == virtual["id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row:
                validate_item_binding(c, context, run, row, lock=False)
            return self.read_in_connection(c, context, run, row or virtual)

    def review_item(self, context: AuthContext, space: UUID, body: ItemReview) -> dict[str, Any]:
        with self.engine.begin() as c:
            run, parent = self._parent(c, context, space, body, write=True)
            virtual = virtual_item(run, parent, body.position)
            review = body.review
            if (
                review.run_id != body.run_id
                or review.finding_id != virtual["id"]
                or review.expected_digest != digest(virtual["proposed_payload"])
            ):
                raise ProductWorkError("候选位置、版本或运行绑定不一致")
            if review.proposal and len(review.proposal.items) != 1:
                raise ProductWorkError("逐条裁决只接受这一条核对内容")
            existing = c.execute(
                select(tables.findings.c.id).where(
                    tables.findings.c.tenant_id == context.tenant.id,
                    tables.findings.c.id == virtual["id"],
                )
            ).first()
            if not existing:
                # Copy AI provenance; all current write privileges are still checked below.
                fields = [
                    "id",
                    "tenant_id",
                    "project_id",
                    "scope_kind",
                    "run_id",
                    "model_invocation_id",
                    "agent_key",
                    "finding_type",
                    "origin_key",
                    "title",
                    "summary",
                    "proposed_payload",
                    "evidence_event_ids",
                    "confidence_basis_points",
                    "preflight_version",
                ]
                row = (
                    c.execute(
                        tables.findings.insert()
                        .values(**{field: virtual[field] for field in fields})
                        .returning(tables.findings)
                    )
                    .mappings()
                    .one()
                )
                _emit(c, context, space, row["finding_type"], "proposed", {**row, "version": 1})
            return self.review_in_connection(c, context, space, review)

    def apply_item(self, context: AuthContext, space: UUID, body: Apply) -> dict[str, Any]:
        with self.engine.begin() as c:
            run, row = self._load(c, context, space, body, write=True)
            if not row["proposed_payload"].get("parent_finding_id"):
                raise ProductWorkError("此入口只应用已逐条裁决的候选")
            return self.apply_in_connection(c, context, space, body)
