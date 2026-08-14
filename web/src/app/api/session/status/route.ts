import {
  forwardJson,
  pdosApiFetch,
  sessionError,
} from "@/lib/pdos-api";

export async function GET() {
  try {
    return forwardJson(await pdosApiFetch("/api/setup/status"));
  } catch {
    return sessionError(503, "AUTH_SERVICE_UNAVAILABLE", "Authentication service unavailable");
  }
}
