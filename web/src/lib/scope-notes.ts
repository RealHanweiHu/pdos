/** 团队备忘（范围条目，M2b；P87、P121 第 3、4、6 项）：读视图类型、标签与确认办理的命令外壳。
 * 备忘不是业务事实；保存、停用、撤回都走通用命令的“预览 → 确认一次”，这里不直接写任何表。 */

export type AnchorKind = "category" | "product" | "proposal" | "project";
export type NoteKind = "convention" | "concern" | "decision_context" | "observation";
export type NoteState = "active" | "expired" | "superseded" | "retired" | "withdrawn";
export type NoteFlag = "review_due" | "object_updated" | "disputed" | "no_formal_decision";
export type Epistemic = "stated" | "verified" | "inferred" | "disputed";
export type Person = { id: string; name: string | null; kind: string | null };
export type ObjectLink = { kind: string; id: string; version: number; title: string | null; updated: boolean };
export type ScopeNote = {
  note_id: string; revision: number; kind: NoteKind; kind_label: string; statement: string;
  anchor: { kind: AnchorKind; kind_label: string; id: string; title: string | null };
  state: NoteState; flags: NoteFlag[]; zone: "constraint" | "background";
  epistemic: Epistemic; epistemic_label: string; confirmation: string; confirmation_label: string;
  generated_by: "human" | "xiaopai_drafted" | "xiaopai"; generated_label: string; source_authority: string;
  subject: ObjectLink | null; formal: ObjectLink | null;
  tags: { customer: string | null; stage: string | null; topic: string | null };
  pinned: boolean; occurred_at: string | null; valid_from: string; valid_to: string | null; review_due_at: string; recorded_at: string;
  action: string; reason: string | null;
  author: Person & { departed: boolean }; confirmed_by: Person | null; review_owner: Person | null;
  run_id: string | null; evidence_count: number;
  relations: { type: string; direction: "from" | "to"; note_id: string }[];
};
export type ScopeNotesView = {
  version: "scope-notes/v1";
  anchor: { kind: AnchorKind; kind_label: string; id: string; title: string | null; category_id: string; product_id: string | null };
  can_write: boolean; audience: { kind: string; text: string }; customers: string[] | null;
  statement_limit: number; review_days: number; notes: ScopeNote[]; inactive_count: number; note: string;
};
export type ScopeNoteVersion = { revision: number; action: string; lifecycle: string; statement: string; epistemic_label: string; confirmation_label: string; generated_label: string; reason: string | null; recorded_at: string; by: Person | null };
export type Stance = "supports" | "opposes" | "context";
export type SourceType = "run" | "discussion" | "receipt" | "original" | "business_object";
/** 一条证据链接，按读者现在的权限给出来源标题；读不到时 title 为 null（当前不可读）。引文原文不保存。 */
export type EvidenceLink = { id: string; source_type: SourceType; source_kind: string | null; source_id: string; source_version: number | null; type_label: string; title: string | null; locator: Record<string, string | number>; has_quote: boolean; stance: Stance; stance_label: string; recorded_at: string; by_xiaopai: boolean };
export type ScopeNoteHistory = { version: "scope-notes/v1"; note: ScopeNote & { evidence?: EvidenceLink[] }; versions: ScopeNoteVersion[] };
/** 服务器列出的、读者现在能读到的证据来源和正式对象；保存时命令按当前权限逐条再核对，页面不另做判断。 */
export type SourceOption = { source_type: SourceType; source_kind: string | null; source_id: string; type_label: string; title: string | null; version: number | null };
export type SourcesView = { version: "scope-note-sources/v1"; anchor: { kind: AnchorKind; id: string; title: string | null }; formal: SourceOption[]; sources: SourceOption[]; note: string };
export type EvidenceDraft = { key: string; stance: Stance; where: string; quote: string };
export type Review = { effect: string; audience?: { kind: string; text: string }; kind_label?: string; statement?: string; zone?: "constraint" | "background"; formal_status?: "linked" | "no_formal_decision" | null; customer?: string | null; review_days?: number; evidence_added?: number; note?: string };
export type Prepared = { command: Record<string, unknown>; review: Review };
export type SimilarChoice = "supersede" | "conflict" | "keep";
export type NoteDraft = { kind: NoteKind; statement: string; epistemic: Epistemic; discussion: boolean; pinned: boolean; customer: string; valid_from: string; formal: string };

export const STATEMENT_LIMIT = 300;
export const REASON_LIMIT = 200;
export const kindNames: Record<NoteKind, { label: string; hint: string }> = {
  convention: { label: "约定", hint: "团队约好的做法或口径。只有约定会约束小Pai 的做法和表达。" },
  concern: { label: "关注点", hint: "客户或团队特别在意的事，例如评审必问的问题。只作背景。" },
  decision_context: { label: "决策背景", hint: "一个决定为什么这样定。尽量关联正式决定或对象，否则标“未形成正式决定”。" },
  observation: { label: "观察", hint: "值得团队留意、还没核实的现象。只作背景。" },
};
export const flagNames: Record<NoteFlag, string> = { review_due: "待复核", object_updated: "对象已更新，待复核", disputed: "有争议", no_formal_decision: "未形成正式决定" };
export const stateNames: Record<NoteState, string> = { active: "有效", expired: "已过期", superseded: "已被替代", retired: "已停用", withdrawn: "已撤回" };
export const epistemicNames: Record<Epistemic, string> = { stated: "有人这样说", inferred: "推断", disputed: "有争议", verified: "已核实" };
export const actionNames: Record<string, string> = { create: "新建", backfill: "补录（只进历史）", revise: "修改", add_evidence: "补充证据", supersede: "被替代", retire: "停用", withdraw: "撤回" };
export const similarNames: Record<SimilarChoice, string> = { supersede: "替代旧条目（旧的进历史）", conflict: "标为相互冲突（两条都降为背景）", keep: "都保留" };
export const anchorNames: Record<AnchorKind, string> = { category: "品类", product: "产品", proposal: "提案", project: "项目" };

export const isScopeNotesView = (value: unknown): value is ScopeNotesView => !!value && typeof value === "object" && (value as ScopeNotesView).version === "scope-notes/v1" && Array.isArray((value as ScopeNotesView).notes);
export const requestKey = () => crypto.randomUUID();
export const optionKey = (option: { source_type: string; source_kind: string | null; source_id: string }) => `${option.source_type}:${option.source_kind ?? ""}:${option.source_id}`;
export const formalKey = (kind: string, id: string) => optionKey({ source_type: "business_object", source_kind: kind, source_id: id });
export const emptyDraft = (): NoteDraft => ({ kind: "convention", statement: "", epistemic: "stated", discussion: false, pinned: false, customer: "", valid_from: "", formal: "" });
export const draftOf = (note: ScopeNote): NoteDraft => ({ kind: note.kind, statement: note.statement, epistemic: note.epistemic, discussion: note.confirmation === "discussion", pinned: note.pinned, customer: note.tags.customer ?? "", valid_from: "", formal: note.formal ? formalKey(note.formal.kind, note.formal.id) : "" });
export const stanceNames: Record<Stance, string> = { supports: "支持这条备忘", opposes: "与这条备忘相反", context: "只作背景" };
export const listPath = (categoryId: string, kind: AnchorKind, id: string, all = false) => `v1/categories/${categoryId}/scope-notes/${kind}/${id}${all ? "/all" : ""}`;
export const itemPath = (categoryId: string, noteId: string) => `v1/categories/${categoryId}/scope-note-items/${noteId}`;
export const sourcesPath = (categoryId: string, kind: AnchorKind, id: string) => `v1/categories/${categoryId}/scope-note-sources/${kind}/${id}`;
export const commandPath = (categoryId: string, preview = false) => `v1/categories/${categoryId}/commands${preview ? "/preview" : ""}`;

export function draftProblem(draft: NoteDraft): string | null {
  const text = draft.statement.trim();
  if (!text) return "请写下备忘内容。";
  if (text.length > STATEMENT_LIMIT) return `内容不超过 ${STATEMENT_LIMIT} 个字。`;
  if (draft.customer.trim().length > 80) return "客户标签不超过 80 个字。";
  return null;
}

/** “kind:id” 形式的正式对象选择；空字符串表示不关联。 */
function formalRef(key: string) {
  const [type, kind, id] = key.split(":");
  return type === "business_object" && kind && id ? { kind, id } : null;
}

/** 备忘正文：由本人选择的字段组成；挂靠对象和正式对象的版本、确认人、复核日期都由服务器绑定。 */
export function bodyPayload(draft: NoteDraft) {
  const formal = draft.kind === "decision_context" ? formalRef(draft.formal) : null;
  return {
    kind: draft.kind, statement: draft.statement.trim(), epistemic: draft.epistemic,
    confirmation: draft.discussion ? "discussion" : "member_confirmed", pinned: draft.pinned,
    ...(draft.customer.trim() ? { customer: draft.customer.trim() } : {}),
    ...(draft.valid_from ? { valid_from: `${draft.valid_from}T00:00:00Z` } : {}),
    ...(formal ? { formal } : {}),
  };
}

/** 补充证据：只带本人选的来源、立场、位置和摘录；摘录在服务器只存摘要，来源版本由服务器绑定。 */
export function evidencePayload(note: { note_id: string; revision: number }, items: EvidenceDraft[], options: SourceOption[]) {
  const known = new Map(options.map(option => [optionKey(option), option]));
  const evidence = items.flatMap(item => {
    const option = known.get(item.key);
    if (!option) return [];
    return [{
      source_type: option.source_type, source_id: option.source_id,
      ...(option.source_kind && option.source_type === "business_object" ? { source_kind: option.source_kind } : {}),
      stance: item.stance,
      ...(item.where.trim() ? { locator: { where: item.where.trim().slice(0, 80) } } : {}),
      ...(item.quote.trim() ? { quote: item.quote.trim().slice(0, 2000) } : {}),
    }];
  });
  return { mode: "evidence", note: { id: note.note_id, revision: note.revision }, evidence };
}

export function evidenceLine(link: EvidenceLink) {
  const where = Object.values(link.locator ?? {}).join("，");
  return [
    `${link.type_label}：${link.title ?? "当前不可读"}`,
    ...(link.source_version ? [`第 ${link.source_version} 版`] : []),
    link.stance_label,
    ...(where ? [`位置 ${where}`] : []),
    ...(link.has_quote ? ["有摘录（原文未保存，按读者权限重新读取）"] : []),
    ...(link.by_xiaopai ? ["小Pai 添加"] : []),
    link.recorded_at.slice(0, 10),
  ].join(" · ");
}

export function relationPayload(choice: SimilarChoice, similar: { note_id: string; revision: number }[]) {
  if (choice === "keep") return { relations: [], kept_similar: similar.map(item => item.note_id) };
  return { relations: similar.map(item => ({ type: choice === "supersede" ? "supersedes" : "conflicts", note: { id: item.note_id, revision: item.revision } })), kept_similar: [] };
}

/** 通用命令外壳。型号范围的对象带上 product_id，其余按品类办理；编号在一次填写内保持不变。 */
export function commandEnvelope(operation: string, payload: unknown, scope: { categoryId: string; productId?: string | null }, ids: { command: string; key: string }) {
  return { category_id: scope.categoryId, command_id: ids.command, idempotency_key: ids.key, operation, product_id: scope.productId ?? null, expected_revision: 1, source_read_set: [], payload };
}

export const noteMeta = (note: ScopeNote) => [
  note.generated_by === "xiaopai" ? "小Pai 记录，未核实" : `${note.confirmed_by?.name ?? "成员"} 确认${note.generated_by === "xiaopai_drafted" ? "（小Pai 起草）" : ""}`,
  note.recorded_at.slice(0, 10), note.epistemic_label,
  ...(note.tags.customer ? [`客户 ${note.tags.customer}`] : []),
  ...(note.author.departed ? [`作者已离开，复核人 ${note.review_owner?.name ?? "对象负责人"}`] : []),
].join(" · ");

export function splitNotes(notes: ScopeNote[]) {
  return { current: notes.filter(note => note.state === "active" || note.state === "expired"), past: notes.filter(note => note.state !== "active" && note.state !== "expired") };
}
