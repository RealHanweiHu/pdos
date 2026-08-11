import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.db.test_safety import configured_test_database_url

SERVER_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    os.environ["DATABASE_URL"] = configured_test_database_url()
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    print("Test database migration reached Alembic head")


if __name__ == "__main__":
    main()
