import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

export async function forwardLearning(projectId: string, jobId?: string) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const path = `/api/projects/${encodeURIComponent(projectId)}/knowledge-learning${jobId ? `/${encodeURIComponent(jobId)}/collect` : ""}`;
  try {
    return forwardJson(await pdosApiFetch(path, { method: jobId ? "POST" : "GET", headers: { Authorization: `Bearer ${token}` } }, jobId ? 30_000 : 5_000));
  } catch {
    return sessionError(503, "KNOWLEDGE_LEARNING_UNAVAILABLE", "经验整理暂不可用，请刷新核对处理结果");
  }
}
