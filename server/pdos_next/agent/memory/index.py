"""Background keyword index for episodes (design §6.2, §14.5).

Only the owner's own words (the user goal, page material already removed) are
indexed; model notes and answers never enter the index (P84 第 7 项). The
activity writes as the owner under ordinary row-level security; failures are
retried by Temporal and never touch the answer path, which scans unindexed
episodes itself. Idempotency key = source ID + source version + embedding
profile version (+ tokenizer and code rule, so a new tokenizer re-indexes).
"""

from uuid import UUID

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert

from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from .models import MemoryEpisode, MemoryIndexEntry

PROFILE_NONE = "none"  # Episode vectorization is M2a ("本人会话记录" category).
SOURCE_VERSION = 1  # Episodes are immutable projections; corrections are separate marks.
REFERENCE_KEYS = {"tenant_id", "owner_id", "episode_id"}


def idempotency_key(episode_id, *, profile_version=PROFILE_NONE):
    from pdos_next.agent.enterprise_search.tokenizer import CODE_RULE, version

    return digest(["memory-index/v1", "episode", str(episode_id), SOURCE_VERSION,
                   profile_version, version(), CODE_RULE])


def workflow_id(reference):
    return (f"pdos-memory-index:{UUID(reference['tenant_id'])}:{UUID(reference['episode_id'])}:"
            f"{idempotency_key(reference['episode_id'])[:16]}")


def _reference(value):
    if not isinstance(value, dict) or set(value) != REFERENCE_KEYS:
        raise DomainError("FORBIDDEN_SCOPE", "索引只接受固定的情景引用。")
    return {key: UUID(str(value[key])) for key in REFERENCE_KEYS}


def index_episode(engine, reference):
    from pdos_next.agent.enterprise_search.tokenizer import CODE_RULE, analyze, version
    from pdos_next.core.database import tenant_session

    ref = _reference(reference)
    with tenant_session(engine, ref["tenant_id"], actor_id=ref["owner_id"],
                        requester_id=ref["owner_id"]) as session:
        episode = session.get(MemoryEpisode, ref["episode_id"])
        if episode is None or episode.owner_id != ref["owner_id"]:
            raise DomainError("FORBIDDEN_SCOPE", "情景记录已不在本人可读范围。")
        words = analyze(episode.goal)
        key = idempotency_key(episode.id)
        statement = insert(MemoryIndexEntry).values(
            tenant_id=episode.tenant_id, owner_id=episode.owner_id,
            session_id=episode.session_id, episode_id=episode.id, source_kind="episode",
            source_version=SOURCE_VERSION, profile_version=PROFILE_NONE, idempotency_key=key,
            terms=func.to_tsvector("simple", " ".join(words["terms"])),
            term_counts=words["counts"], codes=words["codes"], token_count=words["length"],
            tokenizer_version=version(), code_rule_version=CODE_RULE,
        ).on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"]).returning(
            MemoryIndexEntry.id
        )
        created = session.execute(statement).scalar_one_or_none()
    return {"episode_id": str(ref["episode_id"]), "indexed": created is not None}


async def dispatch_pending(engine, tenant_id, client, *, task_queue="pdos-next-domain-v1"):
    """Find episodes without a current index row; the dispatch role sees UUIDs only."""
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from pdos_next.agent.enterprise_search.tokenizer import version
    from pdos_next.core.database import tenant_session

    from .index_workflow import MemoryEpisodeIndex

    with tenant_session(engine, tenant_id) as session:
        rows = session.execute(
            text("SELECT * FROM memory_pending_index_references(:tenant,:tokenizer,100)"),
            {"tenant": tenant_id, "tokenizer": version()},
        ).mappings().all()
    delivered = unavailable = 0
    for row in rows:
        reference = {key: str(row[key]) for key in REFERENCE_KEYS}
        try:
            await client.start_workflow(
                MemoryEpisodeIndex.run, reference, id=workflow_id(reference),
                task_queue=task_queue, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            continue
        except Exception:
            unavailable += 1
        else:
            delivered += 1
    return {"pending": len(rows), "delivered": delivered, "unavailable": unavailable}
