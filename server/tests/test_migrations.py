from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

SERVER_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HEAD = "0376_readable_audit_reports"
EXPECTED_BASE = "0000_scaffold"


def test_migration_history_has_one_append_only_head() -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    # These are the explicit N7 integration boundary and original scaffold, not
    # values inferred from whatever migrations happen to be present at test time.
    assert scripts.get_heads() == [EXPECTED_HEAD]
    assert scripts.get_bases() == [EXPECTED_BASE]
    chain = list(reversed(list(scripts.walk_revisions())))
    assert len(chain) == 377
    assert [step.revision[:4] for step in chain] == [f"{index:04d}" for index in range(377)]
    for index, step in enumerate(chain):
        assert step.down_revision == (chain[index - 1].revision if index else None)
        assert not step.dependencies
        assert not step.branch_labels
