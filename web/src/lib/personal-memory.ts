/** 本人记忆条目 (P86)：类型与纯函数。条目只给本人；小Pai 只能提议，本人确认后才写入。 */

export type NoteKind = "convention" | "background" | "alias";
export type ScopeKind = "global" | "category" | "product" | "proposal" | "project";
export type NoteState = "active" | "stale" | "unavailable" | "expired" | "replaced" | "history";
export type Scope = { kind: ScopeKind; id: string | null; title: string | null; readable: boolean };
export type AliasMeaning = { kind: string; text: string | null; id?: string; readable?: boolean; updated?: boolean };
export type MemoryNote = {
  note_id: string; revision: number; kind: NoteKind; kind_label: string; text: string; scope: Scope; state: NoteState;
  valid_until: string | null; confirmed_at: string; origin: "manual" | "candidate" | "merge"; replaced_by: string | null;
  alias?: { term: string; means: AliasMeaning | null };
};
export type ConflictNote = MemoryNote & { reason: "same_alias" | "similar_text" };
export type NotesView = { version: "memory-notes/v1"; enabled: boolean; limit: number; text_limit: number; active_count: number; notes: MemoryNote[]; deleted_count: number; note: string };
export type HistoryView = { version: "memory-notes/v1"; note_id: string; versions: MemoryNote[] };
export type ConflictView = { version: "memory-notes/v1"; conflicts: ConflictNote[]; choices: Resolution[] };
export type Resolution = "merge" | "replace" | "keep_both";
export type ConflictChoice = { resolution: Resolution; note_ids: string[]; expected_revisions: number[]; merged_text?: string };
export type NoteDraft = {
  kind: NoteKind; text: string; scope: { kind: ScopeKind; id: string | null }; valid_until?: string | null;
  alias_term?: string | null; alias_canonical?: string | null;
};
export type Candidate = {
  candidate_id: string; run_id: string; session_id: string; origin: "explicit" | "proactive"; kind: NoteKind; kind_label: string;
  text: string; scope: Scope; alias: { term: string; means: AliasMeaning } | null; trigger: { run_id: string; text: string }[];
  status: "pending" | "adopted" | "ignored" | "expired" | "voided"; proposed_at: string; expires_at: string; note_id: string | null;
  conflicts: ConflictNote[]; choices: Resolution[]; label: string;
};
export type CandidatesView = { version: "memory-candidates/v1"; items: Candidate[]; count?: number; run_id?: string; declined?: { count: number; note: string } | null };
export type OwnerSettings = { version: "memory-owner-settings/v1"; revision: number; proactive_off: boolean; notes_enabled: boolean; proposals_enabled: boolean; episode_vectors: boolean; effect: string };
export type TenantPolicy = { version: "memory-tenant-policy/v1"; revision: number; work_state_idle_days: number; notes_enabled: boolean; proposals_enabled: boolean; default: boolean };
export type TenantStatistics = { version: "memory-tenant-statistics/v1"; policy: TenantPolicy; active_notes: number; owners_with_notes: number; episode_vectors: { enabled: boolean; profile_version_id: string | null }; note: string };

export const memoryBase = "v1/personal/memory";
export const TEXT_LIMIT = 200;
export const kindNames: Record<NoteKind, { label: string; hint: string }> = {
  convention: { label: "口径", hint: "约束小Pai的说法和做法，例如“回答先给结论”。" },
  background: { label: "背景", hint: "关于你和你的工作，只作背景，例如“我负责充气泵品类”。" },
  alias: { label: "叫法", hint: "你习惯的说法，例如“我说气嘴指气门嘴”；只影响你本人的检索。" },
};
export const stateNames: Record<NoteState, string> = {
  active: "有效", stale: "可能过期", unavailable: "范围不可读", expired: "已过期", replaced: "已替换", history: "历史版本",
};
export const resolutionNames: Record<Resolution, string> = { merge: "合并到旧条目", replace: "替换旧的", keep_both: "都保留" };

export function scopeLabel(scope: Pick<Scope, "kind" | "title" | "readable">) {
  if (scope.kind === "global") return "全局";
  const kind = ({ category: "品类", product: "产品", proposal: "提案", project: "项目" } as Record<string, string>)[scope.kind] ?? "范围";
  return scope.readable === false || !scope.title ? `${kind}（当前不可读）` : `${kind} · ${scope.title}`;
}

export function aliasMeaning(note: Pick<MemoryNote, "alias">) {
  const means = note.alias?.means;
  if (!means) return "";
  if (means.readable === false || !means.text) return "所指对象当前不可读";
  return means.updated ? `${means.text}（对象已更新）` : means.text;
}

export function cleanText(value: string) {
  return value.split(/\s+/).filter(Boolean).join(" ");
}

/** The draft sent to the server; empty optional fields are omitted, never guessed. */
export function draftPayload(draft: NoteDraft): NoteDraft {
  const value: NoteDraft = { kind: draft.kind, text: cleanText(draft.text), scope: draft.scope.kind === "global" ? { kind: "global", id: null } : { kind: draft.scope.kind, id: draft.scope.id } };
  if (draft.valid_until) value.valid_until = new Date(`${draft.valid_until}T23:59:59`).toISOString();
  if (draft.kind === "alias") { value.alias_term = cleanText(draft.alias_term ?? ""); value.alias_canonical = cleanText(draft.alias_canonical ?? ""); }
  return value;
}

export function draftProblem(draft: NoteDraft) {
  if (draft.kind === "alias") {
    if (!cleanText(draft.alias_term ?? "")) return "请写下你说的词。";
    if (!cleanText(draft.alias_canonical ?? "")) return "请写下它指的标准词。";
  } else if (!cleanText(draft.text)) return "请写下要记住的内容。";
  if (cleanText(draft.text).length > TEXT_LIMIT) return `内容最多 ${TEXT_LIMIT} 个字。`;
  if (draft.scope.kind !== "global" && !draft.scope.id) return "请选择作用范围。";
  return "";
}

export function mergedDefault(older: string, newer: string) {
  const joined = older.includes(newer) ? older : `${older}；${newer}`;
  return joined.slice(0, TEXT_LIMIT);
}

/** The owner's explicit choice for similar notes; replace and merge name each old note's revision. */
export function choicePayload(resolution: Resolution, conflicts: Pick<MemoryNote, "note_id" | "revision">[], target: string | null, mergedText: string): ConflictChoice {
  if (resolution === "keep_both") return { resolution, note_ids: [], expected_revisions: [] };
  if (resolution === "merge") {
    const chosen = conflicts.find(item => item.note_id === target) ?? conflicts[0];
    return { resolution, note_ids: [chosen.note_id], expected_revisions: [chosen.revision], merged_text: cleanText(mergedText) };
  }
  return { resolution, note_ids: conflicts.map(item => item.note_id), expected_revisions: conflicts.map(item => item.revision) };
}

export function groupNotes(notes: MemoryNote[]) {
  const current = notes.filter(item => item.state === "active" || item.state === "stale" || item.state === "unavailable");
  return {
    convention: current.filter(item => item.kind === "convention"),
    alias: current.filter(item => item.kind === "alias"),
    background: current.filter(item => item.kind === "background"),
    past: notes.filter(item => item.state === "replaced" || item.state === "expired"),
  };
}

export function isNotesView(value: unknown): value is NotesView {
  return !!value && typeof value === "object" && (value as NotesView).version === "memory-notes/v1" && Array.isArray((value as NotesView).notes);
}

export function isCandidatesView(value: unknown): value is CandidatesView {
  return !!value && typeof value === "object" && (value as CandidatesView).version === "memory-candidates/v1" && Array.isArray((value as CandidatesView).items);
}

export function requestKey() {
  return crypto.randomUUID();
}
