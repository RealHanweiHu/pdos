import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";
export async function reservationForward(request: Request, projectId: string, reservationId?: string, operation: "resource-reservations" | "resource-inventory" | "replacement" | "owner-transfer" | "allocation-release" = "resource-reservations") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  if ([projectId, ...(reservationId ? [reservationId] : [])].some((id) => !/^[0-9a-f-]{36}$/i.test(id))) return sessionError(400, "INVALID_REQUEST", "Invalid reservation identifier");
  const target = operation === "resource-reservations" && !reservationId && request.method === "GET" ? new URL(request.url).searchParams.get("target_id") : null;
  if (target && !/^[0-9a-f-]{36}$/i.test(target)) return sessionError(400, "INVALID_REQUEST", "Invalid reservation identifier");
  try {
    const body = request.method === "POST" ? JSON.stringify(await readBoundedJson(request)) : undefined;
    return forwardJson(await pdosApiFetch(`/api/projects/${projectId}/${operation === "allocation-release" ? `resource-inventory/${reservationId}/release` : (operation === "replacement" || operation === "owner-transfer") ? `resource-reservations/${reservationId}/${operation}` : `${operation}${reservationId ? `/${reservationId}` : ""}`}${(operation === "owner-transfer" || operation === "allocation-release") && request.method === "GET" ? new URL(request.url).search : target ? `?target_id=${encodeURIComponent(target)}` : ""}`, { method: request.method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body }));
  } catch (error) { return sessionError(error instanceof InvalidRequestBodyError ? 400 : 503, "RESERVATION_UNAVAILABLE", "Resource reservation request could not be completed"); }
}
