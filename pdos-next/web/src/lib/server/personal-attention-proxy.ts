import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });

/** Personal metadata read only; identity and current source access belong to the API. */
export async function personalAttentionRead(request: NextRequest) {
  if (request.method !== "GET") return new Response(null, { status: 405, headers: { ...headers, Allow: "GET" } });
  const query = new URLSearchParams();
  for (const [key, value] of request.nextUrl.searchParams) {
    const valid = key === "queue" ? ["decide", "receive", "verify", "external"].includes(value)
      : key === "page_size" ? /^(?:[1-9]|1[0-9]|20)$/.test(value)
      : key === "cursor" ? /^[A-Za-z0-9_-]{1,2048}$/.test(value)
      : false;
    if (!valid || query.has(key)) return error("请只提供有效且唯一的个人注意项分组与分页条件。", 422);
    query.set(key, value);
  }
  if (!query.has("queue")) return error("请选择个人注意项分组。", 422);
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return error("请进入有效会话。", 401, "FORBIDDEN_SCOPE");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return error("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  try {
    const response = await fetch(`${base}/v1/personal/attention?${query}`, {
      method: "GET", headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      signal: AbortSignal.timeout(60000), redirect: "error",
    });
    return new Response(await response.arrayBuffer(), {
      status: response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch { return error("暂未读取到个人注意项，请重新读取。", 503, "SOURCE_UNAVAILABLE"); }
}
