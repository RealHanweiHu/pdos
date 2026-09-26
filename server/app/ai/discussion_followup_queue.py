"""Queue one separate engineering candidate after an authorized child discussion ends."""

import logging
from typing import Any
from uuid import uuid5

from sqlalchemy import Engine, RowMapping, func, select

from app.ai import change_notice_preparation as notices
from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_queue_claim import claim_application_queue
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.change_impact_preparation import ChangeImpactAssessment, encoded
from app.ai.change_work_package_runs import KEY, PURPOSE, RUN_VERSION, ChangeWorkPackageRuns
from app.ai.discussion_followup import KEY as FOLLOWUP_KEY
from app.ai.discussion_followup import MAX_BRIEF_CHARS, VERSION, actual, prompt_for
from app.ai.discussion_sources import require_disclosure
from app.ai.rollout_guard import require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthRepository
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.change_execution_results import _access
from app.domain.product_workspace import ProductWorkError, digest
from app.domain.project_write_lock import lock_project_write_scope

logger = logging.getLogger(__name__)


class DiscussionFollowupQueue:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    def schedule(self) -> bool:
        r, b, i = tables.agent_runs, tables.debate_run_bindings, tables.change_discussion_inputs
        child = r.alias("discussion")
        with self.engine.connect() as c:
            candidate = (
                c.execute(
                    select(r.c.id, r.c.tenant_id, b.c.run_id.label("discussion_id"))
                    .join(b, (b.c.tenant_id == r.c.tenant_id) & (b.c.origin_run_id == r.c.id))
                    .join(child, (child.c.tenant_id == b.c.tenant_id) & (child.c.id == b.c.run_id))
                    .where(
                        r.c.status == "succeeded",
                        child.c.status == "succeeded",
                        r.c.run_context["discussion_followup_version"].as_string() == VERSION,
                        r.c.run_context["discussion_followup_error"].as_string().is_(None),
                        ~select(i.c.id)
                        .where(i.c.tenant_id == r.c.tenant_id, i.c.origin_run_id == r.c.id)
                        .exists(),
                    )
                    .order_by(child.c.completed_at, child.c.id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if candidate is None:
            return False
        try:
            with self.engine.begin() as c:
                BudgetLedger._lock(c, candidate["tenant_id"])
                origin = (
                    c.execute(
                        select(r)
                        .where(r.c.tenant_id == candidate["tenant_id"], r.c.id == candidate["id"])
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                if c.execute(
                    select(i.c.id).where(
                        i.c.tenant_id == origin["tenant_id"], i.c.origin_run_id == origin["id"]
                    )
                ).first() or origin["run_context"].get("discussion_followup_error"):
                    return False
                require_live_key(KEY)
                require_live_key(FOLLOWUP_KEY)
                require_live_key("engineering_intelligence.discussion_convene")
                actor = AuthRepository(self.engine).find_user_context(
                    origin["requested_by_user_id"]
                )
                if actor is None or actor.tenant.id != origin["tenant_id"]:
                    raise ProductWorkError("原发起人不可用")
                for action in (Action.CHANGE_EDIT, Action.QUALITY_VIEW):
                    _access(self.engine, actor, origin["project_id"], action)
                if not lock_project_write_scope(
                    c, tenant_id=origin["tenant_id"], project_id=origin["project_id"]
                ):
                    raise ProductWorkError("原项目不可用")
                bound = (
                    c.execute(
                        select(b).where(
                            b.c.tenant_id == origin["tenant_id"],
                            b.c.run_id == candidate["discussion_id"],
                        )
                    )
                    .mappings()
                    .one()
                )
                require_disclosure(c, origin["tenant_id"], actor.user.id, bound)
                brief = actual(c, origin["tenant_id"], bound["run_id"], require_active=True)
                if len(encoded(brief)) > MAX_BRIEF_CHARS:
                    raise BudgetLedgerError("DISCUSSION_FOLLOWUP_CONTEXT_LIMIT")
                source = origin["run_context"]["impact_source"]
                notices.require_discussion_enabled(source)
                if (
                    notices.rebuild(
                        c,
                        origin["tenant_id"],
                        origin["project_id"],
                        source,
                        actor.user.id,
                    )["digest"]
                    != source["digest"]
                ):
                    raise BudgetLedgerError("DISCUSSION_FOLLOWUP_SOURCE_CHANGED")
                if bound["source"]["digest"] != source["digest"]:
                    raise ProductWorkError("讨论不属于原分析资料版本")
                run_id = uuid5(bound["run_id"], VERSION)
                input_id = uuid5(run_id, "brief")
                input_value = {
                    "id": str(input_id),
                    "origin_run_id": str(origin["id"]),
                    "discussion_run_id": str(bound["run_id"]),
                    **brief,
                }
                now = c.execute(select(func.clock_timestamp())).scalar_one()
                rc: dict[str, Any] = {
                    k: origin["run_context"][k]
                    for k in (
                        "impact_ecr_id",
                        "impact_depth",
                        "impact_expected_digest",
                        "impact_user_instruction",
                        "impact_toolset_version",
                    )
                }
                rc.update(
                    impact_allow_discussion=False,
                    impact_prompt_version=prompt_for(source).version,
                    impact_include_supplier_notices=notices.is_notice(source),
                    impact_schema_digest=digest(ChangeImpactAssessment.model_json_schema()),
                    impact_source={**source, "discussion_input": input_value},
                    discussion_followup_queue=VERSION,
                )
                c.execute(
                    r.insert().values(
                        id=run_id,
                        tenant_id=origin["tenant_id"],
                        project_id=origin["project_id"],
                        agent_key=origin["agent_key"],
                        request_id=str(run_id),
                        requested_by_user_id=actor.user.id,
                        status="running",
                        event_count=0,
                        event_row_ids=[],
                        window_started_at=now,
                        window_ended_at=now,
                        context_version=RUN_VERSION,
                        started_at=now,
                        created_at=now,
                        updated_at=now,
                        run_context=rc,
                    )
                )
                freeze_created_application_run(
                    c,
                    self.gateway,
                    tenant_id=origin["tenant_id"],
                    run_id=run_id,
                    parent_run_id=origin["id"],
                    actor_user_id=actor.user.id,
                    purpose=PURPOSE,
                    auth_version=actor.user.auth_version,
                    issue_lease=False,
                )
                a = tables.application_authorizations
                old_auth = (
                    c.execute(
                        select(a).where(
                            a.c.tenant_id == origin["tenant_id"], a.c.run_id == origin["id"]
                        )
                    )
                    .mappings()
                    .one()
                )
                new_auth = (
                    c.execute(
                        select(a).where(a.c.tenant_id == origin["tenant_id"], a.c.run_id == run_id)
                    )
                    .mappings()
                    .one()
                )
                if (
                    old_auth["pins"] != new_auth["pins"]
                    or old_auth["body"]["policy_version"] != new_auth["body"]["policy_version"]
                    or old_auth["expires_at"] < new_auth["expires_at"]
                ):
                    raise BudgetLedgerError("APPLICATION_AUTHORIZATION_CHANGED")
                c.execute(
                    i.insert().values(
                        id=input_id,
                        tenant_id=origin["tenant_id"],
                        run_id=run_id,
                        origin_run_id=origin["id"],
                        discussion_run_id=bound["run_id"],
                        brief_digest=brief["digest"],
                        body=brief["body"],
                        created_at=now,
                    )
                )
                c.execute(
                    r.update().where(r.c.id == run_id).values(status="queued", started_at=None)
                )
        except Exception as error:
            code = getattr(error, "code", "DISCUSSION_FOLLOWUP_NOT_READY")
            logger.warning("Discussion follow-up admission stopped: %s", code)
            # Record one visible stop. Never create a fresh-budget retry loop.
            with self.engine.begin() as c:
                row = (
                    c.execute(
                        select(r)
                        .where(r.c.id == candidate["id"], r.c.tenant_id == candidate["tenant_id"])
                        .with_for_update()
                    )
                    .mappings()
                    .one()
                )
                if not c.execute(
                    select(i.c.id).where(
                        i.c.tenant_id == row["tenant_id"], i.c.origin_run_id == row["id"]
                    )
                ).first():
                    c.execute(
                        r.update()
                        .where(r.c.id == row["id"])
                        .values(
                            run_context={**row["run_context"], "discussion_followup_error": code},
                            updated_at=func.clock_timestamp(),
                        )
                    )
        return True

    def run_next(self) -> bool:
        scheduled = self.schedule()
        t = tables.agent_runs
        row: RowMapping | None = None
        try:
            with self.engine.begin() as c:
                row = (
                    c.execute(
                        select(t)
                        .where(
                            t.c.context_version == RUN_VERSION,
                            t.c.status == "queued",
                            t.c.run_context["discussion_followup_queue"].as_string() == VERSION,
                        )
                        .order_by(t.c.created_at, t.c.id)
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return scheduled
                BudgetLedger._lock(c, row["tenant_id"])
                row = (
                    c.execute(
                        select(t)
                        .where(t.c.id == row["id"], t.c.status == "queued")
                        .with_for_update(skip_locked=True)
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    return scheduled
                actor = AuthRepository(self.engine).find_user_context(row["requested_by_user_id"])
                if actor is None or actor.tenant.id != row["tenant_id"]:
                    raise ProductWorkError("原发起人不可用")
                require_live_key(KEY)
                require_live_key(FOLLOWUP_KEY)
                notices.require_discussion_enabled(row["run_context"]["impact_source"])
                row = claim_application_queue(
                    c, self.gateway, row, auth_version=actor.user.auth_version, purpose=PURPOSE
                )
            ChangeWorkPackageRuns(self.engine, gateway=self.gateway)._execute(
                row, row["run_context"]["impact_source"]
            )
        except Exception as error:
            if row is None:
                raise
            code = getattr(error, "code", "DISCUSSION_FOLLOWUP_EXECUTION_FAILED")
            logger.warning("Discussion follow-up execution stopped: %s", code)
            # Claimed runs use the existing lease-expiry/result-recovery path.
            with self.engine.begin() as c:
                c.execute(
                    t.update()
                    .where(
                        t.c.tenant_id == row["tenant_id"],
                        t.c.id == row["id"],
                        t.c.status == "queued",
                    )
                    .values(
                        status="failed",
                        error_code=code,
                        completed_at=func.clock_timestamp(),
                        updated_at=func.clock_timestamp(),
                    )
                )
        return True
