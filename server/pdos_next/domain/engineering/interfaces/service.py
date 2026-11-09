"""T1 interface contracts under an engineering configuration (P100 第 4–6 项, D312).

Create and revise are done by a named engineering-role person; each
participating discipline is confirmed or disputed by a project member holding
that project role, never by the responsible person. Revising the content
supersedes earlier confirmations. Affected items must resolve through the real
change-graph owner reads, so impact only propagates through explicit links.
"""

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.core.models import now
from pdos_next.domain.named_records import service as records
from pdos_next.domain.projects.work.rules import require

from .models import InterfaceCurrent, InterfaceVersion
from .schemas import OPERATION, SUBJECT

EFFECT = (
    "保存接口合同的新版本：参与模块与专业、约束、单位、负责人、验证方式和受影响项。"
    "各专业分别确认；修订内容会使已有确认变为“已取代”。影响只沿已登记的受影响项传播，"
    "待核实线索单列，不作为确定影响。"
)
LABEL = "接口"


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


@dataclass
class Validated:
    project: object
    configuration: object
    previous: object
    pointer: object
    body: dict
    scope: dict
    review: dict


def _configuration(s, ctx, product_id, ref, *, series_id=None):
    from pdos_next.domain.builds.configurations.models import EngineeringConfiguration

    row = s.scalar(
        select(EngineeringConfiguration).where(
            EngineeringConfiguration.tenant_id == ctx.tenant_id,
            EngineeringConfiguration.product_id == product_id,
            EngineeringConfiguration.id == ref.id,
        )
    )
    require(row is not None, "工程配置不在当前可读范围。", "FORBIDDEN_SCOPE", 403)
    require(row.revision == ref.revision, "工程配置已有新版本，请核对后重试。", "VERSION_CONFLICT")
    latest = s.scalar(
        select(EngineeringConfiguration.id)
        .where(
            EngineeringConfiguration.tenant_id == ctx.tenant_id,
            EngineeringConfiguration.product_id == product_id,
            EngineeringConfiguration.series_id == row.series_id,
        )
        .order_by(EngineeringConfiguration.revision.desc())
        .limit(1)
    )
    require(latest == row.id, "接口须挂在工程配置的当前版本下。", "VERSION_CONFLICT")
    require(
        series_id is None or row.series_id == series_id,
        "修订时只能改挂到同一工程配置系列的当前版本。",
        "FORBIDDEN_SCOPE",
        403,
    )
    root = s.scalar(
        select(EngineeringConfiguration).where(
            EngineeringConfiguration.tenant_id == ctx.tenant_id,
            EngineeringConfiguration.product_id == product_id,
            EngineeringConfiguration.id == row.series_id,
        )
    )
    require(
        root is not None and (root.owner_id, root.visibility) == (row.owner_id, row.visibility),
        "工程配置的可见范围已变化，接口须先按新范围重核。",
        "VERSION_CONFLICT",
    )
    return row


def _catalog(s, ctx):
    from pdos_next.domain.projects.team import roles

    return {
        role["key"] for role in roles.current(s, ctx.tenant_id)["roles"] if role.get("active", True)
    }


def _affected(s, ctx, product_id, project_id, owner_id, visibility, items):
    """Each explicit affected item must resolve through its real owner read."""
    from pdos_next.domain.change.execution.graph import OwnerReader, audience
    from pdos_next.schemas.change_control.contracts import Ref
    from pdos_next.schemas.verification.contracts import Scope

    scope = Scope(tenant_id=ctx.tenant_id, product_id=product_id, project_id=project_id)
    reader = OwnerReader(
        s, ctx, product_id, scope, audience(product_id, owner_id, visibility), None
    )
    out = []
    for item in items:
        obj = reader.resolve(Ref(id=item.id, revision=item.revision, kind=item.kind, key=item.key))
        out.append({**item.model_dump(mode="json"), "label": obj.label, "current": obj.current})
    return out


def _state(confirmations):
    states = {row["state"] for row in confirmations}
    if "disputed" in states:
        return "disputed"
    return "confirmed" if states == {"confirmed"} else "pending"


def _content(record, affected):
    content = record.model_dump(mode="json", exclude={"action", "project_id", "configuration"})
    content["affected"] = affected
    return content


def _engineering(s, ctx, product_id, project, at):
    return records.require_role(
        s, ctx, product_id, project.id, OPERATION, project.purpose, {"engineering"}, at
    )


def _check_content(s, ctx, product_id, project, record, owner_id, visibility):
    catalog = _catalog(s, ctx)
    missing = sorted(set(record.disciplines) - catalog)
    require(
        not missing,
        f"参与专业须是当前角色目录中的角色：{'、'.join(missing)}。",
        "VALIDATION_FAILED",
    )
    roles = records.project_roles(s, ctx, project.id, record.responsible_id)
    require(roles is not None, "接口负责人须是本项目的在册成员。", "VALIDATION_FAILED")
    return _affected(s, ctx, product_id, project.id, owner_id, visibility, record.affected)


def validate(s, ctx, command, product, payload):
    records.human_only(s, ctx)
    require(
        command.expected_revision == product.revision, "型号范围版本已变化。", "VERSION_CONFLICT"
    )
    at = now()
    record = payload.record
    previous = pointer = None
    if record.action == "create":
        project = records.project(s, ctx, product.id, record.project_id)
        configuration = _configuration(s, ctx, product.id, record.configuration)
        held = _engineering(s, ctx, product.id, project, at)
        owner_id, visibility = configuration.owner_id, configuration.visibility
        affected = _check_content(s, ctx, product.id, project, record, owner_id, visibility)
        body = {
            "revision": 1,
            "project_id": str(project.id),
            "configuration_id": str(configuration.id),
            "configuration": {
                "id": str(configuration.id),
                "revision": configuration.revision,
                "series_id": str(configuration.series_id),
            },
            "content": _content(record, affected),
            "confirmations": [
                {
                    "discipline": key,
                    "state": "pending",
                    "actor_id": None,
                    "note": None,
                    "at_revision": None,
                }
                for key in record.disciplines
            ],
            "superseded": [],
        }
        series_id = configuration.series_id
    else:
        pointer, previous = records.current(
            s,
            ctx,
            product.id,
            payload.interface.id,
            InterfaceVersion,
            InterfaceCurrent,
            lock=True,
            label=LABEL,
        )
        records.expect(previous, payload.interface.revision, LABEL)
        project = records.project(s, ctx, product.id, previous.project_id)
        owner_id, visibility, series_id = (
            previous.owner_id,
            previous.visibility,
            previous.configuration_series_id,
        )
        body = deepcopy(previous.body)
        body["revision"] = previous.revision + 1
        if record.action == "revise":
            configuration = _configuration(
                s, ctx, product.id, record.configuration, series_id=series_id
            )
            require(
                (configuration.owner_id, configuration.visibility) == (owner_id, visibility),
                "工程配置的可见范围已变化，接口须先按新范围重核。",
                "VERSION_CONFLICT",
            )
            held = _engineering(s, ctx, product.id, project, at)
            affected = _check_content(s, ctx, product.id, project, record, owner_id, visibility)
            content = _content(record, affected)
            require(
                content != previous.body["content"]
                or str(configuration.id) != previous.body["configuration_id"],
                "接口内容与挂接配置都没有变化，无需续版。",
                "VALIDATION_FAILED",
            )
            body["superseded"] = body["superseded"] + [
                {**row, "superseded_at_revision": body["revision"]}
                for row in previous.body["confirmations"]
                if row["state"] != "pending"
            ]
            body["content"] = content
            body["configuration_id"] = str(configuration.id)
            body["configuration"] = {
                "id": str(configuration.id),
                "revision": configuration.revision,
                "series_id": str(configuration.series_id),
            }
            body["confirmations"] = [
                {
                    "discipline": key,
                    "state": "pending",
                    "actor_id": None,
                    "note": None,
                    "at_revision": None,
                }
                for key in record.disciplines
            ]
        else:
            configuration = None
            content = previous.body["content"]
            require(
                record.discipline in content["disciplines"],
                "该专业不是本接口的参与专业。",
                "VALIDATION_FAILED",
            )
            require(
                str(ctx.requester_id) != content["responsible_id"],
                "接口负责人不能代替参与专业确认。",
                "INDEPENDENT_REVIEWER_REQUIRED",
                403,
            )
            roles = records.project_roles(s, ctx, project.id, ctx.requester_id)
            require(
                roles is not None and record.discipline in roles,
                "只有担任该专业角色的项目成员才能确认或提出异议。",
                "QUALIFICATION_REQUIRED",
                403,
            )
            target = "confirmed" if record.action == "confirm" else "disputed"
            entry = next(
                row for row in body["confirmations"] if row["discipline"] == record.discipline
            )
            require(entry["state"] != target, "该专业已是这个确认状态。", "VALIDATION_FAILED")
            entry.update(
                state=target,
                actor_id=str(ctx.requester_id),
                note=record.note,
                at_revision=body["revision"],
            )
            held = sorted(roles & {record.discipline})
    body["state"] = _state(body["confirmations"])
    body["action"] = record.action
    body["reason"] = payload.reason
    review = {
        "operation": OPERATION,
        "interface": {"id": str(previous.record_id), "revision": previous.revision}
        if previous
        else None,
        "before": previous.body if previous else None,
        "after": body,
        "roles": held,
        "effect": EFFECT,
    }
    configuration_id = UUID(body["configuration_id"])
    scope = {
        "project_id": project.id,
        "configuration_series_id": series_id,
        "owner_id": owner_id,
        "visibility": visibility,
    }
    return Validated(
        project,
        configuration,
        previous,
        pointer,
        body,
        {**scope, "configuration_id": configuration_id},
        review,
    )


def preview_view(s, ctx, command, product, payload):
    return validate(s, ctx, command, product, payload).review


def apply_validated(s, ctx, command, product, payload, value):
    body = deepcopy(value.body)
    body["record_id"] = str(value.previous.record_id) if value.previous else str(uuid4())
    scope = {
        key: value.scope[key]
        for key in ("project_id", "configuration_series_id", "owner_id", "visibility")
    }
    row = records.write(
        s,
        ctx,
        command,
        product,
        payload,
        versions=InterfaceVersion,
        currents=InterfaceCurrent,
        scope=scope,
        previous=value.previous,
        pointer=value.pointer,
        action=payload.record.action,
        body=body,
        at=now(),
        review=value.review,
        semantic=semantic,
        extra={"configuration_id": value.scope["configuration_id"]},
    )
    row.action_result = {
        "interface_id": body["record_id"],
        "state": row.state,
        "revision": row.revision,
    }
    return row, SUBJECT, row.visibility


def finalize_receipt(s, ctx, command, product, payload, subject, receipt):
    records.bind(subject, receipt, LABEL)


def _view(row, history=()):
    content = row.body["content"]
    return {
        "id": str(row.record_id),
        "version_id": str(row.id),
        "revision": row.revision,
        "state": row.state,
        "project_id": str(row.project_id),
        "configuration": row.body["configuration"],
        "content": content,
        "confirmations": row.body["confirmations"],
        "superseded": row.body["superseded"],
        "recorded_at": row.created_at.isoformat(),
        "actor_id": str(row.actor_id),
        "history": [records.version_view(item) for item in history],
    }


def list_interfaces(s, ctx, product_id, project_id):
    records.project(s, ctx, product_id, project_id)
    rows = s.scalars(
        select(InterfaceVersion)
        .join(
            InterfaceCurrent,
            (InterfaceCurrent.tenant_id == InterfaceVersion.tenant_id)
            & (InterfaceCurrent.version_id == InterfaceVersion.id),
        )
        .where(
            InterfaceVersion.tenant_id == ctx.tenant_id,
            InterfaceVersion.product_id == product_id,
            InterfaceVersion.project_id == project_id,
        )
        .order_by(InterfaceVersion.created_at.desc())
        .limit(200)
    ).all()
    return {"project_id": str(project_id), "items": [_view(row) for row in rows]}


def get_interface(s, ctx, product_id, record_id):
    _, row = records.current(
        s, ctx, product_id, record_id, InterfaceVersion, InterfaceCurrent, label=LABEL
    )
    return _view(row, records.history(s, ctx, product_id, record_id, InterfaceVersion))


def change_owner(s, ctx, product_id, record_id, revision):
    """Exact interface version for the change graph; never the newer current."""
    row = s.scalar(
        select(InterfaceVersion).where(
            InterfaceVersion.tenant_id == ctx.tenant_id,
            InterfaceVersion.product_id == product_id,
            InterfaceVersion.record_id == record_id,
            InterfaceVersion.revision == revision,
        )
    )
    require(row is not None, "固定接口版本不在当前可读范围。", "FORBIDDEN_SCOPE", 403)
    pointer = s.scalar(
        select(InterfaceCurrent).where(
            InterfaceCurrent.tenant_id == ctx.tenant_id, InterfaceCurrent.record_id == record_id
        )
    )
    view = {
        "name": row.body["content"]["name"],
        "content": row.body["content"],
        "configuration": row.body["configuration"],
        "state": row.state,
        "source_status": "current"
        if pointer is not None and pointer.version_id == row.id
        else "needs_recheck",
        "required_source_read_set": [],
    }
    return row, view
