"""Direct actual authority binding; SQL is an explicit result substitute."""

from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path

from pdos_next.domain.professional_authority import service as actual
from pdos_next.domain.professional_authority.models import ProfessionalCurrent, ProfessionalFact
from pdos_next.models import Artifact
from tests.professional_authority.test_assessment import FakeSession

STAGE = Path(__file__).resolve().parent


class BatchSession(FakeSession):
    def __init__(self):
        super().__init__()
        self.new, self.dirty, self.deleted = [], [], []
        self.identity_map = dict(self.rows)
        self.no_autoflush = nullcontext()
        self.statements = []
        self.gets = []
        self.artifacts = {}
        self.safeties = {}
        self.events = []

    def get(self, model, identity):
        self.gets.append((model, identity))
        self.events.append(("get", model.__name__))
        if model is Artifact:
            return self.artifacts.get(identity)
        return super().get(model, identity)

    def scalars(self, query):
        self.statements.append(query)
        entity = query.column_descriptions[0]["entity"]
        if entity is ProfessionalCurrent:
            return (
                self.pointers[: query._limit_clause.value]
                if query._limit_clause is not None
                else self.pointers
            )
        assert entity in (ProfessionalFact, Artifact)
        assert query.get_execution_options()["autoflush"] is False
        assert query.get_execution_options()["populate_existing"] is True
        assert len(query._where_criteria) == 1
        predicate = query._where_criteria[0]
        assert predicate.left.key == "id" and predicate.operator.__name__ == "in_op"
        ids = predicate.right.value
        store = self.rows if entity is ProfessionalFact else self.artifacts
        self.events.append(("batch", entity.__name__))
        # Actual table PK means one row per ID; preserve caller pointer order
        # through map lookup rather than interpreting SQL return order.
        return [store[identity] for identity in reversed(ids) if identity in store]

    def scalar(self, query):
        entity = query.column_descriptions[0]["entity"]
        if entity.__name__ == "OriginalSecurity":
            self.events.append(("security", entity.__name__))
            identity = next(
                part.right.value for part in query._where_criteria if part.left.key == "original_id"
            )
            return self.safeties.get(identity)
        return super().scalar(query)


def evidence(s, ctx, pid, refs):
    # SQL/evidence port substitute deliberately exposes complete source basis.
    return actual._reads(refs), False, {"refs": deepcopy(refs), "security": [{"epoch": 1}]}


def install_assessment_ports(monkeypatch, source_port=evidence):
    monkeypatch.setattr(actual, "_project", lambda *args, **kwargs: (None, None))
    monkeypatch.setattr(actual, "_evidence", source_port)


def assessed(function, session, at, **kwargs):
    return function(
        session,
        session.ctx,
        session.product,
        session.project,
        "verification.request.create",
        "Synthetic dimensional request",
        at,
        **kwargs,
    )


def clone(session):
    # Keep the exact immutable trusted issuer/Engine object; clone synthetic rows.
    return deepcopy(session, {id(session.engine): session.engine})
