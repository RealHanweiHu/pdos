// D98/D282: BOM version difference, rule card and import conversion as the server returns
// them. The page only displays; difference, rules and conversion are computed by the server.
import type { DefinitionReference } from "@/lib/product-view";
import type { SourceRead } from "@/lib/project-plan-view";

export type BomSnapshot = {
  part: string; part_id: string | null; part_revision: number | null; quantity: string | null; unit: string | null;
  loss_rate: string | null; critical: boolean | null; notes: string | null; reference_designators: string[];
};
export type BomDiffLine = {
  key: string; change: "added" | "removed" | "changed"; fields: string[]; before: BomSnapshot | null; after: BomSnapshot | null;
  designators?: { added: string[]; removed: string[] };
};
export type BomDiff = { summary: { added: number; removed: number; changed: number; unchanged: number }; lines: BomDiffLine[] };
export type RulePlace = { key?: string | null; row?: number };
export type RuleItem = RulePlace & { level: "warn" | "fail"; designator?: string; lines?: RulePlace[]; quantity?: string; designators?: number; problem?: string; value?: string };
export type RuleStatus = "pass" | "warn" | "fail" | "not_applicable";
export type BomRule = { code: string; title: string; status: RuleStatus; count: number; items: RuleItem[]; explanation: string };
export type RuleCard = { ruleset: string; status: RuleStatus; lines: number; rules: BomRule[]; basis: string };
export type BomHeader = { id: string | null; name: string; revision: number; visibility?: string; reason?: string | null; created_at?: string; source_status?: string; lines: number };
export type ImportRecord = {
  converter: string; artifact_id: string; expected_revision: number; format: "xlsx" | "csv"; sheet: string | null; header_row: number;
  columns: { field: string; column: number }[]; rows: Record<string, number>; skipped: { row: number; reason: string | null }[];
  ignored_rows: number; unmapped_columns: { column: number; header: string | null }[];
};
export type BomReview = { bom: BomHeader; previous: BomHeader | null; diff: BomDiff; rules: RuleCard; import_basis: ImportRecord | null };

export type ImportColumn = { field: string; column: number };
export type Disposition = { row: number; action: "skip" | "new_part" | "reuse"; part_id?: string | null; expected_part_revision?: number | null; reason?: string | null };
export type ImportIssue = { code: string; message: string; column?: number; row?: number };
export type ImportRow = {
  row: number; status: "ready" | "skipped" | "needs_disposition"; issues: ImportIssue[]; allowed: Disposition["action"][];
  hints: { part_id: string; revision: number; label: string }[]; disposition: Disposition | null; key?: string; part?: string | null;
  resolution?: "new_part" | "matched_internal" | "reuse"; reason?: string; values: Record<string, unknown>;
};
export type ImportPayload = { lines: Record<string, unknown>[]; import_basis: Record<string, unknown>; sources: DefinitionReference[]; required_source_read_set: SourceRead[] };
export type ImportResult = {
  converter: string; format: "xlsx" | "csv"; sheets: string[]; sheet: string | null; header_row: number;
  headers: { column: number; text: string }[]; fields: { field: string; title: string }[]; suggested: boolean;
  columns: (ImportColumn & { header?: string | null })[]; previous: BomHeader | null; artifact: { id: string; revision: number };
  basis_error?: string; complete: boolean; unmapped_columns?: { column: number; header: string | null }[]; rows?: ImportRow[];
  counts?: { ready: number; skipped: number; needs_disposition: number; ignored: number }; issues?: ImportIssue[];
  rules?: RuleCard; diff?: BomDiff; payload?: ImportPayload | null;
};

export const fieldTitles: Record<string, string> = {
  part: "物料", part_revision: "物料版本", quantity: "用量", unit: "单位", loss_rate: "损耗率",
  critical: "关键件", notes: "备注", reference_designators: "位号",
};
export const changeTitles = { added: "新增", removed: "删除", changed: "修改" } as const;
export const ruleStatusTitles: Record<RuleStatus, string> = { pass: "通过", warn: "提示", fail: "未通过", not_applicable: "不适用" };
export const actionTitles: Record<Disposition["action"], string> = { skip: "跳过本行", new_part: "建新物料", reuse: "关联已有物料" };

export function place(item: RulePlace): string {
  return item.row !== undefined ? `原件第 ${item.row} 行` : `行 ${item.key ?? ""}`;
}

export function ruleItemText(rule: BomRule, item: RuleItem): string {
  if (rule.code === "duplicate_designator") return `${item.designator}：${(item.lines ?? []).map(place).join("、")}`;
  if (rule.code === "designator_quantity_mismatch") return `${place(item)}：用量 ${item.quantity}，位号 ${item.designators} 个`;
  if (rule.code === "missing_unit") return `${place(item)}：${item.level === "fail" ? "有用量但没有单位" : "用量与单位都未知"}`;
  if (rule.code === "quantity") return `${place(item)}：${item.problem === "unknown" ? "用量未知" : item.problem === "non_positive" ? `数量 ${item.value} 不是正数` : `数量 ${item.value} 无法识别`}`;
  return place(item);
}

export function valueText(field: string, snapshot: BomSnapshot | null): string {
  if (!snapshot) return "—";
  const value = snapshot[field as keyof BomSnapshot];
  if (field === "reference_designators") return (value as string[]).length ? (value as string[]).join("、") : "未填";
  if (field === "critical") return value ? "是" : "否";
  if (field === "part_revision") return value === null || value === undefined ? "新物料" : `v${value}`;
  return value === null || value === undefined || value === "" ? "未知" : String(value);
}

export function quantityText(snapshot: BomSnapshot | null): string {
  if (!snapshot) return "—";
  return snapshot.quantity === null ? "用量未知" : `${snapshot.quantity} ${snapshot.unit ?? ""}`.trim();
}

const isObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const summaryShape = (value: unknown) => isObject(value) && ["added", "removed", "changed", "unchanged"].every(key => Number.isInteger(value[key]));

export function isDiff(value: unknown): value is BomDiff {
  return isObject(value) && summaryShape(value.summary) && Array.isArray(value.lines)
    && value.lines.every(line => isObject(line) && typeof line.key === "string" && ["added", "removed", "changed"].includes(String(line.change)) && Array.isArray(line.fields));
}
export function isRuleCard(value: unknown): value is RuleCard {
  return isObject(value) && typeof value.ruleset === "string" && Array.isArray(value.rules)
    && value.rules.every(rule => isObject(rule) && typeof rule.code === "string" && typeof rule.title === "string" && Array.isArray(rule.items) && String(rule.status) in ruleStatusTitles);
}
export function isReview(value: unknown): value is BomReview {
  return isObject(value) && isObject(value.bom) && (value.previous === null || isObject(value.previous)) && isDiff(value.diff) && isRuleCard(value.rules);
}

/** Rows still waiting for a named per-row decision, with the actions the server allows. */
export function pendingRows(result: ImportResult | null): ImportRow[] {
  return (result?.rows ?? []).filter(row => row.status === "needs_disposition");
}

export function importRequest(input: {
  artifactId: string; revision: number; sheet: string | null; headerRow: number | null; columns: ImportColumn[] | null;
  dispositions: Disposition[]; previous: { id: string; revision: number } | null; visibility: string;
}) {
  return {
    artifact_id: input.artifactId, expected_revision: input.revision, sheet: input.sheet, header_row: input.headerRow,
    columns: input.columns, dispositions: input.dispositions.map(d => ({ row: d.row, action: d.action, part_id: d.action === "reuse" ? d.part_id ?? null : null, expected_part_revision: d.action === "reuse" ? d.expected_part_revision ?? null : null, reason: d.reason?.trim() || null })),
    previous_id: input.previous?.id ?? null, expected_previous_revision: input.previous?.revision ?? null, visibility: input.visibility,
  };
}

export function mergeReads(...groups: SourceRead[][]): SourceRead[] {
  const reads = new Map<string, SourceRead>();
  for (const read of groups.flat()) {
    const known = reads.get(read.artifact_id);
    if (known && known.expected_revision !== read.expected_revision) throw new Error("同一资料被固定在不同版本，请刷新后重新转换。");
    reads.set(read.artifact_id, read);
  }
  return [...reads.values()].sort((a, b) => a.artifact_id.localeCompare(b.artifact_id));
}

/** The engineering.bom.revise request whose lines are exactly the server conversion. */
export function importCommand(input: {
  productId: string; productRevision: number; name: string; reason: string; visibility: string;
  previous: { id: string; revision: number; required_source_read_set: SourceRead[] } | null; result: ImportResult;
}) {
  const payload = input.result.payload;
  if (!input.result.complete || !payload) throw new Error("还有未处置的行，处置后重新转换。");
  const name = input.name.trim(), reason = input.reason.trim();
  if (name.length < 2 || reason.length < 3) throw new Error("请填写 BOM 名称（至少 2 字）和导入原因（至少 3 字）。");
  return {
    command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: "engineering.bom.revise" as const,
    product_id: input.productId, expected_revision: input.productRevision,
    source_read_set: mergeReads(input.previous?.required_source_read_set ?? [], payload.required_source_read_set),
    payload: {
      name, reason, visibility: input.visibility, previous_id: input.previous?.id ?? null,
      expected_previous_revision: input.previous?.revision ?? null, sources: payload.sources, lines: payload.lines, import_basis: payload.import_basis,
    },
  };
}
