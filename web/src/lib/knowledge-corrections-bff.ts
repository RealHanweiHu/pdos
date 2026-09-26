import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

export async function forwardCorrection(request: Request, projectId: string, segments: string[], method: "GET" | "POST", query?: URLSearchParams) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const path = `/api/projects/${[projectId, ...segments].map(encodeURIComponent).join("/")}${query ? `?${query}` : ""}`;
    const init: RequestInit = { method, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } };
    if (method === "POST") init.body = JSON.stringify(await readBoundedJson(request, 131_072));
    return forwardJson(await pdosApiFetch(path, init, segments.at(-1) === "publish" ? 60_000 : 5_000));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_CORRECTION", "请提交完整的修正内容");
    return sessionError(503, "CORRECTION_UNAVAILABLE", "知识纠错暂不可用，刷新可核对提交结果");
  }
}
