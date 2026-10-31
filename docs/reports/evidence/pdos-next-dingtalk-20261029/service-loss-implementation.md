# G native helper SQL service-loss convergence

Independent stage: 1 shared `dingtalk/workflow.py` + 2 new tests. No migration,
live edit, DB connection, provider/channel call or service startup by the subagent.
Root runs actual PG against the current integrated 0845+ helper.

## Confirmed narrow gap

Native app `active=False` already converges normally: the SQL `dingtalk_service`
identity predicate does not require app.active, then refreshed ordinary guard reads
raise CANCELLED_RUN and existing reserve/send handlers cancel without transport.

When `dingtalk_lock_message_binding` itself emits its explicit SQL42501 (for example
the real service Principal becomes inactive while the helper waits for the app
row), no existing send/Activity catch handled DBAPIError. The failed service UOW
rolls back and Temporal would retry rather than report the expected cancellation.
Converting inside that aborted UOW is insufficient, and revoked service UPDATE RLS
must not be relaxed to save a terminal journal status.

## Minimal delta

Only `ChannelActivities.deliver`, outside `execute(service, reference)` and its
already-exited native UOWs, catches a DBAPIError satisfying **all** these conditions:

- SQLSTATE is 42501;
- PostgreSQL primary message is exactly `DingTalk service binding required`;
- the statement is the actual `SELECT dingtalk_lock_message_binding(...)` call;
- existing `service.cancel_lost(ref)` returns an actual typed Run UUID.

That dispatcher-only primitive independently rechecks the exact persisted
Message/Binding/Application/Run and current identities. Only then the Activity
returns `{state: cancelled, error_code: CANCELLED_RUN}`. The existing completion
workflow subsequently cancels the original native execution and stops. Other SQL
states, generic permission configuration errors and unproved denial propagate as
before. A generic 42501 never grants cancellation.

No guard, helper SQL, ACL, normal app-disable path or outbound action is changed.
No retry/send is added. Existing planned cancellation and original sending/unknown
journals retain their existing semantics; no delivered receipt is synthesized.
There is only import-order normalization outside the Activity branch.

## Offline evidence

- **67 pure tests passed** (9 new + 58 existing), candidate workflow module only,
  DB / Temporal / checkpoint environment removed. Existing scope:
  `tests/dingtalk/test_fence.py`, `test_channel.py`, `test_official.py`.
- Explicit `ruff check --config pdos-next/ruff.toml` passed on all 3 files.
- 1 new native PG case collected without DB variables; no PG execution here.

New pure tests prove rollback precedes dispatcher proof, exact SQL/message/state
matching, UUID proof requirement, unrelated SQL errors remain errors, no revoked
service metadata write, and the normal app-disable cancelled result is unchanged.

## Root-run native PG draft

`test_service_loss_pg.py` uses the original fresh tenant/channel fixtures and real
native application API, binding nonce/finish, verified synthetic inbound Message,
native Run, original registered deterministic graph and original reserve/send UOWs.
After a real reservation commits `sending` + P26, synchronization pauses only the
entry to the real send_reserved implementation. An isolated admin fixture holds
the actual Application row. The real helper waits on that lock; the test then
revokes only the already-existing **synthetic service Principal authorization
fixture** and commits, causing the actual post-wait service check to emit 42501.
This authorization fixture update is not claimed as a separate product admin API.
No Artifact, model result, Message, Run, delivery history or transport result is
fabricated.

The case checks the real SQLSTATE/primary message, cancelled native Message/Run,
same cancel_epoch on replay, zero model/tool calls, zero sends/lookups, no receipt,
and byte-equivalent original sending journal fields / one attempt. The app remains
active, distinguishing this branch from normal application disable. It never calls
send again after cancellation.

Run alongside the existing native `tests/dingtalk/test_fence_pg.py` (send wins the
native revoke/admin lock; wrong actor/tenant retain raw42501) and the root-selected
channel/official/Temporal recovery group (pending/unknown are lookup-only).
The initial actual SQL-loss race, full Temporal run and this candidate's production
acceptance remain pending root execution.
