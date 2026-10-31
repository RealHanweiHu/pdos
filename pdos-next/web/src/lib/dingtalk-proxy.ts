import { cookies } from "next/headers";
import type { NextRequest } from "next/server";
import { sameOrigin } from "@/lib/request-origin";
import { dingMethod, dingPaths, validDingBody } from "./dingtalk";

const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
const error = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers });
export async function dingtalkRequest(request: NextRequest, path: string) {
  if (!dingPaths(path)) return error("此钉钉入口不可用。", 404, "NOT_FOUND");
  const method = dingMethod(path);
  if (request.method !== method) return error("此入口不支持该请求方式。", 405);
  if (request.nextUrl.searchParams.size) return error("本人绑定与投递不接受外部范围或查询参数。", 422);
  if (method === "POST" && !sameOrigin(request)) return error("请求来源不匹配。", 403, "FORBIDDEN_SCOPE");
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return error("请先进入本人有效会话。", 401, "FORBIDDEN_SCOPE");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return error("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  let body: string | undefined;
  if (method === "POST") {
    body = await request.text();
    if (body.length > 16384) return error("请求过长。", 422);
    try { if (!validDingBody(path, JSON.parse(body))) return error("请仅提交本人选择的固定操作。", 422); } catch { return error("请求正文无效。", 422); }
  }
  try {
    const response = await fetch(`${base}/${path}`, { method, body, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(60000) });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...headers, "Content-Type": "application/json" } });
  } catch { return error(method === "GET" ? "暂未读取到当前设置，请重新读取。" : "尚未取得操作回执。先读取当前状态；分享与撤绑保留原请求重试，授权码勿重复使用。", 503, method === "GET" ? "SOURCE_UNAVAILABLE" : "EXTERNAL_OUTCOME_UNKNOWN"); }
}
