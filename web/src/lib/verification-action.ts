import type { SourceRead } from "./project-plan-view";

export type VerificationBuildRef = {
  id: string; revision: number; product_id: string; project_id: string;
  engineering_configuration: { id: string; revision: number };
  manufacturing_configuration: { id: string; revision: number };
};
export type VerificationAction = { selection: VerificationBuildRef; citation_ids: string[] };
export type VerificationSource = { citation_id: string; title: string; source_revision: number };
export type VerificationAnswerRun = {
  run_id: string; product_id?: string | null; project_id?: string | null;
  status: string; reverted: boolean; result?: { result?: Record<string, unknown> } | null;
};
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const revision = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const config = (value: unknown) => record(value) && Object.keys(value).length === 2 && uuid(value.id) && revision(value.revision);
export function verificationBuildRef(value: unknown): value is VerificationBuildRef {
  return record(value) && Object.keys(value).length === 6 && uuid(value.id) && revision(value.revision)
    && uuid(value.product_id) && uuid(value.project_id) && config(value.engineering_configuration) && config(value.manufacturing_configuration);
}
export function validVerificationAction(value: unknown): value is VerificationAction {
  return record(value) && Object.keys(value).length === 2 && verificationBuildRef(value.selection)
    && Array.isArray(value.citation_ids) && value.citation_ids.length > 0
    && value.citation_ids.every(uuid) && new Set(value.citation_ids).size === value.citation_ids.length;
}
export function verificationAnswerSources(run: VerificationAnswerRun): VerificationSource[] {
  if (run.reverted || !["completed", "partial"].includes(run.status) || !uuid(run.product_id) || !uuid(run.project_id)) return [];
  const assistant = run.result?.result?.assistant;
  if (!record(assistant) || !record(assistant.task_result) || assistant.task_result.version !== 1
    || assistant.task_result.format !== "cases" || !Array.isArray(assistant.task_result.rows) || !Array.isArray(assistant.sources)) return [];
  const selected = new Set<string>();
  for (const row of assistant.task_result.rows) if (record(row) && record(row.cells)) {
    for (const cell of Object.values(row.cells)) if (record(cell) && cell.status === "recorded" && uuid(cell.citation_id)) selected.add(cell.citation_id);
  }
  const seen = new Set<string>();
  return assistant.sources.flatMap(source => {
    if (!record(source) || !uuid(source.citation_id) || !selected.has(source.citation_id) || seen.has(source.citation_id)
      || typeof source.title !== "string" || !revision(source.source_revision)) return [];
    seen.add(source.citation_id);
    return [{ citation_id: source.citation_id, title: source.title, source_revision: Number(source.source_revision) }];
  });
}
export function verificationStart(run: VerificationAnswerRun, selection: VerificationBuildRef, citationIds: string[], sources: SourceRead[], key: string, buildName: string) {
  const action = { selection, citation_ids: citationIds }, available = new Set(verificationAnswerSources(run).map(source => source.citation_id));
  if (!validVerificationAction(action) || selection.product_id !== run.product_id || selection.project_id !== run.project_id || citationIds.some(id => !available.has(id))) throw new Error("请重新核对本项目Build与所选案例依据。");
  return { path: "v1/agent-runs" as const, body: {
    goal: `请参考所选历史案例，为“${buildName}”准备复验请求。明确本次测试项与样本数，方法和判据缺少依据的保留待确认。`,
    idempotency_key: key, continue_from_run_id: run.run_id, sources: sources.map(({ artifact_id, expected_revision }) => ({ artifact_id, expected_revision })),
    verification_action: action,
  } };
}
