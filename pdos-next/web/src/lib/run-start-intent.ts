type Start = { goal: string; idempotency_key: string; product_id: string | null; proposal_id?: string; project_id?: string; sources: { artifact_id: string; expected_revision: number }[] };
export type RunStartIntent = { path: "v1/agent-runs"; body: Start };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
/** Restore only an original start in this exact proposal scope, never an arbitrary POST. */
export function restoreRunStart(value: unknown, proposalId?: string, projectId?: string): RunStartIntent | null {
  if (!record(value) || Object.keys(value).some(key => !["path", "body"].includes(key)) || value.path !== "v1/agent-runs" || !record(value.body)) return null;
  const body = value.body;
  if (Object.keys(body).some(key => !["goal", "idempotency_key", "product_id", "proposal_id", "project_id", "sources"].includes(key))
    || typeof body.goal !== "string" || body.goal.length < 3 || body.goal.length > 8000
    || typeof body.idempotency_key !== "string" || body.idempotency_key.length < 8 || body.idempotency_key.length > 160
    || !(body.product_id === null || typeof body.product_id === "string" && uuid.test(body.product_id))
    || body.proposal_id !== proposalId || proposalId !== undefined && body.product_id !== null
    || body.project_id !== projectId || projectId !== undefined && (!uuid.test(projectId) || body.product_id === null)
    || !Array.isArray(body.sources) || body.sources.some(source => !record(source)
      || Object.keys(source).some(key => !["artifact_id", "expected_revision"].includes(key))
      || typeof source.artifact_id !== "string" || !uuid.test(source.artifact_id)
      || !Number.isSafeInteger(source.expected_revision) || Number(source.expected_revision) < 1)) return null;
  return value as RunStartIntent;
}
