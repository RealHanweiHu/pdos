from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

SERVER_ROOT = Path(__file__).resolve().parents[1]


def test_migration_history_has_one_append_only_head() -> None:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["0024_phase_two_agents"]
