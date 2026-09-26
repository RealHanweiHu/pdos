"""Issue closure → knowledge candidate (vNext V1-B7, I10).

Closing an Issue is the moment a team actually learned something, and it is
also the moment nobody has time to write it down. This turns the closure into a
draft candidate automatically.

Free zone (D32): the candidate is built by a deterministic rule from fields the
closer already filled in — no model call, no invention. It lands as a
`draft` memory that changes nothing until a *second* person verifies it, which
is the existing confirm-zone single action (four-eyes still applies).

A closure with nothing recorded produces no candidate: an empty note is worse
than none, because it teaches the team that the knowledge base is noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, select

from app.db.schema import tables
from app.domain.memories import MemoryDraft, MemoryRecord, MemoryService, MemorySourceError

MAX_TITLE = 512


@dataclass(frozen=True)
class CandidateOutcome:
    memory: MemoryRecord | None
    reason: str  # 'created' | 'already_exists' | 'nothing_learned'


def _section(label: str, value: str | None) -> str | None:
    text = (value or "").strip()
    return f"## {label}\n{text}" if text else None


def build_candidate_draft(
    *,
    title: str,
    issue_type: str,
    severity: str,
    root_cause: str | None,
    resolution: str | None,
    closure_criteria: str | None,
) -> MemoryDraft | None:
    """Assemble the candidate, or None when the closure recorded no learning."""
    sections = [
        section
        for section in (
            _section("根因", root_cause),
            _section("解决方案", resolution),
            _section("关闭标准", closure_criteria),
        )
        if section is not None
    ]
    # Root cause or resolution is what makes this reusable; closure criteria
    # alone only restates the exit condition.
    if not any(part.startswith(("## 根因", "## 解决方案")) for part in sections):
        return None
    return MemoryDraft(
        title=f"经验：{title}"[:MAX_TITLE],
        content="\n\n".join(sections),
        applicability=f"来自 {issue_type} 类问题的关闭闭环（严重度 {severity}）。",
        tags=("issue_closure", issue_type, severity),
    )


class KnowledgeCandidateService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._memories = MemoryService(engine)

    def from_issue_closure(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        issue_id: UUID,
        now: datetime | None = None,
    ) -> CandidateOutcome:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    tables.issues.c.title,
                    tables.issues.c.issue_type,
                    tables.issues.c.severity,
                    tables.issues.c.root_cause,
                    tables.issues.c.resolution,
                    tables.issues.c.closure_criteria,
                    tables.issues.c.closure_evidence_ref,
                ).where(
                    tables.issues.c.tenant_id == tenant_id,
                    tables.issues.c.project_id == project_id,
                    tables.issues.c.id == issue_id,
                )
            ).one_or_none()
        if row is None:
            return CandidateOutcome(memory=None, reason="nothing_learned")

        draft = build_candidate_draft(
            title=row.title,
            issue_type=row.issue_type,
            severity=row.severity,
            root_cause=row.root_cause,
            resolution=row.resolution,
            closure_criteria=row.closure_criteria,
        )
        if draft is None:
            return CandidateOutcome(memory=None, reason="nothing_learned")

        source_refs: list[dict[str, object]] = [
            {"kind": "issue", "reference": str(issue_id)},
        ]
        if row.closure_evidence_ref:
            source_refs.append({"kind": "closure_evidence", "reference": row.closure_evidence_ref})
        try:
            memory = self._memories.create(
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                draft=draft,
                source_issue_id=issue_id,
                source_refs=tuple(source_refs),
                now=now,
            )
        except MemorySourceError:
            # The per-Issue unique constraint already holds a candidate:
            # reopening and reclosing must not mint a second one.
            return CandidateOutcome(memory=None, reason="already_exists")
        return CandidateOutcome(memory=memory, reason="created")
