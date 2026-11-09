// D47 shared flow for T1 one-confirmation and T2 named decisions: preview on the
// server, show its review, then submit exactly the prepared command. The token
// comes only from the server preview; the page never invents or reuses one.
import type { ProjectApi, SourceRead } from "@/lib/project-plan-view";

export type Tier = "T1" | "T2";
export type NamedCommand = {
  command_id: string; idempotency_key: string; product_id: string; expected_revision: number;
  operation: string; source_read_set: SourceRead[]; payload: Record<string, unknown>;
};
export type PreparedCommand = { tier: Tier; command: NamedCommand; review: Record<string, unknown>; expires_at: string | null };
export type CommandReceipt = { id: string; subject_type: string; subject_id: string; subject_revision: number; operation: string };

const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f-]{36}$/i.test(value);
const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
export const tokenField = (tier: Tier) => tier === "T2" ? "approval_token" : "confirmation_token";

function newId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, c => (Number(c) ^ (Math.random() * 16) >> (Number(c) / 4)).toString(16));
}

export function makeCommand(product: { id: string; revision: number }, operation: string, payload: Record<string, unknown>, reads: SourceRead[] = []): NamedCommand {
  const id = newId();
  return { command_id: id, idempotency_key: `${operation}:${id}`, product_id: product.id, expected_revision: product.revision, operation, source_read_set: reads.map(read => ({ ...read })), payload: { ...payload } };
}

function sameIdentity(a: NamedCommand, b: Record<string, unknown>) {
  return (["command_id", "idempotency_key", "product_id", "expected_revision", "operation"] as const).every(key => a[key] === b[key]);
}

// The server preview must echo our own command and carry the matching proof field.
export function preparedCommand(raw: unknown, pending: NamedCommand, tier: Tier, now = Date.now()): PreparedCommand | null {
  if (!record(raw) || !record(raw.command) || !record(raw.review) || !sameIdentity(pending, raw.command)) return null;
  const payload = raw.command.payload;
  const field = tokenField(tier);
  if (!record(payload) || typeof payload[field] !== "string" || !(payload[field] as string).length) return null;
  if (tier === "T2" && (raw.write_tier !== "T2" || raw.named_decision !== true)) return null;
  if (tier === "T1" && raw.write_tier === "T2") return null;
  const expires = raw.expires_at;
  if (!(expires === null || expires === undefined || (typeof expires === "string" && Date.parse(expires) > now))) return null;
  return { tier, command: raw.command as NamedCommand, review: raw.review, expires_at: typeof expires === "string" ? expires : null };
}

export function validReceipt(raw: unknown, command: NamedCommand, subjectType: string): raw is CommandReceipt {
  return record(raw) && uuid(raw.id) && uuid(raw.subject_id) && raw.operation === command.operation && raw.subject_type === subjectType && Number.isSafeInteger(raw.subject_revision);
}

export async function previewCommand(api: ProjectApi, command: NamedCommand, tier: Tier) {
  const raw = await api<unknown>("v1/commands/preview", command);
  const prepared = preparedCommand(raw, command, tier);
  if (!prepared) throw new Error(tier === "T2" ? "服务器没有返回与本次请求一致的具名决定预览，请重新核对。" : "服务器没有返回与本次请求一致的确认预览，请重新核对。");
  return prepared;
}

export async function submitPrepared(api: ProjectApi, prepared: PreparedCommand, subjectType: string) {
  if (prepared.expires_at !== null && Date.parse(prepared.expires_at) <= Date.now()) throw new Error("确认已过期，请重新预览。");
  const raw = await api<unknown>("v1/commands", prepared.command);
  if (!validReceipt(raw, prepared.command, subjectType)) throw new Error("提交结果尚未核实，请按原请求重试。");
  return raw;
}

// The server writes a closing sentence into every review; show it verbatim.
export function reviewEffect(review: Record<string, unknown>): string {
  return typeof review.effect === "string" ? review.effect : "";
}

export const tierNames: Record<Tier, string> = { T1: "本人确认一次后生效", T2: "具名决定，由有权本人办理" };
