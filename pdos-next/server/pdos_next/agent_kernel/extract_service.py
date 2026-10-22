"""evidence.extract orchestration: server-side binding, dispatch, coverage, replay.

The model never chooses the source set, the row contract, the skill or the
coverage; every settled result is revalidated against current fixed sources on
replay instead of re-running the model.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.errors import DomainError
from pdos_next.service import digest

from . import policy
from .extract_graph import ExtractTask, budget_for
from .extract_pages import located_page, project_page
from .extract_read_ledger import ExtractReadLedger
from .extract_schemas import ExtractInput, ParameterFocus, draft_registry
from .extract_sources import seal_for
from .models import AgentEvent


class ExtractionService:
    def __init__(self, store, commands, catalog, *, row_registry=None, concurrency=4):
        self.store, self.commands, self.catalog = store, commands, catalog
        self.rows = row_registry or draft_registry()
        self.concurrency = concurrency

    def _loaded_skills(self, session, scope, run):
        """This run's actually loaded skills, re-checked against the pinned event digests."""
        events = session.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run.id)
            .order_by(AgentEvent.sequence)
        ).all()
        skills, seen = [], set()
        for event in events:
            body = event.body
            if not isinstance(body, dict) or body.get("type") != "skill_loaded":
                continue
            key = body.get("key")
            if not isinstance(key, str) or key in seen:
                continue
            skill = self.catalog.load(
                key, scope, lambda s, item: policy.skill_enabled(session, s, item)
            )
            if skill.version != body.get("version"):
                raise DomainError("VERSION_CONFLICT", "已加载技能版本已变化。")
            if body.get("digest") is not None and body["digest"] != skill.digest:
                raise DomainError("VERSION_CONFLICT", "已加载技能内容已变化。")
            seen.add(key)
            skills.append(skill)
        return skills

    def _bind(self, session, ctx, scope, run, payload: ExtractInput):
        proposal_id = payload.proposal_id or scope.proposal_id
        if proposal_id is None:
            raise DomainError("FORBIDDEN_SCOPE", "抽取须绑定当前提案。", 403)
        reads = {UUID(ref["artifact_id"]): ref for ref in run.read_sources}
        if not reads:
            raise DomainError("FORBIDDEN_SCOPE", "本次运行未绑定原件。", 403)
        if payload.artifact_version_ids is None:
            target_ids = sorted(reads)
        else:
            target_ids = list(payload.artifact_version_ids)
            unbound = [identity for identity in target_ids if identity not in reads]
            if unbound:
                raise DomainError(
                    "FORBIDDEN_SCOPE",
                    "抽取范围超出本次运行绑定的原件。",
                    403,
                    detail={"unbound": [str(identity) for identity in unbound]},
                )
        skills = self._loaded_skills(session, scope, run)
        declaration = payload.row_schema
        matching = [
            skill
            for skill in skills
            if any(
                item.kind == declaration.kind and item.version == declaration.version
                for item in skill.row_schemas
            )
        ]
        if not matching:
            raise DomainError(
                "FORBIDDEN_SCOPE",
                "抽取行结构须由当前实际加载的技能声明。",
                403,
                detail={"reason_key": "row_schema_not_declared"},
            )
        try:
            row_model = self.rows.row_model(declaration)
        except ValueError:
            raise DomainError(
                "SOURCE_UNAVAILABLE", "服务器未安装该抽取行结构。"
            ) from None
        focus = None
        if isinstance(payload.focus, ParameterFocus):
            focus = {"parameter": payload.focus.parameter.model_dump(mode="json")}
        elif isinstance(payload.focus, str):
            focus = {"text": payload.focus}
        skill = matching[-1]  # The most recently loaded declaration wins.
        seals = {}
        for identity in target_ids:
            seal, _ = seal_for(
                session, ctx, scope.product_id, identity, reads[identity]["expected_revision"]
            )
            seals[identity] = seal
        task = ExtractTask(
            declaration=declaration,
            row_model=row_model,
            skill_key=skill.key,
            skill_version=skill.version,
            skill_digest=skill.digest,
            skill_content=skill.content,
            focus=focus,
        )
        return SimpleNamespace(proposal_id=proposal_id, task=task, seals=seals)

    def extract(self, scope, arguments, *, graph):
        payload = ExtractInput.model_validate(arguments)
        if scope.isolation != "main":
            raise DomainError("FORBIDDEN_SCOPE", "隔离子任务不能再次派发抽取。", 403)
        with self.store.transaction(scope) as (session, run):
            ctx = self.commands.context(scope)
            binding = self._bind(session, ctx, scope, run, payload)

        def work(seal):
            ledger = ExtractReadLedger([seal])
            if seal.parse_status != "parsed":
                return (
                    seal, (), [], ledger.coverage(seal.artifact_id),
                    {
                        "artifact_id": seal.artifact_id,
                        "code": "source_not_parsed",
                        "parse_status": seal.parse_status,
                        "parse_code": seal.parse_code,
                    },
                )
            try:
                budget_for(seal.total_lines)
                rows, rejected = graph(
                    scope.child("extract", artifact_ids={UUID(seal.artifact_id)}),
                    seal,
                    binding.task,
                    ledger,
                )
            except DomainError as error:
                return (
                    seal, (), [], ledger.coverage(seal.artifact_id),
                    {
                        "artifact_id": seal.artifact_id,
                        "code": error.code,
                        "detail": error.detail if isinstance(error.detail, dict) else None,
                    },
                )
            return seal, rows, rejected, ledger.coverage(seal.artifact_id), None

        ordered = [binding.seals[identity] for identity in sorted(binding.seals, key=str)]
        with ThreadPoolExecutor(max_workers=min(self.concurrency, len(ordered) or 1)) as pool:
            outcomes = list(pool.map(work, ordered))
        rows_out, rejected_out, coverage_out, failures = [], [], [], []
        for seal, rows, rejected, coverage, failure in outcomes:
            rows_out.extend(rows)
            rejected_out.extend({"artifact_id": seal.artifact_id, **item} for item in rejected)
            coverage_out.append(
                {**coverage, "locator_digest": digest([asdict(e) for e in seal.locator_map])}
            )
            if failure is not None:
                failures.append(failure)
        return {
            "row_schema": binding.task.declaration.model_dump(mode="json"),
            "proposal_id": str(binding.proposal_id),
            "skill": {
                "key": binding.task.skill_key,
                "version": binding.task.skill_version,
                "digest": binding.task.skill_digest,
            },
            "rows": rows_out,
            "rejected": rejected_out,
            "coverage": coverage_out,
            "failures": failures,
        }

    def restore(self, scope, arguments, previous):
        """Revalidate a settled extraction against current fixed sources; never re-dispatch.

        Admission (loaded skill, enablement) is not re-checked: the settled result is a
        historical receipt. Any drift in fixed sources, parse inventory, locator maps,
        coverage or quotations refuses the replay instead of re-running the model.
        """
        if not isinstance(previous, dict) or not isinstance(previous.get("coverage"), list):
            raise DomainError("SOURCE_UNAVAILABLE", "原抽取结果缺失。", 503)
        payload = ExtractInput.model_validate(arguments)
        proposal_id = payload.proposal_id or scope.proposal_id
        if previous.get("proposal_id") != str(proposal_id):
            raise DomainError("SOURCE_STALE", "原抽取结果属于不同的提案。")
        with self.store.transaction(scope) as (session, run):
            ctx = self.commands.context(scope)
            reads = {UUID(ref["artifact_id"]): ref for ref in run.read_sources}
            if payload.artifact_version_ids is None:
                target_ids = sorted(reads)
            else:
                target_ids = list(payload.artifact_version_ids)
            stored = {UUID(entry["artifact_id"]): entry for entry in previous["coverage"]}
            if sorted(stored) != sorted(target_ids):
                raise DomainError("SOURCE_STALE", "原抽取的原件集合已变化。")
            for identity in target_ids:
                entry = stored[identity]
                ref = reads.get(identity)
                if ref is None or ref["expected_revision"] != entry["revision"]:
                    raise DomainError("SOURCE_STALE", "原抽取的原件版本绑定已变化。")
                seal, _ = seal_for(session, ctx, scope.product_id, identity, entry["revision"])
                if (
                    seal.revision != entry["revision"]
                    or seal.content_hash != entry["content_hash"]
                    or seal.parse_status != entry["parse_status"]
                    or seal.parse_code != entry["parse_code"]
                    or seal.total_lines != entry["parsed_text"]["total_lines"]
                    or digest([asdict(e) for e in seal.locator_map]) != entry["locator_digest"]
                ):
                    raise DomainError("SOURCE_STALE", "固定原件或解析库存已变化。")
                ledger = ExtractReadLedger([seal])
                for start, end in entry["parsed_text"]["read_ranges"]:
                    cursor, remaining = start - 1, end - start + 1
                    while remaining:
                        size = min(remaining, 200)
                        page_args = {
                            "artifact_version_id": seal.artifact_id,
                            "locator": None,
                            "cursor": cursor,
                            "page_size": size,
                        }
                        wire = located_page(seal, page_args)
                        _, internal, _ = project_page(seal, page_args, wire)
                        try:
                            ledger.record_successful_page(
                                internal,
                                call_id=str(uuid4()),
                                cursor=cursor,
                                page_size=size,
                            )
                        except ValueError:
                            raise DomainError(
                                "SOURCE_STALE", "原抽取覆盖与当前原件不一致。"
                            ) from None
                        cursor += size
                        remaining -= size
                current = ledger.coverage(seal.artifact_id)
                if current != {k: v for k, v in entry.items() if k != "locator_digest"}:
                    raise DomainError("SOURCE_STALE", "原抽取覆盖说明已变化。")
                rows = [
                    row
                    for row in previous.get("rows", [])
                    if row["artifact_id"] == seal.artifact_id
                ]
                verified = ledger.verify_rows(
                    [
                        {
                            "artifact_id": row["artifact_id"],
                            "revision": row["revision"],
                            "locator": row["locator"],
                            "quote": row["quote"],
                            "fields": row["fields"],
                        }
                        for row in rows
                    ]
                )
                if verified.failures or len(verified.rows) != len(rows):
                    raise DomainError("SOURCE_STALE", "原抽取行的引文在当前原件中不再成立。")
        return previous
