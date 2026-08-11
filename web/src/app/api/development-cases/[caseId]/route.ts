import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

type CaseRouteContext = {
  params: Promise<{ caseId: string }>;
};

async function upstreamPath(context: CaseRouteContext) {
  const { caseId } = await context.params;
  return `/api/development-cases/${encodeURIComponent(caseId)}`;
}

export async function GET(_request: Request, context: CaseRouteContext) {
  const token = await currentSessionToken();
  if (!token) {
    return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  }
  try {
    return forwardJson(
      await pdosApiFetch(await upstreamPath(context), {
        headers: { Authorization: `Bearer ${token}` },
      }),
    );
  } catch {
    return sessionError(503, "CASE_SERVICE_UNAVAILABLE", "Case service unavailable");
  }
}

export async function PATCH(request: Request, context: CaseRouteContext) {
  const token = await currentSessionToken();
  if (!token) {
    return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  }
  try {
    const payload = await readBoundedJson(request);
    return forwardJson(
      await pdosApiFetch(await upstreamPath(context), {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "CASE_SERVICE_UNAVAILABLE", "Case service unavailable");
  }
}
