export type Groups = {
  knowledge: Record<string, unknown>[];
  parameters: Record<string, unknown>[];
  snapshot_refs: { call_id: string; content_hash: string }[];
};
export type CategoryInput = { key: string; name: string; purpose: string; groups: Groups };
export type CategoryCandidate = {
  type: "category_candidate";
  input: CategoryInput;
  candidate_digest: string;
  cancel_epoch: number;
  source: Record<string, unknown>;
  snapshots: Record<string, unknown>[];
};
export type CategoryCreateDTO = CategoryInput & {
  deidentified_confirmed: boolean;
  prepared_by_run_id?: string;
  candidate_digest?: string;
  idempotency_key: string;
  confirmation_token?: string;
};
export type CreatedCategory = { id: string; name: string; purpose: string; receiptId?: string; continuationState?: string };
export type CategoryAdopted = {
  type: "category_adopted"; proof_version: 1; run_id: string; category_id: string;
  receipt_id: string; candidate_digest: string; candidate_event_id: string; input_ref: string; cancel_epoch: number;
};
export function adoptedCategory(value: unknown, runId: string): CategoryAdopted | null {
  if (!value || typeof value !== "object") return null;
  const event = value as Partial<CategoryAdopted>;
  const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
  return event.type === "category_adopted" && event.proof_version === 1 && event.run_id === runId
    && [event.category_id, event.receipt_id, event.candidate_event_id, event.input_ref].every(id => typeof id === "string" && uuid.test(id))
    && typeof event.candidate_digest === "string" && /^[a-f0-9]{64}$/.test(event.candidate_digest)
    && Number.isSafeInteger(event.cancel_epoch) ? event as CategoryAdopted : null;
}
export type CategoryPreview = {
  payload: Omit<CategoryCreateDTO, "idempotency_key" | "confirmation_token">;
  confirmation_token: string;
  expires_at: string;
  origin: string;
  writer_id: string;
  groups: Record<keyof Groups, { selected_count: number; available_count: number }>;
  candidate?: { checks: Record<string, boolean>; sources: Record<string, unknown>[] } | null;
};
export type CategoryConfirmationDraft = {
  request: CategoryCreateDTO; preview: CategoryPreview | null; attempted: boolean; rejected: boolean;
};
export type Api = <T>(path: string, body?: unknown) => Promise<T>;
export const groupNames: Record<keyof Groups, string> = {
  knowledge: "初始知识", parameters: "参数字典", snapshot_refs: "公开研究快照",
};
export const groupKeys = Object.keys(groupNames) as (keyof Groups)[];
export const emptyGroups = (): Groups => ({ knowledge: [], parameters: [], snapshot_refs: [] });
export class RequestRejected extends Error {}

export async function personalApi<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) {
    const message = typeof result.message === "string" ? result.message : "请求未完成，请重试或检查当前权限。";
    throw [403, 422].includes(response.status) || result.code === "CONFIRMATION_REQUIRED"
      ? new RequestRejected(message) : new Error(message);
  }
  return result;
}

export function selectedInput(candidate: CategoryCandidate, selected: Record<keyof Groups, boolean>): CategoryInput {
  const groups: Groups = {
    knowledge: selected.knowledge ? candidate.input.groups.knowledge : [],
    parameters: selected.parameters ? candidate.input.groups.parameters : [],
    snapshot_refs: selected.snapshot_refs ? candidate.input.groups.snapshot_refs : [],
  };
  if (!selected.snapshot_refs && groups.knowledge.some(item => knowledgeReferences(item)
    .some(ref => ref && typeof ref === "object" && "type" in ref && ref.type === "snapshot"))) {
    throw new Error("初始知识引用了研究快照。取消快照时，请同时取消初始知识组。");
  }
  return { key: candidate.input.key, name: candidate.input.name, purpose: candidate.input.purpose, groups };
}

function knowledgeReferences(item: Record<string, unknown>): unknown[] {
  const refs: unknown[] = Array.isArray(item.source_refs) ? [...item.source_refs] : [];
  const content = item.content && typeof item.content === "object" ? item.content as Record<string, unknown> : {};
  if (item.kind === "voice" && Array.isArray(content.representative_refs)) refs.push(...content.representative_refs);
  if (item.kind === "competitor") for (const key of ["metrics", "features", "prices"]) {
    if (Array.isArray(content[key])) refs.push(...content[key].map(value => value?.source_ref));
  }
  return refs;
}

export function asCandidate(value: unknown): CategoryCandidate | null {
  if (!value || typeof value !== "object") return null;
  const event = value as Partial<CategoryCandidate>;
  if (event.type !== "category_candidate" || typeof event.candidate_digest !== "string"
    || !/^[a-f0-9]{64}$/.test(event.candidate_digest) || !Number.isSafeInteger(event.cancel_epoch)
    || !event.input || ![event.input.key, event.input.name, event.input.purpose].every(item => typeof item === "string")
    || !event.input.groups || !groupKeys.every(key => Array.isArray(event.input!.groups[key]))
    || !event.source || typeof event.source !== "object" || !Array.isArray(event.snapshots)) return null;
  return event as CategoryCandidate;
}
