"""One request/transaction's authority and directly read source proof."""

from dataclasses import dataclass, field
from functools import wraps

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session


@dataclass
class RequestProof:
    transaction: object
    authority: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    source_rows: dict = field(default_factory=dict)
    read_rows: dict = field(default_factory=dict)
    scope_locks: set = field(default_factory=set)
    scalar_rows: dict = field(default_factory=dict)
    mutation_epoch: int = 0


def authority_current(rows, at):
    """Held membership rows still obey each actual temporary deadline."""
    return all(
        principal.active and (grant.expires_at is None or grant.expires_at > at)
        for principal, grant in rows
    )


@event.listens_for(Session, "before_flush")
def _remember_changed_tables(session, _flush, _instances):
    session.info["request_proof_changed_tables"] = {
        inspect(row).mapper.local_table.name
        for row in (*session.new, *session.dirty, *session.deleted)
    }


def _discard_row_values(proof):
    # A flush does not release row locks. Keep only their markers; loaded
    # values must be reread after a mutation with populate_existing.
    for key in tuple(proof.read_rows):
        held = key[0] == "locked-row" or (
            len(key) == 2 and isinstance(key[1], tuple) and key[1][0] == "locked"
        )
        if not held:
            del proof.read_rows[key]
    proof.scalar_rows.clear()


@event.listens_for(Session, "after_flush_postexec")
def _discard_changed_reads(session, _flush):
    tables = session.info.pop("request_proof_changed_tables", set())
    proof = session.info.get("request_proof")
    if proof is not None:
        _discard_row_values(proof)
        authority_changed = bool(
            tables & {"principals", "grants", "categories", "products", "object_audiences"}
        )
        if authority_changed:
            proof.authority.clear()
        if authority_changed or any(
            name == "artifact_versions"
            or name.startswith("original_")
            or name == "uploaded_originals"
            for name in tables
        ):
            proof.sources.clear()
            proof.source_rows.clear()
        proof.mutation_epoch += 1


@event.listens_for(Session, "after_soft_rollback")
def _discard_rolled_back_reads(session, _previous):
    proof = session.info.get("request_proof")
    if proof is not None:
        proof.authority.clear()
        proof.sources.clear()
        proof.source_rows.clear()
        proof.read_rows.clear()
        proof.scalar_rows.clear()
        proof.scope_locks.clear()
        proof.mutation_epoch += 1


@event.listens_for(Session, "do_orm_execute")
def _discard_direct_mutation_reads(state):
    if state.is_insert or state.is_update or state.is_delete:
        proof = state.session.info.get("request_proof")
        if proof is not None:
            _discard_row_values(proof)
            proof.authority.clear()
            proof.sources.clear()
            proof.source_rows.clear()
            proof.mutation_epoch += 1


def request_proof(session):
    transaction = session.get_transaction()
    if transaction is None:
        raise RuntimeError("A proof requires an active database transaction")
    proof = session.info.get("request_proof")
    if proof is None or proof.transaction is not transaction:
        proof = RequestProof(transaction)
        session.info["request_proof"] = proof
    return proof


def _snapshot_identity(session, model, identity):
    if (
        isinstance(session, Session)
        and session.info.get("read_snapshot")
        and not (session.new or session.dirty or session.deleted)
    ):
        loaded = session.identity_map.get(session.identity_key(model, identity))
        if loaded is not None and not inspect(loaded).expired:
            return loaded
    return None


def batch_read(session, model, identities, *, lock=False):
    """Read the complete direct set once under this transaction's RLS scope."""
    proof = request_proof(session)
    identities = set(identities) - {None}
    if not lock:
        for key in identities:
            loaded = _snapshot_identity(session, model, key)
            if loaded is not None:
                proof.read_rows.setdefault((model, key), loaded)
    missing = {
        key
        for key in identities
        if (model, key) not in proof.read_rows
        or proof.read_rows[(model, key)] is None
        or (lock and not proof.read_rows.get(("locked-row", model, key)))
    }
    if missing:
        query = select(model).where(model.id.in_(missing)).order_by(model.id)
        locked = (query.with_for_update() if lock else query).execution_options(
            populate_existing=True
        )
        rows = {row.id: row for row in session.scalars(locked)}
        proof.read_rows.update({(model, key): rows.get(key) for key in missing})
        if lock:
            proof.read_rows.update({("locked-row", model, key): True for key in rows})
    return {key: proof.read_rows[(model, key)] for key in identities}


def scoped_rows(session, key, query, *, lock=False):
    """Hold an exact query's rows once; a writer upgrades its dependency lock once."""
    proof = request_proof(session)
    saved = proof.read_rows.get(("query", key))
    if saved is None or (lock and not saved[0]):
        locked = (query.with_for_update() if lock else query).execution_options(
            populate_existing=True
        )
        rows = list(session.scalars(locked))
        saved = (lock, rows)
        if rows:
            proof.read_rows[("query", key)] = saved
    return saved[1]


def _held_reads(session, scope_id):
    if (
        isinstance(session, Session)
        and session.info.get("read_snapshot")
        and (session.new or session.dirty or session.deleted)
    ):
        from pdos_next.errors import DomainError

        raise DomainError("INVALID_READ_CONTEXT", "读取快照不能复用写入流程。")
    if not isinstance(session, Session) or session.new or session.dirty or session.deleted:
        return None
    if session.get_transaction() is None:
        return None
    proof = request_proof(session)
    if session.info.get("read_snapshot") or scope_id in proof.scope_locks:
        return proof
    return None


def snapshot_scalar(session, key, query, *, lock=False, scope_id=None):
    """Read once under a GET snapshot or an explicitly held command model lock.

    Audience edits and domain pointer writers take that same model gate. A lock
    upgrade still reads again; flush/rollback discard these scalar results.
    """
    proof = _held_reads(session, scope_id)
    if proof is None:
        return session.scalar(query.with_for_update() if lock else query)
    key = ("scope-scalar", scope_id, key)
    saved = proof.scalar_rows.get(key)
    if saved is None or (lock and not saved[0]):
        value = session.scalar(
            (query.with_for_update() if lock else query).execution_options(populate_existing=True)
        )
        saved = (lock, value)
        proof.scalar_rows[key] = saved
    return saved[1]


def scope_is_held(session, scope_id):
    """True only for this actual RR transaction or its acquired model gate."""
    return _held_reads(session, scope_id) is not None


def snapshot_rows(session, key, query, *, scope_id=None):
    """Complete direct rows under the same explicit snapshot/model gate."""
    proof = _held_reads(session, scope_id)
    if proof is None:
        return list(session.scalars(query))
    key = ("scope-rows", scope_id, key)
    if key not in proof.scalar_rows:
        proof.scalar_rows[key] = list(session.scalars(query))
    return proof.scalar_rows[key]


def snapshot_mappings(session, query, *, scope_id=None):
    """Share an exact raw query only under RR or the actual model gate."""
    import hashlib
    import json
    from copy import deepcopy

    proof = _held_reads(session, scope_id)
    if proof is None:
        return list(session.execute(query).mappings())
    compiled = query.compile()
    shape = str(compiled) + json.dumps(compiled.params, sort_keys=True, default=str)
    key = ("scope-mappings", scope_id, hashlib.sha256(shape.encode()).hexdigest())
    if key not in proof.scalar_rows:
        proof.scalar_rows[key] = tuple(dict(row) for row in session.execute(query).mappings())
    return deepcopy(proof.scalar_rows[key])


def snapshot_get(session, model, identity, *, scope_id=None):
    """Keep an RLS-loaded immutable identity alive inside its held read scope."""
    if _held_reads(session, scope_id) is None:
        if not isinstance(session, Session) and hasattr(session, "get"):
            return session.get(model, identity)
        return session.scalar(
            select(model).where(model.id == identity).execution_options(populate_existing=True)
        )
    # Rows already selected under this Session's RLS identity and actual RR/RO
    # transaction cannot cross an audience edit or import new business state.
    loaded = _snapshot_identity(session, model, identity)
    if loaded is not None:
        return loaded
    return snapshot_scalar(
        session,
        (model, scope_id, identity),
        select(model).where(model.id == identity),
        scope_id=scope_id,
    )


def command_inputs_once(function):
    """Validate/preview/apply share the locked inputs of one exact command transaction.

    Positional clocks are captured by the first assessment. Final action guards
    compare genuine fact/window deadlines against the injected current clock.
    This memo never survives a transaction or grants the old signer's identity.
    """

    @wraps(function)
    def bound(session, ctx, command, product, payload, *clocks, **options):
        from sqlalchemy.orm import Session

        if not isinstance(session, Session):
            return function(session, ctx, command, product, payload, *clocks, **options)
        # Read capability projections use a server-constructed invocation,
        # without a persisted command id or a confirmable command DTO.
        if not callable(getattr(command, "model_dump", None)):
            return function(session, ctx, command, product, payload, *clocks, **options)
        from pdos_next.database import require_context
        from pdos_next.service import digest

        require_context(session, ctx)
        proof = request_proof(session)
        key = (
            "command-inputs",
            function,
            ctx.tenant_id,
            ctx.category_id,
            ctx.actor_id,
            ctx.requester_id,
            ctx.run_id,
            ctx.agent_run_id,
            command.command_id,
            digest(command.model_dump(mode="json")),
            digest(payload.model_dump(mode="json")),
            product.revision,
            digest(options),
        )
        if key not in proof.read_rows:
            proof.read_rows[key] = function(
                session, ctx, command, product, payload, *clocks, **options
            )
        return proof.read_rows[key]

    return bound
