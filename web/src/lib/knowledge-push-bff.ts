import {
  currentSessionToken,
  readBoundedJson,
  InvalidRequestBodyError,
  forwardJson,
  pdosApiFetch,
  sessionError,
} from "@/lib/pdos-api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CONTEXT_KIND = /^[a-z_]{1,32}$/;

/**
 * Cross-project knowledge push (V1-B9).
 *
 * The two query parameters are re-validated here with the same shapes the
 * server declares, so a malformed context never becomes a backend 422 the user
 * has to interpret.
 */
export async function forwardKnowledgePush(request: Request, projectId: string, prepared = false) {
  const url = new URL(request.url);
  const contextKind = url.searchParams.get("context_kind") ?? "";
  const contextEntityId = url.searchParams.get("context_entity_id") ?? "";
  if (!CONTEXT_KIND.test(contextKind) || !UUID.test(contextEntityId)) {
    return sessionError(400, "INVALID_PUSH_CONTEXT", "Knowledge push context is invalid");
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const query = new URLSearchParams({
    context_kind: contextKind,
    context_entity_id: contextEntityId,
  });
  if (prepared && url.searchParams.has("job_id")) {
    const jobId = url.searchParams.get("job_id") ?? "";
    if (!UUID.test(jobId)) return sessionError(400, "INVALID_REQUEST", "请选择有效的准备记录");
    query.set("job_id", jobId);
  }
  try {
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/${prepared ? "knowledge-prepared" : "knowledge-push"}?${query}`,
        { method: "GET", headers: { Authorization: `Bearer ${token}` } },
      ),
    );
  } catch {
    return sessionError(
      503,
      "KNOWLEDGE_PUSH_UNAVAILABLE",
      "Knowledge push is unavailable",
    );
  }
}

export async function forwardPushMetrics() {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    return forwardJson(
      await pdosApiFetch("/api/knowledge/push-metrics", {
        method: "GET",
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  } catch {
    return sessionError(
      503,
      "KNOWLEDGE_PUSH_UNAVAILABLE",
      "Knowledge push is unavailable",
    );
  }
}

export async function forwardEngage(pushId: string) {
  if (!UUID.test(pushId)) {
    return sessionError(404, "PUSH_NOT_FOUND", "Knowledge push was not found");
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    return forwardJson(
      await pdosApiFetch(
        `/api/knowledge/pushes/${encodeURIComponent(pushId)}/engage`,
        { method: "POST", headers: { Authorization: `Bearer ${token}` } },
      ),
    );
  } catch {
    return sessionError(
      503,
      "KNOWLEDGE_PUSH_UNAVAILABLE",
      "Knowledge push is unavailable",
    );
  }
}


export async function forwardKnowledgeFeedback(request: Request, pushId: string) {
  if (!UUID.test(pushId)) return sessionError(404, "PUSH_NOT_FOUND", "Knowledge push was not found");
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = await readBoundedJson(request, 32_768);
    return forwardJson(await pdosApiFetch(`/api/knowledge/pushes/${encodeURIComponent(pushId)}/feedback`, {
      method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "请提交完整的使用反馈");
    return sessionError(503, "KNOWLEDGE_FEEDBACK_UNAVAILABLE", "使用反馈暂不可用");
  }
}
