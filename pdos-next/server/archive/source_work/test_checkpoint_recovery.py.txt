"""Independent durable recovery checks; the caller supplies both verified test stores.

No credential or environment fallback is permitted. Missing checkpoint configuration skips
the integration cases; guard unit cases use a fake connection and never reach a database.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Claim,
    Invocation,
    Qualification,
    Receipt,
    Run,
    WorkRequest,
    now,
)
from pdos_next.runtime import capability, resume
from pdos_next.workflows.checkpoints import verified_checkpoint_url

checkpoint_required = pytest.mark.skipif(
    not os.environ.get("CHECKPOINT_DATABASE_URL"),
    reason="Explicit independent CHECKPOINT_DATABASE_URL required; no fallback",
)


@pytest.fixture
def checkpoint_url():
    explicit = os.environ.get("CHECKPOINT_DATABASE_URL")
    if not explicit:
        pytest.skip("Explicit independent CHECKPOINT_DATABASE_URL required; no fallback")
    verified = make_url(verified_checkpoint_url(explicit))
    assert verified.host == "127.0.0.1" and verified.database == "pdos_checkpoints"
    assert verified.port == int(os.environ["PDOS_STATE_DB_PORT"])
    assert verified.username == "pdos_checkpoint" and not verified.query
    return explicit


def command(setup, operation, payload, artifact=None):
    return {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
        "product_id": str(setup.product),
        "expected_revision": 1,
        "source_read_set": [{"artifact_id": artifact, "expected_revision": 1}] if artifact else [],
        "payload": payload,
    }


def prepared_work(setup):
    original = "Synthetic checkpoint fixture only\nPressure: 150 PSI\nTest conditions unknown"
    response = setup.client.post(
        "/v1/commands",
        headers=setup.headers,
        json=command(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic checkpoint source",
                "source_label": "Synthetic isolated recovery fixture",
                "content": original,
                "visibility": "private",
            },
        ),
    )
    assert response.status_code == 200, response.text
    artifact = response.json()["subject_id"]
    response = setup.client.post(
        "/v1/commands",
        headers=setup.headers,
        json=command(
            setup,
            "ai.work.start",
            {
                "artifact_id": artifact,
                "source_revision": 1,
                "goal": "Record exactly one synthetic sourced pressure claim",
            },
            artifact,
        ),
    )
    assert response.status_code == 200, response.text
    work_id = UUID(response.json()["subject_id"])
    with Session(setup.admin) as s, s.begin():
        s.add(
            Qualification(
                tenant_id=setup.tenant,
                writer_id=setup.agent,
                skill_version="source-claim@1",
                provider_version="synthetic-checkpoint@1",
                operation="evidence.claim.record",
                purpose="source_claim",
                evaluation_kind="synthetic",
                evaluation_ref="synthetic-isolated-checkpoint-fixture-only",
                expires_at=now() + timedelta(hours=1),
                active=True,
            )
        )
    return UUID(artifact), work_id


class CountingProvider:
    version = "synthetic-checkpoint@1"

    def __init__(self, setup):
        self.writer_id = setup.agent
        self.calls = 0

    def extract(self, *, goal, source, artifact_id):
        self.calls += 1
        assert "Synthetic checkpoint fixture only" in source
        return {
            "artifact_id": str(artifact_id),
            "line": 2,
            "quote": "Pressure: 150 PSI",
            "statement": "Synthetic pressure is declared 150 PSI; condition unknown",
            "nature": "extracted",
            "availability": "unknown",
            "visibility": "private",
        }


def run_view(setup, work_id):
    with tenant_session(setup.engine, setup.tenant) as s:
        run = s.scalar(select(Run).where(Run.work_id == work_id))
        work = s.get(WorkRequest, work_id)
        return {
            "id": run.id,
            "lease_id": run.lease_id,
            "lease_until": run.lease_until,
            "status": run.status,
            "work_status": work.status,
            "error_code": work.error_code,
        }


def assert_no_claim(setup):
    with tenant_session(setup.engine, setup.tenant) as s:
        assert s.scalar(select(func.count()).select_from(Claim)) == 0
        assert (
            s.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(Receipt.operation == "evidence.claim.record")
            )
            == 0
        )


def saved_graph_state(checkpoint_url, setup, run_id):
    with PostgresSaver.from_conn_string(verified_checkpoint_url(checkpoint_url)) as saver:
        graph = capability(CountingProvider(setup), saver)
        return graph.get_state({"configurable": {"thread_id": f"{setup.tenant}:{run_id}"}})


@checkpoint_required
def test_completed_checkpoint_and_domain_result_survive_independent_graph_reopen(
    checkpoint_url, setup
):
    _, work_id = prepared_work(setup)
    first_provider = CountingProvider(setup)
    first = resume(
        setup.engine,
        setup.ctx,
        work_id,
        first_provider,
        synthetic_mode=True,
        checkpoint_url=checkpoint_url,
    )
    run = run_view(setup, work_id)
    assert first["status"] == "completed" and first_provider.calls == 1
    state = saved_graph_state(checkpoint_url, setup, run["id"])
    assert state.values["candidate"]["statement"].startswith("Synthetic pressure")
    assert not state.next
    restarted_provider = CountingProvider(setup)
    restarted = resume(
        setup.engine,
        setup.ctx,
        work_id,
        restarted_provider,
        synthetic_mode=True,
        checkpoint_url=checkpoint_url,
    )
    assert restarted["result_id"] == first["result_id"] and restarted_provider.calls == 0
    with tenant_session(setup.engine, setup.tenant) as s:
        invocation = s.scalar(select(Invocation).where(Invocation.run_id == run["id"]))
        assert (
            invocation.status == "completed" and invocation.candidate == state.values["candidate"]
        )
        assert s.scalar(select(func.count()).select_from(Claim)) == 1


def checkpoint_failure():
    raise RuntimeError("Synthetic crash after durable checkpoint")


@checkpoint_required
def test_after_checkpoint_failure_restores_saved_candidate_without_second_send(
    checkpoint_url, setup
):
    _, work_id = prepared_work(setup)
    first_provider = CountingProvider(setup)
    with pytest.raises(DomainError) as failure:
        resume(
            setup.engine,
            setup.ctx,
            work_id,
            first_provider,
            synthetic_mode=True,
            checkpoint_url=checkpoint_url,
            after_checkpoint=checkpoint_failure,
        )
    assert failure.value.code == "MODEL_OUTPUT_INVALID" and first_provider.calls == 1
    run = run_view(setup, work_id)
    assert run["work_status"] == "waiting_input" and run["lease_id"] is None
    assert run["error_code"] == "MODEL_OUTPUT_INVALID"
    state = saved_graph_state(checkpoint_url, setup, run["id"])
    assert state.values["candidate"]["artifact_id"] and not state.next
    assert_no_claim(setup)
    restarted_provider = CountingProvider(setup)
    recovered = resume(
        setup.engine,
        setup.ctx,
        work_id,
        restarted_provider,
        synthetic_mode=True,
        checkpoint_url=checkpoint_url,
    )
    assert recovered["status"] == "completed" and restarted_provider.calls == 0
    with tenant_session(setup.engine, setup.tenant) as s:
        assert s.scalar(select(func.count()).select_from(Claim)) == 1
        assert (
            s.scalar(select(Invocation.status).where(Invocation.run_id == run["id"])) == "completed"
        )


class SyntheticWorkerExit(BaseException):
    """Simulates loss outside ordinary caught worker failures, without killing a process."""


@checkpoint_required
def test_started_unknown_window_is_not_blindly_reissued_after_expired_lease(checkpoint_url, setup):
    _, work_id = prepared_work(setup)

    class LostResultProvider(CountingProvider):
        def extract(self, **kwargs):
            super().extract(**kwargs)
            raise SyntheticWorkerExit("Synthetic process loss after provider send")

    first_provider = LostResultProvider(setup)
    with pytest.raises(SyntheticWorkerExit):
        resume(
            setup.engine,
            setup.ctx,
            work_id,
            first_provider,
            synthetic_mode=True,
            checkpoint_url=checkpoint_url,
        )
    run = run_view(setup, work_id)
    assert first_provider.calls == 1 and run["lease_id"] is not None
    with tenant_session(setup.engine, setup.tenant) as s:
        assert (
            s.scalar(select(Invocation.status).where(Invocation.run_id == run["id"])) == "started"
        )
    # Only this newly seeded synthetic run is altered; model input/invocation/history stay intact.
    with Session(setup.admin) as s, s.begin():
        s.get(Run, run["id"]).lease_until = now() - timedelta(seconds=1)
    restarted_provider = CountingProvider(setup)
    for _ in range(2):
        with pytest.raises(DomainError) as failure:
            resume(
                setup.engine,
                setup.ctx,
                work_id,
                restarted_provider,
                synthetic_mode=True,
                checkpoint_url=checkpoint_url,
            )
        assert failure.value.code == "MODEL_RESULT_UNKNOWN"
    assert restarted_provider.calls == 0
    assert_no_claim(setup)
    with tenant_session(setup.engine, setup.tenant) as s:
        invocation = s.scalar(select(Invocation).where(Invocation.run_id == run["id"]))
        assert invocation.status == "unknown" and invocation.error_code == "MODEL_RESULT_UNKNOWN"
        assert invocation.candidate is None


@checkpoint_required
def test_concurrent_resume_uses_one_active_run_lease(checkpoint_url, setup):
    _, work_id = prepared_work(setup)
    started, release = Event(), Event()

    class BlockingProvider(CountingProvider):
        def extract(self, **kwargs):
            candidate = super().extract(**kwargs)
            started.set()
            assert release.wait(10), "Synthetic provider was not released"
            return candidate

    first_provider, second_provider = BlockingProvider(setup), CountingProvider(setup)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(
            resume,
            setup.engine,
            setup.ctx,
            work_id,
            first_provider,
            synthetic_mode=True,
            checkpoint_url=checkpoint_url,
        )
        try:
            assert started.wait(10), "Synthetic provider was not entered"
            with pytest.raises(DomainError) as rejected:
                resume(
                    setup.engine,
                    setup.ctx,
                    work_id,
                    second_provider,
                    synthetic_mode=True,
                    checkpoint_url=checkpoint_url,
                )
            assert rejected.value.code == "RUN_IN_PROGRESS"
            assert second_provider.calls == 0
        finally:
            release.set()
        result = future.result(timeout=15)
    assert result["status"] == "completed" and first_provider.calls == 1
    assert run_view(setup, work_id)["lease_id"] is None


@checkpoint_required
@pytest.mark.parametrize(
    "changed,code",
    [
        ("source", "SOURCE_UNAVAILABLE"),
        ("qualification", "QUALIFICATION_REQUIRED"),
    ],
)
def test_restore_rechecks_current_source_and_qualification_before_domain_write(
    checkpoint_url,
    setup,
    changed,
    code,
):
    artifact, work_id = prepared_work(setup)
    provider = CountingProvider(setup)
    with pytest.raises(DomainError) as first_failure:
        resume(
            setup.engine,
            setup.ctx,
            work_id,
            provider,
            synthetic_mode=True,
            checkpoint_url=checkpoint_url,
            after_checkpoint=checkpoint_failure,
        )
    assert first_failure.value.code == "MODEL_OUTPUT_INVALID" and provider.calls == 1
    assert_no_claim(setup)
    with Session(setup.admin) as s, s.begin():
        if changed == "source":
            s.get(Artifact, artifact).status = "withdrawn"
        else:
            s.scalar(
                select(Qualification).where(
                    Qualification.writer_id == setup.agent,
                    Qualification.provider_version == provider.version,
                )
            ).active = False
    restarted_provider = CountingProvider(setup)
    with pytest.raises(DomainError) as rejected:
        resume(
            setup.engine,
            setup.ctx,
            work_id,
            restarted_provider,
            synthetic_mode=True,
            checkpoint_url=checkpoint_url,
        )
    assert rejected.value.code == code and restarted_provider.calls == 0
    assert_no_claim(setup)
    assert run_view(setup, work_id)["work_status"] == "waiting_input"


@pytest.mark.parametrize(
    "target",
    [
        "postgresql+psycopg://pdos_checkpoint:synthetic@127.0.0.1:57432/pdos_checkpoints",
        "postgresql+psycopg://pdos_checkpoint:synthetic@localhost:65109/pdos_checkpoints",
        "postgresql+psycopg://pdos_checkpoint:synthetic@127.0.0.1:65109/pdos_test",
        "postgresql+psycopg://pdos_next_app:synthetic@127.0.0.1:65109/pdos_checkpoints",
        "postgresql+psycopg://pdos_checkpoint:synthetic@127.0.0.1:65109/pdos_checkpoints?host=elsewhere",
    ],
)
def test_checkpoint_guard_rejects_nonselected_target_before_connect(monkeypatch, target):
    monkeypatch.setenv("PDOS_STATE_DB_PORT", "65109")
    monkeypatch.setenv("PDOS_STATE_DB_MARKER", "synthetic-marker-only")

    def forbidden(_url):
        raise AssertionError("A rejected checkpoint target must never connect")

    monkeypatch.setattr("pdos_next.workflows.checkpoints.engine_for", forbidden)
    with pytest.raises(RuntimeError, match="explicitly selected independent target"):
        verified_checkpoint_url(target)


def test_checkpoint_guard_rejects_marker_mismatch_and_disposes_fake_engine(monkeypatch):
    monkeypatch.setenv("PDOS_STATE_DB_PORT", "65109")
    monkeypatch.setenv("PDOS_STATE_DB_MARKER", "expected-synthetic-marker")

    class FakeEngine:
        disposed = False

        def connect(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _statement):
            return self

        def scalar_one(self):
            return "wrong-synthetic-marker"

        def dispose(self):
            self.disposed = True

    fake = FakeEngine()
    monkeypatch.setattr("pdos_next.workflows.checkpoints.engine_for", lambda _url: fake)
    with pytest.raises(RuntimeError, match="marker mismatch"):
        verified_checkpoint_url(
            "postgresql+psycopg://pdos_checkpoint:synthetic@127.0.0.1:65109/pdos_checkpoints"
        )
    assert fake.disposed
