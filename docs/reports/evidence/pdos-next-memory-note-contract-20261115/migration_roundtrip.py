"""Migration round trip for s0_0900 on the isolated task database (D512).

Run from the repository root with this worktree's ``.local/runtime.json`` environment:

    python docs/reports/evidence/pdos-next-memory-note-contract-20261115/migration_roundtrip.py

1. Down to s0_0892 and seed personal notes in the old shape (plain, revised, replaced,
   with an end date, alias), as the s0_0865 code wrote them.
2. Up to s0_0900: every version gets the documented defaults.
3. Down again: allowed, since only defaults are present; old columns are byte-identical.
4. Up, write one version with a contract field the old schema cannot hold: down is
   refused. Remove it and down/up once more.
"""

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "server"))

from local_environment import environment, read_state, verified  # noqa: E402
from sqlalchemy import text  # noqa: E402

from pdos_next.core.database import engine_for  # noqa: E402

OLD = ("owner_id", "note_id", "revision", "kind", "text", "scope_kind", "scope_id",
       "category_id", "alias_term", "alias_canonical", "target_kind", "target_id",
       "target_version", "status", "valid_until", "replaced_by", "origin", "candidate_id",
       "request_key", "request_sha256", "id", "tenant_id", "created_at")


def alembic(*args):
    state = verified(read_state())
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT / "server",
                            env=environment(state), capture_output=True, text=True)
    print(f"$ alembic {' '.join(args)} -> exit {result.returncode}")
    if result.returncode:
        lines = result.stderr.strip().splitlines()
        print(next((line for line in lines if "RaiseException" in line), lines[-1]))
    return result.returncode


def rows(engine, tenant, columns):
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(
            f"SELECT {', '.join(columns)} FROM memory_note_versions WHERE tenant_id=:t "
            "ORDER BY note_id, revision"), {"t": tenant})]


def main():
    state = verified(read_state())
    admin = engine_for(state["admin_url"])
    assert alembic("downgrade", "s0_0892") == 0
    tenant, owner = uuid4(), uuid4()
    base = datetime(2026, 11, 1, 9, tzinfo=UTC)
    a, b, c, d, e = (uuid4() for _ in range(5))
    sha = "0" * 64

    def version(note, revision, at, *, status="active", text_value="回答先给结论", kind="convention",
                valid_until=None, replaced_by=None, alias=None):
        return {"id": uuid4(), "tenant_id": tenant, "created_at": at, "owner_id": owner,
                "note_id": note, "revision": revision, "kind": kind, "text": text_value,
                "scope_kind": "global", "scope_id": None, "category_id": None,
                "alias_term": alias, "alias_canonical": "气门嘴" if alias else None,
                "target_kind": None, "target_id": None, "target_version": None,
                "status": status, "valid_until": valid_until, "replaced_by": replaced_by,
                "origin": "manual", "candidate_id": None, "request_key": uuid4(),
                "request_sha256": sha}

    seeded = [
        version(a, 1, base),
        version(b, 1, base + timedelta(hours=1), text_value="周报用表格"),
        version(b, 2, base + timedelta(days=2), text_value="周报用表格，先写结论"),
        version(c, 1, base + timedelta(hours=2), text_value="我负责成本核算", kind="background"),
        version(c, 2, base + timedelta(days=3), text_value="我负责成本核算", kind="background",
                status="replaced", valid_until=base + timedelta(days=3), replaced_by=a),
        version(d, 1, base + timedelta(hours=3), text_value="本月按旧口径",
                valid_until=base + timedelta(days=40)),
        version(e, 1, base + timedelta(hours=4), text_value="我说“气嘴”指气门嘴", kind="alias",
                alias="气嘴"),
    ]
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO principals (id, tenant_id, name, kind, active, access_epoch, created_at) "
                          "VALUES (:id, :t, 'Synthetic migration owner', 'human', true, 1, now())"),
                     {"id": owner, "t": tenant})
        for note in (a, b, c, d, e):
            conn.execute(text("INSERT INTO memory_notes (id, tenant_id, owner_id, created_at) "
                              "VALUES (:id, :t, :o, now())"), {"id": note, "t": tenant, "o": owner})
        for row in seeded:
            conn.execute(text(f"INSERT INTO memory_note_versions ({', '.join(row)}) VALUES "
                              f"({', '.join(':' + key for key in row)})"), row)
    before = rows(admin, tenant, OLD)
    print(f"seeded {len(before)} versions at s0_0892")

    assert alembic("upgrade", "s0_0900") == 0
    after = rows(admin, tenant, (*OLD, "occurred_at", "valid_from", "confirmation", "evidence",
                                 "relations"))
    assert [{key: row[key] for key in OLD} for row in after] == before
    by_key = {(row["note_id"], row["revision"]): row for row in after}
    for row in after:
        assert row["occurred_at"] is None and row["confirmation"] == "member_confirmed"
        assert row["evidence"] == [] and row["relations"] == []
        expected = (by_key[(row["note_id"], row["revision"] - 1)]["created_at"]
                    if row["status"] == "replaced" else row["created_at"])
        assert row["valid_from"] == expected, row
    print("upgrade s0_0900: defaults valid_from=created_at (replaced marker copies the version it "
          "closes), occurred_at=NULL, confirmation=member_confirmed, evidence=[], relations=[]")

    assert alembic("downgrade", "s0_0892") == 0
    assert rows(admin, tenant, OLD) == before
    print("downgrade s0_0892 with defaults only: allowed; old columns unchanged")

    assert alembic("upgrade", "s0_0900") == 0
    extra = version(uuid4(), 1, base + timedelta(days=5), text_value="十月起我调到质量部",
                    kind="background")
    extra.update(occurred_at=base, valid_from=base + timedelta(days=5), confirmation="member_confirmed",
                 evidence=json.dumps([]), relations=json.dumps([]))
    with admin.begin() as conn:
        conn.execute(text("INSERT INTO memory_notes (id, tenant_id, owner_id, created_at) "
                          "VALUES (:id, :t, :o, now())"),
                     {"id": extra["note_id"], "t": tenant, "o": owner})
        conn.execute(text(f"INSERT INTO memory_note_versions ({', '.join(extra)}) VALUES "
                          f"({', '.join(':' + key for key in extra)})"), extra)
    assert alembic("downgrade", "s0_0892") != 0
    print("downgrade with an occurred_at present: refused")
    # Versions are never updated: replace the row by a back-dated one instead.
    backdated = {**extra, "id": uuid4(), "request_key": uuid4(), "occurred_at": None,
                 "valid_from": base + timedelta(days=2)}
    with admin.begin() as conn:
        conn.execute(text("DELETE FROM memory_note_versions WHERE id=:id"), {"id": extra["id"]})
        conn.execute(text(f"INSERT INTO memory_note_versions ({', '.join(backdated)}) VALUES "
                          f"({', '.join(':' + key for key in backdated)})"), backdated)
    extra = backdated
    assert alembic("downgrade", "s0_0892") != 0
    print("downgrade with a back-dated valid_from present: refused")
    with admin.begin() as conn:
        conn.execute(text("DELETE FROM memory_note_versions WHERE id=:id"), {"id": extra["id"]})
    assert alembic("downgrade", "s0_0892") == 0
    assert alembic("upgrade", "head") == 0
    with admin.begin() as conn:
        conn.execute(text("DELETE FROM memory_note_versions WHERE tenant_id=:t"), {"t": tenant})
    # memory_notes is append-only (identities, no content); its synthetic tenant stays.
    print("round trip passed; synthetic versions removed; database at head")


if __name__ == "__main__":
    main()
