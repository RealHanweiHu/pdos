export type WorkProduct = {
  id: string;
  root_id: string;
  session_id: string;
  run_id: string;
  category_id: string | null;
  kind: "document" | "table";
  title: string;
  body: string;
  revision: number;
  origin: "ai_draft" | "human";
  supersedes_id: string | null;
  created_at: string;
  source_currentness?: "updated";
};
export type WorkProductApi = <T>(path: string, body?: unknown) => Promise<T>;
export type WorkProductRun = { run_id: string; status: string; reverted?: boolean; result?: { summary?: string; result?: Record<string, unknown> | null } | null };

export function hasDocumentResult(run: WorkProductRun) {
  return !run.reverted && run.status === "completed" && typeof run.result?.summary === "string" && run.result.summary.trim().length > 0;
}

export function hasTableResult(run: WorkProductRun) {
  if (!hasDocumentResult(run)) return false;
  // This only offers the action for server-assembled tables. Saving still
  // rechecks the stored Run and source ledger on the server.
  const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
  const assistant = run.result?.result?.assistant;
  if (object(assistant)) {
    const task = assistant.task_result, comparison = assistant.comparison;
    if (object(task) && task.version === 1 && typeof task.format === "string"
      && ["blockers", "cases", "review", "commitments"].includes(task.format)
      && Array.isArray(task.columns) && task.columns.length > 0 && Array.isArray(task.rows) && task.rows.length > 0) return true;
    // An unchanged comparison has zero changes but still saves its comparison
    // table and the server's explicit coverage/unknown row.
    if (object(comparison) && comparison.version === 1 && comparison.format === "comparison" && Array.isArray(comparison.rows)) return true;
  }
  const lines = run.result!.summary!.split("\n").map(line => line.trim()).filter(Boolean);
  return lines.some((line, index) => {
    if (index + 1 >= lines.length || !line.startsWith("|") || !line.endsWith("|")) return false;
    const separator = lines[index + 1];
    return separator.startsWith("|") && separator.includes("-") && !separator.replace(/[|:\-\s]/g, "");
  });
}

export function latestWorkProduct(items: WorkProduct[], runId: string, kind: WorkProduct["kind"]) {
  return items.filter(item => item.run_id === runId && item.kind === kind).sort((a, b) => b.revision - a.revision)[0] ?? null;
}

export function originalWorkProduct(items: WorkProduct[], rootId: string) {
  return items.find(item => item.root_id === rootId && item.revision === 1) ?? null;
}

export async function createWorkProductFromRun(api: WorkProductApi, runId: string, kind: WorkProduct["kind"], title: string | undefined, requestKey: string) {
  return api<WorkProduct>("v1/personal/work-products/from-run", { run_id: runId, kind, title, request_key: requestKey });
}

export async function readWorkProducts(api: WorkProductApi, sessionId: string) {
  const value = await api<{ items: WorkProduct[] }>(`v1/personal/work-products?session_id=${encodeURIComponent(sessionId)}`);
  if (!Array.isArray(value.items) || value.items.some(item => item.session_id !== sessionId || !item.id || !item.root_id || !item.run_id || !item.title || !item.body || !Number.isSafeInteger(item.revision))) throw new Error("成果列表无法完整核对，请重新读取。");
  return value.items;
}

export async function reviseWorkProduct(api: WorkProductApi, current: WorkProduct, title: string, body: string, requestKey: string) {
  return api<WorkProduct>(`v1/personal/work-products/${current.id}/revisions`, { expected_revision: current.revision, title, body, request_key: requestKey });
}
