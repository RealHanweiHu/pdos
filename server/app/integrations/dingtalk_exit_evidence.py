"""Read-only evidence collection for the S5-1 real-application exit gate."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, and_, func, select, text
from sqlalchemy.engine import RowMapping

from app.db.schema import tables

RELEASE_SHA_PATTERN = r"^[0-9a-f]{40}$"
TERMINAL_APPROVAL_STATUSES = ("approved", "rejected", "terminated")
UNRESOLVED_OUTBOX_STATUSES = (
    "pending",
    "sending",
    "retry_wait",
    "failed",
    "uncertain",
    "manual",
)


class DingTalkExitEvidenceError(RuntimeError):
    """Raised when the evidence scope or baseline is invalid."""


class GateTruthSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: UUID
    gate_code: str = Field(min_length=1, max_length=64)
    status: Literal["preparing", "reviewing", "approved", "rejected"]
    truth_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DingTalkExitBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    release_sha: str = Field(pattern=RELEASE_SHA_PATTERN)
    tenant_id: UUID
    tenant_slug: str = Field(min_length=1, max_length=128)
    project_id: UUID
    project_code: str = Field(min_length=1, max_length=128)
    captured_at: datetime
    gates: tuple[GateTruthSnapshot, ...] = Field(min_length=1)
    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    passed: bool
    detail: str


class DingTalkExitEvidenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    release_sha: str = Field(pattern=RELEASE_SHA_PATTERN)
    tenant_slug: str
    project_code: str
    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verified_at: datetime
    checks: tuple[EvidenceCheck, ...]
    human_attestations_required: tuple[str, ...] = (
        "unlinked user, wrong corp, and OAuth state replay were exercised and rejected",
        "the same card callback was submitted again before verification",
        "browser console, 390px layout, and Supplier/Customer denial checks passed",
        "the Data Owner reviewed the external DingTalk references and approved the S5-1 gate",
    )

    @property
    def automated_ready(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _gate_truth_sha256(mapping: RowMapping) -> str:
    payload = {
        "gate_id": str(mapping["id"]),
        "status": mapping["status"],
        "updated_at": mapping["updated_at"].astimezone(UTC).isoformat(),
        "decided_at": (
            mapping["decided_at"].astimezone(UTC).isoformat()
            if mapping["decided_at"] is not None
            else None
        ),
        "decided_by_user_id": (
            str(mapping["decided_by_user_id"])
            if mapping["decided_by_user_id"] is not None
            else None
        ),
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _baseline_payload(baseline: DingTalkExitBaseline) -> dict[str, object]:
    return baseline.model_dump(mode="json", exclude={"baseline_sha256"})


def _baseline_sha256(baseline: DingTalkExitBaseline) -> str:
    return hashlib.sha256(_canonical_json(_baseline_payload(baseline)).encode()).hexdigest()


def serialize_dingtalk_exit_baseline(baseline: DingTalkExitBaseline) -> str:
    if baseline.baseline_sha256 != _baseline_sha256(baseline):
        raise DingTalkExitEvidenceError("DINGTALK_EVIDENCE_BASELINE_DIGEST_INVALID")
    return baseline.model_dump_json(indent=2) + "\n"


def parse_dingtalk_exit_baseline(raw: str) -> DingTalkExitBaseline:
    try:
        baseline = DingTalkExitBaseline.model_validate_json(raw)
    except ValueError as error:
        raise DingTalkExitEvidenceError("DINGTALK_EVIDENCE_BASELINE_INVALID") from error
    if baseline.baseline_sha256 != _baseline_sha256(baseline):
        raise DingTalkExitEvidenceError("DINGTALK_EVIDENCE_BASELINE_DIGEST_INVALID")
    return baseline


def _scope(
    connection: Connection,
    *,
    tenant_slug: str,
    project_code: str,
) -> tuple[UUID, UUID]:
    row = connection.execute(
        select(tables.tenants.c.id.label("tenant_id"), tables.projects.c.id.label("project_id"))
        .join(tables.projects, tables.projects.c.tenant_id == tables.tenants.c.id)
        .where(
            tables.tenants.c.slug == tenant_slug,
            tables.tenants.c.status == "active",
            tables.projects.c.code == project_code,
        )
    ).one_or_none()
    if row is None:
        raise DingTalkExitEvidenceError("DINGTALK_EVIDENCE_SCOPE_NOT_FOUND")
    return row.tenant_id, row.project_id


def capture_dingtalk_exit_baseline(
    *,
    engine: Engine,
    tenant_slug: str,
    project_code: str,
    release_sha: str,
) -> DingTalkExitBaseline:
    if len(release_sha) != 40 or any(
        character not in "0123456789abcdef" for character in release_sha
    ):
        raise DingTalkExitEvidenceError("DINGTALK_EVIDENCE_RELEASE_INVALID")
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        tenant_id, project_id = _scope(
            connection,
            tenant_slug=tenant_slug,
            project_code=project_code,
        )
        captured_at = connection.execute(select(func.current_timestamp())).scalar_one()
        rows = connection.execute(
            select(
                tables.gates.c.id,
                tables.gates.c.code,
                tables.gates.c.status,
                tables.gates.c.updated_at,
                tables.gates.c.decided_at,
                tables.gates.c.decided_by_user_id,
            )
            .where(
                tables.gates.c.tenant_id == tenant_id,
                tables.gates.c.project_id == project_id,
            )
            .order_by(tables.gates.c.code, tables.gates.c.id)
        ).all()
    if not rows:
        raise DingTalkExitEvidenceError("DINGTALK_EVIDENCE_GATES_NOT_FOUND")
    gates = tuple(
        GateTruthSnapshot(
            gate_id=row.id,
            gate_code=row.code,
            status=row.status,
            truth_sha256=_gate_truth_sha256(row._mapping),
        )
        for row in rows
    )
    provisional = DingTalkExitBaseline(
        release_sha=release_sha,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        project_id=project_id,
        project_code=project_code,
        captured_at=captured_at,
        gates=gates,
        baseline_sha256="0" * 64,
    )
    return provisional.model_copy(update={"baseline_sha256": _baseline_sha256(provisional)})


def _check(name: str, passed: bool, success: str, failure: str) -> EvidenceCheck:
    return EvidenceCheck(name=name, passed=passed, detail=success if passed else failure)


def _verify_scope(connection: Connection, baseline: DingTalkExitBaseline) -> bool:
    row = connection.execute(
        select(tables.projects.c.id)
        .join(tables.tenants, tables.tenants.c.id == tables.projects.c.tenant_id)
        .where(
            tables.tenants.c.id == baseline.tenant_id,
            tables.tenants.c.slug == baseline.tenant_slug,
            tables.tenants.c.status == "active",
            tables.projects.c.id == baseline.project_id,
            tables.projects.c.code == baseline.project_code,
        )
    ).scalar_one_or_none()
    return row == baseline.project_id


def _delivery_footprint_count(
    connection: Connection,
    *,
    baseline: DingTalkExitBaseline,
    outbox_id: UUID,
    operation: str,
) -> int:
    return connection.execute(
        select(func.count())
        .select_from(
            tables.events.join(
                tables.audit_log,
                and_(
                    tables.audit_log.c.tenant_id == tables.events.c.tenant_id,
                    tables.audit_log.c.event_id == tables.events.c.event_id,
                    tables.audit_log.c.entity == tables.events.c.entity,
                    tables.audit_log.c.entity_id == tables.events.c.entity_id,
                ),
            )
        )
        .where(
            tables.events.c.tenant_id == baseline.tenant_id,
            tables.events.c.project_id == baseline.project_id,
            tables.events.c.event_type == "DINGTALK_NOTIFICATION_DELIVERED",
            tables.events.c.entity_id == outbox_id,
            tables.events.c.timestamp >= baseline.captured_at,
            tables.events.c.payload["outbox_id"].as_string() == str(outbox_id),
            tables.events.c.payload["operation"].as_string() == operation,
            tables.audit_log.c.action.in_(
                ("dingtalk.outbox.delivered", "dingtalk.outbox.reconcile")
            ),
            tables.audit_log.c.timestamp >= baseline.captured_at,
        )
    ).scalar_one()


def verify_dingtalk_exit_evidence(
    *,
    engine: Engine,
    baseline: DingTalkExitBaseline,
    release_sha: str,
) -> DingTalkExitEvidenceReport:
    if len(release_sha) != 40 or any(
        character not in "0123456789abcdef" for character in release_sha
    ):
        raise DingTalkExitEvidenceError("DINGTALK_EVIDENCE_RELEASE_INVALID")
    checks: list[EvidenceCheck] = []
    checks.append(
        _check(
            "release_identity",
            release_sha == baseline.release_sha,
            "verification release matches the captured full SHA",
            "verification release does not match the captured full SHA",
        )
    )
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        verified_at = connection.execute(select(func.current_timestamp())).scalar_one()
        scope_valid = _verify_scope(connection, baseline)
        checks.append(
            _check(
                "scope_identity",
                scope_valid,
                "active tenant and project match the baseline",
                "tenant or project scope no longer matches the baseline",
            )
        )
        if not scope_valid:
            return DingTalkExitEvidenceReport(
                release_sha=release_sha,
                tenant_slug=baseline.tenant_slug,
                project_code=baseline.project_code,
                baseline_sha256=baseline.baseline_sha256,
                verified_at=verified_at,
                checks=tuple(checks),
            )

        password_free_logins = connection.execute(
            select(func.count())
            .select_from(
                tables.events.join(
                    tables.audit_log,
                    and_(
                        tables.audit_log.c.tenant_id == tables.events.c.tenant_id,
                        tables.audit_log.c.event_id == tables.events.c.event_id,
                        tables.audit_log.c.entity == tables.events.c.entity,
                        tables.audit_log.c.entity_id == tables.events.c.entity_id,
                    ),
                ).join(
                    tables.dingtalk_user_bindings,
                    and_(
                        tables.dingtalk_user_bindings.c.tenant_id == tables.events.c.tenant_id,
                        tables.dingtalk_user_bindings.c.user_id == tables.events.c.entity_id,
                        tables.dingtalk_user_bindings.c.status == "active",
                    ),
                )
            )
            .where(
                tables.events.c.tenant_id == baseline.tenant_id,
                tables.events.c.event_type == "USER_SIGNED_IN",
                tables.events.c.timestamp >= baseline.captured_at,
                tables.events.c.payload["authentication_method"].as_string() == "dingtalk_oauth",
                tables.audit_log.c.action == "user.sign_in",
                tables.audit_log.c.timestamp >= baseline.captured_at,
                tables.audit_log.c.context["authentication_method"].as_string() == "dingtalk_oauth",
            )
        ).scalar_one()
        checks.append(
            _check(
                "password_free_login",
                password_free_logins >= 1,
                f"{password_free_logins} linked-user DingTalk login event was recorded",
                "no linked-user DingTalk login event was recorded after the baseline",
            )
        )

        group_rows = connection.execute(
            select(tables.integration_outbox.c.id).where(
                tables.integration_outbox.c.tenant_id == baseline.tenant_id,
                tables.integration_outbox.c.project_id == baseline.project_id,
                tables.integration_outbox.c.operation == "group_markdown",
                tables.integration_outbox.c.status == "succeeded",
                tables.integration_outbox.c.created_at >= baseline.captured_at,
                tables.integration_outbox.c.completed_at >= baseline.captured_at,
                tables.integration_outbox.c.remote_reference.is_not(None),
                func.btrim(tables.integration_outbox.c.remote_reference) != "",
            )
        ).all()
        delivered_groups = sum(
            _delivery_footprint_count(
                connection,
                baseline=baseline,
                outbox_id=row.id,
                operation="group_markdown",
            )
            == 1
            for row in group_rows
        )
        checks.append(
            _check(
                "group_notification",
                delivered_groups >= 1,
                f"{delivered_groups} project group delivery has a remote reference",
                "no succeeded project group delivery with a remote reference was found",
            )
        )

        approval_rows = connection.execute(
            select(
                tables.dingtalk_approval_instances.c.id,
                tables.dingtalk_approval_instances.c.gate_id,
                tables.dingtalk_approval_instances.c.outbox_id,
                tables.dingtalk_approval_instances.c.status,
                tables.integration_outbox.c.remote_reference,
            )
            .join(
                tables.integration_outbox,
                and_(
                    tables.integration_outbox.c.tenant_id
                    == tables.dingtalk_approval_instances.c.tenant_id,
                    tables.integration_outbox.c.id
                    == tables.dingtalk_approval_instances.c.outbox_id,
                ),
            )
            .where(
                tables.dingtalk_approval_instances.c.tenant_id == baseline.tenant_id,
                tables.dingtalk_approval_instances.c.project_id == baseline.project_id,
                tables.dingtalk_approval_instances.c.created_at >= baseline.captured_at,
                tables.dingtalk_approval_instances.c.status.in_(TERMINAL_APPROVAL_STATUSES),
                tables.dingtalk_approval_instances.c.completed_at >= baseline.captured_at,
                tables.integration_outbox.c.status == "succeeded",
                tables.integration_outbox.c.remote_reference.is_not(None),
            )
            .order_by(tables.dingtalk_approval_instances.c.created_at)
        ).all()
        baseline_gates = {gate.gate_id: gate for gate in baseline.gates}
        current_gate_rows = connection.execute(
            select(
                tables.gates.c.id,
                tables.gates.c.code,
                tables.gates.c.status,
                tables.gates.c.updated_at,
                tables.gates.c.decided_at,
                tables.gates.c.decided_by_user_id,
            ).where(
                tables.gates.c.tenant_id == baseline.tenant_id,
                tables.gates.c.project_id == baseline.project_id,
            )
        ).all()
        current_gate_hashes = {
            row.id: _gate_truth_sha256(row._mapping) for row in current_gate_rows
        }
        baseline_gate_hashes = {gate.gate_id: gate.truth_sha256 for gate in baseline.gates}
        gate_truth_unchanged = current_gate_hashes == baseline_gate_hashes
        checks.append(
            _check(
                "gate_truth_unchanged",
                gate_truth_unchanged,
                "the complete project Gate truth set matches the pre-smoke baseline",
                "the project Gate truth set drifted after the pre-smoke baseline",
            )
        )
        eligible_approvals = []
        for approval in approval_rows:
            gate_baseline = baseline_gates.get(approval.gate_id)
            event_count = connection.execute(
                select(func.count())
                .select_from(
                    tables.events.join(
                        tables.audit_log,
                        and_(
                            tables.audit_log.c.tenant_id == tables.events.c.tenant_id,
                            tables.audit_log.c.event_id == tables.events.c.event_id,
                            tables.audit_log.c.entity == tables.events.c.entity,
                            tables.audit_log.c.entity_id == tables.events.c.entity_id,
                        ),
                    )
                )
                .where(
                    tables.events.c.tenant_id == baseline.tenant_id,
                    tables.events.c.project_id == baseline.project_id,
                    tables.events.c.event_type == "DINGTALK_APPROVAL_UPDATED",
                    tables.events.c.entity_id == approval.id,
                    tables.events.c.timestamp >= baseline.captured_at,
                    tables.events.c.payload["status"].as_string() == approval.status,
                    tables.audit_log.c.action == "dingtalk.approval.sync",
                    tables.audit_log.c.timestamp >= baseline.captured_at,
                    tables.audit_log.c.context["system_of_record"].as_string()
                    == "external_evidence_only",
                )
            ).scalar_one()
            if (
                gate_baseline is not None
                and gate_truth_unchanged
                and current_gate_hashes.get(approval.gate_id) == gate_baseline.truth_sha256
                and event_count >= 1
                and _delivery_footprint_count(
                    connection,
                    baseline=baseline,
                    outbox_id=approval.outbox_id,
                    operation="gate_approval_create",
                )
                == 1
                and approval.remote_reference
            ):
                eligible_approvals.append(approval)
        checks.append(
            _check(
                "approval_mirror_gate_truth",
                bool(eligible_approvals),
                "a terminal external approval was mirrored while its PDOS Gate truth "
                "stayed unchanged",
                "no terminal approval proves both mirror update and unchanged PDOS Gate truth",
            )
        )

        approval_receipts = connection.execute(
            select(func.count())
            .select_from(tables.integration_receipts)
            .where(
                tables.integration_receipts.c.tenant_id == baseline.tenant_id,
                tables.integration_receipts.c.channel == "event_aes",
                tables.integration_receipts.c.status == "processed",
                tables.integration_receipts.c.result_code == "approval_sync_requested",
                tables.integration_receipts.c.received_at >= baseline.captured_at,
            )
        ).scalar_one()
        checks.append(
            _check(
                "approval_callback",
                approval_receipts >= 1,
                f"{approval_receipts} authenticated approval callback receipt was processed",
                "no authenticated approval callback receipt was processed after the baseline",
            )
        )

        card_rows = connection.execute(
            select(
                tables.dingtalk_interactive_cards.c.id,
                tables.dingtalk_interactive_cards.c.outbox_id,
                tables.dingtalk_interactive_cards.c.out_track_id,
            )
            .join(
                tables.integration_outbox,
                and_(
                    tables.integration_outbox.c.tenant_id
                    == tables.dingtalk_interactive_cards.c.tenant_id,
                    tables.integration_outbox.c.id == tables.dingtalk_interactive_cards.c.outbox_id,
                ),
            )
            .where(
                tables.dingtalk_interactive_cards.c.tenant_id == baseline.tenant_id,
                tables.dingtalk_interactive_cards.c.project_id == baseline.project_id,
                tables.dingtalk_interactive_cards.c.action_key == "acknowledge",
                tables.dingtalk_interactive_cards.c.status == "acknowledged",
                tables.dingtalk_interactive_cards.c.created_at >= baseline.captured_at,
                tables.dingtalk_interactive_cards.c.acknowledged_at >= baseline.captured_at,
                tables.dingtalk_interactive_cards.c.acknowledged_by_user_id.is_not(None),
                tables.integration_outbox.c.status == "succeeded",
                tables.integration_outbox.c.remote_reference.is_not(None),
            )
        ).all()
        eligible_cards = 0
        for card in card_rows:
            receipt_count = connection.execute(
                select(func.count())
                .select_from(tables.integration_receipts)
                .where(
                    tables.integration_receipts.c.tenant_id == baseline.tenant_id,
                    tables.integration_receipts.c.channel == "card_hmac",
                    tables.integration_receipts.c.external_id == card.out_track_id,
                    tables.integration_receipts.c.status == "processed",
                    tables.integration_receipts.c.result_code == "acknowledged",
                    tables.integration_receipts.c.received_at >= baseline.captured_at,
                )
            ).scalar_one()
            event_audit_count = connection.execute(
                select(func.count())
                .select_from(
                    tables.events.join(
                        tables.audit_log,
                        and_(
                            tables.audit_log.c.tenant_id == tables.events.c.tenant_id,
                            tables.audit_log.c.event_id == tables.events.c.event_id,
                            tables.audit_log.c.entity == tables.events.c.entity,
                            tables.audit_log.c.entity_id == tables.events.c.entity_id,
                        ),
                    )
                )
                .where(
                    tables.events.c.tenant_id == baseline.tenant_id,
                    tables.events.c.project_id == baseline.project_id,
                    tables.events.c.event_type == "DINGTALK_CARD_ACTION_RECEIVED",
                    tables.events.c.entity_id == card.id,
                    tables.events.c.timestamp >= baseline.captured_at,
                    tables.events.c.payload["action"].as_string() == "acknowledge",
                    tables.audit_log.c.project_id == baseline.project_id,
                    tables.audit_log.c.action == "dingtalk.card.acknowledge",
                    tables.audit_log.c.timestamp >= baseline.captured_at,
                )
            ).scalar_one()
            delivery_count = _delivery_footprint_count(
                connection,
                baseline=baseline,
                outbox_id=card.outbox_id,
                operation="interactive_card_create",
            )
            if receipt_count == event_audit_count == delivery_count == 1:
                eligible_cards += 1
        checks.append(
            _check(
                "card_acknowledgement",
                eligible_cards >= 1,
                "a delivered card has exactly one receipt, event, and audit "
                "acknowledgement footprint",
                "no delivered card has a single complete acknowledgement footprint",
            )
        )

        unresolved = connection.execute(
            select(func.count())
            .select_from(tables.integration_outbox)
            .where(
                tables.integration_outbox.c.tenant_id == baseline.tenant_id,
                tables.integration_outbox.c.provider == "dingtalk",
                tables.integration_outbox.c.status.in_(UNRESOLVED_OUTBOX_STATUSES),
            )
        ).scalar_one()
        checks.append(
            _check(
                "outbox_reconciliation",
                unresolved == 0,
                "no unresolved DingTalk outbox records remain",
                f"{unresolved} unresolved DingTalk outbox records require review",
            )
        )
    return DingTalkExitEvidenceReport(
        release_sha=release_sha,
        tenant_slug=baseline.tenant_slug,
        project_code=baseline.project_code,
        baseline_sha256=baseline.baseline_sha256,
        verified_at=verified_at,
        checks=tuple(checks),
    )
