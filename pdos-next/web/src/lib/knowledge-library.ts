import { parseKnowledgeView, type KnowledgeCandidate, type KnowledgeRule, type KnowledgeView } from "./knowledge-experience";
import { workRecord, workUuid, type ProjectWorkApi } from "./project-work";

export type KnowledgeLibraryApi = ProjectWorkApi;
export type KnowledgeLibraryScope = { categoryId: string; principalId: string; productId: string | null };
export type KnowledgeLibraryProduct = Record<string, unknown> & { id: string; category_id: string; visibility: string; name: string; purpose: string; revision: number; status: string };

const text = (value: unknown): value is string => typeof value === "string" && !!value.trim();
const revision = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
function invalid(): never { throw new Error("本品类知识或所选型号的原始读集未能完整核对，请重新读取；不能以其他范围或空列表替代。"); }
function categoryRoot(scope: KnowledgeLibraryScope): string {
  if (!workRecord(scope) || Object.keys(scope).some(key => !["categoryId", "principalId", "productId"].includes(key))
    || !workUuid(scope.categoryId) || !workUuid(scope.principalId) || !(scope.productId === null || workUuid(scope.productId))) invalid();
  return `v1/categories/${scope.categoryId}`;
}
function fixedHistories(rows: (KnowledgeCandidate | KnowledgeRule)[]): boolean {
  const versions = new Set<string>();
  for (const row of rows) {
    const current = row.history.find(version => version.id === row.version_id && version.revision === row.revision);
    if (!current || current.actor_id !== row.author_id || current.created_at !== row.created_at
      || new Set(row.history.map(version => version.revision)).size !== row.history.length) return false;
    for (const [index, version] of row.history.entries()) {
      if (versions.has(version.id) || (index > 0 && row.history[index - 1].revision >= version.revision)) return false;
      versions.add(version.id);
    }
  }
  return true;
}

/** Actual readable product rows only; no first product is selected by this reader. */
export async function readKnowledgeLibraryProducts(api: KnowledgeLibraryApi, scope: KnowledgeLibraryScope): Promise<KnowledgeLibraryProduct[]> {
  const root = categoryRoot(scope), raw = await api<unknown>(`${root}/products`);
  if (!Array.isArray(raw) || !raw.every(row => workRecord(row) && workUuid(row.id) && row.category_id === scope.categoryId
    && revision(row.revision) && text(row.name) && text(row.purpose) && text(row.visibility) && text(row.status))
    || new Set(raw.map(row => row.id)).size !== raw.length) invalid();
  return raw as KnowledgeLibraryProduct[];
}

/** Bounded original view; server usability and fixed references are never recomputed. */
export async function readKnowledgeLibrary(api: KnowledgeLibraryApi, scope: KnowledgeLibraryScope): Promise<KnowledgeView> {
  const root = categoryRoot(scope);
  const raw = await api<unknown>(scope.productId === null ? `${root}/experience` : `${root}/products/${scope.productId}/experience`);
  // The shared parser uses projectId only as an optional filtering constraint.
  const value = parseKnowledgeView(raw, { categoryId: scope.categoryId, principalId: scope.principalId, productId: scope.productId, projectId: "" });
  if (value.projects.length > 100 || value.candidates.length > 100 || value.rules.length > 100
    || value.configurations.filter(row => row.kind === "engineering_configuration").length > 100
    || value.configurations.filter(row => row.kind === "process_revision").length > 100
    || new Set(value.configurations.map(row => `${row.kind}:${row.id}`)).size !== value.configurations.length
    || !fixedHistories(value.candidates) || !fixedHistories(value.rules)) invalid();
  if (scope.productId === null && (value.projects.length || value.configurations.length || value.rules.length
    || value.candidates.some(row => row.project_id !== null))) invalid();
  // A rule can bind a past candidate/configuration absent from these bounded
  // current lists. Its explicit fixed reference must remain that original.
  return value;
}
