import json
from pathlib import Path
from uuid import UUID
from sqlalchemy import select
from app.ai.research_search import LocalIndexSearchProvider
from app.db.schema import tables
from app.domain.research_crawler import ResearchCrawlerWorker
from app.domain.research_search import resolve_search_provider
from tests.test_test_runs_api import Scope, client, isolated_test_run_database
from tests.test_product_discovery_findings_api import seed_discovery
from tests.test_research_crawl_local_index import Pages, patch_reach, setup_source_and_subscription, crawl_until_idle

def test_retrieval_limits_are_reproduced(client, isolated_test_run_database, monkeypatch):
    scope=Scope(client, isolated_test_run_database)
    try:
        seed=seed_discovery(client, scope)
        patch_reach(monkeypatch, Pages())
        setup_source_and_subscription(client, scope, seed, 'https://example.com/docs')
        crawl_until_idle(ResearchCrawlerWorker(scope.engine, enabled=True, max_frontier=50))
        provider=resolve_search_provider(scope.engine, endpoint='https://search.example.test', tenant_id=scope.tenant_id, space_id=scope_id(seed), line_id=line_id(seed))
        assert isinstance(provider, LocalIndexSearchProvider)
        keyword=provider.search('无刷电机 峰值压力',language='auto',time_range=None,limit=5)
        natural=provider.search('帮我搜索无刷电机的峰值压力',language='auto',time_range=None,limit=5)
        no_hit=provider.search('量子电池',language='auto',time_range=None,limit=5)
        assert keyword.status=='completed' and len(keyword.hits)==1
        assert natural.status=='no_results'
        assert no_hit.status=='no_results'
        with scope.engine.begin() as c:
            ids=list(c.execute(select(tables.research_index_documents.c.snapshot_id).where(tables.research_index_documents.c.tenant_id==scope.tenant_id)).scalars())
            assert len(ids)>1
            c.execute(tables.research_index_documents.delete().where(tables.research_index_documents.c.tenant_id==scope.tenant_id, tables.research_index_documents.c.snapshot_id!=ids[0]))
            c.execute(tables.evidence_snapshots.update().where(tables.evidence_snapshots.c.id==ids[0]).values(superseded_by_id=ids[1]))
        stale=resolve_search_provider(scope.engine,endpoint='https://search.example.test',tenant_id=scope.tenant_id,space_id=scope_id(seed),line_id=line_id(seed))
        assert isinstance(stale, LocalIndexSearchProvider) and stale.configured
        assert stale.search('无刷电机',language='auto',time_range=None,limit=5).status=='no_results'
        Path('../tmp/xiaopai-search-probe-20261005.json').write_text(json.dumps({'keyword_hits':len(keyword.hits),'natural_sentence_status':natural.status,'local_miss_status':no_hit.status,'configured_remote_ignored_when_local_exists':True,'only_superseded_document_still_marks_local_configured':True},ensure_ascii=False,indent=2)+'\n')
    finally:
        scope.dispose()

def scope_id(seed):
    return UUID(seed['base'].rsplit('/',1)[-1])

def line_id(seed):
    return UUID(seed['line']['id'])
