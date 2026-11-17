/** 本人记忆条目 (P86)：类型与纯函数。条目只给本人；小Pai 只能提议，本人确认后才写入。 */

export type NoteKind = "convention" | "background" | "alias";
export type ScopeKind = "global" | "category" | "product" | "proposal" | "project";
export type NoteState = "active" | "pending" | "stale" | "unavailable" | "expired" | "replaced" | "history";
export type Scope = { kind: ScopeKind; id: string | null; title: string | null; readable: boolean };
export type AliasMeaning = { kind: string; text: string | null; id?: string; readable?: boolean; updated?: boolean };
/** 统一条目契约（P121 第 6 项，§5.7）：证据链接只存引用，片段正文从不保存。 */
export type SourceType = "run" | "discussion" | "receipt" | "original" | "business_object";
export type SourceKind = "category" | "product" | "proposal" | "project" | "proposal_decision";
export type Stance = "supports" | "opposes" | "context";
export type EvidenceInput = { source_type: SourceType; source_id: string; source_kind?: SourceKind | null; locator?: Record<string, string | number>; stance: Stance };
export type EvidenceLink = EvidenceInput & { source_version: number | null; quoted: boolean; readable: boolean; title: string | null; updated: boolean };
export type RelationType = "conflicts" | "duplicates";
export type RelationRef = { type: RelationType; note_id: string };
export type RelationView = { type: RelationType | "supersedes" | "superseded_by"; label: string; direction: "in" | "out"; note_id: string; text: string };
export type MemoryNote = {
  note_id: string; revision: number; kind: NoteKind; kind_label: string; text: string; scope: Scope; state: NoteState;
  valid_until: string | null; confirmed_at: string; origin: "manual" | "candidate" | "merge"; replaced_by: string | null;
  alias?: { term: string; means: AliasMeaning | null };
  occurred_at?: string | null; valid_from?: string; confirmation?: "member_confirmed"; confirmation_label?: string;
  evidence?: EvidenceLink[]; relations?: RelationView[];
};
export type ConflictNote = MemoryNote & { reason: "same_alias" | "similar_text"; replace_effect?: "replaces" | "history_only" };
export type NotesView = { version: "memory-notes/v1"; enabled: boolean; limit: number; text_limit: number; active_count: number; notes: MemoryNote[]; deleted_count: number; note: string };
export type HistoryView = { version: "memory-notes/v1"; note_id: string; versions: MemoryNote[] };
export type ConflictView = { version: "memory-notes/v1"; conflicts: ConflictNote[]; choices: Resolution[] };
export type Resolution = "merge" | "replace" | "keep_both";
export type ConflictChoice = { resolution: Resolution; note_ids: string[]; expected_revisions: number[]; merged_text?: string };
export type NoteDraft = {
  kind: NoteKind; text: string; scope: { kind: ScopeKind; id: string | null }; valid_until?: string | null;
  alias_term?: string | null; alias_canonical?: string | null;
  /** Form dates (YYYY-MM-DD) or, in a payload, ISO times. Empty = left to the server's default. */
  occurred_at?: string | null; valid_from?: string | null;
  evidence?: EvidenceInput[]; relations?: RelationRef[];
};
export type Candidate = {
  candidate_id: string; run_id: string; session_id: string; origin: "explicit" | "proactive"; kind: NoteKind; kind_label: string;
  text: string; scope: Scope; alias: { term: string; means: AliasMeaning } | null; trigger: { run_id: string; text: string }[];
  status: "pending" | "adopted" | "ignored" | "expired" | "voided"; proposed_at: string; expires_at: string; note_id: string | null;
  conflicts: ConflictNote[]; choices: Resolution[]; label: string;
};
export type CandidatesView = { version: "memory-candidates/v1"; items: Candidate[]; count?: number; run_id?: string; declined?: { count: number; note: string } | null };
export type OwnerSettings = { version: "memory-owner-settings/v1"; revision: number; proactive_off: boolean; notes_enabled: boolean; proposals_enabled: boolean; episode_vectors: boolean; effect: string };
export type TenantPolicy = { version: "memory-tenant-policy/v1"; revision: number; work_state_idle_days: number; notes_enabled: boolean; proposals_enabled: boolean; scope_note_review_days: number; default: boolean };
export type TenantStatistics = { version: "memory-tenant-statistics/v1"; policy: TenantPolicy; active_notes: number; owners_with_notes: number; episode_vectors: { enabled: boolean; profile_version_id: string | null }; note: string };

export const memoryBase = "v1/personal/memory";
export const TEXT_LIMIT = 200;
export const kindNames: Record<NoteKind, { label: string; hint: string }> = {
  convention: { label: "口径", hint: "约束小Pai的说法和做法，例如“回答先给结论”。" },
  background: { label: "背景", hint: "关于你和你的工作，只作背景，例如“我负责充气泵品类”。" },
  alias: { label: "叫法", hint: "你习惯的说法，例如“我说气嘴指气门嘴”；只影响你本人的检索。" },
};
export const stateNames: Record<NoteState, string> = {
  active: "有效", pending: "未生效", stale: "可能过期", unavailable: "范围不可读", expired: "已过期", replaced: "已替换", history: "历史版本",
};
export const stanceNames: Record<Stance, string> = { supports: "支持", opposes: "反对", context: "背景" };
export const relationNames: Record<RelationType, string> = { conflicts: "冲突", duplicates: "重复" };
const sourceNames: Record<SourceType, string> = { run: "对话", discussion: "讨论", receipt: "办理回执", original: "原件", business_object: "业务对象" };
const objectNames: Record<SourceKind, string> = { category: "品类", product: "产品", proposal: "提案", project: "项目", proposal_decision: "G0 决定" };

export function evidenceLabel(link: Pick<EvidenceLink, "source_type" | "source_kind" | "readable" | "title" | "updated">) {
  const kind = link.source_type === "business_object" && link.source_kind ? objectNames[link.source_kind] : sourceNames[link.source_type];
  if (!link.readable) return `${kind}（当前不可读）`;
  const title = link.title ? ` · ${link.title}` : "";
  return `${kind}${title}${link.updated ? "（已有新版本）" : ""}`;
}

/** The links a note shows, as the inputs a revision re-sends (the quote is never re-sent; its digest stays). */
export function evidenceInputs(links: EvidenceLink[] | undefined): EvidenceInput[] {
  return (links ?? []).map(link => ({ source_type: link.source_type, source_id: link.source_id, source_kind: link.source_kind ?? null, locator: link.locator ?? {}, stance: link.stance }));
}

export function ownRelations(note: Pick<MemoryNote, "relations">): RelationRef[] {
  return (note.relations ?? []).filter(item => item.direction === "out" && (item.type === "conflicts" || item.type === "duplicates"))
    .map(item => ({ type: item.type as RelationType, note_id: item.note_id }));
}

const startOfDay = (value: string) => new Date(`${value}T00:00:00`).toISOString();
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

/**
 * The draft sent to the server; empty optional fields are omitted, never guessed.
 * With ``original`` (a revision) the contract fields go only when the owner changed them:
 * left out, the server keeps them; a cleared 事情发生的时间 is sent as null.
 */
export function draftPayload(draft: NoteDraft, original?: NoteDraft): NoteDraft {
  const value: NoteDraft = { kind: draft.kind, text: cleanText(draft.text), scope: draft.scope.kind === "global" ? { kind: "global", id: null } : { kind: draft.scope.kind, id: draft.scope.id } };
  if (draft.valid_until) value.valid_until = new Date(`${draft.valid_until}T23:59:59`).toISOString();
  if (draft.kind === "alias") { value.alias_term = cleanText(draft.alias_term ?? ""); value.alias_canonical = cleanText(draft.alias_canonical ?? ""); }
  const changed = (key: "occurred_at" | "valid_from" | "evidence" | "relations") => !original || JSON.stringify(draft[key] ?? null) !== JSON.stringify(original[key] ?? null);
  if (draft.valid_from && changed("valid_from")) value.valid_from = startOfDay(draft.valid_from);
  if (changed("occurred_at")) {
    if (draft.occurred_at) value.occurred_at = startOfDay(draft.occurred_at);
    else if (original) value.occurred_at = null;
  }
  if (original ? changed("evidence") : (draft.evidence ?? []).length > 0) value.evidence = draft.evidence ?? [];
  if (original ? changed("relations") : (draft.relations ?? []).length > 0) value.relations = draft.relations ?? [];
  return value;
}

export function draftProblem(draft: NoteDraft) {
  if (draft.kind === "alias") {
    if (!cleanText(draft.alias_term ?? "")) return "请写下你说的词。";
    if (!cleanText(draft.alias_canonical ?? "")) return "请写下它指的标准词。";
  } else if (!cleanText(draft.text)) return "请写下要记住的内容。";
  if (cleanText(draft.text).length > TEXT_LIMIT) return `内容最多 ${TEXT_LIMIT} 个字。`;
  if (draft.scope.kind !== "global" && !draft.scope.id) return "请选择作用范围。";
  if (draft.occurred_at && draft.occurred_at > localDay(new Date())) return "事情发生的时间不能晚于今天。";
  if (draft.valid_until && draft.valid_from && draft.valid_until < draft.valid_from) return "有效期须晚于生效起点。";
  return "";
}

export function localDay(value: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
}

/** 生效起点 worth showing: a start other than the day the owner confirmed this version. */
export function startNote(note: Pick<MemoryNote, "state" | "valid_from" | "confirmed_at">) {
  if (!note.valid_from) return "";
  const day = localDay(new Date(note.valid_from));
  if (note.state === "pending") return `自 ${day} 起生效`;
  return day !== localDay(new Date(note.confirmed_at)) ? `自 ${day} 起` : "";
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
  const current = notes.filter(item => item.state === "active" || item.state === "pending" || item.state === "stale" || item.state === "unavailable");
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
