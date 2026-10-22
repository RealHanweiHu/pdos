import { cookies } from "next/headers";
import type { NextRequest } from "next/server";
import { matrixBreaks } from "@/lib/category-matrix";

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });

/** Two exact, read-only routes; scope and document/source permissions remain server owned. */
export async function categoryResearchRead(request: NextRequest, categoryId: string, proposalId?: string) {
  if (request.method !== "GET") return new Response(null, { status: 405, headers: { ...headers, Allow: "GET" } });
  if (!uuid.test(categoryId) || (proposalId !== undefined && !uuid.test(proposalId))) return error("此读取入口不可用。", 404, "NOT_FOUND");
  const query = new URLSearchParams();
  if (proposalId !== undefined) {
    if (request.nextUrl.searchParams.size) return error("用户声音只按当前品类与提案读取。", 422);
  } else {
    for (const [key, value] of request.nextUrl.searchParams) {
      if (key !== "price_breaks") return error("矩阵仅接受价格展示分界。", 422);
      query.append(key, value);
    }
    const values = query.getAll("price_breaks");
    if (values.length) {
      try {
        if (matrixBreaks(values.join(",")).length !== values.length) throw new Error();
      } catch { return error("填写一至十个严格递增的正十进制分界。", 422); }
    }
  }
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return error("请进入有效会话。", 401, "FORBIDDEN_SCOPE");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return error("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  const suffix = proposalId === undefined ? "category-matrix" : `proposals/${proposalId}/voices`;
  try {
    const response = await fetch(`${base}/v1/categories/${categoryId}/${suffix}${query.size ? `?${query}` : ""}`, {
      method: "GET", headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      signal: AbortSignal.timeout(60000), redirect: "error",
    });
    return new Response(await response.arrayBuffer(), {
      status: response.status,
      headers: { ...headers, "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch { return error("暂未读取到当前事实，请重新读取。", 503, "SOURCE_UNAVAILABLE"); }
}
