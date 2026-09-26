"""Every backend route is either reachable from the app or explicitly exempt.

`web/src/app/api/bff-coverage.test.ts` guards one direction: the browser must
not call a `/api/...` path with no route handler behind it. This test guards the
*other* direction, which turned out to be the larger hole — a backend endpoint
with no BFF route at all is capability the product simply does not have, and
nothing failed to tell us. That is how the whole NPI execution surface (builds,
samples, test plans, runs, imports, certifications) sat unreachable after V1
shipped it.

`UNREACHABLE_BACKLOG` is a ledger, not a permission slip: every entry is a
backend capability the app cannot currently use. Deleting entries is the work.
Adding one is a deliberate decision that has to be argued for in review.
"""

from __future__ import annotations

import json
import re
from itertools import product
from pathlib import Path

from app.main import app

WEB_API_ROOT = Path(__file__).resolve().parents[2] / "web" / "src" / "app" / "api"

# Served by the `session` BFF under a different path shape: the browser never
# calls these directly because tokens must not reach client JavaScript.
SESSION_HANDLED = frozenset(
    {
        "/api/auth/login",
        "/api/auth/me",
        "/api/auth/change-password",
        "/api/setup",
        "/api/setup/status",
    }
)

# Called server-side during rendering rather than by the browser.
SERVER_SIDE_ONLY = frozenset({"/api/projects/:id/access"})

# Operator/worker endpoints with no user-facing surface by design.
OPERATIONAL_ONLY = frozenset(
    {
        "/api/projects/:id/reminders/dispatch",
        "/api/projects/:id/reminders/scan",
    }
)

# Backend capability the app cannot reach yet. Shrink this list; do not grow it.
#
# Empty as of 2026-08-28: every backend route is now either reachable from the
# app or named in one of the exemption sets above. An entry added here is a
# capability the product ships without, so it needs an argument in review.
UNREACHABLE_BACKLOG: frozenset[str] = frozenset()

# Credential-scoped consumer endpoints deliberately have no browser-session BFF.
# Their user-facing credential administration is checked through the BFF below.
EXTERNAL_INTEGRATION = frozenset(
    {
        "/api/open/v1/projects/:id/customer-files/read",
        "/api/open/v1/projects/:id/customer-receipts/record",
        "/api/open/v1/projects/:id/customer-reports/query",
        "/api/open/v1/projects/:id/customer-reports/read",
        "/api/open/v1/projects/:id/work/query",
    }
)

EXEMPT = (
    SESSION_HANDLED
    | SERVER_SIDE_ONLY
    | OPERATIONAL_ONLY
    | EXTERNAL_INTEGRATION
    | UNREACHABLE_BACKLOG
)


def backend_routes() -> set[str]:
    routes: set[str] = set()
    for path, operations in app.openapi().get("paths", {}).items():
        if not path.startswith("/api/"):
            continue
        # A finite path enum (issues/risks) has concrete BFF routes. Require all
        # values instead of treating the collection name as an arbitrary UUID.
        for operation in operations.values():
            enums = {
                parameter["name"]: parameter["schema"]["enum"]
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "path" and "enum" in parameter.get("schema", {})
            }
            for values in product(*enums.values()):
                resolved = path
                for name, value in zip(enums, values, strict=True):
                    resolved = resolved.replace("{" + name + "}", str(value))
                routes.add(re.sub(r"\{[^}]+\}", ":id", resolved).rstrip("/"))
    return routes


def mapped_bff_routes() -> set[str]:
    """Read the actual allowlists of BFFs whose URL differs from their upstream."""
    routes: set[str] = set()
    for alias, collection in (
        ("value-measurement", "value-measurement"),
        ("value-workpacks", "value-workpacks"),
        ("open-api-admin", "open-api"),
        ("webhook-admin", "webhooks"),
    ):
        source = (WEB_API_ROOT / alias / "[projectId]/[operation]/route.ts").read_text()
        assert f'"/api/projects/" + projectId + "/{collection}/" + operation' in source
        allowed = re.search(r"const operations = (\[[^;]+\]);", source)
        if allowed is None:
            allowed = re.search(r"(\[\"options\"[^\]]+\])\.includes\(operation\)", source)
        assert allowed is not None, alias
        routes.update(
            f"/api/projects/:id/{collection}/{operation}" for operation in json.loads(allowed[1])
        )
    source = (WEB_API_ROOT / "project-reports/[projectId]/[...reportPath]/route.ts").read_text()
    assert '(customer ? "/customer-reports/" : "/reports/")' in source
    allowed = re.search(
        r"\(customer \? (\[[^\]]+\]) : (\[[^\]]+\])\)\.includes\(path\[0\]\)", source
    )
    assert allowed is not None
    for collection, group in (("customer-reports", 1), ("reports", 2)):
        routes.update(
            f"/api/projects/:id/{collection}/{operation}"
            for operation in json.loads(allowed[group])
        )
        assert 'path[1] === "download"' in source
        routes.add(f"/api/projects/:id/{collection}/:id/download")
    assert '(!customer && path[1] === "bundle-download")' in source
    routes.add("/api/projects/:id/reports/:id/bundle-download")
    return routes


def bff_routes() -> set[str]:
    routes: set[str] = set()
    for route in WEB_API_ROOT.rglob("route.ts"):
        # iCloud leaves " 2" copies in this repo; they are not real sources.
        if " 2" in str(route):
            continue
        parts: list[str] = []
        for segment in route.relative_to(WEB_API_ROOT).parent.parts:
            if segment == ".":
                continue
            if segment.startswith(("[[", "[...")):
                parts.append("**")
            elif segment.startswith("["):
                parts.append(":id")
            else:
                parts.append(segment)
        routes.add("/api" + ("/" + "/".join(parts) if parts else ""))
    return routes | mapped_bff_routes()


def is_covered(path: str, routes: set[str]) -> bool:
    segments = path[len("/api/") :].split("/")
    for route in routes:
        route_segments = route[len("/api") :].strip("/").split("/") if route != "/api" else []
        if route_segments and route_segments[-1] == "**":
            fixed = route_segments[:-1]
            if len(segments) >= len(fixed) and all(
                part in (":id", actual)
                for part, actual in zip(fixed, segments[: len(fixed)], strict=True)
            ):
                return True
        elif len(route_segments) == len(segments) and all(
            part in (":id", actual) for part, actual in zip(route_segments, segments, strict=True)
        ):
            return True
    return False


def test_every_backend_route_is_reachable_or_listed_as_unreachable() -> None:
    routes = bff_routes()
    uncovered = {path for path in backend_routes() if not is_covered(path, routes)}
    surprises = sorted(uncovered - EXEMPT)

    assert not surprises, (
        "backend routes with no BFF route and no exemption — the app cannot "
        f"reach these at all: {surprises}"
    )


def test_the_backlog_does_not_list_routes_that_are_already_reachable() -> None:
    """A stale backlog entry hides that the work is done and invites a rewrite."""
    routes = bff_routes()
    stale = sorted(path for path in UNREACHABLE_BACKLOG if is_covered(path, routes))

    assert not stale, f"these are reachable now and should leave the backlog: {stale}"


def test_the_exemption_list_only_names_routes_that_exist() -> None:
    """A renamed or deleted endpoint must not leave a silent exemption behind."""
    backend = backend_routes()
    phantom = sorted(EXEMPT - backend)

    assert not phantom, f"exemptions for routes the backend no longer serves: {phantom}"


def test_the_scan_actually_found_both_sides() -> None:
    """A silently empty scan would make every assertion above vacuously true."""
    assert len(backend_routes()) > 100
    assert len(bff_routes()) > 20
