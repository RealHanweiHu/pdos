// D56 permission-filtered Excel export. The server applies the page's own read
// permission, labels AI-drafted rows and audits each export; this module only
// builds the request and hands the returned file to the browser.

export type ExportKind = "project" | "bom-diff" | "test-summary" | "my-work";
export type ExportScope = { categoryId: string; productId: string };
export type ExportResult = { blob: Blob; filename: string; rows: number | null; aiRows: number | null; aiCells: number | null };
export type ExportFetch = (input: string, init?: RequestInit) => Promise<Response>;

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const parameter: Record<ExportKind, string | null> = { project: "project_id", "bom-diff": "bom_id", "test-summary": "build_id", "my-work": null };
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** The export URL, or null while the scope is not a real fixed object (the button stays disabled). */
export function exportHref(kind: ExportKind, scope?: ExportScope, id?: string): string | null {
  if (kind === "my-work") return "/api/v1/personal/exports/my-work";
  if (!scope || !uuid.test(scope.categoryId) || !uuid.test(scope.productId) || !id || !uuid.test(id)) return null;
  return `/api/v1/categories/${scope.categoryId}/products/${scope.productId}/exports/${kind}?${new URLSearchParams({ [parameter[kind] as string]: id })}`;
}

export function filenameFrom(disposition: string | null, fallback = "导出.xlsx"): string {
  const encoded = disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (!encoded) return fallback;
  try {
    const name = decodeURIComponent(encoded).replace(/[\\/:*?"<>|\r\n\t]+/g, "_").trim();
    return name.toLowerCase().endsWith(".xlsx") ? name : fallback;
  } catch {
    return fallback;
  }
}

const count = (value: string | null) => (value !== null && /^\d+$/.test(value) ? Number(value) : null);

export function exportSummary(result: Pick<ExportResult, "rows" | "aiRows" | "aiCells">): string {
  if (result.rows === null) return "已导出。";
  const ai = (result.aiRows ?? 0) + (result.aiCells ?? 0);
  if (!ai) return `已导出 ${result.rows} 行，不含 AI 起草内容。`;
  const parts = [result.aiRows ? `${result.aiRows} 行 AI 起草` : "", result.aiCells ? `${result.aiCells} 个 AI 起草单元格` : ""].filter(Boolean);
  return `已导出 ${result.rows} 行，其中 ${parts.join("、")}，文件内已逐条标注。`;
}

export async function readExport(fetcher: ExportFetch, href: string): Promise<ExportResult> {
  let response: Response;
  try {
    response = await fetcher(href, { method: "GET", credentials: "same-origin", cache: "no-store" });
  } catch {
    throw new Error("暂未连上服务，未导出。请稍后重试。");
  }
  const type = response.headers.get("Content-Type") ?? "";
  if (!response.ok || !type.startsWith(XLSX)) {
    let message = "导出未完成，请刷新后重试。";
    try {
      const body = await response.json();
      if (body && typeof body.message === "string" && body.message.trim()) message = body.message;
    } catch { /* keep the generic message */ }
    throw new Error(message);
  }
  return {
    blob: await response.blob(),
    filename: filenameFrom(response.headers.get("Content-Disposition")),
    rows: count(response.headers.get("X-PDOS-Export-Rows")),
    aiRows: count(response.headers.get("X-PDOS-Export-AI-Rows")),
    aiCells: count(response.headers.get("X-PDOS-Export-AI-Cells")),
  };
}
