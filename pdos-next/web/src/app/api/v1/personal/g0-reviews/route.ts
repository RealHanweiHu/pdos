import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });

/** A personal read: requester, tenant and active named assignment belong to the API. */
export async function GET(request: NextRequest) {
  const query = new URLSearchParams();
  for (const [key, value] of request.nextUrl.searchParams) {
    const valid = key === "cursor" ? uuid.test(value) : key === "page_size" && /^[1-9]\d*$/.test(value) && Number(value) <= 100;
    if (!valid || query.has(key)) return error("请只提供有效的个人评审分页条件。", 422);
    query.set(key, value);
  }
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return error("请进入有效会话。", 401, "FORBIDDEN_SCOPE");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return error("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  try {
    const response = await fetch(`${base}/v1/personal/g0-reviews${query.size ? `?${query}` : ""}`, {
      method: "GET", headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      signal: AbortSignal.timeout(60000), redirect: "error",
    });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" } });
  } catch { return error("暂未读取到当前具名评审，请重新读取。", 503, "SOURCE_UNAVAILABLE"); }
}
