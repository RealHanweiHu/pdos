import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; action: string }> };

/** Free-zone scan and confirm-zone batch promotion (V1-A6 / V1-C1). */
const allowedActions = new Set(["scan", "confirm-batch", "batches"]);

export async function POST(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { projectId, action } = await context.params;
    if (!allowedActions.has(action)) {
      return sessionError(404, "RISK_ACTION_NOT_FOUND", "Risk candidate action not found");
    }
    const authorization = { Authorization: `Bearer ${token}` };
    const init: RequestInit = { method: "POST", headers: authorization };
    if (action === "confirm-batch" || action === "batches") {
      const payload = await readBoundedJson(request);
      init.headers = { ...authorization, "Content-Type": "application/json" };
      init.body = JSON.stringify(payload);
    }
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/risk-candidates/${action}`,
        init,
      ),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded risk request is required");
    }
    return sessionError(503, "RISK_SERVICE_UNAVAILABLE", "Risk service unavailable");
  }
}
