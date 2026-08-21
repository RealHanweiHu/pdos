import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type Context = {
  params: Promise<{ projectId: string; gateId: string; roundId: string; slot: string }>;
};

const slots = new Set(["product", "engineering", "quality"]);

export async function PUT(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { projectId, gateId, roundId, slot } = await context.params;
    if (!slots.has(slot)) return sessionError(404, "GATE_SIGNOFF_NOT_FOUND", "Gate signoff not found");
    const payload = await readBoundedJson(request);
    return forwardJson(
      await pdosApiFetch(
        `/api/projects/${encodeURIComponent(projectId)}/gates/${encodeURIComponent(gateId)}/rounds/${encodeURIComponent(roundId)}/signoffs/${slot}`,
        {
          method: "PUT",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(payload),
        },
      ),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "GATE_SERVICE_UNAVAILABLE", "Gate service unavailable");
  }
}
