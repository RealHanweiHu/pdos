import { cookies } from "next/headers";

const responseHeaders = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
export const preferenceError = (message: string, status: number, code = "VALIDATION_FAILED") => Response.json({ code, message }, { status, headers: responseHeaders });

export async function preferenceProxy(suffix: string, body?: unknown) {
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return preferenceError("请进入有效会话。", 401, "UNAUTHENTICATED");
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return preferenceError("服务尚未配置。", 503, "SOURCE_UNAVAILABLE");
  try {
    const response = await fetch(`${base}/v1/personal/preferences${suffix}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store", redirect: "error", signal: AbortSignal.timeout(60000),
    });
    return new Response(await response.arrayBuffer(), { status: response.status, headers: { ...responseHeaders, "Content-Type": response.headers.get("Content-Type") ?? "application/json" } });
  } catch { return preferenceError("个人偏好暂不可用，请重新读取。", 503, "SOURCE_UNAVAILABLE"); }
}
