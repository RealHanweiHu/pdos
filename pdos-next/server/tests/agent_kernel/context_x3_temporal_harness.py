"""Actual HTTP/Temporal harness, with a narrow *existing* READ test surface.

No production registry, SYSTEM_BASE, tool permissions or domain handler changes.
The capacity decorator first executes the real RLS reader on every call/recheck.
"""

import asyncio
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from langgraph.checkpoint.postgres import PostgresSaver
from temporalio.client import Client
from temporalio.worker import Worker

from pdos_next.agent_kernel.activities import KernelActivities, configure_agent_kernel
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.context_budget import segments
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.temporal_port import TemporalPort
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.api import create_app
from pdos_next.enterprise_search.assistant_graph import AssistantExtractGraph
from pdos_next.models import Receipt
from pdos_next.providers.types import ProviderUsage
from pdos_next.service import receipt_view
from pdos_next.workflows.checkpoints import verified_checkpoint_url
from pdos_next.workflows.xiaopai import XiaopaiWork
from tests.agent_kernel.context_x3_capacity import capacity_result, registry
from tests.agent_kernel.test_model_configuration_transactions import configured, submit
from tests.enterprise_search.test_assistant_pg import SyntheticClient


def values(messages):
    for message in messages:
        try:
            value = json.loads(message.get('content') or '{}')
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            yield message, value


async def question_ready(runtime, identity, *, question_id='context_resume'):
    """Drain the real ascending event pages, then require the persisted wait.

    Run status is current, while events(after=0) is only its oldest first page.
    A long run can already be waiting with needs_input after sequence 50.
    Conversely, graph emits needs_input before the Activity commits waiting_input.
    Neither event alone nor status alone proves the durable clarification wait.
    """
    async def wait():
        cursor, pending, recent_types = 0, None, []
        while True:
            response = await runtime.http.get(runtime.path + f'/{identity}/events',
                headers=runtime.person.headers, params={'after': cursor, 'page_size': 50})
            assert response.status_code == 200, response.text
            data = response.json()
            items, status = data['items'], data['status']
            diagnostic = {'status': status, 'after': cursor,
                          'next_cursor': data['next_cursor'], 'recent_types': recent_types[-8:]}
            assert status not in {'failed', 'partial', 'completed', 'cancelled'}, diagnostic
            sequences = [row['sequence'] for row in items]
            assert sequences == sorted(set(sequences)), diagnostic
            assert all(type(number) is int and number > cursor for number in sequences), diagnostic
            expected_cursor = sequences[-1] if sequences else cursor
            assert data['next_cursor'] == expected_cursor, diagnostic
            for row in items:
                event = row['event']
                recent_types.append(event['type'])
                if event['type'] == 'needs_input':
                    ids = [question['id'] for question in event['questions']]
                    pending = event if question_id in ids else None
                elif event['type'] == 'model_unavailable':
                    pending = None
            cursor = expected_cursor
            if len(items) == 50:
                continue  # More committed events may exist; do not reread page one.
            if status == 'waiting_input' and pending is not None:
                return pending
            if status == 'waiting_input':
                raise AssertionError({**diagnostic, 'after': cursor,
                    'recent_types': recent_types[-8:],
                    'reason': 'durable wait has no matching clarification event'})
            await asyncio.sleep(.2)
    return await asyncio.wait_for(wait(), 90)


class LongRunClient:
    """Offline provider; every tool is dispatched by the actual registered graph."""

    def __init__(self, *, recovery=False):
        self.recovery = recovery
        self.child = SyntheticClient()
        self.main_messages, self.main_calls, self.phase = [], 0, 0
        self.read_handle = None

    def close(self):
        pass

    def turn(self, route, **kwargs):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        assert in_registered_agent_graph()
        names = {item['name'] for item in kwargs['tools']}
        if names == {'assistant.passage.read', 'result.read'}:
            return self.child.turn(route, **kwargs)
        assert names == {item['name'] for item in registry().definitions()}
        messages = kwargs['messages']
        self.main_messages.append(deepcopy(messages))
        self.main_calls += 1
        # Explicit synthetic usage, not a claim of real tokenizer measurement.
        estimated = segments(kwargs['system'], kwargs['tools'], messages,
                             kwargs.get('output_schema'))['estimated_total']
        usage = ProviderUsage(estimated, 64)
        tool_values = [value for row, value in values(messages) if row['role'] == 'tool']

        def calls(items):
            return ModelTurn(calls=tuple(ToolCall(id='capacity-' + str(uuid4()), name=name,
                                                 arguments=arguments)
                                         for name, arguments in items), usage=usage)

        def complete(status='completed', questions=()):
            ids = list(dict.fromkeys(row['citation_id'] for value in tool_values
                                    for row in value.get('rows', [])))
            assert ids, 'Use actual verified extracted rows, never invented evidence'
            return ModelTurn(structured={
                'status': status, 'summary': '措施为更换密封圈，依据与回执保持可核对。',
                'result': {'assistant': {'citation_ids': ids, 'unknowns': []}},
                'questions': list(questions), 'unfinished': [],
            }, usage=usage)

        if self.recovery:
            answers = [value['answers'] for _row, value in values(messages) if 'answers' in value]
            assert answers and '继续' in json.dumps(answers, ensure_ascii=False)
            assert any(value.get('omitted') for value in tool_values)
            return complete()
        phase, self.phase = self.phase, self.phase + 1
        if phase == 0:
            return calls([
                ('category.read', {}), ('assistant.search', {'query': '漏气容量验证'}),
                ('category.parameters.list', {'parameter_ids': [], 'cursor': 'bad-cursor'}),
            ])
        if phase == 1:
            found = next(value['items'] for value in tool_values
                         if value.get('items') and 'citation_id' in value['items'][0])
            assert len(found) == 1
            return calls([('assistant.extract', {'citation_ids': [found[0]['citation_id']]})])
        if phase in {2, 3, 5}:
            offset = {2: 1, 3: 4, 5: 7}[phase]
            return calls([('category.parameters.list', {'parameter_ids': [], 'page_size': number})
                          for number in range(offset, offset + 3)])
        if phase == 4:
            omitted = [value for value in tool_values if value.get('omitted')]
            assert omitted, 'The real Host must already have performed cleanup'
            self.read_handle = omitted[0]['result_handle']
            return calls([('result.read', {'handle': self.read_handle, 'page': 1})])
        assert phase == 6
        return complete('needs_input', [{
            'id': 'context_resume', 'question': '是否继续核对已保存结果？',
            'why': '合成恢复检查点；不批准任何业务动作。', 'options': [],
            'recommended': None, 'allow_free_text': True, 'depends_on': [],
        }])


@asynccontextmanager
async def actual_runtime(person, provider, receipt_id, monkeypatch):
    """No fake Store, MemorySaver, direct graph.invoke or direct AI business write."""
    address = os.environ['PDOS_TEMPORAL_ADDRESS']
    endpoint = urlsplit('//' + address)
    assert endpoint.hostname in {'127.0.0.1', 'localhost', '::1'} and endpoint.port
    checkpoint_url = os.environ['PDOS_CHECKPOINT_DATABASE_URL']
    checkpoint = verified_checkpoint_url(checkpoint_url)  # Existing independent DB guard.
    management, runtime, command = configured(person)
    try:
        command['payload']['metadata']['context_window_tokens'] = 32_000
        command['payload']['metadata']['max_output_tokens'] = 1_024
        saved, _ = submit(person, management, command)
        assert saved.status_code == 200, saved.text
        runtime = replace(runtime, provider_client=provider, preload=lambda _: ())
        bootstrap = Bootstrap(person.engine, ports=runtime)
        adapters = bootstrap.adapters()
        readers = dict(adapters.read_tools)
        source_calls = Counter()
        parameters, category = readers['category.parameters.list'], readers['category.read']

        def bounded_parameters(scope, arguments):
            source_calls['parameters', json.dumps(arguments, sort_keys=True)] += 1
            actual = parameters(scope, arguments)  # First: real schema, RLS and current access.
            return capacity_result(arguments['page_size'], actual)

        def category_and_prior_receipt(scope, arguments):
            source_calls['category', '{}'] += 1
            actual = category(scope, arguments)  # First: real RLS category reader.
            with bootstrap.store.transaction(scope) as (session, _run):
                receipt = session.get(Receipt, receipt_id)
                assert receipt and receipt.requester_id == scope.requester_id
                assert receipt.operation == 'evidence.artifact.register'
                actual['prior_human_receipt'] = receipt_view(receipt)
            return actual

        readers.update({'category.parameters.list': bounded_parameters,
                        'category.read': category_and_prior_receipt})
        resumable = dict(adapters.read_resumes)
        for tool in ('assistant.search', 'assistant.extract'):
            original = resumable[tool]

            def observed(scope, arguments, *, intent_key, tool=tool, original=original):
                source_calls['resumable', tool] += 1
                return original(scope, arguments, intent_key=intent_key)

            resumable[tool] = observed
        adapters = replace(adapters, read_tools=readers, tool_registry=registry(),
                           read_resumes=resumable,
                           cost_required=False,
                           provider_for=lambda *_: 'synthetic-assistant-no-egress')
        bootstrap._assistant_adapter.graph = AssistantExtractGraph(
            BoundHost(bootstrap.store, adapters), bootstrap._assistant_adapter,
            checkpointer_factory=lambda: PostgresSaver.from_conn_string(checkpoint),
        )
        monkeypatch.setattr(person.engine, '_pdos_agent_kernel_adapters', None, raising=False)
        configure_agent_kernel(person.engine, adapters)
        temporal = await Client.connect(address, namespace=os.environ['PDOS_TEMPORAL_NAMESPACE'])
        assert await temporal.service_client.check_health()
        port = TemporalPort(temporal, task_queue='context-cleanup-offline-' + str(uuid4()))
        ports = bootstrap.api_ports(port)

        def binding(*args):
            value = bootstrap.binding_for(*args)
            value.token_limit = 2_000_000
            return value

        app = create_app(person.engine, person.auth, agent_runtime_ports=runtime,
                         agent_api_ports=replace(ports, binding_for=binding))

        @asynccontextmanager
        async def worker(*, next_provider=None):
            if next_provider is not None:
                configure_agent_kernel(person.engine, replace(
                    adapters, provider_client=next_provider,
                ))
            activities = KernelActivities(person.engine, checkpoint_url=checkpoint_url,
                                          technical_engine=person.dispatch)
            with ThreadPoolExecutor(max_workers=2) as executor:
                async with Worker(temporal, task_queue=port.task_queue, workflows=[XiaopaiWork],
                                  activities=[activities.advance, activities.reconcile],
                                  activity_executor=executor):
                    yield

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url='http://synthetic.local') as http:
            yield SimpleNamespace(http=http, temporal=temporal, provider=provider, person=person,
                                  bootstrap=bootstrap, worker=worker, checkpoint=checkpoint,
                                  source_calls=source_calls,
                                  path=f'/v1/categories/{person.category}/agent-runs')
    finally:
        management.close()
