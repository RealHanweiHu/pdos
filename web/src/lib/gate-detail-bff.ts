import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type Context = {
  params: Promise<{ projectId: string; gateId: string }>;
};

/**
 * The three gate-review writes that had no route: recording the decision,
 * adjusting a slot's requirement, and granting a grandfather exemption.
 *
 * Each is a separate route file rather than a catch-all, because they are
 * three different authority levels and keeping them distinct makes that
 * visible in the route tree.
 */
export type GateDetailAction = "decisions" | "requirements" | "grandfather-exemptions";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function forwardGateDetail(
  action: GateDetailAction,
  request: Request,
  context: Context,
) {
  const { projectId, gateId } = await context.params;
  if (!UUID.test(gateId)) {
    return sessionError(404, "GATE_NOT_FOUND", "Gate was not found");
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = await readBoundedJson(request);
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/gates/${encodeURIComponent(
          gateId,
        )}/${action}`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(body),
        },
      ),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "Valid JSON request required");
    }
    return sessionError(503, "GATE_SERVICE_UNAVAILABLE", "Gate service unavailable");
  }
}
