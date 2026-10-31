import { cookies } from "next/headers";
import { NextRequest } from "next/server";
import { sameOrigin } from "@/lib/request-origin";
import { loadLocalPreview, localPreviewHost, workspacePreview } from "@/lib/local-preview-server";

export async function POST(request: NextRequest) {
  if (!localPreviewHost(request.headers.get("host")) || !sameOrigin(request)) return Response.json({ message: "此入口只接受本机预览页面的操作。" }, { status: 403 });
  try {
    const config = await loadLocalPreview(request.headers.get("host"));
    if (!config) return Response.json({ message: "综合预览未启用。" }, { status: 404 });
    const input = await request.json();
    const workspace = workspacePreview(config);
    if (workspace && (input.mode !== "workspace" || Object.keys(input).some(key => key !== "mode"))) return Response.json({ message: "产品预览使用同一个演示身份，请从工作台进入。" }, { status: 400 });
    const selected = config.cases.find(item => item.id === input.caseId);
    const role = workspace?.role ?? config.roles.find(item => item.id === input.roleId && item.caseId === selected?.id && selected.roleIds.includes(item.id));
    const entry = workspace ?? selected?.entries.find(item => item.id === input.entryId);
    if (!role || !entry || !entry.href.startsWith("/?")) return Response.json({ message: "请选择此案例的演示身份和入口。" }, { status: 400 });
    const base = process.env.PDOS_NEXT_API_URL;
    if (!base || !localPreviewHost(new URL(base).host)) return Response.json({ message: "本地预览服务未配置。" }, { status: 503 });
    const response = await fetch(`${base}/v1/session`, { headers: { Authorization: `Bearer ${role.token}` }, cache: "no-store", signal: AbortSignal.timeout(8000) });
    if (!response.ok) return Response.json({ message: "演示会话已失效，请重新准备预览。" }, { status: 401 });
    const identity = await response.json();
    // Principal IDs are globally unique; the API binds the tenant from its login record.
    if (identity.principal_id !== role.principalId) return Response.json({ message: "演示身份与服务器记录不匹配。" }, { status: 409 });
    (await cookies()).set("pdos-next-session", role.token, { httpOnly: true, sameSite: "strict", path: "/", maxAge: Math.min(86400, Math.floor((Date.parse(config.expires_at) - Date.now()) / 1000)), secure: request.nextUrl.protocol === "https:" });
    return Response.json({ href: entry.href });
  } catch {
    return Response.json({ message: "预览服务暂不可用或配置已过期，请稍后重试。" }, { status: 503 });
  }
}
