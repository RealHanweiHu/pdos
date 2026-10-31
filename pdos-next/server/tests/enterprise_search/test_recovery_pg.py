"""All registered source families read by one legitimate synthetic requester.

Historical nine/ten-family measurements remain their original evidence; this
candidate genuinely seeds thirteen with native commands and unchanged RLS.
"""
# ruff: noqa: F401, F811 -- imported fixtures register their actual command dependency tree

import hashlib
import json
import os
import statistics
import time
from collections import Counter
from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from change_execution.test_transactions import command as change_command
from change_execution.test_transactions import create_payload as change_payload
from external_wait_pg.test_workflow import create_record
from external_wait_pg.test_workflow import execute as wait_execute
from pdos_next.database import tenant_session
from pdos_next.enterprise_search import indexing
from pdos_next.enterprise_search.assistant_sources import current
from pdos_next.enterprise_search.events import EVENTS, process_event
from pdos_next.enterprise_search.models import SearchChunk, SearchCorpus, SearchSource, SearchTerm
from pdos_next.enterprise_search.query import SearchInput, search
from pdos_next.enterprise_search.recovery import context_reference, plan_rebuild, rebuild_batch
from pdos_next.enterprise_search.recovery_workflow import finish_rebuild
from pdos_next.enterprise_search.schemas import SOURCE_TYPES
from pdos_next.enterprise_search.sources import prepare_read, select_sources
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Grant, Outbox, Receipt, now
from pdos_next.service import digest
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_build_demand import compute
from test_project_first_plan import accepted, post
from test_supply_execution import TEXT, capture_input, recorded
from tests.enterprise_search.test_business_sources_pg import (
    accepted_work,
    change_work,
    created,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from tests.enterprise_search.test_retrieval_pg import index, register, session_for
from tests.preproject.test_g0 import request
from verification_handoff.fixtures import artifact as product_artifact


def add_knowledge(person, index_=0):
    response = post(
        person,
        request(
            person,
            "category.knowledge.add",
            {
                "kind": "boundary",
                "content": {"definition": f"Synthetic recovery knowledge {index_}"},
            },
        ),
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def all_sources(change_work, tmp_path):
    work = change_work
    quality = work.quality
    person = SimpleNamespace(
        **{
            **vars(quality),
            "tokens": {
                **quality.tokens,
                quality.human: quality.headers["Authorization"].removeprefix("Bearer "),
            },
        }
    )
    created(work)
    register(person, "Synthetic recovery artifact", "Synthetic recovery source evidence.")
    add_knowledge(person)
    # Native Build/readiness/supply commands require the real project owner.
    # These roots were category-shared when created; the quality requester reads
    # them via that actual audience while retaining its own private quality facts.
    owner = work.setup
    demand = compute(owner, work.config)
    demand["supply_source"] = product_artifact(owner, TEXT, "Synthetic supply recovery")[
        "artifact_id"
    ]

    def supply():
        payload = capture_input(demand)
        row = payload["records"][0]
        for key in ("source_system", "pool_id", "quality", "availability"):
            row.pop(key)
        row.update(
            record_kind="commitment",
            supplier_id="Synthetic recovery supplier",
            expected_at=(now() + timedelta(days=7)).isoformat(),
        )
        constraints = []

        def diagnostic(context):
            error = context.original_exception
            detail = getattr(error, "diag", None)
            constraints.append(
                (
                    getattr(error, "sqlstate", None),
                    getattr(detail, "constraint_name", None),
                    getattr(detail, "message_primary", None),
                )
            )

        event.listen(owner.engine, "handle_error", diagnostic)
        try:
            return recorded(owner, demand, payload=payload)[1]
        except AssertionError as error:
            raise AssertionError(f"{error}; constraint diagnostics={constraints}") from None
        finally:
            event.remove(owner.engine, "handle_error", diagnostic)

    supply()
    ref = {
        "kind": "artifact",
        "id": demand["supply_source"],
        "revision": 1,
        "position": "line:1;quote_sha256:" + hashlib.sha256(TEXT.encode()).hexdigest(),
    }
    wait = SimpleNamespace(setup=owner, project_id=UUID(work.config["project"]), source=ref)
    wait_number = 0

    def waiting():
        nonlocal wait_number
        wait_number += 1
        record = create_record()
        record["title"] += f" #{wait_number}"
        return wait_execute(wait, record)[1]

    waiting()
    # Native Field remains the tenth family; the current candidate also seeds
    # project status, manufacturing documents and the original physical handoff.
    from tests.enterprise_search.field_feedback_source_harness import create_feedback

    create_feedback(person, work.config)
    from tests.enterprise_search.role_native_source_harness import seed_manufacturing, seed_status

    seed_status(owner, work.config["project"])
    # Keep the actual issuer alive through all further native commands. The
    # nested helper restores this outer report store before yielding sources.
    with seed_manufacturing(person, work.config, tmp_path / "native-role-sources"):
        assert person.engine._pdos_change_store is work.report_store
        # The original results fixture already creates real offer/accept facts
        # owned by this same quality requester.
        sources = authority(person)
        assert set(SOURCE_TYPES) == {row["source_type"] for row in sources}, Counter(
            row["source_type"] for row in sources
        )
        yield SimpleNamespace(
            person=person, work=work, supply=supply, waiting=waiting, sources=sources
        )


def authority(person):
    with readonly(person) as session:
        prepare_read(session, SOURCE_TYPES)
        return [dict(row) for row in session.execute(select_sources(include_body=True)).mappings()]


def readonly(person):
    return tenant_session(
        person.engine,
        person.tenant,
        actor_id=person.human,
        requester_id=person.human,
        category_id=None,
        read_snapshot=True,
    )


def snapshot(person):
    with Session(person.admin) as session:
        chunks = [
            dict(row)
            for row in session.execute(
                select(SearchChunk.__table__)
                .where(SearchChunk.tenant_id == person.tenant)
                .order_by(SearchChunk.id)
            ).mappings()
        ]
        for row in chunks:
            row.pop("created_at")
        return digest(chunks)


def assert_statistics(person):
    with Session(person.admin) as session:
        chunks = session.scalars(
            select(SearchChunk).where(SearchChunk.tenant_id == person.tenant)
        ).all()
        corpus = session.get(SearchCorpus, person.tenant)
        expected = Counter()
        for chunk in chunks:
            expected.update(set(chunk.term_counts) | set(chunk.title_counts))
        assert (corpus.chunk_count, corpus.token_count) == (
            len(chunks),
            sum(row.token_count for row in chunks),
        )
        actual = dict(
            session.execute(
                select(SearchTerm.term, SearchTerm.document_count).where(
                    SearchTerm.tenant_id == person.tenant, SearchTerm.document_count > 0
                )
            ).all()
        )
        assert actual == expected


@pytest.mark.parametrize("damage", ["all_tables", "chunks_only", "statistics_only", "same_count"])
def test_all_registered_sources_rebuild_after_real_derived_damage_without_business_changes(
    all_sources,
    damage,
    record_property,
):
    person = all_sources.person
    ctx = replace(person.ctx, category_id=None)
    original_facts = digest(authority(person))
    initial = indexing.rebuild(person.engine, ctx)
    assert initial["failed"] == 0
    baseline = snapshot(person)
    with Session(person.admin) as session, session.begin():
        if damage in {"all_tables", "chunks_only"}:
            session.execute(delete(SearchChunk).where(SearchChunk.tenant_id == person.tenant))
        if damage == "all_tables":
            session.execute(delete(SearchSource).where(SearchSource.tenant_id == person.tenant))
        if damage in {"all_tables", "statistics_only"}:
            for model in (SearchCorpus, SearchTerm):
                session.execute(delete(model).where(model.tenant_id == person.tenant))
        if damage == "same_count":
            rows = session.scalars(
                select(SearchChunk).where(SearchChunk.tenant_id == person.tenant)
            )
            for row in rows:
                row.text, row.locator = "CORRUPTED_DERIVED_ONLY", {"line_start": 999}
                row.chunk_hash = hashlib.sha256(row.text.encode()).hexdigest()
                row.terms = "'corrupt':1"
    plan = plan_rebuild(person.engine, ctx)
    assert set(SOURCE_TYPES) == {row["source_type"] for row in plan["targets"]}
    batches, cursor = [], 0
    while True:
        batch = rebuild_batch(person.engine, plan, cursor)
        batches.append(batch)
        if batch["next_cursor"] is None:
            break
        cursor = batch["next_cursor"]
    outcome = finish_rebuild(plan, batches)
    assert outcome["status"] == "current" and outcome["ready"] == len(plan["targets"]), outcome
    assert snapshot(person) == baseline
    assert digest(authority(person)) == original_facts
    assert_statistics(person)
    record_property(
        "recovery_family_counts", str(Counter(row["source_type"] for row in plan["targets"]))
    )
    record_property("recovery_damage", damage)
    record_property("recovery_fixed_manifest", plan["manifest_digest"])


def test_all_registered_outbox_replays_do_not_duplicate_family_chunks_or_df(all_sources):
    person = all_sources.person
    indexing.rebuild(person.engine, replace(person.ctx, category_id=None))
    with Session(person.admin) as session:
        events = session.execute(
            select(Outbox, Receipt)
            .join(Receipt, Receipt.id == Outbox.receipt_id)
            .where(Outbox.tenant_id == person.tenant, Outbox.type.in_(EVENTS))
        ).all()
        references = [
            {
                "event_id": str(row.id),
                "event_type": row.type,
                "tenant_id": str(row.tenant_id),
                "category_id": str(row.category_id),
                "actor_id": str(row.actor_id),
                "requester_id": str(receipt.requester_id),
                "subject_id": str(row.subject_id),
                "subject_revision": row.subject_revision,
            }
            for row, receipt in events
        ]
    for reference in references:
        process_event(person.engine, reference)
        before = snapshot(person)
        process_event(person.engine, reference)
        assert snapshot(person) == before
    assert_statistics(person)


def test_registered_families_repair_wrong_derived_scope_identifiers_and_keys(all_sources):
    person = all_sources.person
    ctx = replace(person.ctx, category_id=None)
    assert indexing.rebuild(person.engine, ctx)["failed"] == 0
    baseline, facts = snapshot(person), digest(authority(person))
    for damage in ("category", "source_id", "source_type", "work_key", "chunk_id"):
        with Session(person.admin) as session, session.begin():
            rows = session.scalars(
                select(SearchChunk).where(SearchChunk.tenant_id == person.tenant)
            ).all()
            states = session.scalars(
                select(SearchSource).where(SearchSource.tenant_id == person.tenant)
            ).all()
            identities = {row.source_id: uuid4() for row in rows}
            for row in [*rows, *states]:
                if damage == "category":
                    row.category_id = uuid4()
                elif damage == "source_id":
                    row.source_id = identities[row.source_id]
                elif damage == "source_type":
                    # Issue and CAPA can intentionally share one version ID.
                    # Keep damaged types distinct so the existing unique key
                    # remains valid while every type is still wrong.
                    row.source_type = "damaged_" + row.source_type
                elif damage == "work_key":
                    row.work_key = "0" * 64
                elif isinstance(row, SearchChunk):
                    row.id = uuid4()
        result = indexing.rebuild(person.engine, ctx)
        assert result["failed"] == 0, (damage, result)
        assert snapshot(person) == baseline, damage
        assert digest(authority(person)) == facts
        assert_statistics(person)


def test_source_repair_preserves_other_sources_and_other_tenants_and_requires_actual_read(setup):
    target = register(
        setup, "Repair private source", "Exact source remains authoritative", "private"
    )
    neighbor = register(setup, "Preserved neighbor", "Other source must remain byte identical")
    index(setup, target)
    index(setup, neighbor)
    with Session(setup.admin) as session, session.begin():
        expected = session.scalar(select(SearchSource).where(SearchSource.source_id == target))
        fixed = (expected.source_revision, expected.content_hash)
        template = dict(
            session.execute(select(SearchChunk.__table__).where(SearchChunk.source_id == neighbor))
            .mappings()
            .first()
        )
        template.update(id=uuid4(), tenant_id=setup.other_tenant, source_id=uuid4())
        session.execute(SearchChunk.__table__.insert().values(**template))
        session.add(SearchCorpus(tenant_id=setup.other_tenant, chunk_count=7, token_count=9))
        session.add(SearchTerm(tenant_id=setup.other_tenant, term="SENTINEL", document_count=5))
        for model in (SearchChunk, SearchSource):
            for row in session.scalars(select(model).where(model.source_id == target)):
                row.category_id = uuid4()

    def preserved():
        with Session(setup.admin) as session:
            return digest(
                {
                    model.__tablename__: [
                        dict(row)
                        for row in session.execute(
                            select(model.__table__)
                            .where(
                                model.tenant_id == setup.other_tenant
                                if model in (SearchCorpus, SearchTerm)
                                else (model.tenant_id == setup.other_tenant)
                                | (model.source_id == neighbor)
                            )
                            .order_by(*model.__table__.primary_key)
                        ).mappings()
                    ]
                    for model in (SearchChunk, SearchSource, SearchCorpus, SearchTerm)
                }
            )

    untouched, corrupt = preserved(), snapshot(setup)
    with session_for(setup, actor=setup.peer, personal=True) as session:
        with pytest.raises(DomainError) as refused:
            indexing.project(
                session,
                replace(setup.ctx, actor_id=setup.peer, requester_id=setup.peer),
                "artifact",
                target,
                expected_source=fixed,
                force=True,
                repair_derived=True,
            )
        assert refused.value.reason == "SOURCE_UNAVAILABLE"
    assert snapshot(setup) == corrupt and preserved() == untouched
    with session_for(setup) as session:
        assert (
            indexing.project(
                session,
                setup.ctx,
                "artifact",
                target,
                expected_source=fixed,
                force=True,
                repair_derived=True,
            )["status"]
            == "ready"
        )
        session.execute(text("SELECT public.enterprise_index_statistics_repair()"))
    assert preserved() == untouched
    assert_statistics(setup)


def test_duplicate_projection_checks_actual_text_locator_and_postgresql_vectors(setup):
    identity = register(setup, "Exact repeat source", "Synthetic exact token evidence")
    index(setup, identity)
    baseline = snapshot(setup)
    for field, value in (
        ("text", "Same count corrupted body"),
        ("locator", {"line_start": 999}),
        ("terms", "'corrupt':1"),
    ):
        with Session(setup.admin) as session, session.begin():
            row = session.scalar(select(SearchChunk).where(SearchChunk.source_id == identity))
            setattr(row, field, value)
        assert index(setup, identity)["changed"] is True, field
        assert snapshot(setup) == baseline
        assert index(setup, identity)["changed"] is False
        assert_statistics(setup)


def test_fixed_batch_reports_changed_and_revoked_sources_without_substituting_current_values(setup):
    identity = register(setup, "Fixed recovery source", "Original fixed recovery body")
    index(setup, identity)
    plan = plan_rebuild(setup.engine, setup.ctx)
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, identity).revision += 1
        session.scalar(
            select(SearchSource).where(SearchSource.source_id == identity)
        ).category_id = uuid4()
    batch = rebuild_batch(setup.engine, plan)
    result = finish_rebuild(plan, [batch])
    assert result["status"] == "partial" and result["ready"] == 0
    assert result["unavailable"][0]["code"] == "SOURCE_STALE"
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, identity).status = "withdrawn"
    result = finish_rebuild(plan, [rebuild_batch(setup.engine, plan)])
    assert result["status"] == "partial" and result["ready"] == 0
    assert result["unavailable"][0]["code"] == "SOURCE_UNAVAILABLE"


def test_metadata_helper_cannot_read_bodies_assume_role_or_modify_other_tenants(setup):
    index(setup, register(setup, "Own tenant index", "Own derived metadata"))
    payload = {
        "key": "index-recovery-" + uuid4().hex,
        "name": "Synthetic hidden category",
        "purpose": "Prove tenant statistics retain unreadable derived metadata",
        "idempotency_key": str(uuid4()),
        "deidentified_confirmed": True,
    }
    preview = setup.client.post("/v1/categories/preview", headers=setup.headers, json=payload)
    assert preview.status_code == 200, preview.text
    created = setup.client.post(
        "/v1/categories",
        headers=setup.headers,
        json={
            **payload,
            "confirmation_token": preview.json()["confirmation_token"],
        },
    )
    assert created.status_code == 201, created.text
    second = UUID(created.json()["subject_id"])
    other_category = SimpleNamespace(
        **{**vars(setup), "category": second, "ctx": replace(setup.ctx, category_id=second)}
    )
    hidden = register(other_category, "Other category metadata", "Preserve private category index")
    index(other_category, hidden)
    with Session(setup.admin) as session, session.begin():
        session.add(SearchCorpus(tenant_id=setup.other_tenant, chunk_count=17, token_count=19))
        session.add(
            SearchTerm(tenant_id=setup.other_tenant, term="OTHER_TENANT", document_count=11)
        )
        for model in (SearchCorpus, SearchTerm):
            session.execute(delete(model).where(model.tenant_id == setup.tenant))
    with session_for(setup, actor=setup.peer, personal=True) as session:
        assert (
            session.scalar(
                select(func.count()).select_from(SearchChunk).where(SearchChunk.source_id == hidden)
            )
            == 0
        )
        session.execute(text("SELECT public.enterprise_index_statistics_repair()"))
        for statement in (
            "SET LOCAL ROLE pdos_enterprise_index_maintainer",
            "SELECT public.enterprise_index_statistics_repair("
            "'00000000-0000-0000-0000-000000000000')",
        ):
            with pytest.raises(DBAPIError), session.begin_nested():
                session.execute(text(statement))
    with Session(setup.admin) as session:
        assert session.get(SearchCorpus, setup.other_tenant).chunk_count == 17
        assert session.get(SearchTerm, (setup.other_tenant, "OTHER_TENANT")).document_count == 11
        role = session.execute(
            text(
                "SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreaterole "
                "FROM pg_roles WHERE rolname='pdos_enterprise_index_maintainer'"
            )
        ).one()
        assert not any(role)
        assert not session.scalar(
            text(
                "SELECT has_column_privilege('pdos_enterprise_index_maintainer',"
                "'public.enterprise_search_chunks','text','SELECT')"
            )
        )
        assert not session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN "
                "('pdos_next_app','pdos_agent','pdos_next_auth','pdos_next_dispatch') "
                "AND pg_has_role(rolname,'pdos_enterprise_index_maintainer','MEMBER'))"
            )
        )
        assert (
            session.scalar(
                select(func.count()).select_from(SearchChunk).where(SearchChunk.source_id == hidden)
            )
            > 0
        )
    with Session(setup.admin) as session, session.begin():
        session.execute(text("SET LOCAL ROLE pdos_enterprise_index_maintainer"))
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(text("SELECT text FROM public.enterprise_search_chunks"))
    assert_statistics(setup)


def test_registered_family_search_and_authority_batch_stay_constant_sql_and_under_one_second(
    all_sources,
    record_property,
):
    person = all_sources.person
    # Increase real derived workload across sources written by this same actor.
    for index_ in range(5):
        add_knowledge(person, index_ + 1)
        register(person, f"Synthetic scale artifact {index_}", "Synthetic recovery scale evidence.")
        all_sources.supply()
        all_sources.waiting()
        payload = change_payload(all_sources.work)
        payload["title"] += f" scale #{index_}"
        command, _inputs = change_command(all_sources.work, "change.request.create", payload)
        response = post(all_sources.work.quality, command)
        assert response.status_code == 200, response.text
    indexing.rebuild(person.engine, replace(person.ctx, category_id=None))
    source_rows = authority(person)
    family_counts = Counter(row["source_type"] for row in source_rows)
    assert set(family_counts) == set(SOURCE_TYPES)
    citations, expanded = {}, {}
    historical_families = []
    for kind in SOURCE_TYPES:
        family = [row for row in source_rows if row["source_type"] == kind]
        row = next((row for row in family if row["is_current"]), family[0])
        # Physical handoff facts become historical when the actual request later
        # advances through Start/results. Search that real history explicitly;
        # never manufacture an extra handoff or label the past fact Current.
        if not row["is_current"]:
            historical_families.append(kind)
        with readonly(person) as session:
            found = search(
                session,
                replace(person.ctx, category_id=None),
                SearchInput(
                    query=str(row["source_id"]),
                    source_types=[kind],
                    include_history=not row["is_current"],
                    limit=50,
                ),
            )
        assert found["items"], (kind, found)
        citations[str(uuid4())] = found["items"][0]
        expanded[(kind, str(row["source_id"]))] = found["items"][0]
    for row in source_rows:
        key = row["source_type"], str(row["source_id"])
        if not row["is_current"] or key in expanded:
            continue
        with readonly(person) as session:
            found = search(
                session,
                replace(person.ctx, category_id=None),
                SearchInput(
                    query=key[1],
                    source_types=[key[0]],
                    limit=1,
                ),
            )
        assert found["items"] and found["items"][0]["source_id"] == key[1], (key, found)
        expanded[key] = found["items"][0]
    expanded = {str(uuid4()): item for item in expanded.values()}
    assert len(expanded) > len(citations)
    modes = ("search", "verify_registered", "verify_expanded")
    durations, counts, statements = {mode: [] for mode in modes}, {mode: [] for mode in modes}, []
    profile_path = os.environ.get("PDOS_ENTERPRISE_PROFILE_PATH")
    first_sql, capture_trace, active_mode = [], False, None

    def track(_connection, _cursor, statement, parameters, _context, _many):
        statements.append(True)
        if capture_trace:
            first_sql.append({"mode": active_mode, "sql": statement, "parameters": parameters})

    event.listen(person.engine, "before_cursor_execute", track)
    # Exercise the prepared statement and RLS plans before measuring warm reads.
    # Forty observations keep empirical p95 within the measured distribution;
    # eleven observations with the default exclusive estimator can exceed max.
    warmup, measured = 5, 40
    try:
        for iteration in range(warmup + measured):
            for mode in modes:
                active_mode = mode
                capture_trace = bool(profile_path) and iteration == 0
                with readonly(person) as session:
                    statements.clear()
                    started = time.perf_counter()
                    if mode == "search":
                        value = search(
                            session,
                            replace(person.ctx, category_id=None),
                            SearchInput(
                                query="synthetic",
                                limit=50,
                            ),
                        )
                        assert value["coverage"]["status"] == "current" and value["returned"] > 0
                    else:
                        batch = citations if mode == "verify_registered" else expanded
                        actual, missing = current(session, batch)
                        assert not missing and len(actual) == len(batch), missing
                    durations[mode].append(time.perf_counter() - started)
                    counts[mode].append(len(statements))
    finally:
        event.remove(person.engine, "before_cursor_execute", track)
    if profile_path:
        # Explicit local diagnostics only: context/SQL binds contain synthetic
        # identities, never DSNs, bearer tokens, model credentials or bodies.
        with os.fdopen(
            os.open(profile_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as out:
            json.dump(
                {
                    "context": context_reference(replace(person.ctx, category_id=None)),
                    "request": {"query": "synthetic", "limit": 50},
                    "family_counts": dict(family_counts),
                    "authority_batch_sizes": [len(citations), len(expanded)],
                    "first_sql": first_sql,
                },
                out,
                default=str,
            )
    record_property("warmup_iterations", warmup)
    record_property("measured_iterations", measured)
    for mode in durations:
        p95 = statistics.quantiles(durations[mode][warmup:], n=20, method="inclusive")[18]
        record_property(mode + "_warm_p95_seconds", p95)
        record_property(mode + "_durations_seconds", durations[mode])
        record_property(mode + "_sql_counts", str(sorted(set(counts[mode]))))
    record_property("mixed_source_family_counts", str(family_counts))
    record_property("historical_families_in_authority_batch", historical_families)
    record_property("authority_batch_sizes", [len(citations), len(expanded)])
    print(
        json.dumps(
            {
                "family_counts": dict(family_counts),
                "context": context_reference(replace(person.ctx, category_id=None)),
                "authority_batch_sizes": [len(citations), len(expanded)],
                "warm_p95_seconds": {
                    mode: statistics.quantiles(
                        durations[mode][warmup:],
                        n=20,
                        method="inclusive",
                    )[18]
                    for mode in modes
                },
                "sql_counts": {mode: sorted(set(counts[mode])) for mode in modes},
            }
        )
    )
    for mode in durations:
        assert len(set(counts[mode])) == 1
        assert statistics.quantiles(durations[mode][warmup:], n=20, method="inclusive")[18] < 1.0
    assert set(counts["verify_registered"]) == set(counts["verify_expanded"])


@pytest.mark.parametrize("consumer_fails", [False, True])
def test_mixed_fixture_preserves_outer_report_bytes_until_issuer_teardown(
    tmp_path, monkeypatch, consumer_fails,
):
    """No DB: compose fixture lifetimes with real private stores and report bytes."""
    from pdos_next.domain.change_execution.service import configure_store
    from pdos_next.object_storage import LocalPrivateObjectStore, StorageFailure
    from tests.enterprise_search import role_native_source_harness as harness

    outer = LocalPrivateObjectStore(tmp_path / "outer-change-reports")
    content = b"Synthetic existing change report bytes"
    original = outer.put_new(content, media_type="text/plain")
    engine = SimpleNamespace(_pdos_change_store=outer, fixture_issuer_alive=False)
    person = SimpleNamespace(engine=engine)
    created = []

    def nested_fixture(actual_person, configuration, path):
        assert actual_person is person and configuration == "native-configuration"
        prior = engine._pdos_change_store
        inner = LocalPrivateObjectStore(path / "manufacturing-sources")
        with pytest.raises(StorageFailure) as unavailable:
            inner.read_original(original)
        assert unavailable.value.code == "OBJECT_NOT_FOUND"
        configure_store(engine, inner)
        engine.fixture_issuer_alive = True
        try:
            yield SimpleNamespace(engine=engine, inner=inner)
        finally:
            engine.fixture_issuer_alive = False
            configure_store(engine, prior)

    def save(work, kind):
        assert engine.fixture_issuer_alive and engine._pdos_change_store is work.inner
        created.append(kind)
        return {"kind": kind}

    monkeypatch.setattr(harness.manufacturing, "manufacturing_case", SimpleNamespace(
        __wrapped__=nested_fixture,
    ))
    monkeypatch.setattr(harness.manufacturing, "bootstrap_authority", lambda _work: None)
    monkeypatch.setattr(harness.manufacturing, "payload", lambda _work, kind: kind)
    monkeypatch.setattr(harness.manufacturing, "inputs", lambda _work, _kind, payload: payload)
    monkeypatch.setattr(harness, "save", save)
    expected = (
        pytest.raises(RuntimeError, match="synthetic consumer") if consumer_fails else nullcontext()
    )
    with expected:
        with harness.seed_manufacturing(person, "native-configuration", tmp_path / "inner") as rows:
            assert engine.fixture_issuer_alive
            assert set(rows) == {"work_instruction", "control_plan"} == set(created)
            assert engine._pdos_change_store is outer
            assert engine._pdos_change_store.read_original(original) == content
            if consumer_fails:
                raise RuntimeError("synthetic consumer")
    assert not engine.fixture_issuer_alive and engine._pdos_change_store is outer
