import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });

/**
 * D74 live delivery: pass the API's SSE stream through without buffering.
 * Events only say that something changed; content is read through the normal
 * access-checked endpoints. When this stream drops, the page polls every 30 s.
 */
export async function notificationStream(request: NextRequest) {
  if (request.method !== "GET") return new Response(null, { status: 405, headers: { ...headers, Allow: "GET" } });
  const query = new URLSearchParams();
  for (const [key, value] of request.nextUrl.searchParams) {
    const valid = key === "threads" ? value.split(",").length <= 20 && value.split(",").every(item => uuid.test(item))
      : key === "since" ? /^[0-9.]{0,64}$/.test(value)
      : false;
    if (!valid || query.has(key)) return error("实时通知只按本人与可见讨论读取。", 422);
    query.set(key, value);
  }
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return error("请进入有效会话。", 401, "FORBIDDEN_SCOPE");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return error("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  const last = request.headers.get("last-event-id");
  try {
    const response = await fetch(`${base}/v1/personal/notifications/stream${query.size ? `?${query}` : ""}`, {
      method: "GET", cache: "no-store", redirect: "error", signal: request.signal,
      headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream", ...(last && /^[0-9.]{1,64}$/.test(last) ? { "Last-Event-ID": last } : {}) },
    });
    if (!response.ok || !response.body || !(response.headers.get("Content-Type") ?? "").startsWith("text/event-stream")) {
      return new Response(await response.arrayBuffer(), { status: response.ok ? 502 : response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" } });
    }
    return new Response(response.body, { status: 200, headers: { ...headers, "Content-Type": "text/event-stream; charset=utf-8", "X-Accel-Buffering": "no", Connection: "keep-alive" } });
  } catch { return error("实时通知暂不可用，已改为每 30 秒刷新。", 503, "SOURCE_UNAVAILABLE"); }
}
