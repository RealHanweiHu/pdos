"use client";

type Reference = { kind: string; id: string; revision: number | null; receipt_id: string | null; url: string };
type Basis = { version: "project-current-facts/v1" | "project-current-facts/v2"; as_of: string; currentness: "current" | "updated"; complete: boolean; missing: string[]; references: Reference[]; notice?: string };
const labels: Record<string, string> = { project: "项目", definition: "固定定义", release_package: "发布包", plan: "计划", plan_task: "计划任务", work_task: "任务", project_open_item: "项目事项", project_status_update: "具名状态", project_governance: "阶段与门禁", work_commitment: "承诺", release_decision: "专业签核", release_exception: "例外决定" };
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function projectBasisHref(value: unknown): string | null {
  if (typeof value !== "string" || !value.startsWith("/?") || value.length > 1000) return null;
  const params = new URLSearchParams(value.slice(2));
  const keys = new Set(["area", "category", "product", "project", "projectView"]);
  if ([...params.keys()].some(key => !keys.has(key) || params.getAll(key).length !== 1) || params.get("area") !== "cockpit") return null;
  if (!["category", "product", "project"].every(key => uuid.test(params.get(key) ?? "")) || !["now", "gates", "tasks"].includes(params.get("projectView") ?? "")) return null;
  return value;
}
function basis(value: unknown): Basis | null {
  if (!object(value) || (value.version !== "project-current-facts/v1" && value.version !== "project-current-facts/v2") || typeof value.as_of !== "string" || value.as_of.length > 64 || !Number.isFinite(Date.parse(value.as_of)) || !["current", "updated"].includes(String(value.currentness)) || typeof value.complete !== "boolean" || !Array.isArray(value.references) || value.references.length > 256 || !Array.isArray(value.missing)) return null;
  const references: Reference[] = [];
  for (const ref of value.references) {
    if (!object(ref) || typeof ref.kind !== "string" || !Object.hasOwn(labels, ref.kind) || typeof ref.id !== "string" || !uuid.test(ref.id) || !(ref.revision === null || Number.isInteger(ref.revision) && Number(ref.revision) > 0) || !(ref.receipt_id === null || typeof ref.receipt_id === "string" && uuid.test(ref.receipt_id)) || !projectBasisHref(ref.url)) return null;
    references.push(ref as Reference);
  }
  return { version: value.version, as_of: value.as_of, currentness: value.currentness as Basis["currentness"], complete: value.complete, missing: value.missing.filter((row): row is string => typeof row === "string").slice(0, 20), references };
}

/** Native object/version proof; this is separate from enterprise retrieval citations. */
export function ProjectCurrentBasis({ value }: { value: unknown }) {
  const actual = basis(value);
  if (!actual) return null;
  const references = actual.references.filter((ref, index, rows) => rows.findIndex(row => row.kind === ref.kind && row.id === ref.id && row.revision === ref.revision) === index);
  return <details className="mt-3 text-sm break-words">
    <summary>已读项目当前记录 · 截至 <time dateTime={actual.as_of}>{actual.as_of}</time></summary>
    {actual.currentness === "updated" && <p role="status">项目记录已更新；保留本回答原版本，当前事实请重新读取。</p>}
    {!actual.complete && <p role="status">本次记录有未读取或不可用部分；未知项保留，请到项目核对。</p>}
    <ul className="mt-2 space-y-1">{references.map(ref => <li key={`${ref.kind}:${ref.id}:${ref.revision}`}><a href={ref.url} className="underline underline-offset-4" title="打开当前项目；本回答保留所列固定记录及版本">{labels[ref.kind]} · {ref.id}{ref.revision !== null ? ` · v${ref.revision}` : ""}</a>{ref.receipt_id && <span> · 回执 {ref.receipt_id}</span>}</li>)}</ul>
  </details>;
}
