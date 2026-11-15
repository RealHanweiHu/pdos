"""Background keyword index for episodes (design §6.2, §14.5; P121 第 1 项).

Three rows per episode. The ``episode`` row holds the owner's own words (the user
goal, page material already removed). The ``answer`` row holds 小Pai's side of
the same record: the answer summary and the unfinished items (P121 第 1 项
revises "首期不收回答正文"; D482). The ``object`` row holds the titles of the
specific objects the Run focused on (materials it read, the source it was pinned
to), as they read when the episode was indexed (P121 第 1 项 "当时对象的标题";
D482 余项 ①). The rows stay apart so the owner's Session list search matches
own words only, and so a hit can say which side matched. Nothing here is
returned as text: memory.search rechecks each hit against the dependency
manifest before showing it.

The activity writes as the owner under ordinary row-level security, so an
answer or an object the owner can no longer read is not indexed. Failures are retried by
Temporal and never touch the answer path, which scans unindexed episodes
itself. Idempotency key = source ID + source version + embedding profile
version (+ tokenizer and code rule, so a new tokenizer re-indexes).
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
# The last kind is the newest; an episode without it is still pending (s0_0890).
KINDS = ("episode", "answer", "object")
ANSWER_CHARS = 8000
ANSWERED = ("completed", "partial")
# Fixed sentences the kernel writes when there is no answer of the model's own.
NO_ANSWER = ("结果未通过完整核对。", "运行预算已用完")
# Specific objects only. A scope object (category, product, proposal, project) is
# shared by every episode in that scope; with no rarity weighting its title would
# make each of them match any query that names the scope (D482).
TITLED = frozenset({"artifact", "source"})
OBJECTS_PER_EPISODE = 20
TITLE_CHARS = 200


def idempotency_key(episode_id, *, kind="episode", profile_version=PROFILE_NONE):
    from pdos_next.agent.enterprise_search.tokenizer import CODE_RULE, version

    return digest(["memory-index/v1", kind, str(episode_id), SOURCE_VERSION,
                   profile_version, version(), CODE_RULE])


def workflow_id(reference):
    # Keyed on the newest row kind, so episodes indexed before it existed are dispatched again.
    return (f"pdos-memory-index:{UUID(reference['tenant_id'])}:{UUID(reference['episode_id'])}:"
            f"{idempotency_key(reference['episode_id'], kind=KINDS[-1])[:16]}")


def summaries(session, episodes):
    """小Pai's own answer summary per episode Run, where this reader can read the Run."""
    from sqlalchemy import select

    from pdos_next.agent.kernel.graph import UNVERIFIED
    from pdos_next.agent.kernel.models import AgentRun

    if not episodes:
        return {}
    rows = session.execute(select(AgentRun.id, AgentRun.state, AgentRun.result).where(
        AgentRun.id.in_([episode.run_id for episode in episodes]),
        AgentRun.reverted_at.is_(None))).all()
    found = {}
    for identity, state, result in rows:
        summary = result.get("summary") if isinstance(result, dict) else None
        if state not in ANSWERED or not isinstance(summary, str):
            continue
        summary = summary.removesuffix(UNVERIFIED).strip()
        if summary and not summary.startswith(NO_ANSWER):
            found[identity] = summary[:ANSWER_CHARS]
    return found


def answer_texts(session, episodes):
    """Text of the ``answer`` row per episode: the answer summary and the unfinished items.

    Object titles are a row of their own (``object_texts``).
    """
    answers = summaries(session, episodes)
    texts = {}
    for episode in episodes:
        parts = [answers.get(episode.run_id, "")]
        unfinished = (episode.body.get("model_notes") or {}).get("unfinished") or []
        parts.extend(item for item in unfinished if isinstance(item, str))
        texts[episode.id] = "\n".join(part for part in parts if part)
    return texts


def object_texts(session, episodes):
    """Text of the ``object`` row per episode: titles of the specific objects its Run focused on.

    Each kind is resolved through the enterprise source catalog, which runs under
    this reader's ordinary row-level security: an object the reader cannot read
    now (revoked, withdrawn, deleted) is simply not found and not indexed. Scope
    objects are left out (see ``TITLED``).
    """
    from sqlalchemy import select

    from pdos_next.agent.enterprise_search.schemas import SOURCE_TYPES
    from pdos_next.agent.enterprise_search.sources import catalog, prepare_read

    wanted = {}
    for episode in episodes:
        ids = []
        for item in (episode.body.get("focus_objects") or [])[:OBJECTS_PER_EPISODE]:
            if not isinstance(item, dict) or item.get("kind") not in TITLED:
                continue
            try:
                ids.append(UUID(str(item["id"])))
            except (KeyError, ValueError):
                continue
        wanted[episode.id] = ids
    identities = sorted({identity for ids in wanted.values() for identity in ids}, key=str)
    titles = {}
    if identities:
        prepare_read(session, SOURCE_TYPES)
        source = catalog()
        # "artifact" focus IDs are artifact IDs and "source" focus IDs are the
        # catalog's object IDs; the artifact branch uses its own ID as object ID.
        for identity, title in session.execute(
            select(source.c.object_id, source.c.title)
            .where(source.c.object_id.in_(identities), source.c.is_current)
            .order_by(source.c.object_id, source.c.source_type)
        ).all():
            if isinstance(title, str) and title.strip():
                titles.setdefault(identity, " ".join(title.split())[:TITLE_CHARS])
    return {episode_id: "\n".join(dict.fromkeys(titles[i] for i in ids if i in titles))
            for episode_id, ids in wanted.items()}


def texts_for(session, episodes):
    """{episode id: {kind: text}} for every index row kind, as this reader can read now."""
    answers = answer_texts(session, episodes)
    objects = object_texts(session, episodes)
    return {episode.id: {"episode": episode.goal, "answer": answers[episode.id],
                         "object": objects[episode.id]} for episode in episodes}


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
        texts = texts_for(session, [episode])[episode.id]
        created = []
        for kind in KINDS:
            # Empty rows are written too, so the episode stops being pending.
            words = analyze(texts[kind])
            statement = insert(MemoryIndexEntry).values(
                tenant_id=episode.tenant_id, owner_id=episode.owner_id,
                session_id=episode.session_id, episode_id=episode.id, source_kind=kind,
                source_version=SOURCE_VERSION, profile_version=PROFILE_NONE,
                idempotency_key=idempotency_key(episode.id, kind=kind),
                terms=func.to_tsvector("simple", " ".join(words["terms"])),
                term_counts=words["counts"], codes=words["codes"], token_count=words["length"],
                tokenizer_version=version(), code_rule_version=CODE_RULE,
            ).on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"]).returning(
                MemoryIndexEntry.id
            )
            if session.execute(statement).scalar_one_or_none() is not None:
                created.append(kind)
    return {"episode_id": str(ref["episode_id"]), "indexed": bool(created), "rows": created}


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
