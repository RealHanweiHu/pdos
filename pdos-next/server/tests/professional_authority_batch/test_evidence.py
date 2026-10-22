import ast
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select

from pdos_next.domain.professional_authority import service as actual
from pdos_next.domain.supply_execution import service as supply
from pdos_next.engines.supply_cost.common import SnapshotRef
from pdos_next.models import Artifact, OriginalSecurity
from tests.professional_authority.test_assessment import AT

from .professional_batch_harness import STAGE, BatchSession, clone


@pytest.fixture(autouse=True)
def original_security_ports(monkeypatch):
    # This suite substitutes source IO; actual RLS/source binding is covered in PG tests.
    import pdos_next.original_security as security
    import pdos_next.originals as originals

    monkeypatch.setattr(
        originals,
        "require_original",
        lambda s, ctx, pid, oid: SimpleNamespace(id=oid, product_id=pid),
    )
    monkeypatch.setattr(
        security,
        "security_row",
        lambda s, original, **kw: s.scalar(
            select(OriginalSecurity).where(OriginalSecurity.original_id == original.id)
        ),
    )


class EvidenceSession(BatchSession):
    def __init__(self, uploaded=False):
        super().__init__()
        self.refs = []
        for _index in range(2):
            identity = uuid4()
            original = uuid4() if uploaded else None
            self.artifacts[identity] = Artifact(
                id=identity,
                tenant_id=self.tenant,
                product_id=self.product,
                owner_id=self.subject,
                title="Synthetic",
                source_label="Synthetic",
                content="Synthetic",
                content_hash="a" * 64,
                visibility="category",
                revision=1,
                status="active",
                original_id=original,
                created_at=AT,
            )
            self.refs.append(
                {
                    "artifact_id": str(identity),
                    "expected_revision": 1,
                    "line": 1,
                    "quote": "Synthetic",
                }
            )
            if original:
                self.safeties[original] = SimpleNamespace(
                    epoch=1, source_state="active", disposition="allowed"
                )
        self.identity_map.update(self.artifacts)
        self.source_hook = None
        self.security_hook = None

    def scalar(self, query):
        if (
            query.column_descriptions[0]["entity"].__name__ == "OriginalSecurity"
            and self.security_hook
        ):
            hook, self.security_hook = self.security_hook, None
            hook(self)
        return super().scalar(query)


def sources(s, ctx, pid, reads, references=()):
    s.events.append(("sources", "start"))
    values = {}
    for identity, artifact in s.artifacts.items():
        key = f"artifact:{identity}"
        values[key] = SnapshotRef(
            source_id=key,
            version="1",
            sha256=artifact.content_hash,
            captured_at=AT,
            valid_until=s.grant.expires_at,
            state="current",
        )
        if artifact.original_id:
            key = f"original:{artifact.original_id}"
            values[key] = SnapshotRef(
                source_id=key,
                version="1",
                sha256="b" * 64,
                captured_at=AT,
                valid_until=s.grant.expires_at,
                state="current",
            )
    if s.source_hook:
        s.source_hook(s)
    s.events.append(("sources", "finished"))
    return values, False


def call(function, session):
    return function(session, session.ctx, session.product, session.refs)


@pytest.mark.parametrize("uploaded", [False, True])
def test_complete_native_and_uploaded_source_material_security_matches(uploaded, monkeypatch):
    monkeypatch.setattr(supply, "_sources", sources)
    session = EvidenceSession(uploaded)
    old, new = clone(session), clone(session)
    assert call(actual._evidence, old) == call(actual._evidence, new)
    assert ("batch", "Artifact") not in new.events
    assert new.events.index(("sources", "finished")) < new.events.index(("get", "Artifact"))


def test_sources_callback_effect_is_seen_by_only_post_sources_metadata(monkeypatch):
    monkeypatch.setattr(supply, "_sources", sources)
    session = EvidenceSession(True)
    replacement_original = uuid4()

    def rotate(s):
        artifact = s.artifacts[sorted(s.artifacts, key=str)[-1]]
        artifact.original_id = replacement_original
        s.safeties[artifact.original_id] = SimpleNamespace(
            epoch=3, source_state="active", disposition="allowed"
        )

    session.source_hook = rotate
    old, new = clone(session), clone(session)
    assert call(actual._evidence, old) == call(actual._evidence, new)
    assert call(actual._evidence, clone(session))[2]["security"][-1]["security_epoch"] == 3


@pytest.mark.parametrize("tracked", ["new", "dirty", "deleted"])
def test_pending_artifact_never_refreshed_by_new_bulk(tracked, monkeypatch):
    monkeypatch.setattr(supply, "_sources", sources)
    session = EvidenceSession()
    artifact = next(iter(session.artifacts.values()))
    artifact.status = "withdrawn"
    getattr(session, tracked).append(artifact)
    old, new = clone(session), clone(session)
    assert call(actual._evidence, old) == call(actual._evidence, new)
    assert ("batch", "Artifact") not in new.events
    assert new.artifacts[artifact.id].status == "withdrawn"
    # The real _sources guard handles withdrawal. Here it is a SQL port substitute
    # solely checking that the new metadata read never overwrites pending state.


def test_uploaded_security_sql_boundary_keeps_later_artifact_fresh_get(monkeypatch):
    monkeypatch.setattr(supply, "_sources", sources)
    session = EvidenceSession(True)
    replacement_original = uuid4()

    def replace_later(s):
        identity = sorted(s.artifacts, key=str)[-1]
        changed = deepcopy(s.artifacts[identity])
        changed.original_id = replacement_original
        s.artifacts[identity] = changed
        s.safeties[changed.original_id] = SimpleNamespace(
            epoch=7, source_state="active", disposition="allowed"
        )

    session.security_hook = replace_later
    old, new = clone(session), clone(session)
    before = call(actual._evidence, old)
    after = call(actual._evidence, new)
    assert before == after
    assert before[2]["security"][-1]["security_epoch"] == 7
    assert after[2]["security"][-1]["security_epoch"] == 7
    assert ("batch", "Artifact") not in new.events
    path = STAGE / "unsafe_artifact_metadata_history.py"
    nodes = [
        node
        for node in ast.parse(path.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name in {"_batch_identity_rows", "_evidence"}
    ]
    namespace = dict(vars(actual))
    namespace["inspect"] = inspect
    namespace["OriginalSecurity"] = OriginalSecurity
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    unsafe = call(namespace["_evidence"], clone(session))
    assert unsafe != before and unsafe[2]["security"][-1]["security_epoch"] == 1
    # The final candidate preserves the original uploaded/mixed interleaving.
