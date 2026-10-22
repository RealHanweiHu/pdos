import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });

/** Exact private read routes; the API owns Session identity, scope and current access. */
export async function paiSessionsRead(request: NextRequest, categoryId?: string, sessionId?: string) {
  if (request.method !== "GET") return new Response(null, { status: 405, headers: { ...headers, Allow: "GET" } });
  if ((categoryId !== undefined && !uuid.test(categoryId)) || (sessionId !== undefined && !uuid.test(sessionId))) return error("此会话入口不可用。", 404, "NOT_FOUND");
  const query = new URLSearchParams();
  for (const [key, value] of request.nextUrl.searchParams) {
    if (query.has(key)) return error("会话查询须使用唯一明确的范围与游标。", 422);
    const valid = key === "page_size" ? /^(?:[1-9]|[1-4][0-9]|50)$/.test(value)
      : key === "cursor" ? uuid.test(value)
      : key === "proposal_id" ? categoryId !== undefined && uuid.test(value)
      : key === "q" ? sessionId === undefined && [...value].length <= 160
      : false;
    if (!valid) return error("请使用有效的会话范围、搜索或分页参数。", 422);
    query.set(key, value);
  }
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return error("请进入有效会话。", 401, "FORBIDDEN_SCOPE");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return error("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  const scope = categoryId === undefined ? "personal" : `categories/${categoryId}`;
  const suffix = sessionId === undefined ? "agent-sessions" : `agent-sessions/${sessionId}/runs`;
  try {
    const response = await fetch(`${base}/v1/${scope}/${suffix}${query.size ? `?${query}` : ""}`, {
      method: "GET", headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      signal: AbortSignal.timeout(60000), redirect: "error",
    });
    return new Response(await response.arrayBuffer(), {
      status: response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch { return error("暂未读取到会话记录，请重新读取。", 503, "SOURCE_UNAVAILABLE"); }
}
