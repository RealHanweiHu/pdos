Working directory: pdos-next/server

```sh
.venv/bin/python -m pytest tests/agent_kernel/test_owner_history.py tests/agent_kernel/test_session_views.py -q
# 19 passed in 0.45s
.venv/bin/python -m pytest tests/agent_kernel/test_owner_history_pg.py --collect-only -q
# 3 tests collected in 0.38s; no DB fixtures executed
.venv/bin/python -m ruff check pdos_next/agent_kernel/owner_history.py pdos_next/agent_kernel/session_views.py pdos_next/agent_kernel/api.py tests/agent_kernel/test_owner_history.py tests/agent_kernel/test_owner_history_pg.py
# All checks passed!
```

Repository root:

```sh
git diff --check -- pdos-next/server/pdos_next/agent_kernel/api.py pdos-next/server/pdos_next/agent_kernel/session_views.py
# exit 0
```

No database command, migration, real provider call, real model or embedding was run by this subagent for this change. Root owns the integrated native PG run and its separate evidence.
