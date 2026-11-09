"""Which exported records were written or prepared by the AI identity.

A record is AI-drafted when its writer is an agent principal, or when its
receipt carries an AI run (the AI prepared it and a person confirmed it, T1).
Lookups are batched and run in the reader's own session, so row-level security
limits them exactly as it limits the page read.
"""

from uuid import UUID

from sqlalchemy import or_, select

from pdos_next.core.models import Principal, Receipt


def _ids(values) -> set[UUID]:
    out = set()
    for value in values:
        if value is None:
            continue
        out.add(value if isinstance(value, UUID) else UUID(str(value)))
    return out


class Provenance:
    def __init__(self, s, ctx, *, actors=(), receipts=(), subjects=()):
        self._agents: set[UUID] = set()
        self._receipts: set[UUID] = set()
        self._subjects: set[UUID] = set()
        actor_ids, receipt_ids, subject_ids = _ids(actors), _ids(receipts), _ids(subjects)
        rows = []
        if receipt_ids or subject_ids:
            rows = s.execute(
                select(
                    Receipt.id,
                    Receipt.subject_id,
                    Receipt.actor_id,
                    Receipt.agent_run_id,
                    Receipt.run_id,
                ).where(
                    Receipt.tenant_id == ctx.tenant_id,
                    or_(
                        Receipt.id.in_(receipt_ids or {UUID(int=0)}),
                        Receipt.subject_id.in_(subject_ids or {UUID(int=0)}),
                    ),
                )
            ).all()
        actor_ids |= {row.actor_id for row in rows}
        if actor_ids:
            self._agents = set(
                s.scalars(
                    select(Principal.id).where(
                        Principal.tenant_id == ctx.tenant_id,
                        Principal.id.in_(actor_ids),
                        Principal.kind == "agent",
                    )
                )
            )
        for row in rows:
            if row.agent_run_id or row.run_id or row.actor_id in self._agents:
                self._receipts.add(row.id)
                self._subjects.add(row.subject_id)

    def ai(self, *, actor=None, receipt=None, subject=None) -> bool:
        return bool(
            (actor is not None and _ids([actor]) & self._agents)
            or (receipt is not None and _ids([receipt]) & self._receipts)
            or (subject is not None and _ids([subject]) & self._subjects)
        )
