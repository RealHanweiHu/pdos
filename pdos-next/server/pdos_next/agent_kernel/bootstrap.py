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
from pdos_next.models import Artifact, Category, Grant, Principal, Product, UploadedOriginal
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
    mcp_resolve_secret: object | None = None
    mcp_transport: object | None = None
    mcp_artifacts: object | None = None
    mcp_checkpointer_factory: object | None = None


class Bootstrap:
    def __init__(self, engine, *, ports=None):
        from pdos_next.model_configuration.host import runtime_ports

        self.engine, self.ports = engine, ports if ports is not None else runtime_ports(engine)
        self.store = KernelStore(engine)
        self.catalog, self.registry = SkillCatalog(), default_registry()
        self.commands = DomainCommands(
            engine,
            catalog=self.catalog,
            registry=self.registry,
            route=self.route,
            artifacts=self.ports.research_artifacts,
        )
        self.engine._pdos_category_candidate_owner = self
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
        proposal_facts, outbound_context = None, None
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
            if getattr(data, "project_id", None) is not None:
                from .project_scope import require_project

                actual_project = require_project(
                    session, ctx, data.project_id, data.product_id, lock=True
                )
                private = private or actual_project.visibility != "category"
        elif (
            data.product_id is not None
            or data.proposal_id is not None
            or getattr(data, "project_id", None) is not None
            or data.sources
        ):
            raise DomainError("FORBIDDEN_SCOPE", "个人入口不能绑定业务对象。", 403)
        if data.proposal_id is not None:
            from pdos_next.domain.preproject.access import proposal
            from pdos_next.domain.preproject.views import read

            from .proposal_context import binding, collect

            actual = proposal(session, ctx, data.proposal_id, lock=True)
            proposal_facts = collect(session, ctx, actual, read(session, ctx, actual.id))
            outbound_context = binding(ctx, actual, proposal_facts)
            private = private or proposal_facts.private_context
            identities = proposal_facts.customer_identities
            refs.extend(session.get(Artifact, UUID(ref["artifact_id"]))
                        for ref in proposal_facts.read_sources)
        for ref in data.sources:
            refs.append(
                source_for(session, ctx, data.product_id, ref.artifact_id, ref.expected_revision)
            )
        reads = {}
        for artifact in refs:
            from pdos_next.domain.preproject.claim_access import source_privacy

            source_for(session, ctx, artifact.product_id, artifact.id, artifact.revision)
            private = private or source_privacy(
                session, ctx, SimpleNamespace(source_kind="artifact", artifact_id=artifact.id)
            ) != "shared"
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
        categories = {"customer" if identities else "internal"}
        if proposal_facts:
            categories.update(proposal_facts.data_categories)
        if any(artifact.original_id is not None for artifact in refs):
            # Registered bytes have original provenance regardless of a free-text label.
            categories.add("customer_original")
        return SimpleNamespace(
            private_context=private,
            data_categories=tuple(sorted(categories)),
            customer_identities=identities,
            read_sources=reads,
            outbound_context=outbound_context,
            validation_budget_id=budgets[0].id if budgets else None,
            token_limit=(
                min(2_147_483_647, budgets[0].input_token_limit + budgets[0].output_token_limit)
                if budgets else 100000
            ),
        )

    def project_context(self, scope, goal, fields=None):
        with tenant_session(
            self.engine, scope.tenant_id, actor_id=scope.writer_id,
            requester_id=scope.requester_id, category_id=scope.category_id, read_snapshot=True,
        ) as session:
            self.store.authority(session, scope)
            run = session.get(AgentRun, scope.run_id)
            from .execution import check_run_binding

            check_run_binding(run, scope, for_write=False)
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
                from pdos_next.domain.preproject.access import proposal
                from pdos_next.domain.preproject.views import read

                from .proposal_context import bound_head, validate

                bound_head(run, proposal(session, self.commands.context(scope), scope.proposal_id))
                if fields is None or "proposal" in fields:
                    value["proposal"] = read(
                        session, self.commands.context(scope), scope.proposal_id,
                    )
                    validate(session, scope, run, extra_value=value["proposal"])
                else:
                    validate(session, scope, run)
            if getattr(scope, "project_id", None) is not None and (
                fields is None or "project" in fields
            ):
                from .project_scope import require_project

                actual_project = require_project(
                    session, self.commands.context(scope), scope.project_id, scope.product_id
                )
                value["project"] = {
                    "id": str(actual_project.id),
                    "name": actual_project.name,
                    "revision": actual_project.revision,
                    "visibility": actual_project.visibility,
                }
            if run.continued_from_id is not None:
                from .conversation import memory
                value["conversation"] = memory(
                    session, run, readers=getattr(self, "_history_readers", {}),
                )
        if "conversation" in value:
            from pdos_next.service import digest
            fingerprint = digest(value["conversation"])
            with self.store.transaction(scope, lock=True) as (session, current):
                previous = current.versions.get("conversation_memory_digest")
                if previous is not None and previous != fingerprint:
                    raise DomainError("SOURCE_STALE", "原工作记忆来源已变化，请重新核对后继续。")
                if previous is None:
                    current.versions = {
                        **current.versions, "conversation_memory_digest": fingerprint,
                    }
        return value

    def check_conversation(self, scope):
        from pdos_next.service import digest

        from .conversation import memory
        with self.store.transaction(scope) as (session, run):
            if run.continued_from_id is None:
                return
            current = memory(session, run, readers=getattr(self, "_history_readers", {}))
            if digest(current) != run.versions.get("conversation_memory_digest"):
                raise DomainError("SOURCE_STALE", "原工作来源或权限已变化，不能沿用旧记忆出站。")
            for page in run.versions.get("conversation_history_pages", {}).values():
                current = memory(
                    session, run, readers=getattr(self, "_history_readers", {}),
                    before=UUID(page["before"]) if page["before"] else None,
                    page_size=page["page_size"],
                    include_research_rows=page["include_research_rows"],
                )
                if digest(current) != page["digest"]:
                    raise DomainError("SOURCE_STALE", "已读取的历史工作来源或权限已变化。")

    def conversation_history(self, scope, arguments):
        from pdos_next.service import digest

        from .conversation import HistoryInput, memory
        payload = HistoryInput.model_validate(arguments)
        with self.store.transaction(scope, lock=True) as (session, run):
            value = memory(session, run, readers=getattr(self, "_history_readers", {}),
                           before=payload.before, page_size=payload.page_size,
                           include_research_rows=payload.include_research_rows)
            key = f"{payload.before or ''}:{payload.page_size}:{payload.include_research_rows}"
            pages = run.versions.get("conversation_history_pages", {})
            run.versions = {**run.versions, "conversation_history_pages": {**pages, key: {
                "before": str(payload.before) if payload.before else None,
                "page_size": payload.page_size, "digest": digest(value),
                "include_research_rows": payload.include_research_rows,
            }}}
            return value

    def prepare_candidate(self, scope, spec, arguments, intent_key):
        if spec.tier not in {"T0", "T1", "T2-prepare-only"}:
            raise DomainError("FORBIDDEN_SCOPE", "该工具不是领域候选。", 403)
        with self.commands.transaction(scope) as session:
            self.store.authority(session, scope)
            if spec.name == "category.create":
                from .category_candidate import prepare

                return prepare(session, scope, spec, arguments, intent_key, self)
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
            if spec.name in CONTENT_OPERATIONS:
                from .domain_candidates import record

                event_id = record(session, scope, command, intent_key)
            else:
                event_id = None
            return {
                "command": command.model_dump(mode="json"),
                "requires_human": True,
                "write_tier": "T2" if spec.tier == "T2-prepare-only" else "T1",
                "state": "candidate",
                **({"event_id": str(event_id)} if event_id else {}),
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
        from .research_result import attach

        return attach(result, tool_results)

    def default_preload(self, scope):
        if scope.isolation != "main":
            return ()
        with self.store.transaction(scope) as (session, run):
            self.store.authority(session, scope)
            if scope.category_id is None:
                return ("category_framing",)
            if scope.proposal_id is None:
                if scope.project_id is not None:
                    # A project run is not proposal drafting. Which project method applies is
                    # not derivable from the bound scope, so the catalog stays as the only
                    # entry and skill.load decides, under the server's own scope check.
                    return ()
                return ("proposal_drafting",)
            from pdos_next.domain.preproject.models import Proposal, ProposalSubmission

            proposal = session.get(Proposal, scope.proposal_id)
            if not proposal:
                raise DomainError("FORBIDDEN_SCOPE", "立项提案不可读。")
            submission = session.get(ProposalSubmission, proposal.current_submission_id) \
                if proposal.current_submission_id else None
            if (proposal.status == "in_review" and submission
                    and submission.reviewer_id == scope.requester_id):
                return ("gap_check", "option_comparison")
            skills = ["proposal_drafting", "gap_check"]
            original_versions = {
                (UUID(ref["id"]), ref["version"]) for ref in proposal.source_refs
                if ref.get("type") == "original"
            }
            customer_original = False
            for ref in run.read_sources:
                identity, version = UUID(ref["artifact_id"]), ref["expected_revision"]
                if (identity, version) not in original_versions:
                    continue
                try:
                    artifact = source_for(
                        session, self.commands.context(scope), scope.product_id, identity, version
                    )
                except DomainError:
                    continue
                original = (
                    session.get(UploadedOriginal, artifact.original_id)
                    if artifact.original_id else None
                )
                if (
                    artifact and artifact.tenant_id == scope.tenant_id
                    and artifact.category_id == scope.category_id
                    and artifact.status == "active"
                    and artifact.revision == version
                    and original and original.tenant_id == scope.tenant_id
                    and original.category_id == scope.category_id
                    and original.product_id == artifact.product_id
                    and original.status == "parsed" and original.scan_status == "clean"
                ):
                    customer_original = True
                    break
            if customer_original:
                skills.append("rfq_extraction")
            return tuple(skills)

    def adapters(self):
        from .domain_reads import DomainReads
        from .m3_calculators import ENGINES, handlers
        from .m3_definition_diff import DefinitionDiffReads
        from .m3_object_reads import M3ObjectReads
        from .m3_spec_compare import SpecCompareReads
        from .platform_reads import PlatformReads

        domain_reads = DomainReads(self.store, self.commands)
        definition_diff = DefinitionDiffReads(self.store, self.commands, domain_reads)
        spec_compare = SpecCompareReads(self.store, self.commands, self.catalog)
        platform_reads = PlatformReads(self.store, self.commands)
        local_reads = {
            **domain_reads.handlers(), **definition_diff.handlers(),
            **M3ObjectReads(self.store, self.commands).handlers(), **handlers,
            **spec_compare.handlers(), **platform_reads.handlers(),
        }

        adapters = KernelAdapters(
            route_for=self.route_for,
            project_context=self.project_context,
            verify_result=self.verify_result,
            prepare_candidate=self.prepare_candidate,
            execute_command=self.commands.execute,
            recover_command=self.commands.recover,
            read_tools={
                **domain_reads.handlers(),
                **definition_diff.handlers(),
                **M3ObjectReads(self.store, self.commands).handlers(),
                **handlers,
                **spec_compare.handlers(),
                **platform_reads.handlers(),
                **self.ports.read_tools,
            },
            provider_client=self.ports.provider_client,
            provider_for=self.provider_for,
            preload=self.ports.preload or self.default_preload,
            rate_card_for=self.ports.rate_card_for,
            cost_required=True,
            context_guard=self.check_conversation,
            skill_catalog=self.catalog,
            tool_registry=self.registry,
            compute_engines=ENGINES,
            read_restores={
                **spec_compare.restores(), **definition_diff.restores(), **platform_reads.restores()
            },
        )
        self._history_readers = {
            name: (lambda scope, args, previous, consumer, callback=callback: callback(scope, args))
            for name, callback in local_reads.items()
            if name not in self.ports.read_tools  # Custom host callbacks are not proven local.
        }
        self._history_readers.update({
            name: (lambda scope, args, previous, consumer, engine=engine: engine.calculate(args))
            for name, engine in ENGINES.items()
        })
        adapters.read_tools["conversation.history"] = self.conversation_history
        from .extract_adapter import ExtractReadAdapter
        from .extract_graph import ExtractGraph
        from .extract_service import ExtractionService
        from .host import BoundHost
        from .mcp_adapter import McpReadAdapter
        from .mcp_graph import McpGraph

        mcp_adapter = McpReadAdapter(
            self.store, self.catalog,
            resolve_secret=self.ports.mcp_resolve_secret, transport=self.ports.mcp_transport,
            artifacts=self.ports.mcp_artifacts,
            graph=McpGraph(BoundHost(self.store, adapters),
                           checkpointer_factory=self.ports.mcp_checkpointer_factory),
        )
        adapters.read_tools.update(mcp_adapter.handlers())
        adapters.read_resumes.update(mcp_adapter.resumes())
        adapters.read_restores["mcp.read"] = mcp_adapter.restore

        extract_adapter = ExtractReadAdapter(
            ExtractionService(self.store, self.commands, self.catalog),
            ExtractGraph(
                BoundHost(self.store, adapters),
                artifact_read=adapters.read_tools["evidence.artifact.read"],
                checkpointer_factory=self.ports.research_checkpointer_factory,
            ),
        )
        adapters.read_tools.update(extract_adapter.handlers())
        adapters.read_restores.update(extract_adapter.restores())
        if self.ports.research_service is not None:
            from pdos_next.research.tools import ResearchToolHost

            from .category_research_refs import CategoryResearchRefs
            from .host import BoundHost
            from .registered_snapshot_reads import RegisteredSnapshotReads
            from .research_adapter import ResearchReadAdapter
            from .research_graph import ResearchGraph
            from .research_instruction import ResearchInstruction

            artifacts = self.ports.research_artifacts
            if artifacts is None:
                raise DomainError("SOURCE_UNAVAILABLE", "研究作业存储尚未绑定。")
            researcher = ResearchGraph(
                BoundHost(self.store, adapters), artifacts=artifacts,
                checkpointer_factory=self.ports.research_checkpointer_factory,
                registered_reads=RegisteredSnapshotReads(self.store),
                instruction_for=ResearchInstruction(self.store, self.catalog),
            )
            tool_host = ResearchToolHost(
                self.ports.research_service, researcher=researcher,
                parameter_versions=self.research_parameters,
            )
            research_adapter = ResearchReadAdapter(
                tool_host, artifacts, user_messages=self.research_messages,
                read_refs=CategoryResearchRefs(self.store, artifacts),
            )
            adapters.read_tools.update(research_adapter.handlers())
            self._history_readers.update({
                name: (lambda scope, args, previous, consumer, restore=restore:
                       restore(scope, args, previous))
                for name, restore in research_adapter.restores().items()
            })
            self._history_readers["research.fanout"] = research_adapter.admit_history
            adapters.read_restores.update(research_adapter.restores())
            if self.ports.research_checkpointer_factory is not None:
                adapters.read_resumes["research.fanout"] = research_adapter.resume
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
