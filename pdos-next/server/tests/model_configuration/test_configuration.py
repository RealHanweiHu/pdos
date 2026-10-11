"""Only explicit synthetic inputs/ports. Never imports app, conftest, DB or env loaders."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from pdos_next.errors import DomainError
from pdos_next.model_configuration.ports import (
    ManagementContext,
    RuntimeFacts,
    RuntimeQuery,
    SecretBinding,
    SecretMaterial,
)
from pdos_next.model_configuration.runtime import RuntimeConfiguration
from pdos_next.model_configuration.service import ConfigurationService
from pdos_next.model_gateway.ports import CallPermit
from pdos_next.schemas.model_configuration import ModelMetadata, SaveConfiguration

NOW = datetime(2026, 10, 2, tzinfo=UTC)
SYNTHETIC_KEY = "synthetic-test-only-credential"


class SyntheticStore:
    def __init__(self):
        self.rows = {}
        self.history = []

    def current(self, tenant_id):
        return self.rows.get(tenant_id)

    def append(self, version, *, expected_revision):
        old = self.current(version.tenant_id)
        if (old.revision if old else 0) != expected_revision:
            raise DomainError("MODEL_CONFIGURATION_STALE", "synthetic CAS")
        self.rows[version.tenant_id] = version
        self.history.append(version)


class SyntheticAdmin:
    def __init__(self, context):
        self.context, self.allowed = context, True

    def is_current_human_admin(self, context):
        return self.allowed and context == self.context


class SyntheticSecrets:
    def __init__(self, context, protocol):
        self.binding = SecretBinding(context.tenant_id, uuid4(), uuid4(), protocol, True)
        self.resolved = 0
        self.failure = False
        self.wrong_material = False
        self.rotate_on_resolve = False

    def current(self, tenant_id, protocol):
        if self.failure:
            raise RuntimeError(SYNTHETIC_KEY)
        return self.binding

    def resolve(self, binding):
        self.resolved += 1
        result = SecretMaterial(
            replace(binding, version=uuid4()) if self.wrong_material else binding,
            SecretStr(SYNTHETIC_KEY),
        )
        if self.rotate_on_resolve:
            self.binding = replace(binding, version=uuid4())
        return result


class SyntheticPolicy:
    def __init__(self):
        self.overrides = {}
        self.called = 0

    def current_facts(self, query, binding_digest):
        self.called += 1
        return replace(
            RuntimeFacts(
                query, binding_digest, NOW + timedelta(minutes=1), True, True, True, True, False
            ),
            **self.overrides,
        )


@pytest.fixture
def setup():
    ctx = ManagementContext(uuid4(), uuid4())
    store, admin = SyntheticStore(), SyntheticAdmin(ctx)
    metadata = ModelMetadata(
        protocol="openai-compatible",
        base_url="https://synthetic.invalid/v1",
        model="synthetic-model",
        model_version="synthetic-v1",
    )
    secrets, policy = SyntheticSecrets(ctx, metadata.protocol), SyntheticPolicy()
    service = ConfigurationService(store, admin, secrets)
    query = RuntimeQuery(
        ctx.tenant_id,
        uuid4(),
        uuid4(),
        "evidence.claim.record",
        "source_claim",
        "skill-v1",
        "tools-v1",
        0,
    )
    return ctx, store, admin, metadata, secrets, policy, service, query


def save(setup, *, enabled=True):
    ctx, store, _, metadata, _, _, service, _ = setup
    head = store.current(ctx.tenant_id)
    plan = service.plan(
        ctx,
        SaveConfiguration(
            expected_revision=head.revision if head else 0, metadata=metadata, enabled=enabled
        ),
        now=NOW,
    )
    return service.apply_plan(ctx, plan, now=NOW)


def assert_code(code, function):
    with pytest.raises(DomainError) as error:
        function()
    assert error.value.reason == code
    assert SYNTHETIC_KEY not in str(error.value)


@pytest.mark.parametrize("protocol", ["openai-compatible", "anthropic-native"])
def test_plan_save_masked_read_runtime_selection(setup, protocol):
    ctx, store, admin, metadata, secrets, policy, service, query = setup
    metadata = metadata.model_copy(update={"protocol": protocol})
    secrets.binding = replace(secrets.binding, protocol=protocol)
    plan = service.plan(
        ctx, SaveConfiguration(expected_revision=0, metadata=metadata, enabled=True), now=NOW
    )
    assert store.history == []
    assert plan.preview().requires_requalification is True
    version = service.apply_plan(ctx, plan, now=NOW)
    reading = service.reading(ctx)
    assert reading.credential_display == "已绑定 ••••"
    assert reading.enabled and reading.revision == 1
    assert SYNTHETIC_KEY not in reading.model_dump_json()
    assert str(secrets.binding.reference) not in reading.model_dump_json()
    assert str(secrets.binding.version) not in reading.model_dump_json()
    assert SYNTHETIC_KEY not in repr(plan) + repr(version) + repr(plan.preview())
    runtime = RuntimeConfiguration(store, secrets, policy)
    selected = runtime.select(query, now=NOW)
    assert selected.state == "authorizer_check"
    assert selected.code == "MODEL_AUTHORIZER_CHECK_REQUIRED"
    assert selected.route.protocol == protocol
    assert selected.route.version == version.provider_version
    assert selected.route.api_key.get_secret_value() == SYNTHETIC_KEY
    assert selected.route.target_url.endswith(
        "messages" if protocol == "anthropic-native" else "chat/completions"
    )
    assert SYNTHETIC_KEY not in repr(selected) + selected.route.digest
    assert secrets.resolved == 1
    assert admin.allowed


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "actor_id",
        "run_id",
        "grant",
        "qualified",
        "api_key",
        "secret_reference",
        "secret_version",
        "write_tier",
    ],
)
def test_trusted_and_secret_field_injection_forbidden(setup, field):
    metadata = setup[3]
    body = dict(expected_revision=0, metadata=metadata.model_dump(), enabled=False)
    with pytest.raises(ValidationError) as error:
        SaveConfiguration.model_validate({**body, field: SYNTHETIC_KEY})
    assert SYNTHETIC_KEY not in str(error.value)
    with pytest.raises(ValidationError):
        ModelMetadata.model_validate({**metadata.model_dump(), field: SYNTHETIC_KEY})


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:password@synthetic.invalid/v1",
        "https://synthetic.invalid/v1?api_key=private",
        "https://synthetic.invalid/v1#private",
        "http://synthetic.invalid/v1",
        "file:///private",
        "https://synthetic.invalid/../v1",
        "https://synthetic.invalid/v1 bad",
        "https://synthetic.invalid:bad/v1",
        "https://synthetic.invalid/%2e%2e",
        "https://synthetic.invalid\\evil/v1",
    ],
)
def test_provider_target_policy_reused(setup, endpoint):
    with pytest.raises(ValidationError):
        ModelMetadata.model_validate({**setup[3].model_dump(), "base_url": endpoint})


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol", "other"),
        ("max_output_tokens", True),
        ("max_output_tokens", 0),
        ("max_output_tokens", 32769),
        ("timeout_seconds", float("nan")),
        ("timeout_seconds", 91.0),
        ("response_bytes", 1),
        ("model", "unsafe\ntext"),
        ("model_version", ""),
        ("openai_output_parameter", "tools"),
    ],
)
def test_closed_metadata_limits(setup, field, value):
    with pytest.raises(ValidationError):
        ModelMetadata.model_validate({**setup[3].model_dump(), field: value})


def test_non_admin_and_revocation_between_preview_and_save(setup):
    ctx, store, admin, metadata, _, _, service, _ = setup
    payload = SaveConfiguration(expected_revision=0, metadata=metadata, enabled=True)
    plan = service.plan(ctx, payload, now=NOW)
    admin.allowed = False
    assert_code("MODEL_ADMIN_REQUIRED", lambda: service.plan(ctx, payload, now=NOW))
    assert_code("MODEL_ADMIN_REQUIRED", lambda: service.apply_plan(ctx, plan, now=NOW))
    assert store.history == []


def test_cross_tenant_and_actor_contexts_cannot_consume_plan(setup):
    ctx, store, admin, metadata, _, _, service, _ = setup
    plan = service.plan(ctx, SaveConfiguration(expected_revision=0, metadata=metadata), now=NOW)
    for other in (replace(ctx, tenant_id=uuid4()), replace(ctx, actor_id=uuid4())):
        admin.context = other  # Even an independent authorized administrator cannot take this plan.
        assert_code(
            "MODEL_CONFIGURATION_SCOPE_MISMATCH",
            lambda other=other: service.apply_plan(other, plan, now=NOW),
        )
    assert store.history == []


def test_expiry_stale_and_same_revision_digest_change(setup):
    ctx, store, _, metadata, _, _, service, _ = setup
    plan = service.plan(ctx, SaveConfiguration(expected_revision=0, metadata=metadata), now=NOW)
    assert_code(
        "MODEL_CONFIGURATION_PREVIEW_EXPIRED",
        lambda: service.apply_plan(ctx, plan, now=NOW + timedelta(minutes=5)),
    )
    save(setup)
    assert_code("MODEL_CONFIGURATION_STALE", lambda: service.apply_plan(ctx, plan, now=NOW))
    plan = service.plan(ctx, SaveConfiguration(expected_revision=1, metadata=metadata), now=NOW)
    store.rows[ctx.tenant_id] = replace(store.rows[ctx.tenant_id], enabled=False)
    assert_code("MODEL_CONFIGURATION_STALE", lambda: service.apply_plan(ctx, plan, now=NOW))


def test_secret_rotation_rejects_plan_and_previous_runtime_binding(setup):
    ctx, store, _, metadata, secrets, policy, service, query = setup
    original = save(setup)
    runtime = RuntimeConfiguration(store, secrets, policy)
    selected = runtime.select(query, now=NOW)
    plan = service.plan(
        ctx, SaveConfiguration(expected_revision=1, metadata=metadata, enabled=True), now=NOW
    )
    secrets.binding = replace(secrets.binding, version=uuid4())
    assert_code("MODEL_SECRET_CHANGED", lambda: service.apply_plan(ctx, plan, now=NOW))
    assert runtime.select(query, now=NOW).reason == "MODEL_SECRET_CHANGED"
    assert service.reading(ctx).credential_status == "changed"
    assert store.history == [original]
    renewed = save(setup)
    assert renewed.provider_version != original.provider_version
    assert renewed.binding_digest != original.binding_digest
    assert_code(
        "MODEL_CONFIGURATION_CHANGED",
        lambda: runtime.currentness(
            selected, query, now=lambda: NOW, require_permit_current=lambda _: None
        )(permit_for(selected, query)),
    )


def permit_for(selection, query):
    return CallPermit(
        uuid4(),
        "synthetic-request-digest",
        selection.route.digest,
        query.writer_id,
        selection.configuration.provider_version,
        NOW + timedelta(minutes=1),
        egress_allowed=True,
        protocol=selection.route.protocol,
    )


def test_disabled_not_configured_and_missing_secret(setup):
    _, store, _, _, secrets, policy, _, query = setup
    runtime = RuntimeConfiguration(store, secrets, policy)
    assert runtime.select(query, now=NOW).reason == "MODEL_NOT_CONFIGURED"
    save(setup, enabled=False)
    assert runtime.select(query, now=NOW).reason == "MODEL_DISABLED"
    secrets.binding = None
    save(setup)
    assert runtime.select(query, now=NOW).reason == "MODEL_SECRET_MISSING"
    assert secrets.resolved == 0


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("permitted", False, "MODEL_PERMISSION_DENIED"),
        ("qualified", False, "MODEL_QUALIFICATION_REQUIRED"),
        ("egress_allowed", False, "MODEL_EGRESS_REQUIRED"),
        ("budget_available", False, "MODEL_BUDGET_REQUIRED"),
        ("cancelled", True, "MODEL_CANCELLED"),
        ("permitted", None, "MODEL_PERMISSION_FACT_MISSING"),
        ("qualified", None, "MODEL_QUALIFICATION_FACT_MISSING"),
        ("egress_allowed", None, "MODEL_EGRESS_FACT_MISSING"),
        ("budget_available", None, "MODEL_BUDGET_FACT_MISSING"),
        ("cancelled", None, "MODEL_CANCEL_FACT_MISSING"),
        ("qualified", 1, "MODEL_QUALIFICATION_FACT_MISSING"),
        ("expires_at", NOW, "MODEL_POLICY_EXPIRED"),
        ("expires_at", NOW.replace(tzinfo=None), "MODEL_POLICY_EXPIRED"),
        ("binding_digest", "different", "MODEL_POLICY_SCOPE_MISMATCH"),
    ],
)
def test_current_facts_fail_closed_before_secret_resolution(setup, field, value, code):
    _, store, _, _, secrets, policy, _, query = setup
    save(setup)
    policy.overrides = {field: value}
    selected = RuntimeConfiguration(store, secrets, policy).select(query, now=NOW)
    assert selected.reason == code and selected.state == "unavailable" and selected.route is None
    assert secrets.resolved == 0


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "run_id",
        "writer_id",
        "operation",
        "purpose",
        "skill_version",
        "tool_version",
        "cancel_epoch",
    ],
)
def test_policy_query_must_match_all_bound_dimensions(setup, field):
    _, store, _, _, secrets, policy, _, query = setup
    save(setup)
    value = uuid4() if field.endswith("_id") else 1 if field == "cancel_epoch" else "changed"
    policy.overrides = {"query": replace(query, **{field: value})}
    assert RuntimeConfiguration(store, secrets, policy).select(query, now=NOW).reason == (
        "MODEL_POLICY_SCOPE_MISMATCH"
    )
    assert secrets.resolved == 0


def test_currentness_compounds_main_guard_and_rechecks_after_cancellation(setup):
    _, store, _, _, secrets, policy, _, query = setup
    save(setup)
    runtime = RuntimeConfiguration(store, secrets, policy)
    selected = runtime.select(query, now=NOW)
    permit = permit_for(selected, query)
    seen = []
    check = runtime.currentness(
        selected, query, now=lambda: NOW, require_permit_current=lambda p: seen.append(p.call_id)
    )
    check(permit)
    assert seen == [permit.call_id]
    policy.overrides = {"cancelled": True}
    assert_code("MODEL_CANCELLED", lambda: check(permit))
    policy.overrides = {}
    assert_code("MODEL_PERMIT_BINDING_MISMATCH", lambda: check(replace(permit, writer_id=uuid4())))
    assert_code("MODEL_PERMIT_BINDING_MISMATCH", lambda: check(replace(permit, expires_at=NOW)))
    missing = runtime.currentness(selected, query, now=lambda: NOW, require_permit_current=None)
    assert_code("MODEL_PERMIT_INTERFACE_MISSING", lambda: missing(permit))


def test_scoped_ports_errors_and_secret_material_drift_fail_closed(setup):
    ctx, store, _, metadata, secrets, policy, service, query = setup
    save(setup)
    runtime = RuntimeConfiguration(store, secrets, policy)
    secrets.binding = replace(secrets.binding, tenant_id=uuid4())
    assert runtime.select(query, now=NOW).reason == "MODEL_SECRET_SCOPE_MISMATCH"
    secrets.binding = replace(secrets.binding, tenant_id=ctx.tenant_id)
    secrets.failure = True
    assert runtime.select(query, now=NOW).reason == "MODEL_SECRET_UNAVAILABLE"
    assert service.reading(ctx).credential_status == "unavailable"
    assert_code(
        "MODEL_SECRET_UNAVAILABLE",
        lambda: service.plan(
            ctx, SaveConfiguration(expected_revision=1, metadata=metadata), now=NOW
        ),
    )
    secrets.failure = False
    secrets.wrong_material = True
    assert runtime.select(query, now=NOW).reason == "MODEL_SECRET_MISSING"
    secrets.wrong_material = False
    secrets.rotate_on_resolve = True
    assert runtime.select(query, now=NOW).reason == "MODEL_SECRET_CHANGED"


def test_configuration_change_and_disable_invalidate_old_permit(setup):
    ctx, store, _, metadata, secrets, policy, service, query = setup
    original = save(setup)
    runtime = RuntimeConfiguration(store, secrets, policy)
    selected = runtime.select(query, now=NOW)
    plan = service.plan(
        ctx,
        SaveConfiguration(
            expected_revision=1,
            metadata=metadata.model_copy(update={"model_version": "v2"}),
            enabled=True,
        ),
        now=NOW,
    )
    updated = service.apply_plan(ctx, plan, now=NOW)
    assert updated.provider_version != original.provider_version
    check = runtime.currentness(
        selected, query, now=lambda: NOW, require_permit_current=lambda _: None
    )
    assert_code("MODEL_CONFIGURATION_CHANGED", lambda: check(permit_for(selected, query)))
    disabled = save(setup, enabled=False)
    assert disabled.revision == 3
    assert len(store.history) == 3 and store.history[0].enabled is True
    assert runtime.select(query, now=NOW).reason == "MODEL_DISABLED"


def test_missing_interfaces_do_not_implicitly_enable(setup):
    ctx, store, _, metadata, secrets, policy, _, query = setup
    save(setup)
    payload = SaveConfiguration(expected_revision=1, metadata=metadata)
    assert_code(
        "MODEL_ADMIN_INTERFACE_MISSING",
        lambda: ConfigurationService(store, None, secrets).plan(ctx, payload, now=NOW),
    )
    assert RuntimeConfiguration(store, None, policy).select(query, now=NOW).reason == (
        "MODEL_SECRET_INTERFACE_MISSING"
    )
    assert RuntimeConfiguration(store, secrets, None).select(query, now=NOW).reason == (
        "MODEL_POLICY_INTERFACE_MISSING"
    )


def test_forged_construct_payload_is_revalidated(setup):
    ctx, _, _, metadata, _, _, service, _ = setup
    forged = SaveConfiguration.model_construct(
        expected_revision=0,
        enabled=True,
        metadata=metadata.model_copy(update={"base_url": "https://u:secret@synthetic.invalid"}),
    )
    assert_code("MODEL_CONFIGURATION_INPUT_INVALID", lambda: service.plan(ctx, forged, now=NOW))


def test_port_policy_exception_is_redacted_and_missing_facts_are_unavailable(setup):
    _, store, _, _, secrets, _, _, query = setup
    save(setup)

    class MissingPolicy:
        def current_facts(self, query, binding_digest):
            return None

    class BrokenPolicy:
        def current_facts(self, query, binding_digest):
            raise RuntimeError(SYNTHETIC_KEY)

    for policy, code in [
        (MissingPolicy(), "MODEL_POLICY_FACTS_MISSING"),
        (BrokenPolicy(), "MODEL_POLICY_UNAVAILABLE"),
    ]:
        result = RuntimeConfiguration(store, secrets, policy).select(query, now=NOW)
        assert result.reason == code and result.route is None
        assert SYNTHETIC_KEY not in repr(result)


def test_unavailable_secret_and_wrong_tenant_storage_are_rejected(setup):
    ctx, store, _, _, secrets, policy, _, query = setup
    secrets.binding = replace(secrets.binding, available=False)
    save(setup)
    runtime = RuntimeConfiguration(store, secrets, policy)
    assert runtime.select(query, now=NOW).reason == "MODEL_SECRET_MISSING"
    store.rows[ctx.tenant_id] = replace(store.rows[ctx.tenant_id], tenant_id=uuid4())
    assert runtime.select(query, now=NOW).reason == "MODEL_CONFIGURATION_SCOPE_MISMATCH"


def test_secret_resolution_exception_and_invalid_credential_never_escape(setup):
    _, store, _, _, secrets, policy, _, query = setup
    save(setup)
    runtime = RuntimeConfiguration(store, secrets, policy)

    def broken_resolve(_):
        raise RuntimeError(SYNTHETIC_KEY)

    secrets.resolve = broken_resolve
    assert runtime.select(query, now=NOW).reason == "MODEL_SECRET_UNAVAILABLE"
    secrets.resolve = lambda binding: SecretMaterial(binding, SecretStr("bad credential"))
    assert runtime.select(query, now=NOW).reason == "MODEL_SECRET_INVALID"


def test_version_and_metadata_are_immutable(setup):
    from dataclasses import FrozenInstanceError

    version = save(setup)
    with pytest.raises(FrozenInstanceError):
        version.enabled = False
    with pytest.raises(ValidationError):
        version.metadata.model = "mutated"


def test_sensitive_port_exception_tracebacks_and_request_validation_are_redacted(setup):
    import traceback

    from pdos_next.model_configuration.service import parse_save_payload

    ctx, _, _, metadata, secrets, _, service, _ = setup
    secrets.failure = True
    for action in [
        lambda: service.plan(
            ctx, SaveConfiguration(expected_revision=0, metadata=metadata), now=NOW
        ),
        lambda: parse_save_payload({"api_key": SYNTHETIC_KEY}),
    ]:
        with pytest.raises(DomainError) as error:
            action()
        trace = "".join(traceback.format_exception(error.value))
        assert SYNTHETIC_KEY not in trace
        assert error.value.__suppress_context__ is True


def test_main_permit_guard_cannot_outlive_permit_expiry(setup):
    _, store, _, _, secrets, policy, _, query = setup
    save(setup)
    runtime = RuntimeConfiguration(store, secrets, policy)
    selected = runtime.select(query, now=NOW)
    times = iter([NOW, NOW + timedelta(minutes=2)])
    check = runtime.currentness(
        selected, query, now=lambda: next(times), require_permit_current=lambda _: None
    )
    assert_code("MODEL_PERMIT_BINDING_MISMATCH", lambda: check(permit_for(selected, query)))


def test_public_common_preview_restores_without_secret_ref_or_second_store(setup):
    ctx, store, _, metadata, secrets, _, service, _ = setup
    payload = SaveConfiguration(expected_revision=0, metadata=metadata, enabled=True)
    initial = service.plan(ctx, payload, now=NOW)
    reviewed = initial.preview()
    restored = service.restore_reviewed_plan(
        ctx, payload, reviewed, now=NOW + timedelta(seconds=20)
    )
    assert restored.digest == initial.digest
    assert restored.version == initial.version
    assert str(secrets.binding.reference) not in reviewed.model_dump_json()
    service.apply_plan(ctx, restored, now=NOW + timedelta(seconds=20))
    assert len(store.history) == 1


def test_public_preview_reconstruction_rejects_rotated_secret_and_payload_changes(setup):
    ctx, _, _, metadata, secrets, _, service, _ = setup
    payload = SaveConfiguration(expected_revision=0, metadata=metadata, enabled=True)
    reviewed = service.plan(ctx, payload, now=NOW).preview()
    changed = payload.model_copy(update={"enabled": False})
    assert_code(
        "MODEL_CONFIGURATION_PREVIEW_CHANGED",
        lambda: service.restore_reviewed_plan(ctx, changed, reviewed, now=NOW),
    )
    secrets.binding = replace(secrets.binding, version=uuid4())
    assert_code(
        "MODEL_CONFIGURATION_PREVIEW_CHANGED",
        lambda: service.restore_reviewed_plan(ctx, payload, reviewed, now=NOW),
    )
