/** Owner deletes one own Session (P121 第 8 项): path and exact response shapes. */
export type DeletionCounts = { episodes: number; marks: number; index_rows: number; vectors: number; candidates: number };
export type DeletionNotice = { now: string; by_retention: string; kept: string };
export type SessionDeletionPreview = {
  version: "agent-session-deletion/v1"; session_id: string; deleted: false; will_remove: DeletionCounts;
  kept: { runs: number; receipts: number; adopted_notes: number };
  blocked: { reason_key: string; message: string } | null; notice: DeletionNotice;
};
export type SessionDeleted = {
  version: "agent-session-deletion/v1"; session_id: string; deleted: true; deleted_at: string;
  removed: DeletionCounts; notice: DeletionNotice;
};

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const text = (value: unknown) => typeof value === "string" && value.length > 0;
const counts = (value: unknown) => record(value) && ["episodes", "marks", "index_rows", "vectors", "candidates"].every(key => count(value[key]));
const notice = (value: unknown) => record(value) && text(value.now) && text(value.by_retention) && text(value.kept);

export function deletionPath(categoryId: string | null, sessionId: string): string {
  if (!uuid.test(sessionId) || categoryId !== null && !uuid.test(categoryId)) throw new Error("会话标识无法核对。");
  return `${categoryId === null ? "v1/personal" : `v1/categories/${categoryId}`}/agent-sessions/${sessionId}/deletion`;
}

export function validPreview(value: unknown, sessionId: string): value is SessionDeletionPreview {
  return record(value) && value.version === "agent-session-deletion/v1" && value.session_id === sessionId && value.deleted === false
    && counts(value.will_remove) && notice(value.notice)
    && record(value.kept) && ["runs", "receipts", "adopted_notes"].every(key => count((value.kept as Record<string, unknown>)[key]))
    && (value.blocked === null || record(value.blocked) && text(value.blocked.reason_key) && text(value.blocked.message));
}

export function validDeleted(value: unknown, sessionId: string): value is SessionDeleted {
  return record(value) && value.version === "agent-session-deletion/v1" && value.session_id === sessionId && value.deleted === true
    && text(value.deleted_at) && counts(value.removed) && notice(value.notice);
}

export function deletedSummary(result: SessionDeleted): string {
  const gone = result.removed;
  return `已清除情景记录 ${gone.episodes} 条、标记 ${gone.marks} 条、检索索引 ${gone.index_rows} 条、向量 ${gone.vectors} 条、未采纳的记忆提议 ${gone.candidates} 条。它不再出现在会话列表、搜索和小Pai 的回忆里。`;
}
