"""A frozen early-M3 web candidate and M3-owned real schema comparison."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import time

import m3_early_environment as fixture


def schema():
    current = fixture.state()
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from migrations.candidates.m3_preproject import ATOMIC_GUARDS, FUNCTIONS, SECURITY
    from pdos_next.database import engine_for
    from pdos_next.domain.preproject.category_models import TABLES as CATEGORY_TABLES
    from pdos_next.domain.preproject.models import TABLES
    from pdos_next.models import Base
    from sqlalchemy import text

    owned = {table.name for table in (*TABLES, *CATEGORY_TABLES)}

    def include(obj, name, kind, reflected, compare_to):
        table = obj if kind == "table" else getattr(obj, "table", None)
        return table is None or table.name in owned

    engine = engine_for(current["admin_url"])
    with engine.connect() as c:
        differences = compare_metadata(
            MigrationContext.configure(c, opts={"include_object": include}), Base.metadata
        )
        fields = c.execute(
            text(
                "SELECT table_name,column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name IN "
                "('definition_revisions','definition_specs','projects','products')"
            )
        ).all()
        expected = {
            ("definition_revisions", "sealed"),
            ("definition_revisions", "g0_decision_id"),
            ("definition_specs", "item_status"),
            ("definition_specs", "origin"),
            ("definition_specs", "modality"),
            ("projects", "g0_decision_id"),
            ("products", "target_price"),
            ("products", "target_price_currency"),
            ("products", "target_price_basis"),
            ("products", "target_price_includes_tax"),
            ("products", "target_price_as_of"),
        }
        supplements = expected.issubset(set(fields))
        guarded = c.scalar(
            text("SELECT count(*) FROM pg_trigger WHERE tgname='m3_atom' AND NOT tgisinternal")
        )
        expected_functions = dict(
            re.findall(
                r"CREATE (?:OR REPLACE )?FUNCTION (\w+)\(.*?AS \$\$(.*?)\$\$;",
                SECURITY + FUNCTIONS + ATOMIC_GUARDS,
                re.S,
            )
        )
        actual_functions = dict(
            c.execute(
                text(
                    "SELECT proname,prosrc FROM pg_proc JOIN pg_namespace n ON n.oid=pronamespace "
                    "WHERE n.nspname='public'"
                )
            ).all()
        )
        function_mismatches = [
            name for name, body in expected_functions.items() if actual_functions.get(name) != body
        ]
        sealed_guards = c.scalar(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgname IN "
                "('m3_sealed_definition','m3_sealed_spec','m3_sealed_source') AND NOT tgisinternal"
            )
        )
    engine.dispose()
    fixture.REPORT.mkdir(parents=True, exist_ok=True)
    (fixture.REPORT / "owned-schema.json").write_text(
        json.dumps(
            {
                "owned_tables": len(owned),
                "differences": repr(differences),
                "supplement_fields_present": supplements,
                "deferred_atoms": guarded,
                "functions_checked": len(expected_functions),
                "function_mismatches": function_mismatches,
                "sealed_guards": sealed_guards,
                "active_alembic_heads_changed": False,
            },
            indent=2,
        )
        + "\n"
    )
    if differences or not supplements or guarded != 4 or function_mismatches or sealed_guards != 3:
        raise RuntimeError("M3 owned schema mismatch; see scoped evidence")
    print("M3 owned schema and actual supplemental fields match; 4 deferred atoms installed")


def ownership():
    """Inventory every installed definer, not just M3's functions."""
    current = fixture.state()
    from pdos_next.database import engine_for
    from pdos_next.domain.preproject.category_models import TABLES as CATEGORY_TABLES
    from pdos_next.domain.preproject.models import TABLES
    from sqlalchemy import text

    engine = engine_for(current["admin_url"])
    with engine.connect() as c:
        functions = [
            dict(row)
            for row in c.execute(
                text(
                    "SELECT p.oid::regprocedure::text AS signature,r.rolname AS owner,"
                    "r.rolsuper AS superuser,r.rolbypassrls AS bypassrls,p.proconfig AS settings "
                    "FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner "
                    "WHERE p.pronamespace='public'::regnamespace AND p.prosecdef ORDER BY 1"
                )
            ).mappings()
        ]
        tables = [
            dict(row)
            for row in c.execute(
                text(
                    "SELECT relname AS name,pg_get_userbyid(relowner) AS owner,"
                    "relrowsecurity AS rls,relforcerowsecurity AS force_rls "
                    "FROM pg_class WHERE relnamespace='public'::regnamespace "
                    "AND relkind='r' ORDER BY 1"
                )
            ).mappings()
        ]
        roles = [
            dict(row)
            for row in c.execute(
                text(
                    "SELECT rolname,rolsuper,rolbypassrls,rolcanlogin,"
                    "pg_has_role(rolname,'pdos_next_owner','MEMBER') AS owner_member,"
                    "has_schema_privilege(rolname,'public','CREATE') AS schema_create "
                    "FROM pg_roles WHERE rolname IN "
                    "('pdos_next_owner','pdos_next_app','pdos_next_auth','pdos_next_dispatch','pdos_agent')"
                )
            ).mappings()
        ]
        agent_writes = c.scalars(
            text(
                "SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace "
                "AND relkind='r' AND has_table_privilege('pdos_agent',oid,'INSERT,UPDATE,DELETE')"
            )
        ).all()
        heads = c.scalars(text("SELECT version_num FROM alembic_version ORDER BY 1")).all()
    engine.dispose()
    migration_files = [
        str(p.relative_to(fixture.local.SERVER))
        for p in sorted((fixture.local.SERVER / "migrations").glob("schema_s0_*.py"))
        if "SECURITY DEFINER" in p.read_text()
    ]
    owned = {t.name for t in (*TABLES, *CATEGORY_TABLES)}
    owned_tables = [t for t in tables if t["name"] in owned]
    if (
        any(f["superuser"] or f["bypassrls"] or f["owner"] != "pdos_next_owner" for f in functions)
        or len(owned_tables) != len(owned)
        or any(not t["rls"] or not t["force_rls"] for t in owned_tables)
        or any(
            r["owner_member"] or r["schema_create"]
            for r in roles
            if r["rolname"] != "pdos_next_owner"
        )
        or agent_writes
    ):
        raise RuntimeError("Ordinary owner or runtime role boundary failed")
    (fixture.REPORT / "definer-ownership.json").write_text(
        json.dumps(
            {
                "target": f"127.0.0.1:{current['port']}/pdos_test",
                "marker": current["marker"],
                "alembic_heads": heads,
                "definer_count": len(functions),
                "definers": functions,
                "owned_tables": owned_tables,
                "roles": roles,
                "agent_direct_write_tables": agent_writes,
                "active_schema_files_containing_definers": migration_files,
                "production_changed": False,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"{len(functions)} installed definers inventoried; "
        "ordinary owner and runtime roles verified"
    )


def web():
    source = fixture.local.ROOT / "web"
    target = fixture.local.ROOT / f".local/m3-early-web-{time.time_ns()}"
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(
            "node_modules",
            ".next*",
            ".env*",
            "*.tsbuildinfo",
            ".DS_Store",
            "output",
        ),
    )
    (target / "node_modules").symlink_to(source / "node_modules", target_is_directory=True)
    # Unlike web/.next, this candidate's build path is outside the repository ignore pattern.
    # Tailwind must not recursively scan its own freshly emitted webpack bundle.
    with (target / ".gitignore").open("a") as ignore:
        ignore.write("\n.next/\nnode_modules/\nfont-cache/\n")
    # Node's production font download hung, and bounded gstatic retrieval timed out.
    # Replay only the actual existing Geist WOFF2 cache; application source is unchanged.
    font_cache = target / "font-cache"
    font_cache.mkdir()
    cached_css = next(
        (
            p
            for p in (source / ".next/static/css").glob("*.css")
            if "font-family:Geist;" in p.read_text() and "font-family:Geist Mono;" in p.read_text()
        ),
        None,
    )
    if cached_css is None:
        raise RuntimeError("Actual existing Geist font cache unavailable")
    faces = re.findall(r"@font-face\{[^}]+\}", cached_css.read_text())
    responses, font_sources = {}, []
    for family in ("Geist", "Geist Mono"):
        declarations = []
        for face in faces:
            if f"font-family:{family};" not in face or "src:url(" not in face:
                continue
            relative = re.search(r"url\(/_next/(static/media/[^)]+)\)", face).group(1)
            original = source / ".next" / relative
            path = font_cache / original.name
            content = original.read_bytes()
            if content[:4] != b"wOF2":
                raise RuntimeError("Cached font is not an actual WOFF2 file")
            path.write_bytes(content)
            font_sources.append(
                {"cached_source": str(original), "sha256": hashlib.sha256(content).hexdigest()}
            )
            subset = "latin" if "-s.p.woff2" in original.name else "cached"
            face = face.replace("/_next/" + relative, str(path)).replace("src:url(", "src: url(")
            declarations.append(f"/* {subset} */\n" + face + "\n")
        if not declarations:
            raise RuntimeError(f"Cached {family} declarations unavailable")
        url = (
            f"https://fonts.googleapis.com/css2?family={family.replace(' ', '+')}"
            ":wght@100..900&display=swap"
        )
        responses[url] = "".join(declarations)
    response_path = font_cache / "responses.json"
    response_path.write_text(json.dumps(responses))
    env = {**os.environ, "NEXT_FONT_GOOGLE_MOCKED_RESPONSES": str(response_path)}
    inputs = [p for p in sorted((target / "src").rglob("*")) if p.is_file()]
    inputs += [
        target / name
        for name in (
            "package.json",
            "pnpm-lock.yaml",
            "next.config.ts",
            "postcss.config.mjs",
            "tsconfig.json",
            "eslint.config.mjs",
        )
        if (target / name).is_file()
    ]
    files = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    checks = []
    node_modules = source / "node_modules"
    for name, arguments in (
        (
            "affected-lint",
            [
                "node",
                str(node_modules / "eslint/bin/eslint.js"),
                "src/components/preproject",
                "src/app/categories",
                "src/app/api/[...path]/route.ts",
                "postcss.config.mjs",
            ],
        ),
        ("build", ["node", str(node_modules / "next/dist/bin/next"), "build", "--webpack"]),
        ("typecheck", ["node", str(node_modules / "typescript/bin/tsc"), "--noEmit"]),
    ):
        with (fixture.REPORT / f"web-{name}-{target.name}.log").open("x") as output:
            result = subprocess.run(
                arguments, cwd=target, env=env, stdout=output, stderr=subprocess.STDOUT
            )
        checks.append({"name": name, "exit_code": result.returncode})
        if result.returncode:
            raise RuntimeError(f"Frozen M3 web {name} failed; evidence retained")
    changed = [
        name
        for name, sha in files.items()
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != sha
    ]
    (fixture.REPORT / "web-candidate.json").write_text(
        json.dumps(
            {
                "files": files,
                "checks": checks,
                "live_source_changes_after_copy": changed,
                "candidate": str(target),
                "actual_font_cache": font_sources,
                "scope": "Frozen full web build; affected lint; no main .next touched",
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"Frozen web build/typecheck/affected lint passed: {len(files)} files; "
        f"source drift {len(changed)}"
    )
    state = fixture.state()
    state["web_candidate"] = str(target)
    fixture.local.save(state)


if __name__ == "__main__":
    schema()
    web()
