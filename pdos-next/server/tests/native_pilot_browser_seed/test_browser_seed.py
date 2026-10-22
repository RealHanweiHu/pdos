"""Keep the actual prepared synthetic fixture alive without creating a Pilot.

Only the explicit private JSON contains its short-lived fixture bearer. Nothing
renews authority, consumes Pilot confirmation, creates an observation or grants
qualification. Root alone runs the browser against this finite local server.
"""

import json
import os
import socket
import stat
import threading
import time
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import uvicorn
from native_pilot_transactions import fixtures as native
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.quality_execution import service as issue_owner
from pdos_next.models import Grant, LoginSession, Product, now
from pdos_next.safety import verify_test_target
from pdos_next.schemas.manufacturing_trials.contracts import (
    Counts,
    ExceptionFact,
    Ref,
    ResultRecord,
    YieldScope,
)
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import digest


def _write_private_new(path: Path, value):
    content = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            assert stat.S_IMODE(os.fstat(output.fileno()).st_mode) == 0o600
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _empty_sources(value):
    """Explicit unfinished UI template; it must never be accepted as an original."""
    if isinstance(value, SourceRef):
        return None
    if isinstance(value, BaseModel):
        result = value.model_dump(mode="json")
        for key in type(value).model_fields:
            child = getattr(value, key)
            if isinstance(child, (BaseModel, tuple)):
                result[key] = _empty_sources(child)
        return result
    if isinstance(value, tuple):
        return [_empty_sources(child) for child in value]
    return value


def _templates(work):
    create, stats = work.create, work.create.statistics
    assert stats is not None and work.population_count == 2
    with native.publication.session(work) as s:
        row, viewed = issue_owner.get_issue_for_change(
            s, work.setup.ctx, work.setup.product, work.issue_id
        )
        assert row.project_id == work.project_id and viewed.is_current
        issue = Ref(kind="issue", id=row.issue_id, revision=row.revision)
        issue_metadata = {
            "id": str(row.issue_id),
            "revision": row.revision,
            "version_id": str(row.id),
        }
    scope = YieldScope(
        basis=create.details.basis,
        manufacturing_baseline=create.details.manufacturing_baseline,
        line=create.details.line,
        cohort_key=stats.statistics_basis_key,
        window_start=stats.window_start,
        window_end=stats.window_end,
        criterion=Ref(kind="criterion", id=stats.criterion_id, revision=stats.criterion_revision),
        nature="synthetic",
        minimum_sample=stats.minimum_sample,
    )
    records, originals = {}, {}
    prior_id = None
    for revision, complete in ((1, False), (2, True)):
        record = ResultRecord(
            observation_id=uuid4(),
            expected_pilot_revision=revision,
            previous_observation_id=prior_id,
            correction_reason="Original correction records completed rework" if complete else None,
            scope=scope,
            counts=Counts(
                input_count=work.population_count,
                output_count=work.population_count,
                first_pass=1,
                first_failed=1,
                first_unknown=0,
                final_good=2 if complete else 1,
                reworked_good=1 if complete else 0,
                scrap=0,
                rework_pending=0 if complete else 1,
                undecided=0,
                unprocessed=0,
                rework_cycles=1 if complete else 0,
            ),
            exceptions=(
                ExceptionFact(
                    key="real-current-issue",
                    description="Retain the actual same-project failure Issue",
                    source=create.details.source,
                    issue=issue,
                    disposition=create.details.source,
                ),
            ),
            observed={
                "occurred_at": work.output_occurred_at + timedelta(seconds=20 if complete else 10),
                "original_timezone": "UTC",
                "source": create.details.source,
            },
            source=create.details.source,
        )
        key = "complete" if complete else "partial"
        records[key] = _empty_sources(record)
        originals[key] = native.result_values(create.details.pilot_id, record)
        prior_id = record.observation_id
    return records, originals, issue_metadata


@pytest.mark.skipif(
    os.environ.get("PDOS_NATIVE_PILOT_BROWSER_SEED") != "1",
    reason="Explicit finite local browser seed only",
)
@pytest.mark.parametrize("launch_work", [{"window_minutes": 45, "fact_minutes": 60}], indirect=True)
def test_prepare_finite_actual_native_pilot_browser_seed(native_case, browser_seed_authorization):
    work, setup = native_case, native_case.setup
    directory, port = browser_seed_authorization
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    captured = now()
    token = setup.tokens[setup.human]
    # Read only this explicit fixture's original login metadata as admin; the
    # public app role cannot read the auth role's private LoginSession table.
    with Session(setup.admin) as s:
        product = s.get(Product, setup.product)
        login = s.get(LoginSession, digest(token))
        grant = s.scalar(
            select(Grant).where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == setup.human,
            )
        )
        assert product is not None and product.category_id == setup.category
        assert login is not None and not login.revoked and login.expires_at > captured
        assert (login.tenant_id, login.principal_id) == (setup.tenant, setup.human)
        assert grant is not None and grant.can_write and grant.expires_at > captured
        credentials = {
            "login_expires_at": login.expires_at.isoformat(),
            "grant_id": str(grant.id),
            "grant_epoch": grant.access_epoch,
            "grant_expires_at": grant.expires_at.isoformat(),
        }
        product_metadata = {"revision": product.revision, "name": product.name}
        professional_facts = []
        deadlines = [login.expires_at, grant.expires_at, work.execution_scope.window.finish]
        for receipt in work.authority_receipts[setup.human].values():
            fact = s.get(ProfessionalFact, UUID(receipt["subject_id"]))
            assert fact is not None
            assert fact.subject_id == setup.human and fact.project_id == work.project_id
            assert fact.valid_from <= captured < fact.valid_until and fact.nature == "synthetic"
            professional_facts.append(
                {
                    "id": str(fact.id),
                    "revision": fact.revision,
                    "kind": fact.kind,
                    "role": fact.role,
                    "nature": fact.nature,
                    "operations": fact.operations,
                    "valid_from": fact.valid_from.isoformat(),
                    "valid_until": fact.valid_until.isoformat(),
                }
            )
            deadlines.append(fact.valid_until)
    records, originals, issue = _templates(work)
    # The fixture has not called any Pilot inputs/preview/execute. All IDs below
    # are actual parent reads or explicitly pending UI template identities.
    with native.publication.session(work) as s:
        assert (
            s.scalar(
                select(native.NativePilotRun.id).where(
                    native.NativePilotRun.tenant_id == setup.tenant,
                    native.NativePilotRun.product_id == setup.product,
                )
            )
            is None
        )
    sock, server, thread = None, None, None
    errors = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
        server = uvicorn.Server(
            uvicorn.Config(
                setup.client.app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                access_log=False,
            )
        )

        def serve():
            try:
                server.run(sockets=[sock])
            except BaseException as error:
                errors.append(type(error).__name__)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        started_by = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < started_by:
            time.sleep(0.1)
        assert server.started and not errors, "Own actual synthetic API startup failed"
        seed = {
            "schema_version": "pdos-native-pilot-browser-seed-v1",
            "synthetic": True,
            "created_at": captured.isoformat(),
            "api_host": "127.0.0.1",
            "api_port": port,
            "tenant_id": str(setup.tenant),
            "principal_id": str(setup.human),
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "product": product_metadata,
            "project_id": str(work.project_id),
            "purpose": work.purpose,
            "bearer": token,
            **credentials,
            "professional_facts": professional_facts,
            "effective_until": min(deadlines).isoformat(),
            "create": work.create.model_dump(mode="json"),
            "statistics_template": native.statistics_declaration(
                work.create.details.pilot_id, work.create.statistics
            ),
            "result_templates": records,
            "original_values_templates": originals,
            "read_ids": {
                "prior_build_id": work.upstream.build_id,
                "basis": work.basis.model_dump(mode="json"),
                "publication": {"id": work.published["id"], "revision": work.published["revision"]},
                "line": work.line.model_dump(mode="json"),
                "samples": [sample.model_dump(mode="json") for sample in work.samples],
                "issue": issue,
                "line_receipt_id": work.line_receipt["id"],
                "statistics_original_id": str(work.statistics_original_id),
            },
            "store": {"kind": type(work.store).__name__, "root": str(work.store.root)},
            "live_runtime": {
                "professional_issuer_key": work.issuer.key,
                "line_issuer_key": work.line_issuer.key,
                "line_execution_scope": work.execution_scope.model_dump(mode="json"),
            },
            "template_bindings": {
                "new_pilot": (
                    "Replace statistics_template.pilot_id with the actual UI Pilot id, register "
                    "that JSON line through the public artifact command and select its source."
                ),
                "records": (
                    "Replace expected_pilot_revision, previous_observation_id and observation_id "
                    "from actual Current/previous observation; bind the actual UI Pilot id in "
                    "the original JSON wrapper before registering/uploading it."
                ),
                "sources": (
                    "Every null source is unfinished template data. Use actual original selection "
                    "and its real line hash for record/observed/exception/disposition references."
                ),
                "fixed_draft": (
                    "Alternatively restore an unconfirmed UI draft with create.details.pilot_id; "
                    "its statistics original is prepared. No Pilot confirmation was consumed."
                ),
            },
            "boundary": (
                "Finite local synthetic fixture only; qualification unknown, no start or release. "
                "Neither templates nor hashes are owner evidence. Do not renew fixture authority "
                "or event clocks."
            ),
            "finish_file": str(directory / "finish"),
            "maximum_wait_seconds": 1200,
        }
        _write_private_new(directory / "seed.json", seed)
        print("Actual synthetic Pilot browser scope ready; API port", port, flush=True)
        deadline = time.monotonic() + 1200
        while not (directory / "finish").exists() and time.monotonic() < deadline:
            assert thread.is_alive() and not errors, (
                "Own synthetic API stopped before browser finish"
            )
            time.sleep(0.2)
        assert (directory / "finish").exists(), (
            "Finite browser checkpoint elapsed without finish signal"
        )
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(10)
            if thread.is_alive():
                server.force_exit = True
                thread.join(5)
        if sock is not None:
            sock.close()
        assert thread is None or not thread.is_alive(), "Own synthetic API did not stop"
