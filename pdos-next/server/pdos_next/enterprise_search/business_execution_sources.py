"""Fixed execution records; imported raw readings and SourceRef text stay isolated."""

from sqlalchemy import Text, and_, case, cast, func, literal, null
from sqlalchemy.dialects.postgresql import JSONB

from pdos_next.domain.build_execution.models import ActualConfiguration, BuildLot
from pdos_next.domain.build_start.models import BuildStart
from pdos_next.domain.builds.models import Build
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results.models import TestResultActionFact

from .business_sources import array_fields, object_fields


def time_fact(value):
    return case(
        (value["occurred_at"].astext.is_(None), null().cast(JSONB)),
        else_=object_fields(
            value, "occurred_at", "original_timezone", "effective_at", "received_at", "actor_id"
        ),
    )


def conclusion(value):
    return case(
        (value["actor_id"].astext.is_(None), null().cast(JSONB)),
        else_=object_fields(value, "text", "actor_id").op("||")(
            func.jsonb_build_object(
                "at",
                time_fact(value["at"]),
                "source_reference",
                object_fields(value["source"], "kind", "id", "revision"),
            )
        ),
    )


def run_result_facts(value):
    return object_fields(value, "id", "revision", "request_id", "status", "result").op("||")(
        func.jsonb_build_object(
            "record_kind",
            "test_run",
            "coverage",
            array_fields(
                value["coverage"], ("sample_id", "item_id"), name="enterprise_run_coverage"
            ),
            "computed_results",
            array_fields(
                value["computed_results"],
                ("coverage", "result", "measurement_id"),
                name="enterprise_computed_results",
            ),
            "professional_conclusion",
            conclusion(value["professional_conclusion"]),
            "disposition",
            conclusion(value["disposition"]),
            *[
                part
                for key in ("actual_start", "actual_end", "preliminary_result", "final_result")
                for part in (key, time_fact(value[key]))
            ],
        )
    )


def build_records(native, *, build=Build, readable):
    result = []
    records = (
        (
            BuildStart,
            "build_start",
            "开工记录",
            (
                "status",
                "occurred_at",
                "occurred_timezone",
                "assessment_id",
                "assessment_revision",
                "engineering_authorization_id",
                "engineering_authorization_revision",
                "manufacturing_authorization_id",
                "manufacturing_authorization_revision",
            ),
        ),
        (
            ActualConfiguration,
            "actual_configuration",
            "实际配置记录",
            (
                "status",
                "planned_engineering_configuration_id",
                "planned_manufacturing_configuration_id",
                "actual_engineering_configuration_id",
                "actual_engineering_revision",
                "actual_manufacturing_configuration_id",
                "actual_manufacturing_revision",
                "observed_at",
            ),
        ),
        (
            BuildLot,
            "build_output",
            "实物产出记录",
            (
                "status",
                "lot_label",
                "actual_configuration_id",
                "actual_configuration_revision",
                "observed_unit_count",
                "unit",
                "observation_nature",
                "occurred_at",
                "received_at",
            ),
        ),
    )
    for source, record_kind, label, fields in records:
        model = readable(source)
        facts = func.jsonb_build_object(
            "record_kind",
            record_kind,
            "build_id",
            model.build_id,
            "build_revision",
            model.build_revision,
            *[part for key in fields for part in (key, getattr(model, key))],
        )
        if source is BuildStart:
            facts = facts.op("||")(
                func.jsonb_build_object(
                    "execution_scope",
                    object_fields(
                        model.execution_scope,
                        "purpose",
                        "quantity",
                        "unit",
                        "site",
                        "window_start",
                        "window_end",
                        "window_timezone",
                    ),
                    "continuation_permission",
                    "not_evaluated",
                )
            )
        result.append(
            native(
                "build",
                model,
                None,
                literal(True),
                model.build_id,
                literal(label + " · ") + build.name,
                facts,
                model.required_source_read_set,
                build_parent=True,
            )
        )
    return result


def result_records(native, *, versions=VerificationRunVersion, readable):
    m, v, p = readable(TestResultActionFact), versions, readable(VerificationRunCurrent)
    facts = run_result_facts(v.run_snapshot).op("||")(
        func.jsonb_build_object(
            "record_kind",
            "test_result_action",
            "operation",
            m.operation,
            "actor_id",
            m.actor_id,
            "run_version_id",
            v.id,
            "run_revision",
            v.revision,
        )
    )
    return [
        native(
            "test_run",
            m,
            (
                p,
                and_(
                    p.tenant_id == m.tenant_id, p.product_id == m.product_id, p.run_id == m.run_id
                ),
            ),
            p.run_version_id == m.next_run_version_id,
            m.run_id,
            case(
                (m.operation == "test.run.review", "专业评审记录 · "),
                (m.operation == "test.disposition.decide", "测试处置记录 · "),
                else_="测试结果记录 · ",
            )
            + cast(m.run_id, Text),
            facts,
            m.required_source_read_set,
            build_parent=True,
            build_revision=v.build_revision,
            joins=(
                (
                    v,
                    and_(
                        v.tenant_id == m.tenant_id,
                        v.category_id == m.category_id,
                        v.product_id == m.product_id,
                        v.project_id == m.project_id,
                        v.build_id == m.build_id,
                        v.run_id == m.run_id,
                        v.id == m.next_run_version_id,
                        v.revision == m.next_run_revision,
                    ),
                ),
            ),
            extra_private=v.visibility != "category",
        )
    ]
