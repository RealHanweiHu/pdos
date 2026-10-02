"""Pinned published definition references with sparse local item/section overlays."""

from copy import deepcopy
from typing import Any

from sqlalchemy import Connection, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB

from app.domain.product_workspace import ProductWorkError


def effective_content(table: Any) -> Any:
    return cast(
        func.cehub_product.resolve_definition_content(
            table.c.tenant_id, table.c.base_definition_id, table.c.content
        ),
        JSONB,
    )


def resolve_content(
    c: Connection, tenant: Any, base: Any, overlay: dict[str, Any]
) -> dict[str, Any]:
    if base is None:
        return deepcopy(overlay)
    return dict(
        c.execute(
            select(
                func.cehub_product.resolve_definition_content(tenant, base, cast(overlay, JSONB))
            )
        ).scalar_one()
    )


def expand_definition(c: Connection, row: Any) -> Any:
    if row is None or row.get("base_definition_id") is None:
        return row
    return {
        **row,
        "content": resolve_content(c, row["tenant_id"], row["base_definition_id"], row["content"]),
    }


def sparse_content(
    c: Connection, tenant: Any, base: Any, content: dict[str, Any]
) -> dict[str, Any]:
    if base is None:
        return deepcopy(content)
    parent = resolve_content(c, tenant, base, {})
    parent_items = {item["item_key"]: item for item in parent["items"]}
    if not parent_items.keys() <= {item["item_key"] for item in content["items"]}:
        raise ProductWorkError("父版规格标识必须保留；不适用时请明确处置，不能删除")
    value = {
        key: deepcopy(value)
        for key, value in content.items()
        if key != "items"
        and (
            key in {"title", "owner_user_id", "reviewers", "change_reason"}
            or value != parent.get(key)
        )
    }
    value["items"] = [
        deepcopy(item) for item in content["items"] if item != parent_items.get(item["item_key"])
    ]
    return value


# Named responsibilities and local publication decisions are never inherited by a merge.
LOCAL_FIELDS = {"title", "owner_user_id", "reviewers", "change_reason"}


def merge_paths(content: dict[str, Any]) -> dict[str, Any]:
    return {
        **{
            f"field/{key}": value
            for key, value in content.items()
            if key not in LOCAL_FIELDS | {"items"}
        },
        **{f"items/{item['item_key']}": item for item in content["items"]},
    }


def three_way(
    base: dict[str, Any], local: dict[str, Any], incoming: dict[str, Any]
) -> list[dict[str, Any]]:
    old, ours, theirs = (merge_paths(value) for value in (base, local, incoming))
    return [
        {
            "path": path,
            "base": old.get(path),
            "local": ours.get(path),
            "incoming": theirs.get(path),
            "conflict": ours.get(path) != old.get(path) and ours.get(path) != theirs.get(path),
        }
        for path in sorted(old.keys() | theirs.keys())
        if old.get(path) != theirs.get(path)
    ]


def accept_changes(
    local: dict[str, Any], incoming: dict[str, Any], paths: tuple[str, ...]
) -> dict[str, Any]:
    result = deepcopy(local)
    target = merge_paths(incoming)
    items = {item["item_key"]: item for item in result["items"]}
    for path in paths:
        if path not in target:
            raise ProductWorkError("不能删除父版规格；请保留标识并记录不适用处置")
        if path.startswith("field/"):
            result[path.removeprefix("field/")] = deepcopy(target[path])
        else:
            key = path.removeprefix("items/")
            item = deepcopy(target[path])
            # Upstream approval/ownership does not confirm this product's changed specification.
            item.update(
                state="needs_confirmation",
                owner_user_id=items.get(key, {}).get("owner_user_id"),
                disposition_reason=None,
            )
            items[key] = item
    result["items"] = list(items.values())
    return result
