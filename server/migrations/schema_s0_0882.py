"""Source use reads for named withdrawal (D310, P120): signed use and business dependents.

Assigned s0_0882 (down s0_0881) at the 11-11 integration; placeholder
s0_0873 (down s0_0872) in the D47 session (file, revision, down_revision,
this snapshot's name and the downgrade guard text moved together).
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

SCHEMA_SQL = (
    "CREATE FUNCTION public.d47_source_signed(t uuid, c uuid, p uuid, root uuid)\n RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $source_signed$\n WITH artifacts AS (\n  SELECT a.id FROM public.artifact_versions a WHERE a.tenant_id=t AND a.category_id=c\n   AND (a.id=root OR a.original_id=root) AND a.product_id IS NOT DISTINCT FROM p\n )\n SELECT category_access(t,c,false) AND (\n  EXISTS(SELECT 1 FROM public.definition_sources ds JOIN public.definition_revisions d\n   ON d.tenant_id=ds.tenant_id AND d.id=ds.definition_id\n   WHERE ds.tenant_id=t AND ds.category_id=c AND ds.artifact_id IN (SELECT id FROM artifacts)\n    AND (d.sealed OR d.status='published'))\n  OR EXISTS(SELECT 1 FROM public.claims cl WHERE cl.tenant_id=t AND cl.category_id=c\n   AND cl.artifact_id IN (SELECT id FROM artifacts) AND public.m3_evidence_signed_consumed(t,c,cl.id)))\n$source_signed$",
    'REVOKE ALL ON FUNCTION public.d47_source_signed(uuid,uuid,uuid,uuid) FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch',
    'GRANT EXECUTE ON FUNCTION public.d47_source_signed(uuid,uuid,uuid,uuid) TO pdos_next_app',
    "CREATE FUNCTION public.d47_source_dependents(t uuid, c uuid, p uuid, root uuid)\n RETURNS TABLE(table_name text, reference_count integer)\n LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $source_use$\nDECLARE graph jsonb[]='{}'; reached uuid[]; selected integer[]; node jsonb; links uuid[]; row_id uuid; i integer; changed boolean;\nBEGIN\n IF NOT category_access(t,c,false) THEN RETURN; END IF;\n IF NOT (\n  EXISTS(SELECT 1 FROM public.uploaded_originals WHERE tenant_id=t AND category_id=c AND id=root\n   AND product_id IS NOT DISTINCT FROM p AND (owner_id=scope_requester() OR visibility IN ('category','audience'))) OR\n  EXISTS(SELECT 1 FROM public.artifact_versions WHERE tenant_id=t AND category_id=c AND id=root\n   AND product_id IS NOT DISTINCT FROM p AND (owner_id=scope_requester() OR visibility IN ('category','audience')))\n ) THEN RETURN; END IF;\n SELECT coalesce(array_agg(jsonb_build_object('table',n.table_name,'id',n.node_id,'links',n.links)),'{}')\n  INTO graph FROM public.m3_lifecycle_nodes(t,c) n;\n reached=ARRAY[root]; selected='{}'; changed=true;\n WHILE changed LOOP\n  changed=false;\n  IF cardinality(graph)>0 THEN\n   FOR i IN 1..cardinality(graph) LOOP\n    IF i=ANY(selected) THEN CONTINUE; END IF;\n    node=graph[i]; row_id=(node->>'id')::uuid;\n    SELECT coalesce(array_agg(v::uuid),'{}') INTO links FROM jsonb_array_elements_text(node->'links') AS x(v);\n    IF row_id=root OR links && reached THEN\n     selected=array_append(selected,i);\n     IF row_id IS NOT NULL AND NOT row_id=ANY(reached) THEN reached=array_append(reached,row_id); END IF;\n     changed=true;\n    END IF;\n   END LOOP;\n  END IF;\n END LOOP;\n RETURN QUERY SELECT graph[k]->>'table', count(*)::integer FROM unnest(selected) AS u(k) GROUP BY 1 ORDER BY 1;\nEND\n$source_use$",
    'REVOKE ALL ON FUNCTION public.d47_source_dependents(uuid,uuid,uuid,uuid) FROM PUBLIC,pdos_agent,pdos_next_auth,pdos_next_dispatch',
    'GRANT EXECUTE ON FUNCTION public.d47_source_dependents(uuid,uuid,uuid,uuid) TO pdos_next_app',
)

DOWNGRADE_SQL = (
    'DROP FUNCTION public.d47_source_dependents(uuid,uuid,uuid,uuid)',
    'DROP FUNCTION public.d47_source_signed(uuid,uuid,uuid,uuid)',
)
