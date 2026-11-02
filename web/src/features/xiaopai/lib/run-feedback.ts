export const feedbackReasons = {
  wrong_object: "对象错误", wrong_value: "数值错误", missing_source: "缺少来源",
  not_useful: "没有帮助", too_many_actions: "操作过多", should_not_automate: "不应自动执行",
} as const;
export type FeedbackReason = keyof typeof feedbackReasons;
export type FeedbackRequest = { idempotency_key: string; categories: FeedbackReason[]; comment: string; skill_load_event_id: string | null };
export type UsedSkill = { load_event_id: string; key: string; version: string; digest: string; isolation: string };
export type FeedbackVersion = { model_version: string | null; model_route_digest: string | null; tool_definitions: Record<string,string>; prompt_prefixes: Record<string,string>; skills: UsedSkill[]; cancel_epoch: number };
export type FeedbackRecord = { id: string; sequence: number; recorded_at: string; recorded_by: string; request: FeedbackRequest; versions: FeedbackVersion };
export type FeedbackReading = { run_id: string; owner_id: string; current_versions: FeedbackVersion; items: FeedbackRecord[]; next_before: number | null };
export type PendingFeedback = { root: string; run_id: string; owner_id: string; request: FeedbackRequest };
const uuid = /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i;
export function sameFeedback(a: FeedbackRequest,b: FeedbackRequest): boolean {
  return a.idempotency_key===b.idempotency_key && a.comment.trim()===b.comment.trim()
    && a.skill_load_event_id===b.skill_load_event_id && JSON.stringify([...a.categories].sort())===JSON.stringify([...b.categories].sort());
}
export function restoreFeedback(value: unknown, run: string, owner: string, root: string): PendingFeedback | null {
  if (!value || typeof value!=="object" || Array.isArray(value)) return null;
  const p=value as Record<string,unknown>;
  if (Object.keys(p).sort().join(",")!=="owner_id,request,root,run_id" || p.run_id!==run || p.owner_id!==owner || p.root!==root || !p.request || typeof p.request!=="object") return null;
  const request=p.request as Record<string,unknown>;
  if (Object.keys(request).sort().join(",")!=="categories,comment,idempotency_key,skill_load_event_id"
    || typeof request.idempotency_key!=="string" || !uuid.test(request.idempotency_key)
    || typeof request.comment!=="string" || request.comment.trim().length>2000
    || request.skill_load_event_id!==null && (typeof request.skill_load_event_id!=="string" || !uuid.test(request.skill_load_event_id))
    || !Array.isArray(request.categories) || request.categories.length<1 || request.categories.length>6
    || new Set(request.categories).size!==request.categories.length
    || request.categories.some(key=>typeof key!=="string" || !Object.hasOwn(feedbackReasons,key))) return null;
  return value as PendingFeedback;
}
