import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; supplierId: string; recordId: string; operation: string }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function POST(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const { projectId, supplierId, recordId, operation } = await context.params;
  if (![projectId, supplierId, recordId].every(id => uuid.test(id)) || !["preview", "confirm"].includes(operation)) {
    return sessionError(400, "INVALID_SUPPLIER_REPLY", "Invalid supplier reply reference");
  }
  try {
    const body = JSON.stringify(await readBoundedJson(request));
    return forwardJson(await pdosApiFetch(`/api/projects/${projectId}/npi/supplier-replies/${supplierId}/${recordId}/${operation}`, {
      method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body,
    }));
  } catch (error) {
    return sessionError(error instanceof InvalidRequestBodyError ? 400 : 503, "SUPPLIER_REPLY_UNAVAILABLE", "供方回复暂不可用，请保留原内容后重试");
  }
}
