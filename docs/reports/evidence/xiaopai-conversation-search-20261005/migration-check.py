import json
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
url="postgresql+psycopg://pdos_test:synthetic-chat-search-only@127.0.0.1:49458/pdos_test"
engine=create_engine(url)
config=Config("alembic.ini")
with engine.connect() as c:
    before=c.execute(text("SELECT count(*) FROM cehub_evidence.evidence_snapshots")).scalar_one()
    before_guard=c.execute(text("SELECT pg_get_functiondef('cehub_ai.require_application_tool_observation()'::regprocedure)")).scalar_one()
command.downgrade(config,"0422_research_index_documents")
with engine.connect() as c:
    prior=c.execute(text("SELECT pg_get_functiondef('cehub_ai.require_application_tool_observation()'::regprocedure)")).scalar_one()
    assert "conversation.search_public" not in prior
    assert "discussion.convene" in prior and "quality.prepare_capa" in prior
command.upgrade(config,"head")
with engine.connect() as c:
    after=c.execute(text("SELECT count(*) FROM cehub_evidence.evidence_snapshots")).scalar_one()
    after_guard=c.execute(text("SELECT pg_get_functiondef('cehub_ai.require_application_tool_observation()'::regprocedure)")).scalar_one()
    head=c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert before==after and before_guard==after_guard
    protected={name:not c.execute(text("SELECT has_table_privilege('pdos_agent',:name,'INSERT')"),dict(name=name)).scalar_one() for name in ["cehub_evidence.evidence_snapshots","cehub_evidence.research_sources","cehub_ai.conversations"]}
    assert all(protected.values())
print(json.dumps(dict(head=head,snapshot_count_preserved=before,guard_roundtrip_identical=True,agent_zero_direct_insert=protected),ensure_ascii=False))
engine.dispose()
