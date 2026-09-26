import { currentSessionToken, forwardJson, pdosApiFetch, sessionError, readBoundedJson, InvalidRequestBodyError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; riskId: string; action: string }> };

/** Confirm-zone promotion, its undo, and free-zone dismissal (V1-C1). */
const allowedActions = new Set(["confirm", "unconfirm", "dismiss"]);

export async function POST(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { projectId, riskId, action } = await context.params;
    if (!allowedActions.has(action)) {
      return sessionError(404, "RISK_ACTION_NOT_FOUND", "Risk action not found");
    }
    const payload = action === "unconfirm" && request.body ? await readBoundedJson(request) : undefined;
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/risks/${encodeURIComponent(riskId)}/${action}`,
        { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: payload ? JSON.stringify(payload) : undefined },
      ),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "无效撤销请求");
    return sessionError(503, "RISK_SERVICE_UNAVAILABLE", "Risk service unavailable");
  }
}
