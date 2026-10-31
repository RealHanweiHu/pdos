"""Capacity arithmetic and safety of the test-only restricted registered face."""

import json
import math
from types import SimpleNamespace

import pytest
from pdos_next.agent_kernel.context_runtime import progress_message, protected_result
from tests.agent_kernel.context_x3_capacity import (
    ROUTE,
    SCHEMA,
    TOOLS,
    batch,
    capacity_result,
    compact_for_sizing,
    first_messages,
    protected_controls,
    registry,
    sizing_plan,
)

from pdos_next.agent_kernel.context_budget import fit_messages
from pdos_next.agent_kernel.disclosure import disclosure
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.result_continuation import page_view
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.errors import DomainError


def test_restricted_face_reuses_exact_existing_read_specs_and_fixed_system():
    original, restricted = default_registry(), registry()
    assert {item['name'] for item in restricted.definitions()} == set(TOOLS) - {
        'assistant.passage.read',
    }
    for name in TOOLS:
        assert restricted.get(name) == original.get(name)
        assert restricted.get(name).tier == 'READ'
    assert AgentKernel(None, restricted).system == AgentKernel(None, original).system


def test_capacity_is_bounded_ordinary_transport_not_evidence_or_business_facts():
    native = {'items': [], 'next_cursor': None, 'as_of': 'volatile transport timestamp'}
    result = capacity_result(1, native)
    assert native['as_of'] == 'volatile transport timestamp'
    assert 'as_of' not in result and not protected_result('category.parameters.list', result)
    assert result['synthetic_capacity']['purpose'] == 'context-cleanup-test-only'
    with pytest.raises(AssertionError):
        capacity_result(1, {'items': [{'id': 'must-not-hide-real-data'}], 'next_cursor': None})


def test_32k_actual_meter_crosses_focus_then_cleans_at_least_20_percent():
    plan = sizing_plan()
    assert not plan['fixed']['over_focus'] and not plan['after_first']['over_focus']
    assert plan['after_second']['over_focus']
    fitted, cleanup = plan['fitted'], plan['fitted']['cleanup']
    assert fitted['window'] == 32_000 and not fitted['over_focus']
    assert cleanup['triggered'] and cleanup['applied']
    assert cleanup['saved_tokens'] >= math.ceil(.2 * fitted['focus'])
    assert 2 <= cleanup['replaced_results'] <= 3
    # Successful cleanup stops while traversing older results; the entire newer
    # batch is still retained and the public metric must report all three.
    assert cleanup['retained_latest_results'] == 3
    original = {row['tool_call_id']: json.loads(row['content']) for row in plan['original']
                if row['role'] == 'tool'}
    reduced = {row['tool_call_id']: json.loads(row['content']) for row in plan['reduced']
               if row['role'] == 'tool'}
    for index, (name, value) in enumerate(protected_controls()):
        assert protected_result(name, value)
        assert reduced[f'plan-0-{index}'] == original[f'plan-0-{index}']
    for index in range(3):
        assert reduced[f'plan-2-{index}'] == original[f'plan-2-{index}']
    omitted = [reduced[f'plan-1-{index}'] for index in range(3)
               if reduced[f'plan-1-{index}'].get('omitted')]
    assert len(omitted) >= 2
    assert all(value['read_more']['tool'] == 'result.read' for value in omitted)


@pytest.mark.parametrize('window', [None, 32_000])
def test_unchanged_full_production_face_still_rejects_32k_before_provider(window):
    full = default_registry()
    route = SimpleNamespace(context_window_tokens=window, max_output_tokens=ROUTE.max_output_tokens)
    with pytest.raises(DomainError) as caught:
        fit_messages(route, AgentKernel(None, full).system, disclosure(full, 'main', ()),
                     first_messages(), SCHEMA, allow_envelope=True)
    assert caught.value.reason == 'CONTEXT_INCOMPLETE'
    assert caught.value.detail['context_budget']['fixed_admission_tokens'] > (
        caught.value.detail['context_budget']['focus']
    )
    assert caught.value.detail['reason_key'] == 'fixed_context_exceeds_window'
    assert caught.value.detail['context_budget']['window_configured'] == (window is not None)


def test_real_page_framing_progress_and_third_batch_fit_without_losing_prior_omissions():
    plan = sizing_plan()
    selected, messages = registry(), plan['reduced']
    old_omissions = {row['tool_call_id']: row['content'] for row in messages
                     if row['role'] == 'tool' and json.loads(row['content']).get('omitted')}
    first = next(json.loads(row['content']) for row in messages if row['role'] == 'tool'
                 and json.loads(row['content']).get('omitted'))
    raw = capacity_result(1, {'items': [], 'next_cursor': None})
    page = page_view(raw, first['result_handle'], 1, 3_936)
    assert page['total_pages'] == 1 and json.loads(page['preview']) == raw
    messages.append(progress_message(messages=messages, goal='继续核对', turn=4,
                                      tools_used=9, model_limit=12, tool_limit=40))
    messages = batch(messages, [('result.read', page)], number=3)
    messages.append(progress_message(messages=messages, goal='继续核对', turn=5,
                                      tools_used=10, model_limit=12, tool_limit=40))
    system = AgentKernel(None, selected).system
    messages, _ = fit_messages(ROUTE, system, selected.definitions(), messages, SCHEMA,
                               compact_tool=compact_for_sizing, allow_envelope=True)
    messages = batch(messages, [('category.parameters.list', capacity_result(number, {
        'items': [], 'next_cursor': None,
    })) for number in range(7, 10)], number=4)
    messages.append(progress_message(messages=messages, goal='继续核对', turn=6,
                                      tools_used=13, model_limit=12, tool_limit=40))
    messages, budget = fit_messages(ROUTE, system, selected.definitions(), messages, SCHEMA,
                                    compact_tool=compact_for_sizing, allow_envelope=True)
    assert not budget['over_focus'] and budget['cleanup']['applied']
    assert budget['cleanup']['saved_tokens'] >= math.ceil(.2 * budget['focus'])
    assert budget['cleanup']['retained_latest_results'] == 3
    final = {row['tool_call_id']: row['content'] for row in messages if row['role'] == 'tool'}
    for identity, content in old_omissions.items():
        assert final[identity] == content
