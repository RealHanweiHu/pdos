import { cookies } from "next/headers";
import { NextRequest } from "next/server";
import { sameOrigin } from "@/lib/request-origin";

export async function POST(request: NextRequest) {
  if (!["localhost", "127.0.0.1"].includes(request.nextUrl.hostname)) return Response.json({ message: "此会话仅供本机合成预览。" }, { status: 403 });
  if (!sameOrigin(request)) return Response.json({ message: "请求来源不匹配。" }, { status: 403 });
  const token = process.env.PDOS_NEXT_LOCAL_SESSION;
  const base = process.env.PDOS_NEXT_API_URL;
  if (!token || !base || !["localhost", "127.0.0.1"].includes(new URL(base).hostname)) {
    return Response.json({ message: "本地合成会话尚未配置。" }, { status: 503 });
  }
  try {
    const response = await fetch(`${base}/v1/session`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(5000) });
    if (!response.ok) return Response.json({ message: "会话已失效。" }, { status: 401 });
    (await cookies()).set("pdos-next-session", token, { httpOnly: true, sameSite: "strict", path: "/", maxAge: 86400, secure: request.nextUrl.protocol === "https:" });
    return Response.json({ status: "ok" });
  } catch { return Response.json({ message: "本地服务暂不可用。" }, { status: 503 }); }
}
