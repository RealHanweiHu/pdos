"""Actual HTTP/worker composition. Configuration and secrets remain trusted host ports."""

from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, text

from pdos_next.clock import now
from pdos_next.contracts import SourceRead
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.model_configuration.persistence import SessionConfigurationStore
from pdos_next.model_configuration.ports import SecretMaterial
from pdos_next.model_configuration.service import current_secret, secret_digest
from pdos_next.models import Artifact, Category, Grant, Principal, Product
from pdos_next.service import require_access, source_for

from .api import ApiPorts
from .bindings import DomainBinding, WriteSource, execution_key
from .domain_adapter import DomainCommands
from .execution import scope_for_run
from .host import KernelAdapters
from .models import AgentRun, AgentToolCall, ValidationBudget
from .persistence import KernelStore
from .skills import SkillCatalog
from .tools import default_registry


@dataclass(frozen=True)
class RuntimePorts:
    secrets: object | None = None
    rate_card_for: object | None = None
    provider_for: object | None = None
    provider_client: object | None = None
    read_tools: dict = field(default_factory=dict)
    preload: object | None = None
    research_service: object | None = None
    research_artifacts: object | None = None
    research_checkpointer_factory: object | None = None


class Bootstrap:
    def __init__(self, engine, *, ports=None):
        self.engine, self.ports = engine, ports or RuntimePorts()
        self.store = KernelStore(engine)
        self.catalog, self.registry = SkillCatalog(), default_registry()
        self.commands = DomainCommands(
            engine,
            catalog=self.catalog,
            registry=self.registry,
            route=self.route,
            artifacts=self.ports.research_artifacts,
        )
        if self.ports.research_artifacts is not None:
            self.engine._pdos_research_artifacts = self.ports.research_artifacts

    def route(self, session, scope):
        # Lock the actual head without giving an Agent identity configuration write access.
        revision = session.scalar(
            text("SELECT kernel_model_configuration_lock(:tenant)"), {"tenant": scope.tenant_id}
        )
        if revision is None:
            raise DomainError("SOURCE_UNAVAILABLE", "模型配置尚未登记。")
        version = SessionConfigurationStore(session).current(scope.tenant_id)
        if version is None or not version.enabled:
            raise DomainError("SOURCE_UNAVAILABLE", "当前租户模型尚未启用。")
        secret = current_secret(self.ports.secrets, scope.tenant_id, version.metadata.protocol)
        if (
            secret is None
            or not secret.available
            or secret_digest(secret) != secret_digest(version.secret)
        ):
            raise DomainError("SOURCE_UNAVAILABLE", "模型凭据绑定尚未配置或已经变更。")
        try:
            material = self.ports.secrets.resolve(secret)
        except Exception:
            raise DomainError("SOURCE_UNAVAILABLE", "模型凭据暂不可用。") from None
        if not isinstance(material, SecretMaterial) or material.binding != secret:
            raise DomainError("SOURCE_UNAVAILABLE", "模型凭据与当前登记不一致。")
        latest = current_secret(self.ports.secrets, scope.tenant_id, version.metadata.protocol)
        if secret_digest(latest) != secret_digest(secret):
            raise DomainError("VERSION_CONFLICT", "模型凭据已轮换。")
        return replace(
            version.metadata.route(material.credential, version.metadata.model_version),
            configuration_digest=version.binding_digest,
        )

    def route_for(self, scope):
        with self.commands.transaction(scope) as session:
            self.store.authority(session, scope)
            return self.route(session, scope)

    def provider_for(self, scope, route):
        if self.ports.provider_for is None:
            raise DomainError("SOURCE_UNAVAILABLE", "模型服务商的签约身份尚未绑定。")
        return self.ports.provider_for(scope, route)

    @staticmethod
    def writer_for(session, ctx):
        rows = list(
            session.scalars(
                select(Principal)
                .where(
                    Principal.tenant_id == ctx.tenant_id,
                    Principal.kind == "agent",
                    Principal.active.is_(True),
                )
                .execution_options(populate_existing=True)
                .with_for_update(read=True)
            )
        )
        if len(rows) != 1:
            raise DomainError("SOURCE_UNAVAILABLE", "租户须登记唯一的小 Pai 执行身份。")
        return rows[0].id

    def binding_for(self, session, ctx, data):
        writer = self.writer_for(session, ctx)
        private, identities, refs = False, (), []
        if ctx.category_id is not None:
            require_access(session, ctx, data.product_id, lock=True)
            writer_grant = session.scalar(
                select(Grant)
                .where(Grant.category_id == ctx.category_id, Grant.principal_id == writer)
                .execution_options(populate_existing=True)
                .with_for_update(read=True)
            )
            if writer_grant is None or (
                writer_grant.expires_at is not None and writer_grant.expires_at <= now()
            ):
                raise DomainError("FORBIDDEN_SCOPE", "小Pai当前没有该品类的读取授权。", 403)
            category = session.scalar(
                select(Category)
                .where(Category.id == ctx.category_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
            if category is None:
                raise DomainError("FORBIDDEN_SCOPE", "运行品类不在当前范围。", 403)
            if data.product_id is not None:
                product = session.scalar(
                    select(Product)
                    .where(Product.id == data.product_id)
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
                private = product.visibility != "category"
        elif data.product_id is not None or data.proposal_id is not None or data.sources:
            raise DomainError("FORBIDDEN_SCOPE", "个人入口不能绑定业务对象。", 403)
        if data.proposal_id is not None:
            from pdos_next.domain.preproject.access import proposal

            actual = proposal(session, ctx, data.proposal_id, lock=True)
            private = private or actual.effective_visibility != "category"
            identities = tuple(actual.customer_identities)
            # Registered proposal source facts belong to its owner, never to client policy input.
            for ref in actual.source_refs:
                if ref.get("type") == "original":
                    original_id = UUID(ref["id"])
                    refs.extend(
                        session.scalars(
                            select(Artifact).where(
                                Artifact.original_id == original_id,
                                Artifact.category_id == ctx.category_id,
                                Artifact.status == "active",
                            )
                        )
                    )
        for ref in data.sources:
            refs.append(
                source_for(session, ctx, data.product_id, ref.artifact_id, ref.expected_revision)
            )
        reads = {}
        for artifact in refs:
            source_for(session, ctx, data.product_id, artifact.id, artifact.revision)
            private = private or artifact.visibility != "category"
            reads[artifact.id] = {
                **SourceRead(
                    artifact_id=artifact.id, expected_revision=artifact.revision
                ).model_dump(mode="json"),
                "product_id": str(artifact.product_id) if artifact.product_id is not None else None,
            }
        reads = [reads[k] for k in sorted(reads, key=str)]
        budgets = list(
            session.scalars(
                select(ValidationBudget)
                .where(
                    ValidationBudget.requester_id == ctx.requester_id,
                    ValidationBudget.active.is_(True),
                )
                .order_by(ValidationBudget.created_at.desc(), ValidationBudget.id)
                .limit(1)
            )
        )
        return SimpleNamespace(
            private_context=private,
            data_categories=("customer" if identities else "internal",),
            customer_identities=identities,
            read_sources=reads,
            validation_budget_id=budgets[0].id if budgets else None,
        )

    def project_context(self, scope, goal):
        with self.commands.transaction(scope) as session:
            self.store.authority(session, scope)
            run = session.get(AgentRun, scope.run_id)
            value = {"goal": goal, "sources": run.read_sources}
            if scope.category_id:
                category = session.get(Category, scope.category_id)
                value["category"] = {
                    "id": str(category.id),
                    "name": category.name,
                    "purpose": category.purpose,
                }
            if scope.product_id:
                product = require_access(session, self.commands.context(scope), scope.product_id)
                value["product"] = {
                    "id": str(product.id),
                    "name": product.name,
                    "revision": product.revision,
                    "visibility": product.visibility,
                }
            if scope.proposal_id:
                from pdos_next.domain.preproject.views import read

                value["proposal"] = read(session, self.commands.context(scope), scope.proposal_id)
            return value

    def prepare_candidate(self, scope, spec, arguments, intent_key):
        if spec.tier not in {"T0", "T1", "T2-prepare-only"}:
            raise DomainError("FORBIDDEN_SCOPE", "该工具不是领域候选。", 403)
        with self.commands.transaction(scope) as session:
            self.store.authority(session, scope)
            if spec.name == "evidence.claim.record":
                from .claim_candidate import prepare

                return prepare(session, scope, spec, arguments, intent_key, self)
            if spec.name == "research.snapshot.register":
                from .snapshot_command import prepare

                session.info["domain_command_owner"] = self.commands
                return prepare(session, scope, spec, arguments, intent_key, self)
            from pdos_next.domain.preproject.provenance import (
                CONTENT_OPERATIONS,
                prepare_from_intent,
            )

            if spec.name in CONTENT_OPERATIONS:
                arguments = prepare_from_intent(
                    session,
                    scope,
                    spec.name,
                    arguments,
                    intent_key,
                    catalog=self.catalog,
                    registry=self.registry,
                    route=self.route,
                )
            command = self.commands.command(session, scope, spec.name, arguments, intent_key)
            if spec.name in CONTENT_OPERATIONS and "expected_revision" in arguments:
                # Question confirmation uses the proposal revision supplied in
                # the actual model response, rather than the category revision.
                command.expected_revision = arguments["expected_revision"]
            return {
                "command": command.model_dump(mode="json"),
                "requires_human": True,
                "write_tier": "T2" if spec.tier == "T2-prepare-only" else "T1",
                "state": "candidate",
            }

    def recover_call(self, ctx, run_id, call_id):
        with tenant_session(
            self.engine,
            ctx.tenant_id,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
        ) as session:
            run, call = session.get(AgentRun, run_id), session.get(AgentToolCall, call_id)
            if (
                not run
                or run.requester_id != ctx.requester_id
                or run.category_id != ctx.category_id
                or not call
                or call.run_id != run.id
                or call.state != "completed"
            ):
                raise DomainError("FORBIDDEN_SCOPE", "调用不在当前运行的可读范围。", 403)
            try:
                binding = DomainBinding.model_validate(call.execution_binding)
                model = session.get(AgentToolCall, binding.model_call_id)
                scope = scope_for_run(run)
                original = model.result["calls"][binding.response_index]
            except (ValidationError, AttributeError, IndexError, KeyError, TypeError):
                raise DomainError("SOURCE_UNAVAILABLE", "原调用的可信模型账本不可用。") from None
            source = WriteSource(
                skill=binding.skill,
                model_call_id=binding.model_call_id,
                response_index=binding.response_index,
            )
        result = self.commands.recover(
            scope,
            self.registry.get(call.tool),
            original["arguments"],
            execution_key(run_id, source.model_call_id, source.response_index),
            source=source,
        )
        if result is None:
            raise DomainError("SOURCE_UNAVAILABLE", "原调用尚无已提交的领域回执。")
        return result

    def verify_result(self, scope, result, tool_results):
        self.store.current(scope)
        for tool in tool_results:
            value = tool.get("value", {})
            if tool.get("tier") == "T0" and isinstance(value, dict) and "id" in value:
                with self.commands.transaction(scope) as session:
                    from pdos_next.models import Receipt

                    row = session.get(Receipt, UUID(value["id"]))
                    if row is None:
                        raise DomainError("FORBIDDEN_SCOPE", "结果没有当前可读的领域回执。", 403)
                    self.commands.read_receipt(session, scope, row)
        return result

    def adapters(self):
        from .domain_reads import DomainReads
        from .m3_calculators import ENGINES, handlers
        from .m3_object_reads import M3ObjectReads

        adapters = KernelAdapters(
            route_for=self.route_for,
            project_context=self.project_context,
            verify_result=self.verify_result,
            prepare_candidate=self.prepare_candidate,
            execute_command=self.commands.execute,
            recover_command=self.commands.recover,
            read_tools={
                **DomainReads(self.store, self.commands).handlers(),
                **M3ObjectReads(self.store, self.commands).handlers(),
                **handlers,
                **self.ports.read_tools,
            },
            provider_client=self.ports.provider_client,
            provider_for=self.provider_for,
            preload=self.ports.preload,
            rate_card_for=self.ports.rate_card_for,
            cost_required=True,
            skill_catalog=self.catalog,
            tool_registry=self.registry,
            compute_engines=ENGINES,
        )
        if self.ports.research_service is not None:
            from pdos_next.research.tools import ResearchToolHost

            from .host import BoundHost
            from .registered_snapshot_reads import RegisteredSnapshotReads
            from .research_adapter import ResearchReadAdapter
            from .research_graph import ResearchGraph

            artifacts = self.ports.research_artifacts
            if artifacts is None:
                raise DomainError("SOURCE_UNAVAILABLE", "研究作业存储尚未绑定。")
            researcher = ResearchGraph(
                BoundHost(self.store, adapters), artifacts=artifacts,
                checkpointer_factory=self.ports.research_checkpointer_factory,
                registered_reads=RegisteredSnapshotReads(self.store),
            )
            tool_host = ResearchToolHost(
                self.ports.research_service, researcher=researcher,
                parameter_versions=self.research_parameters,
            )
            research_adapter = ResearchReadAdapter(
                tool_host, artifacts, user_messages=self.research_messages,
            )
            adapters.read_tools.update(research_adapter.handlers())
            adapters.read_restores.update(research_adapter.restores())
        return adapters

    def research_messages(self, scope):
        from .models import AgentInput

        with self.store.transaction(scope) as (session, run):
            answers = session.scalars(select(AgentInput).where(AgentInput.run_id == run.id)).all()
            # Only persisted human input supplies URL grants; model text does not.
            import json

            return [run.goal, *[json.dumps(row.answers, ensure_ascii=False) for row in answers]]

    def research_parameters(self, scope):
        from pdos_next.domain.preproject.category_models import ParameterCurrent
        from pdos_next.research.types import ParameterVersion

        with self.store.transaction(scope) as (session, _):
            return tuple(ParameterVersion(row.parameter_id, row.current_version) for row in
                         session.scalars(select(ParameterCurrent).where(
                             ParameterCurrent.category_id == scope.category_id,
                         ))) if scope.category_id is not None else ()

    def api_ports(self, temporal):
        return ApiPorts(
            writer_for=self.writer_for,
            binding_for=self.binding_for,
            start_workflow=temporal.start,
            signal_workflow=temporal.signal,
            cancel_workflow=temporal.cancel,
            recover_call=self.recover_call,
        )
