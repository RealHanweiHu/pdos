export const candidateLabels: Record<string, string> = {
  "platform.link.create": "平台关联", "proposal.create": "立项提案",
  "proposal.question.create": "待决问题", "proposal.item.patch": "提案条目修订",
  "product.definition.item.patch": "定义条目修订", "category.knowledge.add": "品类知识",
  "category.knowledge.withdraw": "知识撤回", "category.knowledge.promote": "去标识知识沉淀",
  "category.parameter.publish": "规格字典版本",
  "research.snapshot.register": "研究来源登记",
};
export type DomainCommand = {
  command_id: string; idempotency_key: string; category_id: string; product_id: string | null;
  operation: string; expected_revision: number; source_read_set: unknown[];
  payload: Record<string, unknown> & { prepared_by_run_id?: string; candidate_digest?: string; prepared_event_id?: string; snapshot_id?: string; confirmation_token?: string | null };
};
export type CandidateReceipt = { id: string; subject_id: string; subject_type: string; operation: string; result: Record<string, unknown> };
export type DomainCandidate = {
  event_id: string; sequence: number; operation: string | null;
  command_id: string | null; idempotency_key: string | null;
  state: "pending" | "adopted" | "cancelled" | "unavailable";
  command: DomainCommand | null; receipt: CandidateReceipt | null;
  summary?: { title: string; url: string; visibility: string; retrieved_at: string };
};
export type CandidatePage = { run_id: string; items: DomainCandidate[]; next_cursor: number | null };
export type CandidatePreview = { command: DomainCommand; expires_at: string; review: Record<string, unknown> };
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function boundCandidateCommand(value: unknown, category: string, run: string, eventId?: string): value is DomainCommand {
  const base = object(value) && typeof value.operation === "string" && Object.hasOwn(candidateLabels, value.operation)
    && value.category_id === category && typeof value.command_id === "string" && uuid.test(value.command_id)
    && typeof value.idempotency_key === "string" && value.idempotency_key.length >= 8
    && (value.product_id === null || typeof value.product_id === "string" && uuid.test(value.product_id))
    && Number.isSafeInteger(value.expected_revision) && Number(value.expected_revision) > 0
    && Array.isArray(value.source_read_set) && object(value.payload);
  if (!base || !object(value) || !object(value.payload)) return false;
  if (value.operation === "research.snapshot.register") return typeof eventId === "string" && uuid.test(eventId)
    && value.payload.prepared_event_id === eventId && typeof value.payload.snapshot_id === "string" && uuid.test(value.payload.snapshot_id)
    && Object.keys(value.payload).every(key => ["snapshot_id", "prepared_event_id", "confirmation_token"].includes(key));
  return value.payload.prepared_by_run_id === run && typeof value.payload.candidate_digest === "string"
    && /^[a-f0-9]{64}$/.test(value.payload.candidate_digest);
}
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (!object(value)) return value;
  return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
}
export function sameCandidateCommand(a: DomainCommand, b: DomainCommand) {
  const withoutToken = (command: DomainCommand) => {
    const payload = { ...command.payload }; delete payload.confirmation_token;
    return canonical({ ...command, payload });
  };
  return JSON.stringify(withoutToken(a)) === JSON.stringify(withoutToken(b));
}
export function matchesPendingCandidate(item: DomainCandidate | undefined, command: DomainCommand, eventId: string, category: string, run: string) {
  return !!item && item.event_id === eventId && item.state === "pending" && !!item.command
    && item.command_id === command.command_id && item.idempotency_key === command.idempotency_key
    && boundCandidateCommand(command, category, run, eventId)
    && boundCandidateCommand(item.command, category, run, eventId)
    && sameCandidateCommand(item.command, command);
}
