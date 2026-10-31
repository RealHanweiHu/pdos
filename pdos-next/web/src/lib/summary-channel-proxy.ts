import { cookies } from "next/headers";
import type { NextRequest } from "next/server";
import { sameOrigin } from "./request-origin";

export const summaryChannelPath = (path: string) => /^v1\/personal\/inbox\/(?:summary-channels|summary-deliveries(?:\/[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}\/reconcile)?)$/i.test(path);
export async function summaryChannelRequest(request: NextRequest, path: string) {
  const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
  const error = (message: string, status: number) => Response.json({ code: "VALIDATION_FAILED", message }, { status, headers });
  if (!summaryChannelPath(path)) return error("摘要投递入口不存在。", 404);
  const method = path.endsWith("/reconcile") ? "POST" : "GET";
  if (request.method !== method || request.nextUrl.searchParams.size) return error("请使用本人原投递记录，不提交外部范围。", 405);
  if (method === "POST") { if (!sameOrigin(request)) return error("请求来源不匹配。", 403); try { const raw = await request.text(); if (raw.length > 32 || raw.trim() !== "{}") return error("回执查询不接受发送正文或身份。", 422); } catch { return error("回执查询正文无效。", 422); } }
  const token = (await cookies()).get("pdos-next-session")?.value, base = process.env.PDOS_NEXT_API_URL;
  if (!token) return error("请先进入本人会话。", 401);
  if (!base) return error("服务尚未配置。", 503);
  try { const response = await fetch(`${base}/${path}`, { method, ...(method === "POST" ? { body: "{}" } : {}), headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(60000) }); return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...headers, "Content-Type": "application/json" } }); } catch { return error("暂未读取到摘要投递回执，请稍后只查询原记录。", 503); }
}
