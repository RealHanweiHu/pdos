"""Shared: this worktree's marked pdos_test only; never prints credentials."""
import os, sys
from pathlib import Path
WORKTREE = Path("/Users/huhanwei/Developer/ai-native-R&D-platform/.claude/worktrees/charming-almeida-2d1941")
sys.path[:0] = [str(WORKTREE / "tools"), str(WORKTREE / "server"), str(WORKTREE / "server/tests/..")]
import local_environment as le  # noqa: E402
assert le.ROOT == WORKTREE, le.ROOT
STATE = le.verified(le.read_state())
OBJECTS = WORKTREE / ".local/objects"
def env():
    value = le.environment(STATE)
    value.pop("PDOS_NEXT_ENV_FILE", None)
    value.update(PDOS_OBJECT_ROOT=str(OBJECTS), PDOS_WORKFLOWS_ENABLED="0",
                 PDOS_FILE_SECURITY_PROFILE="local-synthetic-v1", PYTHONPATH=str(WORKTREE / "server"))
    return value
