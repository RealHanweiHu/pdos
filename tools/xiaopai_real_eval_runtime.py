"""Local real-provider evaluation composition; unchanged HTTP/Temporal/kernel owners."""

import argparse
import asyncio
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
TENANT = UUID('78340ac0-57c2-4235-87c6-a468dd3d8173')
CURRENT = ContextVar('real_eval_scope', default=None)
SAMPLE = ContextVar('real_eval_usage_sample', default=None)
WRITE_LOCK = threading.Lock()


def append_json(path, value):
    with WRITE_LOCK, path.open('a') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, default=str) + '\n')


def observe_domain_errors(evidence):
    """Record the original reason behind collapsed public codes; behaviour unchanged."""
    import sys

    from pdos_next.errors import DomainError

    original = DomainError.__init__

    def init(self, code, message, *args, **kwargs):
        original(self, code, message, *args, **kwargs)
        frames, run_id, frame = [], None, sys._getframe(1)
        while frame is not None and len(frames) < 8:
            name = frame.f_code.co_filename
            if '/pdos_next/' in name:
                frames.append(f"{name.split('/pdos_next/')[-1]}:{frame.f_lineno}:{frame.f_code.co_name}")
            if run_id is None:
                run_id = getattr(frame.f_locals.get('scope'), 'run_id', None)
            frame = frame.f_back
        append_json(evidence / 'domain-errors.jsonl', {
            'at': datetime.now(UTC).isoformat(), 'run_id': str(run_id) if run_id else None,
            'code': self.code, 'reason': self.reason, 'message': self.message, 'frames': frames,
        })

    DomainError.__init__ = init


def observe_provider(evidence):
    from pdos_next.agent.kernel.gateway import AgentGateway
    from pdos_next.providers import agent_client

    original_gateway = AgentGateway.turn
    original_parse = agent_client.parse_turn

    def gateway(self, scope, *args, **kwargs):
        token = CURRENT.set(scope)
        try:
            return original_gateway(self, scope, *args, **kwargs)
        except Exception as error:
            diag = getattr(getattr(error, 'orig', None), 'diag', None)
            if diag is not None:
                append_json(evidence / 'database-failures.jsonl', {
                    'run_id': str(scope.run_id), 'error_type': type(error).__name__,
                    **{key:getattr(diag,key,None) for key in (
                        'sqlstate','message_primary','table_name','constraint_name')},
                })
            raise
        finally:
            CURRENT.reset(token)

    def parse(body, route, request_id=None):
        slot = SAMPLE.get()
        if slot is not None:
            from hashlib import sha256

            payload = json.dumps(body,ensure_ascii=False,default=str).encode()
            fingerprint = sha256(payload).hexdigest()
            folder = ROOT / '.local/real-eval-20261101/wire'
            folder.mkdir(mode=0o700,parents=True,exist_ok=True)
            path = folder/(fingerprint+'.response.json')
            path.write_bytes(payload)
            path.chmod(0o600)
            slot['private_response_path'] = str(path.relative_to(ROOT))
            slot['response_sha256'] = fingerprint
            slot['raw_usage'] = deepcopy(body.get('usage'))
            slot['body_request_id'] = body.get('id')
            slot['header_request_id'] = request_id
        return original_parse(body, route, request_id=request_id)

    class ObservedClient(agent_client.AgentProviderClient):
        def __init__(self):
            super().__init__()
            self.client.event_hooks['request'].append(self.capture_request)

        @staticmethod
        def capture_request(request):
            from hashlib import sha256

            slot = SAMPLE.get()
            if slot is None:
                return
            payload = request.content
            fingerprint = sha256(payload).hexdigest()
            folder = ROOT / '.local/real-eval-20261101/wire'
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = folder / (fingerprint + '.json')
            if not path.exists():
                path.write_bytes(payload)
                path.chmod(0o600)
            slot.update(request_body_sha256=fingerprint,request_bytes=len(payload),
                        private_request_path=str(path.relative_to(ROOT)))

        def close(self):
            # The runtime owns this shared observation client. Activity host
            # teardown must not close it while another Activity may use it.
            pass

        def shutdown(self):
            super().close()

        def turn(self, route, **kwargs):
            scope = CURRENT.get()
            sample = {'started_at': datetime.now(UTC).isoformat(),
                      'run_id': str(scope.run_id) if scope else None,
                      'isolation': scope.isolation if scope else None,
                      'protocol': route.protocol, 'route_digest': route.digest}
            token = SAMPLE.set(sample)
            started = time.monotonic()
            try:
                result = super().turn(route, **kwargs)
                sample['request_id'] = result.request_id
                sample['normalized_usage'] = {key: getattr(result.usage, key) for key in (
                    'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_creation_tokens')}
                sample['public_turn'] = {'text':result.text, 'structured':result.structured,
                    'calls':[call.model_dump(mode='json') for call in result.calls]}
                sample['outcome'] = 'returned'
                return result
            except BaseException as error:
                sample['outcome'] = 'error'
                sample['error_type'] = type(error).__name__
                sample['provider_error_code'] = getattr(error,'code',None)
                sample['provider_error_unknown'] = getattr(error,'unknown',None)
                sample['request_id'] = getattr(error, 'request_id', None)
                raise
            finally:
                sample['elapsed_ms'] = (time.monotonic() - started) * 1000
                sample['finished_at'] = datetime.now(UTC).isoformat()
                append_json(evidence / 'provider-observations.jsonl', sample)
                SAMPLE.reset(token)

    AgentGateway.turn = gateway
    agent_client.parse_turn = parse
    return ObservedClient()


async def serve(args):
    import local_environment as local
    import uvicorn
    from pdos_next.core.database import engine_for
    from pdos_next.workflows.checkpoints import verified_checkpoint_url
    from sqlalchemy.engine import make_url
    from temporalio.client import Client
    from temporalio.worker import Worker

    local.STATE = ROOT / '.local/comprehensive-runtime-20261022.json'
    state = local.verified(local.read_state())
    assert state['marker'] == 'c351c0ca-b874-49b9-bf1b-44c3ad150aaf'
    os.environ.update(local.environment(state))
    os.environ.update(PDOS_STATE_DB_PORT=str(state['port']),
                      PDOS_STATE_DB_MARKER=state['marker'],
                      PDOS_TENANT_RUNTIME_CONFIG=str(ROOT / '.local/comprehensive-minimax-20261023.json'),
                      PDOS_ENVIRONMENT='development')
    checkpoint_source = make_url(state['m3_checkpoint_url']).set(drivername='postgresql+psycopg')
    checkpoint = checkpoint_source.render_as_string(hide_password=False)
    verified_checkpoint_url(checkpoint)
    args.evidence.mkdir(parents=True, exist_ok=True)
    client = await asyncio.wait_for(Client.connect(args.temporal, namespace=args.namespace), 10)
    engine, auth, dispatch = (engine_for(state[key]) for key in ('app_url','auth_url','dispatch_url'))
    from pdos_next.agent.kernel.activities import KernelActivities, configure_agent_kernel
    from pdos_next.agent.kernel.bootstrap import Bootstrap
    from pdos_next.agent.kernel.temporal_port import TemporalPort
    from pdos_next.agent.model_configuration.host import runtime_ports
    from pdos_next.api import create_app
    from pdos_next.workflows.xiaopai import XiaopaiWork

    observe_domain_errors(args.evidence)
    provider = observe_provider(args.evidence)
    ports = replace(runtime_ports(engine), provider_client=provider)
    bootstrap = Bootstrap(engine, ports=ports)
    configure_agent_kernel(engine, bootstrap.adapters())
    activities = KernelActivities(engine, checkpoint_url=checkpoint, technical_engine=dispatch)
    queue = args.queue
    temporal = TemporalPort(client, task_queue=queue)
    app = create_app(engine, auth, workflow_enabled=True, agent_runtime_ports=ports,
                     agent_api_ports=bootstrap.api_ports(temporal))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    config = uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning', access_log=False)
    server = uvicorn.Server(config)
    from contextlib import AsyncExitStack

    # role 'api' / 'worker' mirror production, where the API and the Temporal worker are
    # separate processes; 'both' is the original single-process composition.
    async with AsyncExitStack() as stack:
        if args.role in ('both', 'worker'):
            executor = stack.enter_context(ThreadPoolExecutor(max_workers=4))
            await stack.enter_async_context(Worker(
                client, task_queue=queue, workflows=[XiaopaiWork],
                activities=[activities.advance, activities.reconcile],
                activity_executor=executor, max_concurrent_activities=2))
        public = {'role':args.role, 'task_queue':queue, 'temporal':args.temporal,
                  'namespace':args.namespace, 'database':'pdos_test',
                  'database_port':state['port'], 'marker':state['marker'],
                  'tenant_id':str(TENANT), 'pid':os.getpid(),
                  'runtime_config':'comprehensive-minimax-20261023.json',
                  'provider_observer':'transparent parse_turn usage-only; unchanged request/response',
                  'started_at':datetime.now(UTC).isoformat()}
        if args.role in ('both', 'api'):
            task = asyncio.create_task(server.serve())
            for _ in range(100):
                if server.started:
                    break
                if task.done():
                    await task
                await asyncio.sleep(.1)
            if not server.started:
                raise RuntimeError('Evaluation API did not start')
            public.update(api_port=port, api_base=f'http://127.0.0.1:{port}')
        else:
            task = asyncio.create_task(asyncio.Event().wait())
        (args.evidence / 'runtime.json').write_text(json.dumps(public,indent=2)+'\n')
        print(json.dumps(public), flush=True)
        try:
            await task
        finally:
            server.should_exit = True
            provider.shutdown()
            for item in (engine,auth,dispatch):
                item.dispose()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--temporal',default='127.0.0.1:58708')
    parser.add_argument('--namespace',default='pdos-next')
    parser.add_argument('--queue',default='pdos-real-eval-20261101')
    parser.add_argument('--role',choices=['both','api','worker'],default='both')
    asyncio.run(serve(parser.parse_args()))
