import { cookies } from "next/headers";
import type { NextRequest } from "next/server";

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });

export async function GET(request: NextRequest, context: { params: Promise<{ categoryId: string; entryId: string }> }) {
  const { categoryId, entryId } = await context.params;
  if (!uuid.test(categoryId) || !uuid.test(entryId)) return error("此读取入口不可用。", 404, "NOT_FOUND");
  if (request.nextUrl.searchParams.size) return error("细分关联仅按当前品类与竞品固定版本读取。", 422);
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return error("请进入有效会话。", 401, "FORBIDDEN_SCOPE");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return error("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  try {
    const response = await fetch(`${base}/v1/categories/${categoryId}/competitors/${entryId}/segment-assignment`, {
      method: "GET", headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      signal: AbortSignal.timeout(60000), redirect: "error",
    });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" } });
  } catch { return error("暂未读取到竞品与固定细分，请重新读取。", 503, "SOURCE_UNAVAILABLE"); }
}
