import { cookies } from "next/headers";
import type { NextRequest } from "next/server";
import { sameOrigin } from "./request-origin";
import { uuid, validSimilarFeedback } from "./similar-history";

type Scope = { categoryId: string; productId: string; issueId?: string; changeId?: string };
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });
export async function similarHistoryProxy(request: NextRequest, params: Promise<Scope>, feedback = false, kind: "issue" | "change" = "issue") {
  const { categoryId, productId, issueId, changeId } = await params;
  const objectId = kind === "change" ? changeId : issueId;
  if (![categoryId, productId, objectId].every(uuid)) return error("记录范围无效。", 422);
  let suffix = "", body: unknown;
  if (feedback) {
    if (!sameOrigin(request)) return error("请从当前站点记录反馈。", 403, "FORBIDDEN_SCOPE");
    if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") return error("反馈格式无效。", 422);
    if (request.nextUrl.searchParams.size) return error("反馈不接受其他身份或范围。", 422);
    try { const raw = await request.text(); if (raw.length > 4096) return error("反馈过长。", 422); body = JSON.parse(raw); } catch { return error("反馈格式无效。", 422); }
    if (!validSimilarFeedback(body)) return error("请只提交当前卡片的明确动作。", 422);
    if (kind === "change" && body.action === "merge_prepared") return error("变更不支持问题归并。", 422);
    suffix = "/feedback";
  } else {
    const query = request.nextUrl.searchParams;
    if ([...query.keys()].length !== 1 || !uuid(query.get("version_id"))) return error("请选择固定记录版本。", 422);
    suffix = `?version_id=${encodeURIComponent(query.get("version_id")!)}`;
  }
  return forward(categoryId, productId, `${kind === "change" ? "change-execution" : "quality-issues"}/${objectId}/similar-history${suffix}`, feedback, body);
}

export async function similarHistorySuggestionsProxy(request: NextRequest, params: Promise<Pick<Scope, "categoryId" | "productId">>) {
  const { categoryId, productId } = await params;
  if (![categoryId, productId].every(uuid)) return error("查询范围无效。", 422);
  const query = request.nextUrl.searchParams, keys = [...query.keys()];
  const kind = query.get("kind"), title = query.get("title")?.trim(), project = query.get("project_id");
  if (new Set(keys).size !== keys.length || keys.some(key => !["kind", "title", "project_id"].includes(key))
    || !["issue", "change"].includes(kind ?? "") || !title || [...title].length > 240
    || (query.has("project_id") && !uuid(project))) return error("请提供当前标题及有效项目范围，标题不超过240字符。", 422);
  const bounded = new URLSearchParams({ kind: kind!, title });
  if (project) bounded.set("project_id", project);
  return forward(categoryId, productId, `similar-history?${bounded}`);
}

async function forward(categoryId: string, productId: string, path: string, feedback = false, body?: unknown) {
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return error("请进入有效会话。", 401, "UNAUTHENTICATED");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return error("服务暂未配置。", 503, "SOURCE_UNAVAILABLE");
  try {
    const response = await fetch(`${base}/v1/categories/${categoryId}/products/${productId}/${path}`, {
      method: feedback ? "POST" : "GET", cache: "no-store", redirect: "error", signal: AbortSignal.timeout(60000),
      headers: { Authorization: `Bearer ${token}`, ...(feedback ? { "Content-Type": "application/json" } : {}) },
      body: feedback ? JSON.stringify(body) : undefined,
    });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" } });
  } catch { return error("相似历史暂不可读，请稍后重试。", 503, "SOURCE_UNAVAILABLE"); }
}
