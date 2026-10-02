import { parseWorkFocus, type WorkFocus } from "./conversation-work-focus";
import type { ProductConversationScope, ProductConversationSource, MatrixSelection } from "./product-conversation";

const pageLabels: Record<string, string> = {
  "/": "驾驶舱", "/my-work": "我的工作", "/projects": "项目", "/product-work": "产品工作",
  "/portfolio": "项目组合", "/knowledge": "知识库", "/ai-review": "AI 待办",
  "/requirements": "需求池", "/cases": "开发案例",
  "/search": "搜索", "/capture": "资料采集", "/settings": "设置",
};
export type XiaopaiPageContext = {
  href: string;
  label: string;
  projectId: string;
  spaceId: string;
  lineId?: string;
  tab?: string;
  productScope?: ProductConversationScope;
  productSources?: ProductConversationSource[];
  scopeError?: string;
  matrixSelection?: MatrixSelection;
  focus?: WorkFocus;
};

// Only our own workspace routes can become page context. This is a hint;
// every actual project/object read is authorized again by the server.
export function resolveXiaopaiPageContext(path: string, params: URLSearchParams, hash = ""): XiaopaiPageContext {
  const label = pageLabels[path] ?? (path.startsWith("/settings/") ? "设置" : "当前页面");
  const focus = parseWorkFocus(params.get("focus_kind"), params.get("focus_id")) ??
    ["task", "issue", "risk", "capa", "gate"].map(kind => parseWorkFocus(kind, params.get(kind) ?? params.get(`${kind}_id`))).find(Boolean);
  const spaceId = path === "/product-work" ? params.get("space") ?? "" : "";
  const lineId = path === "/product-work" ? params.get("line") ?? "" : "";
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const recordId = path === "/product-work" ? params.get("record_id") : null;
  const invalid = (recordId !== null && !uuid.test(recordId)) || (spaceId && !uuid.test(spaceId)) || (lineId && lineId !== "all" && (!spaceId || !uuid.test(lineId)));
  const object = hash.match(/^#(product|work|research|competitor|segment|opportunity|experiment|strategy|definition|evidence)-(.+)$/);
  const productSources: ProductConversationSource[] = object && uuid.test(object[2]) ? [{ kind: object[1] as ProductConversationSource["kind"], id: object[2] }] : [];
  return {
    href: `${path}${params.size ? `?${params}` : ""}${hash}`,
    label,
    projectId: params.get("project") ?? params.get("project_id") ?? "",
    spaceId, lineId, tab: path === "/product-work" ? params.get("tab") ?? "research" : undefined,
    productScope: invalid ? undefined : spaceId ? { scope_kind: lineId && lineId !== "all" ? "product_line" : "market_space", market_space_id: spaceId, ...(lineId && lineId !== "all" ? { product_line_id: lineId } : {}) } : { scope_kind: "personal" },
    ...(path === "/product-work" && spaceId && recordId && !invalid ? { matrixSelection: { record_id: recordId, roadmap_ids: [] } } : {}),
    productSources: path === "/product-work" && spaceId && !invalid ? productSources : [],
    ...(invalid ? { scopeError: "页面中的市场空间、产品线或矩阵记录编号无效，请先返回产品工作区核对范围。" } : {}),
    focus,
  };
}

export function restoreXiaopaiPageContext(source: string | null): XiaopaiPageContext | null {
  if (!source || !source.startsWith("/") || source.startsWith("//")) return null;
  const url = new URL(source, "https://pdos.invalid");
  if (url.origin !== "https://pdos.invalid" || !(url.pathname in pageLabels || url.pathname.startsWith("/settings/"))) return null;
  return resolveXiaopaiPageContext(url.pathname, url.searchParams, url.hash);
}
