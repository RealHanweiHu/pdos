"""uvicorn on 127.0.0.1:8898 against the marked pdos_test; workflows off (runs are saved, not executed)."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from common import WORKTREE, OBJECTS, env  # noqa: E402
OBJECTS.mkdir(parents=True, exist_ok=True)
os.chdir(WORKTREE / "server")
os.execve(sys.executable, [sys.executable, "-m", "uvicorn", "pdos_next.asgi:app", "--host", "127.0.0.1", "--port", "8898"], env())
