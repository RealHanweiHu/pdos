import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const headers = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });

/** Metadata-only read; page entry never creates a query embedding or background batch. */
export async function embeddingSettingsRead(request: NextRequest, categoryId: string) {
  if (request.method !== "GET") return new Response(null, { status: 405, headers: { ...headers, Allow: "GET" } });
  if (!uuid.test(categoryId)) return error("Embedding 设置范围不可用。", 404, "NOT_FOUND");
  const query = new URLSearchParams();
  for (const [key, value] of request.nextUrl.searchParams) {
    if (query.has(key) || !(key === "after" && uuid.test(value) || key === "page_size" && /^(?:[1-9]|[1-9][0-9]|100)$/.test(value))) return error("Embedding 记录分页条件无效。", 422);
    query.set(key, value);
  }
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return error("请进入有效会话。", 401, "FORBIDDEN_SCOPE");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return error("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  try {
    const response = await fetch(`${base}/v1/categories/${categoryId}/embedding-profile${query.size ? `?${query}` : ""}`, {
      method: "GET", headers: { Authorization: `Bearer ${token}` }, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(60000),
    });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" } });
  } catch { return error("Embedding 设置暂不可读，请重新读取。", 503, "SOURCE_UNAVAILABLE"); }
}
