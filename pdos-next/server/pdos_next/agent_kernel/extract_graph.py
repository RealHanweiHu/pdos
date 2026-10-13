"""Isolated extraction subtask: only evidence.artifact.read, host-verified rows back.

The child run never sees write or research tools, never receives raw text it did
not read through the registered read tool, and never reports its own coverage;
the host ledger is the only coverage authority.
"""

import json
from contextlib import nullcontext
from dataclasses import dataclass
from uuid import uuid4

from pydantic import ValidationError

from pdos_next.errors import DomainError

from .extract_pages import project_page
from .extract_read_ledger import ExtractReadLedger
from .extract_schemas import ArtifactReadInput, CitationDraft, RowSchemaDeclaration
from .graph import AgentKernel, Budget
from .read_execution import ReadSource
from .tools import default_registry

MAX_PAGE_LINES = 200  # evidence.artifact.read v2 page contract
MAX_PAGES_PER_ARTIFACT = 120  # one dispatch covers at most 24,000 derived lines


def replay_pages(ledger, seal, tool_results):
    """Re-record checkpointed settled reads after a process restart.

    Each replayed page is re-derived from and byte-compared against the current
    seal; a drifted source refuses instead of inheriting stale coverage.
    """
    for entry in tool_results:
        if not isinstance(entry, dict) or entry.get("tool") != "evidence.artifact.read":
            continue
        value = entry.get("value")
        if not isinstance(value, dict) or "execution_ref" not in value:
            continue
        wire = {key: item for key, item in value.items() if key != "execution_ref"}
        if set(wire) != {
            "artifact_version_id",
            "revision",
            "content_hash",
            "parse_status",
            "parse_code",
            "blocks",
            "next_cursor",
        }:
            continue
        if wire["artifact_version_id"] != seal.artifact_id or not wire["blocks"]:
            continue
        call_id = value["execution_ref"].get("call_id")
        if call_id is not None and ledger.has_page(call_id):
            continue  # This process's trusted read path already recorded the page.
        cursor = wire["blocks"][0]["derived_line_start"] - 1
        replay_args = {
            "artifact_version_id": seal.artifact_id,
            "locator": None,
            "cursor": cursor,
            "page_size": len(wire["blocks"]),
        }
        try:
            _, internal, _ = project_page(seal, replay_args, wire)
            ledger.record_successful_page(
                internal, call_id=call_id, cursor=cursor, page_size=len(wire["blocks"])
            )
        except (ValueError, TypeError, KeyError) as error:
            raise DomainError(
                "SOURCE_STALE", "原抽取检查点的读取页与当前原件不一致。"
            ) from error


@dataclass(frozen=True)
class ExtractTask:
    """Server-bound extraction facts; none of this comes from the model."""

    declaration: RowSchemaDeclaration
    row_model: type[CitationDraft]
    skill_key: str
    skill_version: str
    skill_digest: str
    skill_content: str
    focus: dict | None


def budget_for(total_lines):
    pages = max(1, -(-total_lines // MAX_PAGE_LINES))
    if pages > MAX_PAGES_PER_ARTIFACT:
        raise DomainError(
            "VALIDATION_FAILED",
            "原件超出单次抽取上限。",
            422,
            detail={"reason_key": "artifact_too_large", "total_lines": total_lines},
        )
    return Budget(model_turns=min(4 + pages, 24), tool_calls=min(pages + 8, 128))


class ExtractGraph:
    """Run one artifact's isolated extraction inside the registered graph."""

    def __init__(self, host, *, artifact_read, checkpointer_factory=None):
        self.host, self.artifact_read = host, artifact_read
        self.checkpointer_factory = checkpointer_factory

    def __call__(self, scope, seal, task: ExtractTask, ledger: ExtractReadLedger):
        host = self.host
        artifact_read = self.artifact_read
        budget = budget_for(seal.total_lines)

        class ReadOnlyExtractHost:
            def current(self, bound):
                host.current(bound)

            def enabled(self, *_):
                return False

            def qualified(self, *_):
                return False

            def context(self, bound, *_):
                self.current(bound)
                return {
                    "extraction_task": {
                        "artifact_version_id": seal.artifact_id,
                        "revision": seal.revision,
                        "content_hash": seal.content_hash,
                        "parse_status": seal.parse_status,
                        "total_lines": seal.total_lines,
                        "page_size_limit": MAX_PAGE_LINES,
                        "row_schema": task.declaration.model_dump(mode="json"),
                        **({"focus": task.focus} if task.focus else {}),
                    },
                    "output_contract": {
                        "rows": "array of rows matching the declared row schema",
                    },
                    "instruction": (
                        "Read the assigned original only through evidence.artifact.read, "
                        "page by page. Return result.rows matching the declared row "
                        "contract; every row quotes an exact substring at a location you "
                        "actually read. Coverage and unreadable ranges are reported by "
                        "the host, never by your rows."
                    ),
                    "extraction_skill": task.skill_content,
                }

            def model(self, bound, **kwargs):
                self.current(bound)
                try:
                    initial = kwargs["messages"][0]
                    actual = json.loads(initial["content"])["context"]["extraction_skill"]
                    if initial["role"] != "user" or actual != task.skill_content:
                        raise ValueError
                except (KeyError, IndexError, TypeError, ValueError):
                    raise DomainError(
                        "VERSION_CONFLICT", "原抽取检查点未包含固定的子任务说明。"
                    ) from None
                if hasattr(host, "gateway"):
                    return host.gateway.turn(
                        bound, emit=lambda event: self.emit(bound, event), **kwargs
                    )
                return host.model(bound, **kwargs)

            def read(self, bound, spec, arguments, intent_key, *, source=None):
                self.current(bound)
                if spec.name != "evidence.artifact.read":
                    raise DomainError(
                        "FORBIDDEN_SCOPE", "抽取子任务只拥有登记的原件读取。"
                    )
                data = ArtifactReadInput.model_validate(arguments)
                read_callback = getattr(host, "read_callback", None)
                if callable(read_callback):
                    if not isinstance(source, ReadSource):
                        raise DomainError(
                            "FORBIDDEN_SCOPE", "抽取读取缺少实际模型账本来源。"
                        )
                    result = read_callback(
                        bound,
                        spec,
                        arguments,
                        intent_key,
                        source=source,
                        callback=lambda *_: artifact_read(bound, arguments),
                    )
                    wire = {
                        key: value for key, value in result.items() if key != "execution_ref"
                    }
                    call_id = result["execution_ref"]["call_id"]
                else:
                    # Pure graph harnesses have no persistent call ledger; the local
                    # reference keeps one code path and never becomes a trusted receipt.
                    wire = artifact_read(bound, arguments)
                    call_id = str(uuid4())
                    result = {
                        **wire,
                        "execution_ref": {"call_id": call_id, "read_kind": "harness/local"},
                    }
                try:
                    _, internal, _ = project_page(seal, data.model_dump(mode="json"), wire)
                    ledger.record_successful_page(
                        internal,
                        call_id=call_id,
                        cursor=data.cursor,
                        page_size=data.page_size,
                    )
                except ValueError as error:
                    raise DomainError(
                        "INTEGRITY_MISMATCH", "完成页与固定原件不一致。"
                    ) from error
                return result

            def prepare(self, *_):
                raise DomainError("FORBIDDEN_SCOPE", "抽取子任务无写权。")

            def write(self, *_):
                raise DomainError("FORBIDDEN_SCOPE", "抽取子任务无写权。")

            def receipt(self, *_):
                raise DomainError("FORBIDDEN_SCOPE", "抽取子任务无写权。")

            def verify(self, bound, output, results):
                self.current(bound)
                replay_pages(ledger, seal, results)
                rows, rejected = [], []
                for index, raw in enumerate(output["result"].get("rows", [])):
                    try:
                        draft = task.row_model.model_validate(raw)
                    except ValidationError:
                        rejected.append({"index": index, "code": "invalid_extraction_row"})
                        continue
                    verified = ledger.verify_rows(
                        [
                            {
                                "artifact_id": str(draft.artifact_version_id),
                                "revision": seal.revision,
                                "locator": draft.locator,
                                "quote": draft.quote,
                                "fields": draft.model_dump(
                                    mode="json",
                                    exclude={"artifact_version_id", "locator", "quote"},
                                ),
                            }
                        ]
                    )
                    if verified.failures:
                        rejected.append(
                            {"index": index, "code": verified.failures[0].code}
                        )
                    else:
                        rows.append(verified.rows[0].as_dict())
                return {**output, "result": {"rows": rows, "rejected": rejected}}

            def emit(self, bound, event):
                # Raw child source text never re-enters the main model or its payload.
                host.emit(
                    bound,
                    {
                        "type": "extract_child",
                        "event_type": event.get("type"),
                        "artifact_id": seal.artifact_id,
                        **{
                            key: event[key]
                            for key in ("tool", "status", "code")
                            if key in event
                        },
                    },
                )

            def finish(self, bound, output):
                self.current(bound)  # Never finish the parent Run.

        checkpoint = (
            self.checkpointer_factory() if self.checkpointer_factory else nullcontext(None)
        )
        with checkpoint as saver:
            state = AgentKernel(
                ReadOnlyExtractHost(), default_registry(), budget=budget
            ).execute(
                scope,
                goal=(
                    f"抽取固定原件 {seal.artifact_id}@{seal.revision} "
                    f"的 {task.declaration.kind} 行"
                ),
                execution_key={
                    "tool": "evidence.extract",
                    "artifact_id": seal.artifact_id,
                    "revision": seal.revision,
                    "row_schema": task.declaration.model_dump(mode="json"),
                    "skill": {"key": task.skill_key, "digest": task.skill_digest},
                },
                checkpointer=saver,
            )
        if state.get("__interrupt__"):
            raise DomainError("SOURCE_UNAVAILABLE", "抽取子任务未完成，需主循环澄清。")
        output = state["output"]
        if output["status"] != "completed":
            raise DomainError("SOURCE_UNAVAILABLE", "抽取子任务未形成已核对结果。")
        result = output["result"]
        return result["rows"], result["rejected"]
