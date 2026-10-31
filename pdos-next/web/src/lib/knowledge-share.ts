import { knowledgeAnswerRoot, knowledgeShareRequest, type KnowledgeShare } from "./verified-knowledge";
import { workRecord, workUuid, type ProjectWorkApi } from "./project-work";

export type KnowledgeSharePending = {
  version: "knowledge-share/v1"; principal_id: string; run_root: string;
  category_id: string; run_id: string; recipient_id: string;
  request: ReturnType<typeof knowledgeShareRequest>;
};
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).length === keys.length && Object.keys(value).every(key => keys.includes(key));
const hash = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
export function knowledgeShareStorage(principal: string, root: string, run: string) { return `pdos.knowledge-share.v1:${principal}:${root}:${run}`; }
export function restoreKnowledgeShare(value: unknown, principal: string, root: string, run: string): KnowledgeSharePending | null {
  if (!workRecord(value) || !exact(value, ["version", "principal_id", "run_root", "category_id", "run_id", "recipient_id", "request"])
    || value.version !== "knowledge-share/v1" || value.principal_id !== principal || !workUuid(principal)
    || value.run_root !== root || !/^v1\/(?:personal|categories\/[a-f0-9-]{36})\/agent-runs$/i.test(root)
    || value.run_id !== run || !workUuid(run) || !workUuid(value.category_id) || !workUuid(value.recipient_id)
    || root !== "v1/personal/agent-runs" && root !== `v1/categories/${value.category_id}/agent-runs`
    || !workRecord(value.request)) return null;
  const body = value.request;
  if (!exact(body, ["run_id", "kind", "feedback_id", "request_key", "preview_digest"])
    || body.run_id !== run || !["missing_material", "shared_feedback"].includes(String(body.kind))
    || !workUuid(body.request_key) || !hash(body.preview_digest)
    || (body.kind === "shared_feedback" ? !workUuid(body.feedback_id) : body.feedback_id !== null)) return null;
  return structuredClone(value) as KnowledgeSharePending;
}
export function prepareKnowledgeShare(value: KnowledgeShare, principal: string, root: string, key: string): KnowledgeSharePending {
  const pending = restoreKnowledgeShare({ version: "knowledge-share/v1", principal_id: principal,
    run_root: root, category_id: value.recipient.category_id, run_id: value.run_id,
    recipient_id: value.recipient.id, request: knowledgeShareRequest(value, key) }, principal, root, value.run_id);
  if (!pending) throw new Error("请先核对本人原回答、目标品类与本次分享。");
  return pending;
}
export async function requestKnowledgeShare(api: ProjectWorkApi, pending: KnowledgeSharePending, reading: boolean) {
  const value = await api<unknown>(`${knowledgeAnswerRoot(pending.category_id)}/gaps${reading ? "/recover" : ""}`, pending.request);
  if (!workRecord(value) || value.state !== "shared" || !workUuid(value.id)
    || value.recipient_id !== pending.recipient_id || value.request_key !== pending.request.request_key
    || value.run_id !== pending.run_id || value.kind !== pending.request.kind
    || value.feedback_id !== pending.request.feedback_id) throw new Error("原提交结果尚未核对；原请求已保留，请读取原结果。");
  return value;
}
