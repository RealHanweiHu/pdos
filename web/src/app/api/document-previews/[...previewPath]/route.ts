import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";
type Context = { params: Promise<{ previewPath: string[] }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export async function GET(request: Request, context: Context) {
  const path = (await context.params).previewPath;
  const shapes = [["projects", "#", "compare"], ["projects", "#", "#"], ["projects", "#", "#", "original"], ["projects", "#", "#", "text"], ["projects", "#", "#", "email-text"]];
  if (!shapes.some(shape => shape.length === path.length && shape.every((part,i) => part === "#" ? uuid.test(path[i]) : part === path[i]))) return sessionError(404, "PREVIEW_NOT_FOUND", "资料查看入口不存在");
  const token = await currentSessionToken(); if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "请先登录");
  try {
    const input = new URL(request.url).searchParams, query = new URLSearchParams();
    for (const key of path.at(-1) === "compare" ? ["left", "right", "left_page", "right_page"] : path.at(-1) === "email-text" ? ["after_ordinal"] : ["page", "offset"]) { const value = input.get(key); if (value) query.set(key,value); }
    const upstream = await pdosApiFetch(`/api/document-previews/${path.map(encodeURIComponent).join("/")}${query.size ? `?${query}` : ""}`, { headers: { Authorization: `Bearer ${token}` } }, 60000);
    if (path.at(-1) === "original" && upstream.ok) {
      const headers = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
      for (const key of ["content-type", "content-length", "content-disposition", "x-document-sha256", "x-document-pages"]) { const value = upstream.headers.get(key); if (value) headers.set(key,value); }
      return new Response(upstream.body, { status: upstream.status, headers });
    }
    return forwardJson(upstream);
  } catch { return sessionError(503, "PREVIEW_UNAVAILABLE", "原件暂不可读取，请稍后重试"); }
}
