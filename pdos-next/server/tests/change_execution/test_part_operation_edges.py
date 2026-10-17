"""Actual ORM/query discovery with in-memory SQL and owner-view substitutes; no DB proof."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

from pdos_next.domain.builds.models import Build
from pdos_next.domain.change_execution import graph
from pdos_next.domain.configurations.models import (
    BomLine,
    BomRevision,
    EngineeringConfiguration,
    PartIdentity,
    ProcessRevision,
)
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import Ref
from pdos_next.schemas.verification.contracts import Scope


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class MemorySql:
    """Evaluate actual ORM WHERE expressions; never replace OwnerReader._query."""

    def __init__(self, rows):
        self.rows, self.queries = list(rows), []

    @classmethod
    def matches(cls, row, clause):
        if isinstance(clause, BooleanClauseList):
            results = [cls.matches(row, child) for child in clause.clauses]
            return all(results) if clause.operator is operators.and_ else any(results)
        assert isinstance(clause, BinaryExpression), clause
        left = getattr(row, clause.left.name)
        right = clause.right.value
        if clause.operator is operators.eq:
            return left == right
        if clause.operator is operators.in_op:
            return left in right
        raise AssertionError(f"Unexpected SQL predicate: {clause}")

    def scalars(self, statement):
        self.queries.append(statement)
        model = statement.column_descriptions[0]["entity"]
        rows = [
            row
            for row in self.rows
            if type(row) is model
            and all(self.matches(row, clause) for clause in statement._where_criteria)
        ]
        return Rows(sorted(rows, key=lambda row: str(row.id)))

    def scalar(self, statement):
        rows = self.scalars(statement).all()
        return rows[0] if rows else None


class ProjectedReader(graph.OwnerReader):
    """Owner SQL/ACL/version/project guards remain actual; source checking is a substitute."""

    def __init__(self, *args, source_status=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_status = source_status or {}

    def _load(self, ref):
        model = {
            "part": PartIdentity,
            "bom": BomRevision,
            "engineering_configuration": EngineeringConfiguration,
            "manufacturing_configuration": ProcessRevision,
            "operation": ProcessRevision,
            "spec": DefinitionRevision,
            "build": Build,
        }[ref.kind]
        row = graph._row(self.s, self.ctx, self.pid, model, ref.id)
        view = {"name": row.name if hasattr(row, "name") else "fixed definition"}
        if isinstance(row, BomRevision):
            view["lines"] = [
                {
                    "key": line.key,
                    "part_id": str(line.part_id),
                    "expected_part_revision": line.part_revision,
                }
                for line in self.s.rows
                if isinstance(line, BomLine)
                and (line.tenant_id, line.product_id, line.bom_id)
                == (row.tenant_id, row.product_id, row.id)
            ]
        elif isinstance(row, EngineeringConfiguration):
            view.update(
                definition_id=str(row.definition_id),
                definition_revision=row.definition_revision,
                bom_id=str(row.bom_id),
                bom_revision=row.bom_revision,
            )
        elif isinstance(row, ProcessRevision):
            view.update(
                engineering_configuration_id=str(row.engineering_configuration_id),
                engineering_revision=row.engineering_revision,
                operations=row.operations,
            )
            if ref.kind == "operation":
                view["selected_operation"] = next(
                    operation for operation in row.operations if operation["key"] == ref.key
                )
        elif isinstance(row, Build):
            engineering = self.s.scalar(
                select(EngineeringConfiguration).where(
                    EngineeringConfiguration.id == row.engineering_configuration_id
                )
            )
            process = self.s.scalar(
                select(ProcessRevision).where(
                    ProcessRevision.id == row.manufacturing_configuration_id
                )
            )
            view.update(
                engineering={"id": str(engineering.id), "revision": engineering.revision},
                manufacturing={"id": str(process.id), "revision": process.revision},
            )
        view["source_status"] = self.source_status.get(ref.id, "current")
        return row, view, [], {"fixed_owner": str(row.id), "revision": row.revision}


@pytest.fixture
def case():
    tenant, product, project, actor = (uuid4() for _ in range(4))
    scope = Scope(tenant_id=tenant, product_id=product, project_id=project)

    def make(model, **values):
        defaults = {"id": uuid4(), "tenant_id": tenant, "product_id": product}
        if model is not BomLine:
            defaults.update(owner_id=actor, visibility="category", revision=1)
        if hasattr(model, "name"):
            defaults["name"] = model.__name__
        return model(**(defaults | values))

    part, other_part = make(PartIdentity), make(PartIdentity)
    definition = make(DefinitionRevision)
    bom = make(BomRevision)
    engineering = make(
        EngineeringConfiguration,
        definition_id=definition.id,
        definition_revision=definition.revision,
        bom_id=bom.id,
        bom_revision=bom.revision,
    )
    operation = {
        "key": "assembly",
        "name": "实际装配工序",
        "bom_line_keys": ["seal", "spare_seal"],
        "depends_on": [],
        "sop": None,
    }
    process = make(
        ProcessRevision,
        engineering_configuration_id=engineering.id,
        engineering_revision=engineering.revision,
        operations=[operation],
    )
    lines = [
        make(BomLine, bom_id=bom.id, part_id=part.id, part_revision=1, key=key)
        for key in ("seal", "spare_seal")
    ]
    lines.append(
        make(BomLine, bom_id=bom.id, part_id=other_part.id, part_revision=1, key="body")
    )
    session = MemorySql([part, other_part, definition, bom, engineering, process, *lines])
    ctx = SimpleNamespace(tenant_id=tenant, requester_id=actor)
    reader = ProjectedReader(
        session, ctx, product, scope, graph.audience(product, actor, "category"), None
    )
    return SimpleNamespace(
        scope=scope,
        actor=actor,
        make=make,
        reader=reader,
        session=session,
        part=part,
        other_part=other_part,
        definition=definition,
        bom=bom,
        engineering=engineering,
        process=process,
        operation=operation,
    )


def part_links(case):
    ref = Ref(id=case.part.id, revision=1, kind="part")
    return ref, case.reader.links(case.reader.resolve(ref))


def test_exact_part_lines_produce_one_direct_operation_and_preserve_each_bom_line(case):
    _, links = part_links(case)
    assert [ref for ref, _ in links if ref.kind == "operation"] == [
        Ref(id=case.process.id, revision=1, kind="operation", key="assembly")
    ]
    assert {ref.key for ref, _ in links if ref.kind == "bom"} == {"seal", "spare_seal"}


def test_same_line_key_in_newer_bom_does_not_move_old_part_to_new_process(case):
    newer_bom = case.make(
        BomRevision, revision=2, series_id=case.bom.id, previous_id=case.bom.id,
        expected_previous_revision=1,
    )
    line = case.make(
        BomLine, bom_id=newer_bom.id, part_id=case.other_part.id, part_revision=1, key="seal"
    )
    newer_engineering = case.make(
        EngineeringConfiguration, revision=2, bom_id=newer_bom.id, bom_revision=2,
        definition_id=case.definition.id, definition_revision=1,
    )
    newer_process = case.make(
        ProcessRevision, revision=2, engineering_configuration_id=newer_engineering.id,
        engineering_revision=2, operations=[case.operation],
    )
    case.session.rows.extend([newer_bom, line, newer_engineering, newer_process])
    _, links = part_links(case)
    assert {ref.id for ref, _ in links if ref.kind == "operation"} == {case.process.id}
    assert {ref.id for ref, _ in links if ref.kind == "bom"} == {case.bom.id}


def test_part_used_by_two_independent_boms_keeps_both_explicit_operation_relations(case):
    bom = case.make(BomRevision)
    line = case.make(
        BomLine, bom_id=bom.id, part_id=case.part.id, part_revision=1, key="gasket"
    )
    engineering = case.make(
        EngineeringConfiguration, bom_id=bom.id, bom_revision=1,
        definition_id=case.definition.id, definition_revision=1,
    )
    process = case.make(
        ProcessRevision, engineering_configuration_id=engineering.id, engineering_revision=1,
        operations=[{**case.operation, "key": "inspect_gasket", "bom_line_keys": ["gasket"]}],
    )
    case.session.rows.extend([bom, line, engineering, process])
    operations = {ref for ref, _ in part_links(case)[1] if ref.kind == "operation"}
    assert operations == {
        Ref(id=case.process.id, revision=1, kind="operation", key="assembly"),
        Ref(id=process.id, revision=1, kind="operation", key="inspect_gasket"),
    }


@pytest.mark.parametrize("absent", ["engineering", "process", "exact_line"])
def test_missing_actual_relation_never_guesses_from_names_or_same_bom(absent, case):
    if absent == "engineering":
        case.session.rows.remove(case.engineering)
    elif absent == "process":
        case.session.rows.remove(case.process)
    else:
        case.process.operations = [
            {
                **case.operation, "key": "named_after_part", "name": case.part.name,
                "bom_line_keys": [],
            },
            {**case.operation, "key": "different_part", "bom_line_keys": ["body"]},
            {**case.operation, "key": "missing_line", "bom_line_keys": ["not_registered"]},
        ]
    assert not any(ref.kind == "operation" for ref, _ in part_links(case)[1])


@pytest.mark.parametrize("broken", ["bom_revision", "engineering_revision", "part_revision"])
def test_reverse_discovery_does_not_upgrade_or_repair_fixed_version_mismatches(broken, case):
    # SQL-owner substitution deliberately returns inconsistent persisted material;
    # discovery must not repair it by silently changing a fixed reference.
    if broken == "bom_revision":
        case.engineering.bom_revision = 2
    elif broken == "engineering_revision":
        case.process.engineering_revision = 2
    else:
        for line in case.session.rows:
            if isinstance(line, BomLine) and line.part_id == case.part.id:
                line.part_revision = 2
    assert not any(ref.kind == "operation" for ref, _ in part_links(case)[1])


@pytest.mark.parametrize("foreign", ["tenant_id", "product_id"])
def test_reverse_queries_keep_real_tenant_and_product_scope(foreign, case):
    setattr(case.process, foreign, uuid4())
    assert not any(ref.kind == "operation" for ref, _ in part_links(case)[1])


def capture(case):
    ref = Ref(id=case.part.id, revision=1, kind="part")
    return graph.capture_graph(
        case.reader, identity=uuid4(), roots=(ref,), captured_at=datetime(2026, 10, 17, tzinfo=UTC),
        expires_at=datetime(2026, 10, 17, tzinfo=UTC) + timedelta(minutes=10),
        nature="synthetic", sources=(case.reader.resolve(ref).source,),
    )


def test_captured_edge_keeps_real_part_source_and_excludes_another_projects_build(case):
    other_build = case.make(
        Build, project_id=uuid4(), engineering_configuration_id=case.engineering.id,
        manufacturing_configuration_id=case.process.id,
    )
    case.session.rows.append(other_build)
    snapshot = capture(case)
    direct = [
        edge for edge in snapshot.edges
        if edge.origin.kind == "part" and edge.target.kind == "operation"
    ]
    assert len(direct) == 1
    assert direct[0].source == case.reader.resolve(direct[0].origin).source
    assert all(node.scope == case.scope for node in snapshot.nodes)
    assert not any(node.ref.id == other_build.id for node in snapshot.nodes)


def test_unreadable_process_is_not_exposed_as_an_operation_node(case):
    case.process.visibility, case.process.owner_id = "private", uuid4()
    snapshot = capture(case)
    assert not any(node.ref.id == case.process.id for node in snapshot.nodes)
    assert not any(edge.target.id == case.process.id for edge in snapshot.edges)


def test_new_reverse_edge_still_requires_the_real_target_currentness(case):
    case.reader.source_status[case.process.id] = "needs_recheck"
    with pytest.raises(DomainError) as caught:
        capture(case)
    assert caught.value.reason == "RECHECK_REQUIRED"


def test_spec_to_engineering_uses_existing_exact_definition_identity_without_future_nodes(case):
    ref = Ref(id=case.definition.id, revision=1, kind="spec")
    links = case.reader.links(case.reader.resolve(ref))
    assert [value for value, _ in links] == [
        Ref(id=case.engineering.id, revision=1, kind="engineering_configuration")
    ]
    case.engineering.definition_id = uuid4()
    assert case.reader.links(case.reader.resolve(ref)) == ()
