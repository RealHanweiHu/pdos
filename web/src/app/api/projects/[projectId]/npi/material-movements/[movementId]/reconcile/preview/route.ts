import {
  currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch,
  readBoundedJson, sessionError,
} from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; movementId: string }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const { projectId, movementId } = await context.params;
  if (![projectId, movementId].every(id => uuid.test(id))) {
    return sessionError(400, "INVALID_RECONCILIATION_REFERENCE", "Invalid material reconciliation reference");
  }
  try {
    const body = JSON.stringify(await readBoundedJson(request));
    return forwardJson(await pdosApiFetch(
      `/api/projects/${projectId}/npi/material-movements/${movementId}/reconcile/preview`,
      { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body },
    ));
  } catch (error) {
    return sessionError(error instanceof InvalidRequestBodyError ? 400 : 503,
      "RECONCILIATION_PREVIEW_UNAVAILABLE", "余额核对预览未完成，请保留输入后重试");
  }
}
