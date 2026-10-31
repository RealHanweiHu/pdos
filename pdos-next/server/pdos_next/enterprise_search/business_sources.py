"""Explicit internal-field projectors, using ordinary domain and parent RLS only."""

from sqlalchemy import Integer, Text, and_, case, cast, column, exists, func, literal, null, select
from sqlalchemy.dialects.postgresql import JSONB, UUID, aggregate_order_by, array

from pdos_next.domain.builds.models import Build
from pdos_next.domain.change_execution.models import ChangeCurrent, ChangeRequestVersion
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.domain.external_wait.models import ExternalWaitCurrent, ExternalWaitVersion
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.supply_execution.models import SupplyCurrent, SupplySnapshot
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.models import Product

from .readable_sources import readable as shared_readable


def object_fields(value, *fields):
    parts = []
    for field in fields:
        label, path = (field, (field,)) if isinstance(field, str) else field
        selected = value
        for key in path:
            selected = selected[key]
        parts.extend((label, selected))
    return func.jsonb_build_object(*parts)


def array_fields(value, fields, *, name):
    rows = (
        func.jsonb_array_elements(func.coalesce(value, literal("[]").cast(JSONB)))
        .table_valued(column("value", JSONB), with_ordinality="ordinal")
        .render_derived(name=name)
    )
    return (
        select(
            func.coalesce(
                func.jsonb_agg(
                    aggregate_order_by(object_fields(rows.c.value, *fields), rows.c.ordinal)
                ),
                func.jsonb_build_array(),
            )
        )
        .select_from(rows)
        .scalar_subquery()
    )


def change_orders(value):
    rows = (
        func.jsonb_array_elements(value)
        .table_valued(column("value", JSONB), with_ordinality="ordinal")
        .render_derived(name="enterprise_change_orders")
    )
    row = rows.c.value
    data = func.jsonb_build_object(
        "id",
        row["id"],
        "plan_items",
        array_fields(
            row["plan"]["items"],
            (
                "id",
                "discipline",
                "verification_requirement",
                ("intent_kind", ("intent", "kind")),
            ),
            name="enterprise_change_items",
        ),
        "approvals",
        array_fields(
            row["approvals"],
            ("actor_id", "at", "discipline", "text"),
            name="enterprise_change_approvals",
        ),
        "implementations",
        array_fields(
            row["implementations"],
            (
                "item_id",
                "executor_id",
                "outcome",
                "occurred_at",
                "received_at",
                "note",
            ),
            name="enterprise_change_implementations",
        ),
        "effectivity",
        array_fields(
            row["effectivity"],
            (
                "item_id",
                "stage",
                "outcome",
                "covered_units",
                "occurred_at",
                "received_at",
            ),
            name="enterprise_change_effectivity",
        ),
        "verifications",
        array_fields(
            row["verifications"],
            (
                "actor_id",
                "at",
                "text",
                ("result", ("fact", "result")),
                ("applicable_as_recorded", ("fact", "applicable")),
            ),
            name="enterprise_change_verifications",
        ),
        "closure",
        object_fields(row["closure"], "text", "actor_id", "at"),
    )
    return (
        select(
            func.coalesce(
                func.jsonb_agg(aggregate_order_by(data, rows.c.ordinal)), func.jsonb_build_array()
            )
        )
        .select_from(rows)
        .scalar_subquery()
    )


def projectors(artifacts, selected, *, dependencies=None, identity=None):
    from .sources import bound_tenant

    def readable(model):
        if identity is not None:
            return model
        return shared_readable(model)

    product = readable(Product)
    project = readable(Project)
    build = readable(Build)

    def native(
        kind,
        model,
        pointer,
        current,
        object_id,
        title,
        facts,
        reads,
        condition=True,
        *,
        build_parent=False,
        build_revision=None,
        joins=(),
        extra_private=False,
        extra_customer_original=False,
        nature="structured",
        optional_scope=False,
        record_owner=None,
        record_visibility=None,
        record_revision=None,
    ):
        if identity is not None:
            return select(literal(kind).label("source_type"), model.id.label("source_id")).where(
                model.tenant_id == bound_tenant(),
                object_id == identity,
            )
        roots = (
            func.jsonb_array_elements(reads)
            .table_valued(column("value", JSONB))
            .render_derived(name="enterprise_reads_" + kind)
        )
        root_match = and_(
            artifacts.c.tenant_id == model.tenant_id,
            artifacts.c.source_id == cast(roots.c.value["artifact_id"].astext, UUID),
        )
        changed_root = exists(
            select(1)
            .select_from(roots)
            .join(artifacts, root_match)
            .where(
                artifacts.c.source_revision
                != cast(roots.c.value["expected_revision"].astext, Integer)
            )
            .correlate(model)
        )
        visible_root = exists(
            select(1).select_from(artifacts).where(root_match).correlate(model, roots)
        )
        missing_root = exists(select(1).select_from(roots).where(~visible_root).correlate(model))
        refs = (
            select(
                func.coalesce(
                    func.jsonb_agg(
                        aggregate_order_by(
                            func.jsonb_build_object(
                                "type",
                                "artifact",
                                "id",
                                roots.c.value["artifact_id"],
                                "version",
                                roots.c.value["expected_revision"],
                            ),
                            roots.c.value["artifact_id"].astext,
                            roots.c.value["expected_revision"].astext,
                        )
                    ),
                    func.jsonb_build_array(),
                )
            )
            .select_from(roots)
            .correlate(model)
            .scalar_subquery()
        )
        original_ids = (
            select(func.coalesce(func.array_agg(artifacts.c.original_id), array([], type_=UUID)))
            .select_from(roots)
            .join(artifacts, root_match)
            .where(artifacts.c.original_id.is_not(None))
            .correlate(model)
            .scalar_subquery()
        )
        if dependencies is not None:
            # This finds possible scan IDs only. The final metadata query still
            # applies the complete authority relation, hashes and current pointers.
            return (
                select(original_ids.label("original_ids"))
                .select_from(model)
                .join(
                    dependencies,
                    and_(dependencies.c.source_type == kind, dependencies.c.source_id == model.id),
                )
                .where(model.tenant_id == bound_tenant())
            )
        private_root = exists(
            select(1)
            .select_from(roots)
            .join(artifacts, root_match)
            .where(artifacts.c.private)
            .correlate(model)
        )
        original_root = exists(
            select(1)
            .select_from(roots)
            .join(artifacts, root_match)
            .where(artifacts.c.customer_original)
            .correlate(model)
        )
        structured = func.jsonb_build_object(
            "object_id",
            object_id,
            "kind",
            kind,
            "facts",
            facts,
            "source_refs",
            refs,
            "record_policy",
            "仅表示该版本已登记的事实，当前业务适用性仍须复核。",
        ).cast(JSONB)
        body = cast(structured, Text)
        owner = model.owner_id if record_owner is None else record_owner
        visibility = model.visibility if record_visibility is None else record_visibility
        revision = model.revision if record_revision is None else record_revision
        private = (
            (visibility != "category")
            | func.coalesce(project.visibility != "category", False)
            | func.coalesce(product.visibility != "category", False)
            | private_root
            | extra_private
        )
        if build_parent:
            private |= build.visibility != "category"
        query = (
            select(
                literal(kind).label("source_type"),
                model.id.label("source_id"),
                model.tenant_id,
                model.category_id,
                model.product_id,
                model.project_id,
                null().cast(UUID).label("proposal_id"),
                owner.label("owner_id"),
                revision.label("source_revision"),
                title.label("title"),
                func.encode(func.sha256(func.convert_to(body, "UTF8")), "hex").label(
                    "content_hash"
                ),
                body.label("body"),
                structured.label("structured"),
                literal(nature).label("nature"),
                private.label("private"),
                (original_root | extra_customer_original).label("customer_original"),
                current.label("is_current"),
                model.created_at,
                null().cast(UUID).label("original_id"),
                object_id.label("object_id"),
                original_ids.label("original_ids"),
                case((changed_root, "needs_recheck"), else_="current").label("read_basis_status"),
            )
            .select_from(model)
            .join(
                project,
                and_(
                    project.tenant_id == model.tenant_id,
                    project.product_id == model.product_id,
                    project.id == model.project_id,
                    project.category_id == model.category_id,
                ),
                isouter=optional_scope,
            )
            .join(
                product,
                and_(
                    product.tenant_id == model.tenant_id,
                    product.id == model.product_id,
                    product.category_id == model.category_id,
                ),
                isouter=optional_scope,
            )
        )
        for target, onclause in joins:
            query = query.join(target, onclause)
        if build_parent:
            query = query.join(
                build,
                and_(
                    build.tenant_id == model.tenant_id,
                    build.category_id == model.category_id,
                    build.product_id == model.product_id,
                    build.project_id == model.project_id,
                    build.id == model.build_id,
                    build.revision
                    == (model.build_revision if build_revision is None else build_revision),
                ),
            )
        if pointer is not None:
            query = query.join(pointer[0], pointer[1])
        query = query.where(model.tenant_id == bound_tenant(), ~missing_root, condition)
        if optional_scope:
            query = query.where(
                model.product_id.is_(None) | product.id.is_not(None),
                model.project_id.is_(None) | project.id.is_not(None),
            )
        if len(selected) <= 1:
            return query
        # The registered JSON body is identical for its text and hash. In mixed
        # reads, compute the nested facts/read references once before deriving
        # those two representations, rather than expanding the same subqueries
        # three times for each version.
        columns = list(query.selected_columns)
        projected = query.with_only_columns(*[
            field for field in columns if field.key not in {"content_hash", "body"}
        ]).cte("enterprise_projected_" + kind + "_" + model.__table__.name).prefix_with(
            "MATERIALIZED",
        )
        body = cast(projected.c.structured, Text)
        replacements = {
            "body": body,
            "content_hash": func.encode(func.sha256(func.convert_to(body, "UTF8")), "hex"),
        }
        return select(*[
            (replacements[field.key] if field.key in replacements else projected.c[field.key])
            .label(field.key)
            for field in columns
        ])

    q = readable(QualityIssueVersion)
    qc = readable(QualityIssueCurrent)
    quality_pointer = (
        qc,
        and_(
            qc.tenant_id == q.tenant_id,
            qc.product_id == q.product_id,
            qc.project_id == q.project_id,
            qc.issue_id == q.issue_id,
        ),
    )
    quality_current = qc.issue_version_id == q.id
    result = []
    if "issue" in selected:
        value = q.issue_snapshot
        facts = func.jsonb_build_object(
            "issue_id",
            q.issue_id,
            "title",
            value["title"],
            "status",
            q.status,
            "risk",
            value["risk"],
            "needs_recheck",
            value["needs_recheck"],
            "recheck_reasons",
            value["recheck_reasons"],
            "merged_into",
            value["merged_into"],
            "root_cause",
            object_fields(value["root_cause"], "text", "actor_id", "at"),
            "containment",
            array_fields(
                value["containment"], ("id", "text", "executor_id"), name="enterprise_containment"
            ),
            "closure",
            object_fields(value["closure"], "text", "actor_id", "at"),
        )
        result.append(
            native(
                "issue",
                q,
                quality_pointer,
                quality_current,
                q.issue_id,
                value["title"].astext,
                facts,
                q.required_source_read_set,
            )
        )
    if "capa" in selected:
        value = q.issue_snapshot["capa"]
        facts = func.jsonb_build_object(
            "issue_id",
            q.issue_id,
            "capa_id",
            value["id"],
            "issue_status",
            q.status,
            "hypotheses",
            array_fields(value["hypotheses"], ("text",), name="enterprise_hypotheses"),
            "actions",
            array_fields(
                value["actions"],
                (
                    "id",
                    "kind",
                    "text",
                    "executor_id",
                    ("completion_text", ("completion", "text")),
                    ("completed_by", ("completion", "executor_id")),
                    ("completed_at", ("completion", "at", "occurred_at")),
                ),
                name="enterprise_capa_actions",
            ),
            "requirement",
            object_fields(value["requirement"], "method", "acceptance", "observation_until"),
            "effectiveness",
            object_fields(value["effectiveness"], "text", "result", "actor_id", "at"),
        )
        result.append(
            native(
                "capa",
                q,
                quality_pointer,
                quality_current,
                cast(value["id"].astext, UUID),
                literal("CAPA · ") + q.issue_snapshot["title"].astext,
                facts,
                q.required_source_read_set,
                value["id"].astext.is_not(None),
            )
        )
    if "change" in selected:
        m, p = readable(ChangeRequestVersion), readable(ChangeCurrent)
        value = m.request_snapshot
        facts = object_fields(
            value, "id", "title", "reason", "status", "needs_recheck", "recheck_reasons"
        ).op("||")(func.jsonb_build_object("orders", change_orders(value["orders"])))
        result.append(
            native(
                "change",
                m,
                (
                    p,
                    and_(
                        p.tenant_id == m.tenant_id,
                        p.product_id == m.product_id,
                        p.change_id == m.change_id,
                    ),
                ),
                p.version_id == m.id,
                m.change_id,
                value["title"].astext,
                facts,
                m.required_source_read_set,
            )
        )
    if "external_wait" in selected:
        m, p = readable(ExternalWaitVersion), readable(ExternalWaitCurrent)
        value = m.body
        facts = func.jsonb_build_object(
            "wait",
            object_fields(
                value,
                "wait_id",
                "revision",
                "state",
                "responsible_id",
                "title",
                "target",
                "request_content",
                "closure_condition",
                "blocking",
                "next_check_at",
                "original_timezone",
            ),
            "delivery",
            object_fields(value["delivery"], "at", "status", "time_basis"),
            "commitment",
            object_fields(value["counterparty_commitment"], "promised_at", "original_timezone"),
            "reply",
            object_fields(value["reply"], "at", "status", "time_basis"),
        )
        result.append(
            native(
                "external_wait",
                m,
                (
                    p,
                    and_(
                        p.tenant_id == m.tenant_id,
                        p.product_id == m.product_id,
                        p.wait_id == m.wait_id,
                    ),
                ),
                p.version_id == m.id,
                m.wait_id,
                value["title"].astext,
                facts,
                m.reads,
            )
        )
    if "supply" in selected:
        m, p = readable(SupplySnapshot), readable(SupplyCurrent)
        facts = func.jsonb_build_object(
            "build_id",
            m.build_id,
            "status",
            m.status,
            "commitments",
            array_fields(
                m.snapshot["commitments"],
                ("record_id", "supplier_id", "material_id", "quantity", "unit", "expected_at"),
                name="enterprise_supply_commitments",
            ),
        )
        result.append(
            native(
                "supply",
                m,
                (
                    p,
                    and_(
                        p.tenant_id == m.tenant_id,
                        p.product_id == m.product_id,
                        p.build_id == m.build_id,
                    ),
                ),
                p.snapshot_id == m.id,
                m.id,
                literal("供应承诺 · ") + cast(m.build_id, Text),
                facts,
                m.required_source_read_set,
                build_parent=True,
            )
        )
    if "build" in selected:
        m = build
        engineering = readable(EngineeringConfiguration)
        manufacturing = readable(ProcessRevision)
        configuration = (
            select(engineering.required_source_read_set)
            .where(
                engineering.tenant_id == m.tenant_id,
                engineering.product_id == m.product_id,
                engineering.id == m.engineering_configuration_id,
            )
            .correlate(m)
        )
        process = (
            select(manufacturing.required_source_read_set)
            .where(
                manufacturing.tenant_id == m.tenant_id,
                manufacturing.product_id == m.product_id,
                manufacturing.id == m.manufacturing_configuration_id,
            )
            .correlate(m)
        )
        facts = func.jsonb_build_object(
            *[
                part
                for key in (
                    "name",
                    "type",
                    "purpose",
                    "planned_quantity",
                    "unit",
                    "planned_start",
                    "planned_end",
                    "engineering_configuration_id",
                    "manufacturing_configuration_id",
                    "verification_objectives",
                )
                for part in (key, getattr(m, key))
            ],
            "plan_status",
            m.status,
        )
        result.append(
            native(
                "build",
                m,
                None,
                literal(True),
                m.id,
                m.name,
                facts,
                configuration.scalar_subquery().op("||")(process.scalar_subquery()),
                configuration.exists() & process.exists(),
            )
        )
        from .business_execution_sources import build_records

        result.extend(build_records(native, build=build, readable=readable))
    if "test_run" in selected:
        from .business_execution_sources import result_records

        m = readable(VerificationRunVersion)
        p = readable(VerificationRunCurrent)
        facts = object_fields(
            m.run_snapshot, "id", "revision", "request_id", "status", "result"
        ).op("||")(
            func.jsonb_build_object(
                *[
                    part
                    for key in (
                        "actual_start",
                        "actual_end",
                        "preliminary_result",
                        "final_result",
                    )
                    for part in (
                        key,
                        object_fields(
                            m.run_snapshot[key], "occurred_at", "original_timezone", "effective_at"
                        ),
                    )
                ]
            )
        )
        result.append(
            native(
                "test_run",
                m,
                (
                    p,
                    and_(
                        p.tenant_id == m.tenant_id,
                        p.product_id == m.product_id,
                        p.run_id == m.run_id,
                    ),
                ),
                p.run_version_id == m.id,
                m.run_id,
                literal("测试运行 · ") + cast(m.run_id, Text),
                facts,
                m.required_source_read_set,
                build_parent=True,
            )
        )
        result.extend(result_records(native, versions=m, readable=readable))
    if "field_feedback" in selected:
        from .field_feedback_sources import projectors as field_projectors

        result.extend(field_projectors(native, readable))
    from .role_native_sources import projectors as role_projectors

    result.extend(role_projectors(native, readable, selected))
    return result
