"""DRAFT actual 32k cleanup + Human wait + Worker replacement; root alone runs PG.

This is a restricted existing-tool surface capacity test. The full production
surface's 32k fixed-prefix rejection is intentionally preserved in the pure case.
"""

import asyncio
import json
import math
import os
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select

from pdos_next.agent_kernel.context_runtime import protected_result
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.agent_kernel.session_checkpoints import main_checkpoint_config
from pdos_next.database import tenant_session
from pdos_next.service import digest
from tests.agent_kernel.context_x3_capacity import CAPACITY_TOKENS
from tests.agent_kernel.context_x3_temporal_harness import (
    LongRunClient,
    actual_runtime,
    question_ready,
    values,
)
from tests.enterprise_search.test_retrieval_pg import index
from tests.enterprise_search.verification_action_harness import start
from tests.preproject.test_g0 import post, request

pytestmark = pytest.mark.skipif(
    not os.environ.get('TEST_DATABASE_URL')
    or not os.environ.get('PDOS_TEMPORAL_ADDRESS')
    or not os.environ.get('PDOS_CHECKPOINT_DATABASE_URL'),
    reason='Root-owned verified isolated PG/checkpoint/local Temporal environment required',
)


def actual_state(runtime, identity):
    """Read the real Run-scoped Postgres checkpoint; never a fake/memory Store."""
    person = runtime.person
    with tenant_session(person.engine, person.tenant, actor_id=person.human,
                        category_id=person.category) as session:
        run = session.get(AgentRun, identity)
        assert run and run.requester_id == person.human
        writer, layout = run.writer_id, run.versions.get('checkpoint_layout')
    scope = runtime.bootstrap.store.scope(
        tenant_id=person.tenant, requester_id=person.human, writer_id=writer,
        category_id=person.category, run_id=identity,
    )
    with PostgresSaver.from_conn_string(runtime.checkpoint) as saver:
        saved = saver.get_tuple(main_checkpoint_config(scope, layout))
        assert saved is not None
        if layout:
            assert saved.metadata['pdos_run_id'] == str(identity)
        state = deepcopy(saved.checkpoint['channel_values'])
    assert state['run_id'] == str(identity)
    return state


def actual_ledger(runtime, identity):
    person = runtime.person
    with tenant_session(person.engine, person.tenant, actor_id=person.human,
                        category_id=person.category) as session:
        run = session.get(AgentRun, identity)
        calls = {str(row.id): {'tool': row.tool, 'state': row.state,
                              'result': deepcopy(row.result),
                              'binding': deepcopy(row.execution_binding)}
                 for row in session.scalars(select(AgentToolCall).where(
                     AgentToolCall.run_id == identity,
                 ))}
        events = [deepcopy(row.body) for row in session.scalars(select(AgentEvent).where(
            AgentEvent.run_id == identity,
        ).order_by(AgentEvent.sequence))]
        return calls, events, deepcopy(run.versions)


def tool_map(messages):
    return {row['tool_call_id']: value for row, value in values(messages) if row['role'] == 'tool'}


def assert_protected_survives(provider, state):
    before, after = {}, tool_map(state['messages'])
    names = {}
    for messages in provider.main_messages:
        for row in messages:
            names.update({call['id']: call['name'] for call in row.get('tool_calls', [])})
        for identity, value in tool_map(messages).items():
            before.setdefault(identity, value)
    protected = {identity: value for identity, value in before.items()
                 if protected_result(names[identity], value)}
    assert any(value.get('prior_human_receipt') for value in protected.values())
    assert any(value.get('rows') for value in protected.values())
    assert any(value.get('error') for value in protected.values())
    for identity, value in protected.items():
        # result.read ordinary fragment may later be reversibly omitted again;
        # actual evidence/receipt/error rows must remain byte-for-byte equivalent.
        if names[identity] != 'result.read':
            assert after[identity] == value


def assert_full_results(state, calls):
    capacities = [item for item in state['tool_results']
                  if item['value'].get('synthetic_capacity')]
    assert len(capacities) == 9
    assert {item['value']['synthetic_capacity']['number'] for item in capacities} == set(
        range(1, 10)
    )
    for item in capacities:
        value = item['value']
        assert value['synthetic_capacity']['body'] == '容' * CAPACITY_TOKENS
        raw = {key: child for key, child in value.items() if key != 'execution_ref'}
        row = calls[value['execution_ref']['call_id']]
        assert row['tool'] == 'category.parameters.list' and row['state'] == 'completed'
        assert row['result'] == raw  # Full durable original, not model placeholder.
    assert any(item['value'].get('prior_human_receipt') for item in state['tool_results'])
    assert any(item['value'].get('rows') for item in state['tool_results'])
    assert any(item['value'].get('error') for item in state['tool_results'])


def test_actual_http_temporal_32k_cleanup_preserves_ledger_then_worker_resume_does_not_regrow(
    setup, monkeypatch,
):
    registered = post(setup, request(setup, 'evidence.artifact.register', {
        'title': '漏气容量验证唯一合成记录', 'content': '漏气容量验证。措施：更换密封圈。',
        'source_label': 'context-cleanup-test-only', 'visibility': 'category',
    }))
    assert registered.status_code == 200, registered.text
    native_receipt = registered.json()
    assert native_receipt['operation'] == 'evidence.artifact.register'
    index(setup, UUID(native_receipt['subject_id']))
    provider = LongRunClient()

    async def scenario():
        async with actual_runtime(
            setup, provider, UUID(native_receipt['id']), monkeypatch,
        ) as runtime:
            payload = {'goal': '核对漏气容量验证中的密封圈措施，保留证据与回执后等待本人继续。',
                       'idempotency_key': str(uuid4())}
            async with runtime.worker():
                identity, handle = await start(runtime, payload, complete=False)
                event = await question_ready(runtime, identity)
                assert event['questions'][0]['id'] == 'context_resume'
                assert provider.main_calls == 7 and provider.child.child_calls == 2
                waiting = actual_state(runtime, identity)
                calls_before, events_before, versions_before = actual_ledger(runtime, identity)
                assert_full_results(waiting, calls_before)
                assert_protected_survives(provider, waiting)
                applied = [event for event in events_before if event['type'] == 'context_observed'
                           and event['isolation'] == 'main' and event['cleanup'].get('applied')]
                assert applied
                for metric in applied:
                    cleanup = metric['cleanup']
                    assert metric['window'] == 32_000 and not (
                        metric['admission_tokens'] > metric['focus']
                    )
                    assert cleanup['before_tokens'] > metric['focus']
                    assert cleanup['saved_tokens'] >= math.ceil(.2 * metric['focus'])
                assert versions_before['context_runtime_v1']['cleanup_count'] >= 1
                omitted_before = {key: value for key, value in tool_map(waiting['messages']).items()
                                  if value.get('omitted')}
                assert omitted_before and provider.read_handle
                pages = [value for _row, value in values(waiting['messages'])
                         if value.get('result_handle') == provider.read_handle
                         and value.get('format') == 'json_fragment' and value.get('preview')]
                # The explicit result.read must restore an actual source page.
                restored = [row for row in calls_before.values() if row['tool'] == 'result.read']
                assert len(restored) == 1 and restored[0]['state'] == 'completed'
                page = restored[0]['result']
                assert page['result_handle'] == provider.read_handle and page['total_pages'] == 1
                assert json.loads(page['preview'])['synthetic_capacity']['body'] == (
                    '容' * CAPACITY_TOKENS
                )
                # It is fine for a later cleanup to omit the restored model preview.
                assert pages or any(value.get('omitted')
                                    for value in tool_map(waiting['messages']).values())
                progress = [value for _row, value in values(waiting['messages'])
                            if value.get('type') == 'server_progress']
                assert {row['turn'] for row in progress} == {4, 5, 6}
                assert all(row['remaining_goal_quote'] in payload['goal'] for row in progress)
                assert all(row['source'] == 'runtime_state' and row['data_only']
                           for row in progress)
                before_io = runtime.source_calls.copy()
                assert before_io['resumable', 'assistant.search'] == 1
                assert before_io['resumable', 'assistant.extract'] == 1
                assert before_io['category', '{}'] == 1
                # Nine ordinary reads, one actual cursor error and one explicit revalidation.
                assert sum(count for (kind, _key), count in before_io.items()
                           if kind == 'parameters') == 11

            # A new Activity object and fresh provider cannot remember the old local phases.
            resumed_provider = LongRunClient(recovery=True)
            async with runtime.worker(next_provider=resumed_provider):
                answered = await runtime.http.post(runtime.path + f'/{identity}/answers',
                    headers=setup.headers, json={'answers': {'context_resume': '继续'},
                                                 'idempotency_key': str(uuid4())})
                assert answered.status_code == 202, answered.text
                outcome = await asyncio.wait_for(handle.result(), 90)
                assert outcome['status'] == 'completed', outcome
                assert resumed_provider.main_calls == 1 and resumed_provider.child.calls == 0
                assert runtime.source_calls == before_io
                finished = actual_state(runtime, identity)
                calls_after, events_after, _versions = actual_ledger(runtime, identity)
                assert_full_results(finished, calls_after)
                for call_id, row in calls_before.items():
                    assert digest(calls_after[call_id]) == digest(row)
                resumed_tools = tool_map(resumed_provider.main_messages[0])
                for key, value in omitted_before.items():
                    assert resumed_tools[key] == value  # No restoration/regrowth on resume.
                metrics = [event for event in events_after if event['type'] == 'context_observed']
                assert len({event['model_call_id'] for event in metrics}) == len(metrics)
                record = await runtime.http.get(runtime.path + f'/{identity}',
                                                headers=setup.headers)
                assert record.status_code == 200, record.text
                answer = record.json()['result']['result']['assistant']
                assert answer['lookup'] == 'cited' and answer['sources'][0]['quote'] == '更换密封圈'
                # Existing process pagination exposes metrics without returning source bodies.
                process = await runtime.http.get(
                    runtime.path + f'/{identity}/process?page_size=100', headers=setup.headers,
                )
                assert process.status_code == 200, process.text
                observed = [row['context_metrics'] for row in process.json()['steps']
                            if row.get('context_metrics')]
                assert any(row.get('cleanup', {}).get('applied') for row in observed)
                assert '容' * 100 not in process.text and '更换密封圈' not in process.text
                denied = await runtime.http.get(
                    runtime.path + f'/{identity}/process',
                    headers={'Authorization': 'Bearer ' + setup.tokens[setup.peer]},
                )
                assert denied.status_code == 403
                before_calls = resumed_provider.main_calls
                replay = await runtime.http.post(runtime.path, headers=setup.headers, json=payload)
                assert replay.status_code == 202 and replay.json()['run_id'] == str(identity)
                assert resumed_provider.main_calls == before_calls
                assert runtime.source_calls == before_io
                history = await handle.fetch_history()
                assert '容' * 100 not in str(history) and '更换密封圈' not in str(history)
                assert len([row for row in history.events
                            if row.HasField('activity_task_scheduled_event_attributes')]) == 2

    asyncio.run(scenario())
