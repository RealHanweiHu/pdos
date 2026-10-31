"""Event API pagination/state ordering regressions; no Store or database involved."""

import asyncio
from types import SimpleNamespace

import pytest

from tests.agent_kernel.context_x3_temporal_harness import question_ready


def event(number, kind='context_observed'):
    body = {'type': kind}
    if kind == 'needs_input':
        body['questions'] = [{'id': 'context_resume'}]
    return {'sequence': number, 'event': body}


def runtime(pages):
    class Http:
        def __init__(self):
            self.requests = []

        async def get(self, path, *, headers, params):
            self.requests.append((path, headers, params.copy()))
            assert pages, 'Do not poll page one or silently hide a failed durable wait'
            page = pages.pop(0)
            return SimpleNamespace(status_code=200, text='synthetic event page', json=lambda: page)

    return SimpleNamespace(http=Http(), path='/existing/agent-runs',
                           person=SimpleNamespace(headers={'Authorization': 'Bearer synthetic'}))


def test_current_wait_status_with_clarification_after_first_50_events_uses_real_cursor():
    expected = event(58, 'needs_input')
    ports = runtime([
        {'status': 'waiting_input', 'items': [event(n) for n in range(1, 51)], 'next_cursor': 50},
        {'status': 'waiting_input', 'items': [*[event(n) for n in range(51, 58)], expected],
         'next_cursor': 58},
    ])
    assert asyncio.run(question_ready(ports, 'run')) == expected['event']
    assert [request[2]['after'] for request in ports.http.requests] == [0, 50]


def test_graph_event_can_precede_activity_committing_wait_state():
    expected = event(1, 'needs_input')
    ports = runtime([
        {'status': 'running', 'items': [expected], 'next_cursor': 1},
        {'status': 'waiting_input', 'items': [], 'next_cursor': 1},
    ])
    assert asyncio.run(question_ready(ports, 'run')) == expected['event']
    assert [request[2]['after'] for request in ports.http.requests] == [0, 1]


def test_real_model_unavailable_wait_is_an_explicit_failure_not_a_clarification():
    ports = runtime([{'status': 'waiting_input', 'items': [event(1, 'model_unavailable')],
                      'next_cursor': 1}])
    with pytest.raises(AssertionError, match='model_unavailable'):
        asyncio.run(question_ready(ports, 'run'))
    assert len(ports.http.requests) == 1


@pytest.mark.parametrize('status', ['failed', 'partial', 'completed', 'cancelled'])
def test_terminal_run_does_not_reuse_a_historical_question(status):
    ports = runtime([{'status': status, 'items': [event(1, 'needs_input')], 'next_cursor': 1}])
    with pytest.raises(AssertionError, match=status):
        asyncio.run(question_ready(ports, 'run'))


def test_invalid_cursor_cannot_create_a_successful_wait():
    ports = runtime([{'status': 'waiting_input', 'items': [event(1, 'needs_input')],
                      'next_cursor': 0}])
    with pytest.raises(AssertionError):
        asyncio.run(question_ready(ports, 'run'))
