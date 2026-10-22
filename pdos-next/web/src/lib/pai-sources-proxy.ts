import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const headers = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });

/** Exact GET routes for source metadata; no upload, mutation, redirect or inference. */
export async function paiSourcesRead(request: NextRequest, categoryId: string, runId?: string) {
  if (request.method !== "GET") return new Response(null, { status: 405, headers: { ...headers, Allow: "GET" } });
  if (!uuid.test(categoryId) || runId !== undefined && !uuid.test(runId)) return error("来源入口不可用。", 404, "NOT_FOUND");
  const query = new URLSearchParams();
  for (const [key, value] of request.nextUrl.searchParams) {
    if (runId !== undefined || query.has(key)) return error("请使用唯一明确的来源范围。", 422);
    const valid = key === "page_size" ? /^(?:[1-9]|[1-4][0-9]|50)$/.test(value) : ["product_id", "proposal_id", "cursor"].includes(key) && uuid.test(value);
    if (!valid) return error("来源查询范围或游标无效。", 422);
    query.set(key, value);
  }
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return error("请进入有效会话。", 401, "FORBIDDEN_SCOPE");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return error("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  const suffix = runId === undefined ? "agent-input-sources" : `agent-runs/${runId}/source-bindings`;
  try {
    const response = await fetch(`${base}/v1/categories/${categoryId}/${suffix}${query.size ? `?${query}` : ""}`, {
      method: "GET", headers: { Authorization: `Bearer ${token}` }, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(60000),
    });
    return new Response(await response.arrayBuffer(), {
      status: response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch { return error("来源元数据暂不可读，请重新读取。", 503, "SOURCE_UNAVAILABLE"); }
}
