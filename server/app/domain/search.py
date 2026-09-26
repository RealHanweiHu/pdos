"""Source-authorized keyword search with deterministic relevance and bounded source reading."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, and_, func, or_, select, union_all

from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain import search_sources

SearchList = list
MAX_TERMS = 8
MAX_LIMIT = 50
SEARCHABLE_KINDS = tuple(search_sources.KIND_ACTIONS)


class SearchQueryError(ValueError):
    pass


class SearchAccessError(PermissionError):
    pass


@dataclass(frozen=True)
class SearchHit:
    kind: str
    id: UUID
    project_id: UUID | None
    title: str
    excerpt: str
    score: int
    occurred_at: datetime
    project_name: str | None = None
    status: str | None = None
    locator: str | None = None
    fragment_ordinal: int | None = None
    fragment_count: int = 0
    href: str = ""


@dataclass(frozen=True)
class SearchResult:
    hits: SearchList[SearchHit]
    total_scanned: int
    truncated: bool
    next_cursor: str | None = None
    terms: tuple[str, ...] = ()
    terms_truncated: bool = False


def parse_terms(query: str) -> list[str]:
    seen = list(dict.fromkeys(query.lower().split()))
    if not seen:
        raise SearchQueryError("请填写搜索词")
    if len(query) > 200:
        raise SearchQueryError("搜索词不能超过200字")
    return seen[:MAX_TERMS]


def href(row: Any) -> str:
    kind, identity, project = row["kind"], row["id"], row["project_id"]
    if kind == "requirement":
        return "/requirements"
    if kind == "memory":
        return f"/knowledge?project={project}&memory={identity}"
    if kind == "attachment":
        return (
            f"/ask?project={project}&conversation={row['conversation_id']}"
            f"&attachment={identity}&fragment={row['fragment_ordinal'] or 1}"
        )
    tab = {
        "project": "overview",
        "task": "work-items",
        "issue": "work-items",
        "risk": "work-items",
        "decision": "decisions",
        "document": "documents",
        "specification": "engineering",
        "sample": "quality",
    }[kind]
    location = f"/projects?project={project}&tab={tab}&entity_id={identity}"
    if kind == "document":
        match = re.fullmatch(r"page:(\d+)(?:#part:\d+)?", row.get("locator") or "")
        if match and 1 <= int(match[1]) <= 500:
            location += f"&page={int(match[1])}"
    return location


def _actor(c: Any, tenant: UUID, user: UUID, expected_role: str) -> str:
    role = c.execute(
        select(tables.users.c.role)
        .join(tables.tenants, tables.tenants.c.id == tables.users.c.tenant_id)
        .where(
            tables.users.c.tenant_id == tenant,
            tables.users.c.id == user,
            tables.users.c.is_active.is_(True),
            tables.tenants.c.status == "active",
        )
    ).scalar_one_or_none()
    if role != expected_role or role is None or not is_allowed(Role(role), Action.WORK_ITEM_VIEW):
        raise SearchAccessError("当前身份不能搜索这些资料")
    return str(role)


def _fingerprint(
    tenant: UUID, user: UUID, terms: list[str], wanted: tuple[str, ...], project: UUID | None
) -> str:
    return sha256(
        json.dumps(
            [str(tenant), str(user), terms, sorted(wanted), str(project)], ensure_ascii=False
        ).encode()
    ).hexdigest()


def _decode(cursor: str, fingerprint: str) -> tuple[int, datetime, str, UUID]:
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if (
            not isinstance(value, dict)
            or value.get("query") != fingerprint
            or type(value["score"]) is not int
        ):
            raise ValueError
        stamp = datetime.fromisoformat(value["at"])
        if (
            stamp.tzinfo is None
            or value["kind"] not in SEARCHABLE_KINDS
            or not 0 <= value["score"] <= 100
        ):
            raise ValueError
        return value["score"], stamp, value["kind"], UUID(value["id"])
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise SearchQueryError("翻页条件已失效，请按当前条件重新搜索") from error


class SearchService:
    def __init__(self, engine: Engine):
        self._engine = engine

    def search(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        role: str,
        query: str,
        kinds: tuple[str, ...] | None = None,
        limit: int = 20,
        now: datetime | None = None,
        project_id: UUID | None = None,
        cursor: str | None = None,
    ) -> SearchResult:
        terms = parse_terms(query)
        wanted = tuple(dict.fromkeys(kinds or SEARCHABLE_KINDS))
        if set(wanted) - set(SEARCHABLE_KINDS):
            raise SearchQueryError("未知的搜索资料类型")
        capped = max(1, min(limit, MAX_LIMIT))
        fingerprint = _fingerprint(tenant_id, user_id, terms, wanted, project_id)
        with (
            self._engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            current_role = _actor(c, tenant_id, user_id, role)
            statements = [
                search_sources.statement(
                    kind,
                    tenant=tenant_id,
                    user=user_id,
                    role=current_role,
                    terms=terms,
                    project_id=project_id,
                )
                for kind in wanted
            ]
            results = union_all(*statements).subquery("search_results")
            statement = select(
                *(col for col in results.c if col.name != "body"),
                search_sources.excerpt(results.c.body, terms).label("excerpt"),
            )
            if cursor:
                score, stamp, kind, identity = _decode(cursor, fingerprint)
                statement = statement.where(
                    or_(
                        results.c.score < score,
                        and_(results.c.score == score, results.c.occurred_at < stamp),
                        and_(
                            results.c.score == score,
                            results.c.occurred_at == stamp,
                            results.c.kind > kind,
                        ),
                        and_(
                            results.c.score == score,
                            results.c.occurred_at == stamp,
                            results.c.kind == kind,
                            results.c.id > identity,
                        ),
                    )
                )
            records = (
                c.execute(
                    statement.order_by(
                        results.c.score.desc(),
                        results.c.occurred_at.desc(),
                        results.c.kind,
                        results.c.id,
                    ).limit(capped + 1)
                )
                .mappings()
                .all()
            )
        next_cursor = None
        if len(records) > capped:
            last = records[capped - 1]
            next_cursor = (
                base64.urlsafe_b64encode(
                    json.dumps(
                        {
                            "query": fingerprint,
                            "score": last["score"],
                            "at": last["occurred_at"].isoformat(),
                            "kind": last["kind"],
                            "id": str(last["id"]),
                        }
                    ).encode()
                )
                .decode()
                .rstrip("=")
            )
        return SearchResult(
            hits=[
                SearchHit(
                    **{
                        key: row[key]
                        for key in (
                            "kind",
                            "id",
                            "project_id",
                            "title",
                            "excerpt",
                            "score",
                            "occurred_at",
                            "project_name",
                            "status",
                            "locator",
                            "fragment_ordinal",
                            "fragment_count",
                        )
                    },
                    href=href(row),
                )
                for row in records[:capped]
            ],
            total_scanned=len(records),
            truncated=len(records) > capped,
            next_cursor=next_cursor,
            terms=tuple(terms),
            terms_truncated=len(set(query.lower().split())) > MAX_TERMS,
        )

    def source(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        role: str,
        kind: str,
        identity: UUID,
        fragment: int = 1,
        offset: int = 0,
        length: int = 6000,
    ) -> dict[str, Any]:
        if (
            kind not in SEARCHABLE_KINDS
            or not 0 <= offset <= 2_000_000
            or not 1 <= length <= 12_000
            or fragment < 1
        ):
            raise SearchQueryError("原文读取参数不正确")
        with (
            self._engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            current_role = _actor(c, tenant_id, user_id, role)
            source = search_sources.statement(
                kind,
                tenant=tenant_id,
                user=user_id,
                role=current_role,
                terms=[],
                fragment=fragment if kind in {"document", "attachment"} else None,
            ).subquery("source_detail")
            row = (
                c.execute(
                    select(
                        *(col for col in source.c if col.name != "body"),
                        func.substring(source.c.body, offset + 1, length).label("text"),
                        func.length(source.c.body).label("total_characters"),
                    ).where(source.c.id == identity)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise SearchAccessError("原资料不存在、已失效或当前无权读取")
            return {
                **dict(row),
                "href": href(row),
                "offset": offset,
                "next_offset": offset + length
                if offset + length < row["total_characters"]
                else None,
            }


# --- Field capture support (V2-10, G14/D37) --------------------------------
#
# D37 rules out scanning, so a sample is identified by its printed serial
# number appearing in what the engineer wrote or dictated. Matching is
# deterministic and case-insensitive; ambiguity is reported rather than
# resolved, because guessing which prototype a defect belongs to is exactly
# the mistake that makes field records untrustworthy.


@dataclass(frozen=True)
class SampleMatch:
    sample_id: UUID
    serial_number: str
    project_id: UUID
    matched_text: str


class SampleMatcher:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def match(
        self, *, tenant_id: UUID, project_id: UUID, text_value: str
    ) -> SearchList[SampleMatch]:
        """Every project sample whose serial number appears in the text.

        Returns all matches, not a best guess. Two serials in one note means
        the note is ambiguous, and the caller must ask rather than pick.
        """
        if not text_value.strip():
            return []
        lowered = text_value.lower()
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    tables.samples.c.id,
                    tables.samples.c.serial_number,
                    tables.samples.c.project_id,
                ).where(
                    tables.samples.c.tenant_id == tenant_id,
                    tables.samples.c.project_id == project_id,
                )
            ).all()
        matches = [
            SampleMatch(
                sample_id=row.id,
                serial_number=row.serial_number,
                project_id=row.project_id,
                matched_text=row.serial_number,
            )
            for row in rows
            if row.serial_number and row.serial_number.lower() in lowered
        ]
        # Longest serial first: when SN-1 and SN-12 both appear, the more
        # specific identifier is the one a person most likely meant.
        matches.sort(key=lambda match: -len(match.serial_number))
        return matches
