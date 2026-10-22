import type { CandidateDraft, KnowledgeResultRef, KnowledgeScope, KnowledgeTarget } from "./knowledge-experience";
import { parseWorkSources, workRecord, workUuid, type WorkSource } from "./project-work";

type Availability = { selectable: boolean; reason: string | null };
export type KnowledgeNativeVisibility = "private" | "category" | "audience";
export type KnowledgeNativeResult = Availability & {
  receipt_id: string;
  family: "field" | "change" | "other";
  title: string;
  operation: string;
  subject: { kind: string; id: string; revision: number };
  recorded_at: string;
  visibility: KnowledgeNativeVisibility;
};
export type KnowledgeNativeSource = Availability & {
  ref: WorkSource;
  title: string;
  excerpt: string;
  visibility: KnowledgeNativeVisibility;
};
export type KnowledgeNativeConfiguration = Availability & { ref: KnowledgeTarget; name: string };
export type KnowledgeNativeContext = {
  scope: { category_id: string; product_id: string; project_id: string | null; principal_id: string };
  as_of: string;
  result_options: KnowledgeNativeResult[];
  source_options: KnowledgeNativeSource[];
  configuration_options: KnowledgeNativeConfiguration[];
  next_cursor?: string | null;
};
export type KnowledgeNativeKeys = {
  results: string[];
  sources: string[];
  configurations: string[];
};
export type KnowledgeNativeSelection = {
  /** Memory-only stale-context guard; never part of a knowledge command. */
  context_key: string;
  result_receipts: KnowledgeResultRef[];
  sources: WorkSource[];
  configurations: KnowledgeTarget[];
};

const nonempty = (value: unknown): value is string => typeof value === "string" && !!value.trim();
const revision = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).every(key => keys.includes(key));
const unique = (values: string[]) => new Set(values).size === values.length;
const visible = (value: unknown) => value === "private" || value === "category" || value === "audience";
const instant = (value: unknown) => typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const availability = (value: Record<string, unknown>) => typeof value.selectable === "boolean" && (value.reason === null || nonempty(value.reason));
export const knowledgeNativeAvailable = (value: Availability) => value.selectable === true && value.reason === null;
export const knowledgeNativeSourceKey = (ref: WorkSource) => JSON.stringify([ref.kind, ref.id, ref.revision, ref.position]);
export const knowledgeNativeConfigurationKey = (ref: KnowledgeTarget) => JSON.stringify([ref.kind, ref.id, ref.revision]);

function source(value: unknown): value is WorkSource {
  if (!workRecord(value) || !exact(value, ["kind", "id", "revision", "position"]) || value.kind !== "artifact" || !workUuid(value.id) || !revision(value.revision) || !nonempty(value.position)) return false;
  try { return parseWorkSources(JSON.stringify([value])).length === 1; } catch { return false; }
}
function configuration(value: unknown): value is KnowledgeTarget {
  return workRecord(value) && exact(value, ["kind", "id", "revision"]) && workUuid(value.id) && revision(value.revision) && ["engineering_configuration", "process_revision"].includes(String(value.kind));
}

/** Validate response shape and the current caller/page binding, never authority. */
export function parseKnowledgeNativeContext(value: unknown, scope: KnowledgeScope): KnowledgeNativeContext {
  if (!workRecord(value) || !exact(value, ["scope", "as_of", "result_options", "source_options", "configuration_options", "next_cursor"]) || !workRecord(value.scope) || !exact(value.scope, ["category_id", "product_id", "project_id", "principal_id"]) || !instant(value.as_of)) throw new Error("实际结果与原件目录尚未完整取得，请重新读取。");
  const bound = value.scope;
  if (!workUuid(bound.category_id) || !workUuid(bound.product_id) || !workUuid(bound.principal_id) || !(bound.project_id === null || workUuid(bound.project_id)) || bound.category_id !== scope.categoryId || bound.product_id !== scope.productId || bound.principal_id !== scope.principalId || bound.project_id !== (scope.projectId || null)) throw new Error("目录不属于当前本人、品类、型号或项目，旧材料已隐藏。");
  if (!(value.next_cursor === undefined || value.next_cursor === null || nonempty(value.next_cursor))) throw new Error("实际目录的分页位置未核实，请重新读取。");
  if (!Array.isArray(value.result_options) || !value.result_options.every(row => workRecord(row) && exact(row, ["receipt_id", "family", "title", "operation", "subject", "recorded_at", "visibility", "selectable", "reason"]) && workUuid(row.receipt_id) && ["field", "change", "other"].includes(String(row.family)) && nonempty(row.title) && nonempty(row.operation) && workRecord(row.subject) && exact(row.subject, ["kind", "id", "revision"]) && nonempty(row.subject.kind) && workUuid(row.subject.id) && revision(row.subject.revision) && instant(row.recorded_at) && visible(row.visibility) && availability(row)) || !unique(value.result_options.map(row => row.receipt_id))) throw new Error("实际结果回执目录不完整或重复，请重新读取。");
  if (!Array.isArray(value.source_options) || !value.source_options.every(row => workRecord(row) && exact(row, ["ref", "title", "excerpt", "visibility", "selectable", "reason"]) && source(row.ref) && nonempty(row.title) && nonempty(row.excerpt) && visible(row.visibility) && availability(row)) || !unique(value.source_options.map(row => knowledgeNativeSourceKey(row.ref)))) throw new Error("实际原件目录不完整或重复，请重新读取。");
  if (!Array.isArray(value.configuration_options) || !value.configuration_options.every(row => workRecord(row) && exact(row, ["ref", "name", "selectable", "reason"]) && configuration(row.ref) && nonempty(row.name) && availability(row)) || !unique(value.configuration_options.map(row => knowledgeNativeConfigurationKey(row.ref)))) throw new Error("实际配置目录不完整或重复，请重新读取。");
  return value as KnowledgeNativeContext;
}

export function knowledgeNativeContextKey(context: KnowledgeNativeContext): string {
  return JSON.stringify(context);
}

function selected<T extends Availability>(options: T[], keys: string[], key: (value: T) => string): T[] {
  if (!Array.isArray(keys) || !keys.every(nonempty) || !unique(keys)) throw new Error("所选实际引用重复或不完整，请重新选择。");
  return keys.map(value => {
    const row = options.find(option => key(option) === value);
    if (!row || !knowledgeNativeAvailable(row)) throw new Error("所选记录已不在本次可用目录中，请重新读取后明确选择。");
    return row;
  });
}

export function selectKnowledgeNative(context: KnowledgeNativeContext, scope: KnowledgeScope, keys: KnowledgeNativeKeys): KnowledgeNativeSelection {
  const current = parseKnowledgeNativeContext(context, scope);
  const results = selected(current.result_options, keys.results, row => row.receipt_id);
  const sources = selected(current.source_options, keys.sources, row => knowledgeNativeSourceKey(row.ref));
  const configurations = selected(current.configuration_options, keys.configurations, row => knowledgeNativeConfigurationKey(row.ref));
  if (!sources.length) throw new Error("请明确选择至少一条实际原件；结果回执可以不选。");
  const versions = new Map<string, number>();
  for (const { ref } of sources) {
    if (versions.has(ref.id) && versions.get(ref.id) !== ref.revision) throw new Error("所选原件包含同一对象的不同版本，请重新选择。");
    versions.set(ref.id, ref.revision);
  }
  return {
    context_key: knowledgeNativeContextKey(current),
    result_receipts: results.map(row => ({ receipt_id: row.receipt_id })),
    sources: sources.map(row => ({ ...row.ref })),
    configurations: configurations.map(row => ({ ...row.ref })),
  };
}

/** Preserve the candidate's title, audience, project and applicability hypothesis. */
export function knowledgeNativeDraftPatch(selection: KnowledgeNativeSelection, context: KnowledgeNativeContext, scope: KnowledgeScope): Pick<CandidateDraft, "sources" | "result_receipts"> {
  const current = parseKnowledgeNativeContext(context, scope);
  if (selection.context_key !== knowledgeNativeContextKey(current)) throw new Error("实际目录已刷新，不能沿用旧选择。请按当前固定版本重新选择。");
  const checked = selectKnowledgeNative(current, scope, {
    results: selection.result_receipts.map(row => row.receipt_id),
    sources: selection.sources.map(knowledgeNativeSourceKey),
    configurations: selection.configurations.map(knowledgeNativeConfigurationKey),
  });
  if (JSON.stringify(checked) !== JSON.stringify(selection)) throw new Error("所选固定引用与实际目录不一致，请重新选择。");
  return { result_receipts: JSON.stringify(checked.result_receipts), sources: JSON.stringify(checked.sources) };
}
