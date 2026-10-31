"""Current metadata shape; migration 0716 freezes its separate copy."""

SHAPE = """COALESCE(
  jsonb_typeof(execution_binding)='object'
  AND execution_binding->>'kind' IN ('unbound','read','model','domain_t0','embedding_query')
  AND (execution_binding->>'kind' NOT IN ('model','domain_t0') OR (
    execution_binding ?& ARRAY['model_version','model_route_digest',
      'tool_definitions_digest','cancel_epoch']
    AND jsonb_typeof(execution_binding->'model_version')='string'
    AND length(execution_binding->>'model_version') BETWEEN 1 AND 160
    AND execution_binding->>'model_route_digest' ~ '^[a-f0-9]{64}$'
    AND execution_binding->>'tool_definitions_digest' ~ '^[a-f0-9]{64}$'
    AND jsonb_typeof(execution_binding->'cancel_epoch')='number'
    AND execution_binding->>'cancel_epoch' ~ '^[0-9]+$'
  ))
  AND (execution_binding->>'kind'<>'model' OR (
    execution_binding ?& ARRAY['prompt_digest','loaded_skills','isolation']
    AND execution_binding->>'prompt_digest' ~ '^[a-f0-9]{64}$'
    AND jsonb_typeof(execution_binding->'loaded_skills')='array'
    AND execution_binding->>'isolation' IN
      ('main','research','extract','mcp','assistant_extract','assistant_compare')
    AND tool='model'
  ))
  AND (execution_binding->>'kind'<>'domain_t0' OR (
    execution_binding ?& ARRAY['operation','skill','model_call_id',
      'response_index','command_digest']
    AND jsonb_typeof(execution_binding->'operation')='string'
    AND length(execution_binding->>'operation') BETWEEN 1 AND 160
    AND execution_binding->>'command_digest' ~ '^[a-f0-9]{64}$'
    AND jsonb_typeof(execution_binding->'response_index')='number'
    AND execution_binding->>'response_index' ~ '^[0-9]+$'
    AND execution_binding->>'model_call_id'
      ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
    AND jsonb_typeof(execution_binding->'skill')='object'
    AND (execution_binding->'skill') ?& ARRAY['key','version','digest','load_event_id']
    AND jsonb_typeof(execution_binding->'skill'->'key')='string'
    AND length(execution_binding->'skill'->>'key') BETWEEN 1 AND 160
    AND jsonb_typeof(execution_binding->'skill'->'version')='string'
    AND length(execution_binding->'skill'->>'version') BETWEEN 1 AND 160
    AND execution_binding->'skill'->>'digest' ~ '^[a-f0-9]{64}$'
    AND execution_binding->'skill'->>'load_event_id'
      ~ '^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$'
    AND tool<>'model'
    AND (state<>'completed' OR (receipt_id IS NOT NULL AND result IS NOT NULL))
  )), false)"""
