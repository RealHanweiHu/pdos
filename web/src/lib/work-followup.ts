import type { SourceRead } from "./project-plan-view";
import { validWorkCommand, type WorkCommand, type WorkScope } from "./project-work";
import type { DomainCandidate } from "./domain-candidate";

export type WorkAssignment = { assignee_id: string; recipient_id: string };
export type WorkFollowupAction = { project_id: string; citation_ids: string[]; assignment?: WorkAssignment | null };
export type WorkAnswerRun = {
  run_id: string; status: string; reverted: boolean; product_id?: string | null;
  project_id?: string | null; result?: { result?: Record<string, unknown> } | null;
};
export type WorkAnswerSource = { citation_id: string; source_id: string; source_revision: number; source_type: string; title: string };
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
export function validWorkFollowupAction(value: unknown): value is WorkFollowupAction {
  return record(value) && Object.keys(value).every(key => ["project_id", "citation_ids", "assignment"].includes(key))
    && uuid(value.project_id)
    && Array.isArray(value.citation_ids) && value.citation_ids.length > 0 && value.citation_ids.length <= 20
    && value.citation_ids.every(uuid) && new Set(value.citation_ids).size === value.citation_ids.length
    && (value.assignment == null || record(value.assignment) && Object.keys(value.assignment).length === 2
      && uuid(value.assignment.assignee_id) && uuid(value.assignment.recipient_id));
}
export function workAnswerSources(run: WorkAnswerRun): WorkAnswerSource[] {
  if (run.reverted || !["completed", "partial"].includes(run.status) || !uuid(run.product_id) || !uuid(run.project_id)) return [];
  const assistant = run.result?.result?.assistant;
  if (!record(assistant) || !Array.isArray(assistant.sources)) return [];
  const seen = new Set<string>();
  return assistant.sources.flatMap(value => {
    if (!record(value) || !uuid(value.citation_id) || !uuid(value.source_id) || typeof value.source_type !== "string"
      || typeof value.title !== "string" || !Number.isSafeInteger(value.source_revision) || Number(value.source_revision) < 1 || seen.has(value.citation_id)) return [];
    seen.add(value.citation_id);
    return [{ citation_id: value.citation_id, source_id: value.source_id, source_type: value.source_type, title: value.title, source_revision: Number(value.source_revision) }];
  }).slice(0, 20);
}
export function workFollowupStart(run: WorkAnswerRun, citationIds: string[], sources: SourceRead[], key: string, assignment?: WorkAssignment) {
  const action = { project_id: run.project_id!, citation_ids: citationIds, ...(assignment ? { assignment } : {}) };
  const available = new Set(workAnswerSources(run).map(value => value.citation_id));
  if (!validWorkFollowupAction(action) || citationIds.some(id => !available.has(id)) || !uuid(key)) throw new Error("请核对本项目与所选讨论依据。");
  const originals = new Map<string, number>();
  for (const value of sources) {
    if (!uuid(value.artifact_id) || !Number.isSafeInteger(value.expected_revision) || value.expected_revision < 1
      || originals.has(value.artifact_id) && originals.get(value.artifact_id) !== value.expected_revision) throw new Error("请核对任务原件的固定版本。");
    originals.set(value.artifact_id, value.expected_revision);
  }
  if (!originals.size) throw new Error("请明确选择任务原件；聊天内容不能代替原件。");
  return { path: "v1/agent-runs" as const, body: {
    goal: "请沿用本次讨论，为缺失资料准备跟进任务。按明确来源起草标题、目标和成果要求；方法、判据和其他缺项保留待本人确认。只形成候选，确认后再创建任务。",
    idempotency_key: key, continue_from_run_id: run.run_id,
    sources: [...originals].map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision })),
    work_followup_action: action,
  } };
}
export function workFollowupCandidate(item: DomainCandidate, scope: WorkScope): item is DomainCandidate & { command: WorkCommand } {
  return item.kind === "work_followup" && item.operation === "work.task.create"
    && validWorkCommand(item.command, scope) && item.command.operation === "work.task.create"
    && item.command_id === item.command.command_id && item.idempotency_key === item.command.idempotency_key;
}
