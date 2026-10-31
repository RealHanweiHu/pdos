"""Human retrieval choices; they never grant access or change the Run's object scope."""

from copy import deepcopy
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field

from pdos_next.schema_base import StrictModel
from pdos_next.service import digest


class SearchPreferences(StrictModel):
    scope: Literal["current", "same_category"] = "same_category"
    include_customer_private: bool = Field(default=False, strict=True)


def defaults():
    return SearchPreferences().model_dump(mode="json")


def configure_start(session, ctx, run, requested):
    """Persist an explicit human choice and freeze that request before dispatch."""
    if requested is None:
        return
    from .work_state import _append, _human, _lock, empty, latest, user_goal

    _human(session, ctx, None)
    _lock(session, run.tenant_id, run.session_id)
    row = latest(session, run.session_id)
    body = deepcopy(row.body) if row else empty()
    goal = {"run_id": str(run.id), "text": user_goal(run.goal)}
    body["root_goal"] = body["root_goal"] or goal
    body["current_goal"] = body["current_goal"] or goal
    body["search_preferences"] = requested.model_dump(mode="json")
    run.versions = {**run.versions, "requested_search_preferences": body["search_preferences"]}
    _append(
        session, run, body, origin="human",
        key=uuid5(NAMESPACE_URL, f"pdos-search-preferences:{run.id}"),
        fingerprint=digest(body["search_preferences"]),
        revision=(row.revision if row else 0) + 1,
    )
