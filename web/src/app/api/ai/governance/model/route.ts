import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

const UPSTREAM_PATH = "/api/ai/governance/model";

async function authorizationHeaders() {
  const token = await currentSessionToken();
  return token ? { Authorization: `Bearer ${token}` } : null;
}

export async function GET() {
  const authorization = await authorizationHeaders();
  if (!authorization) {
    return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  }
  try {
    return forwardJson(await pdosApiFetch(UPSTREAM_PATH, { headers: authorization }));
  } catch {
    return sessionError(
      503,
      "MODEL_GOVERNANCE_UNAVAILABLE",
      "Model governance service unavailable",
    );
  }
}

export async function PATCH(request: Request) {
  const authorization = await authorizationHeaders();
  if (!authorization) {
    return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  }
  try {
    const payload = await readBoundedJson(request);
    return forwardJson(
      await pdosApiFetch(UPSTREAM_PATH, {
        method: "PATCH",
        headers: { ...authorization, "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(
      503,
      "MODEL_GOVERNANCE_UNAVAILABLE",
      "Model governance service unavailable",
    );
  }
}
